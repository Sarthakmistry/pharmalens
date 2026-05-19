"""
agents/compiler.py
PharmaLens wiki compiler — 3-step LLM chain.

Step 1: Extract entities and signals from a raw document  (1 LLM call, cached)
Step 2: Determine which wiki pages need updating           (pure Python)
Step 3: Write or update each wiki page                    (1 LLM call per page, cached)

Called by orchestrator.py for each new unprocessed file.
Caches are built once per pipeline run in the orchestrator and passed through context.
"""

import json
import os
import re
import time
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

from agents.logger import get_logger

logger = get_logger("pharmalens.compiler")

# ── setup ─────────────────────────────────────────────────────────────────────

load_dotenv()  # must be before genai.Client()

client = genai.Client()

FLASH_MODEL = "gemini-2.5-flash"

try:
    BASE_DIR = Path(__file__).parent.parent
except NameError:
    BASE_DIR = Path.cwd().parent

WIKI_DIR      = BASE_DIR / "wiki"
REFERENCE_DIR = BASE_DIR / "reference"
PROMPTS_DIR   = BASE_DIR / "agents" / "prompts"
TEMPLATES_DIR = PROMPTS_DIR / "templates"

SCHEMA = (PROMPTS_DIR / "CLAUDE.md").read_text()

# load reference data once at module level
DRUGS      = json.loads((REFERENCE_DIR / "drugs.json").read_text())
INDICATIONS = json.loads((REFERENCE_DIR / "indications.json").read_text())
COMPANIES  = json.loads((REFERENCE_DIR / "companies.json").read_text())

# build reverse alias maps — used for entity resolution
BRAND_TO_INN = {}
for inn, data in DRUGS.items():
    for alias in data.get("aliases", []):
        BRAND_TO_INN[alias.lower()] = inn
    for brand in data.get("brand_names", []):
        BRAND_TO_INN[brand.lower()] = inn

ALIAS_TO_INDICATION = {}
for slug, data in INDICATIONS.items():
    for alias in data.get("aliases", []):
        ALIAS_TO_INDICATION[alias.lower()] = slug
    for code in data.get("icd10", []):
        ALIAS_TO_INDICATION[code.lower()] = slug
    if data.get("mesh"):
        ALIAS_TO_INDICATION[data["mesh"].lower()] = slug
    if data.get("ctgov_condition"):
        ALIAS_TO_INDICATION[data["ctgov_condition"].lower()] = slug

ALIAS_TO_COMPANY = {}
for slug, data in COMPANIES.items():
    for alias in data.get("aliases", []):
        ALIAS_TO_COMPANY[alias.lower()] = slug


# ── wiki helpers ──────────────────────────────────────────────────────────────

def read_wiki_page(page_path: str) -> str:
    """Read an existing wiki page. Returns empty string if not found."""
    full_path = WIKI_DIR / page_path
    if full_path.exists():
        return full_path.read_text()
    return ""


def _strip_fenced_code_block(content: str) -> str:
    """Strip ```markdown ... ``` or ``` ... ``` wrapper the LLM sometimes adds."""
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped[stripped.index("\n") + 1:]  # drop opening fence line
        if stripped.endswith("```"):
            stripped = stripped[: stripped.rfind("```")].rstrip()
    return stripped


def write_wiki_page(page_path: str, content: str) -> str:
    """Write content to a wiki page, creating parent directories as needed."""
    full_path = WIKI_DIR / page_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(_strip_fenced_code_block(content))
    return page_path


# ── prompt helpers ────────────────────────────────────────────────────────────

def load_prompt(doc_type: str) -> str:
    """Load the extraction prompt for a given document type.
    Raises ValueError if no prompt file exists — fail loud, not silent.
    """
    prompt_file = PROMPTS_DIR / f"compiler_{doc_type}.txt"
    if prompt_file.exists():
        return prompt_file.read_text()
    raise ValueError(
        f"No prompt file found for document type '{doc_type}'. "
        f"Expected: {PROMPTS_DIR}/compiler_{doc_type}.txt — "
        f"Either add the prompt file or update classify_document() in orchestrator.py"
    )


def load_page_template(page_type: str) -> str:
    """Load the formatting template for a specific wiki page type.
    Only injected in Step 3 calls — not in Step 1 extraction or index updates.
    Raises ValueError if template file is missing.
    """
    template_file = TEMPLATES_DIR / f"{page_type}.md"
    if template_file.exists():
        return template_file.read_text()
    raise ValueError(
        f"No template found for page type '{page_type}'. "
        f"Expected: {TEMPLATES_DIR}/{page_type}.md"
    )


def build_system_prompt() -> str:
    """Build the system instruction: CLAUDE.md schema + reference data summary."""
    drug_summary = {
        k: {
            "inn": v["inn"],
            "brand_names": v["brand_names"],
            "company": v["company"],
            "indications": v["indications"],
        }
        for k, v in DRUGS.items()
    }
    indication_summary = {
        k: {"aliases": v.get("aliases", []), "icd10": v.get("icd10", [])}
        for k, v in INDICATIONS.items()
    }

    return f"""{SCHEMA}

Reference data (use for entity resolution — do NOT invent entity names):
DRUGS: {json.dumps(drug_summary, indent=2)}
INDICATIONS: {json.dumps(indication_summary, indent=2)}

Entity resolution rules:
- Always normalize brand names to INN using the DRUGS reference
- Always normalize indication aliases to indication slugs using INDICATIONS
- Never create wiki pages for entities not in the reference data
- If an entity is not in reference data, note it in extraction output but do not create pages
"""


# ── document pre-processors ───────────────────────────────────────────────────

def preprocess_ctgov(raw: str) -> str:
    """Parse CT.gov JSON and return only the fields defined in our extraction spec.
    Filters interventions to DRUG and BIOLOGICAL types only.
    Falls back to raw text if JSON is malformed.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:12000]

    relevant = {
        "nct_id":                    data.get("NCTId"),
        "brief_title":               data.get("BriefTitle"),
        "overall_status":            data.get("OverallStatus"),
        "phase":                     data.get("Phase"),
        "study_type":                data.get("StudyType"),
        "start_date":                data.get("StartDate"),
        "primary_completion_date":   data.get("PrimaryCompletionDate"),
        "completion_date":           data.get("CompletionDate"),
        "last_updated":              data.get("LastUpdatePostDate"),
        "lead_sponsor":              data.get("LeadSponsorName"),
        "lead_sponsor_class":        data.get("LeadSponsorClass"),
        "collaborator":              data.get("CollaboratorName"),
        "conditions":                data.get("Condition"),
        "brief_summary":             data.get("BriefSummary"),
        "enrollment_count":          data.get("EnrollmentCount"),
        "enrollment_type":           data.get("EnrollmentType"),
        "intervention_type":         data.get("InterventionType"),
        "intervention_name":         data.get("InterventionName"),
        "primary_outcome_measure":   data.get("PrimaryOutcomeMeasure"),
        "primary_outcome_timeframe": data.get("PrimaryOutcomeTimeFrame"),
        "has_results":               data.get("HasResults"),
    }

    # filter out non-drug intervention types
    if relevant.get("intervention_type") not in ("DRUG", "BIOLOGICAL"):
        relevant["intervention_type"] = None
        relevant["intervention_name"] = None

    relevant = {k: v for k, v in relevant.items() if v is not None}
    return json.dumps(relevant, indent=2)


def preprocess_pubmed(raw: str) -> str:
    """Parse PubMed JSON and return only the fields defined in our extraction spec.
    Falls back to raw text if JSON is malformed.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:12000]

    relevant = {
        "pmid":               data.get("pmid"),
        "doi":                data.get("doi"),
        "pubmed_date":        data.get("pubmed_date"),
        "title":              data.get("title"),
        "journal":            data.get("journal"),
        "journal_abbr":       data.get("journal_abbr"),
        "publication_types":  data.get("publication_types", []),
        "abstract":           data.get("abstract"),
        "mesh_major_topics":  data.get("mesh_major_topics", []),
        "first_author":       data.get("first_author"),
        "industry_sponsored": data.get("industry_sponsored"),
        "industry_note":      data.get("industry_note"),
    }

    relevant = {k: v for k, v in relevant.items() if v is not None}
    return json.dumps(relevant, indent=2)


def preprocess_text(raw: str, max_chars: int) -> str:
    """Clean and intelligently truncate plain text documents.

    Removes blank lines to compact the text. If the document exceeds max_chars,
    keeps the first 70% and last 30% with a truncation notice in between.

    The 70/30 split is deliberate for earnings transcripts:
    - First 70%: CEO prepared remarks, CFO financial summary (highest signal)
    - Last 30%: analyst Q&A session often contains forward guidance and risk flags
    - Middle: less critical boilerplate, legal disclaimers, repetitive detail
    """
    cleaned = "\n".join(line for line in raw.splitlines() if line.strip())

    if len(cleaned) <= max_chars:
        return cleaned

    keep_start    = int(max_chars * 0.70)
    keep_end      = int(max_chars * 0.30)
    chars_dropped = len(cleaned) - max_chars

    return (
        cleaned[:keep_start]
        + f"\n\n[... {chars_dropped:,} characters truncated — middle section omitted ...]\n\n"
        + cleaned[-keep_end:]
    )

def preprocess_document(file_path: Path, doc_type: str) -> str:
    """Pre-process a raw file before passing to the LLM.

    JSON files (ctgov, pubmed): parse and extract only the fields the compiler
    needs — avoids passing hundreds of irrelevant fields to the LLM.

    Text/HTML files (edgar, genepool): clean and truncate intelligently.
    8-K files get the exhibit extractor before truncation.
    10-Q files get more chars since they contain XBRL + MD&A sections.

    Returns a clean string ready for the Step 1 extraction prompt.
    """
    raw = file_path.read_text(errors="replace")

    if doc_type == "ctgov":
        return preprocess_ctgov(raw)
    elif doc_type == "pubmed":
        return preprocess_pubmed(raw)
    elif doc_type == "edgar_8k":
        return preprocess_text(raw, max_chars=8000)
    elif doc_type == "edgar_10q":
        return preprocess_text(raw, max_chars=20000)
    elif doc_type == "genepool":
        return preprocess_text(raw, max_chars=8000)
    else:
        return preprocess_text(raw, max_chars=12000)


# ── path helpers ──────────────────────────────────────────────────────────────

def get_company_from_path(path: Path) -> str | None:
    """Extract company slug from path for edgar and ctgov files."""
    parts = path.parts
    for source in ("edgar", "ctgov"):
        if source in parts:
            idx = list(parts).index(source)
            if idx + 1 < len(parts):
                return parts[idx + 1]
    return None


def get_drug_from_path(path: Path) -> str | None:
    """Extract drug INN from pubmed path."""
    parts = path.parts
    if "pubmed" in parts:
        idx = list(parts).index("pubmed")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return None


def classify_document(path: Path) -> str:
    """Infer document type from folder path — no LLM needed.
    Folder structure: raw/edgar/{company}/8k/ or raw/edgar/{company}/10q/
    Returns: ctgov | edgar_8k | edgar_10q | genepool | pubmed | unknown
    """
    parts       = path.parts
    parts_lower = [p.lower() for p in parts]

    if "ctgov" in parts:
        return "ctgov"
    elif "edgar" in parts:
        if "10q" in parts_lower:
            return "edgar_10q"
        elif "8k" in parts_lower:
            return "edgar_8k"
        else:
            logger.warning(f"classify_document | Unknown edgar subfolder for {path}")
            return "edgar_8k"
    elif "genepool" in parts:
        return "genepool"
    elif "pubmed" in parts:
        return "pubmed"
    else:
        return "unknown"


# ── 3-step compiler chain ─────────────────────────────────────────────────────

def compile_document_step1(
    file_path: Path,
    context: dict,
    raw_content: str,
    doc_type: str,
    system_prompt: str,
) -> dict:
    """Step 1 — extract structured entities and signals from the raw document.
    One LLM call. Returns parsed JSON dict.
    system_prompt is passed in by compile_document (built once, or from cache).
    """
    step1_prompt = f"""Document to process:
---
{raw_content}
---

File path: {file_path}
Document type: {doc_type}
Company context (from path): {context.get('company', 'unknown')}
Drug context (from path): {context.get('drug', 'unknown')}
File date (use this as event_date and last_updated — do not use dates from document body): {context.get('file_date', 'unknown')}

Extract all relevant entities and signals. Return a JSON object:
{{
  "all_drugs_mentioned": [
    {{
      "name": "risankizumab",
      "brand_name": "Skyrizi",
      "revenue_usd_m": 3425,
      "revenue_growth_pct": 70.5,
      "direction": "growing",
      "sentiment": "bullish",
      "commentary": "one sentence from management or results",
      "is_pipeline": false,
      "is_blockbuster": true
    }}
  ],
  "companies_mentioned": ["novo-nordisk"],
  "indications_mentioned": ["glp1-obesity"],
  "trial_ids": ["NCT03819153"],
  "event_type": "fda_approval | trial_completion | trial_termination | earnings_signal | news | pubmed_result | null",
  "event_summary": "one sentence describing the key signal",
  "sentiment": "bullish | bearish | neutral | null",
  "sentiment_reasoning": "brief quote or paraphrase supporting sentiment",
  "key_facts": ["fact 1", "fact 2"],
  "event_date": "YYYY-MM-DD or null",
  "requires_new_event_page": true,
  "suggested_event_slug": "2026-04-02-semaglutide-ckd-fda-approval",
  "clinical_findings": {{
    "study_design": "RCT | meta-analysis | systematic review | observational | null",
    "sample_size": "3533 patients | null",
    "comparator": "placebo | standard of care | competitor drug | null",
    "primary_outcome": "exact outcome measure as stated in abstract",
    "primary_result": "exact result with numbers",
    "secondary_results": ["result 1 with numbers", "result 2 with numbers"],
    "safety_note": "any adverse event finding or null",
    "conclusions_verbatim": "copy the CONCLUSIONS section exactly as written",
    "journal": "journal name",
    "publication_year": "YYYY",
    "industry_sponsored": true
  }}
}}
Return ONLY valid JSON with no markdown fences.
"""

    step1_response = client.models.generate_content(
        model=FLASH_MODEL,
        contents=step1_prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )

    try:
        return json.loads(step1_response.text)
    except json.JSONDecodeError:
        raise ValueError(
            f"Step 1 JSON parse failed for {file_path}. "
            f"Response was: {step1_response.text[:300]}"
        )


def collect_entity_pages(extracted: dict, pages_to_update: list, context: dict) -> None:
    """Step 2a — validate extracted entities against reference data.
    Appends page update entries for drugs, companies, and indications.
    Entities not found in reference files are logged and skipped.
    Modifies pages_to_update in place.
    """
    # enrich all_drugs_mentioned with is_tracked flag (set here in Python, not by LLM)
    all_drugs = extracted.get("all_drugs_mentioned", [])
    for drug in all_drugs:
        drug["is_tracked"] = drug.get("name", "") in DRUGS
    extracted["all_drugs_mentioned"] = all_drugs

    # derive tracked drug names for page routing
    tracked_drug_names = [d["name"] for d in all_drugs if d.get("is_tracked")]

    # fallback: if LLM missed the company, inject from path context
    companies_mentioned = extracted.get("companies_mentioned", [])
    if not companies_mentioned and context.get("company") in COMPANIES:
        logger.warning(
            f"STEP2 | companies_mentioned empty — "
            f"falling back to path context: {context['company']}"
        )
        companies_mentioned = [context["company"]]

    entity_configs = [
        {
            "reference": DRUGS,
            "path_fn":   lambda e: f"drugs/{e}.md",
            "type":      "drug",
            "ref_name":  "reference/drugs.json",
            "entities":  tracked_drug_names,
        },
        {
            "reference": COMPANIES,
            "path_fn":   lambda e: f"companies/{e}.md",
            "type":      "company",
            "ref_name":  "reference/companies.json",
            "entities":  companies_mentioned,
        },
        {
            "reference": INDICATIONS,
            "path_fn":   lambda e: f"indications/{e}/_index.md",
            "type":      "indication_hub",
            "ref_name":  "reference/indications.json",
            "entities":  extracted.get("indications_mentioned", []),
        },
    ]

    for config in entity_configs:
        for entity in config["entities"]:
            normalized = entity if entity in config["reference"] else entity.lower()

            # fall back to alias maps when the LLM returns a name instead of a slug
            if normalized not in config["reference"]:
                if config["type"] == "indication_hub":
                    normalized = ALIAS_TO_INDICATION.get(entity.lower(), normalized)
                elif config["type"] == "company":
                    normalized = ALIAS_TO_COMPANY.get(entity.lower(), normalized)

            if normalized in config["reference"]:
                page_path = config["path_fn"](normalized)
                pages_to_update.append({
                    "path":              page_path,
                    "type":              config["type"],
                    "entity":            normalized,
                    "current":           read_wiki_page(page_path),
                    "all_drugs_mentioned": all_drugs,  # carries is_tracked flag
                })
            else:
                logger.warning(
                    f"STEP2 | SKIP ENTITY | '{entity}' not in {config['ref_name']}"
                )


def collect_trial_and_event_pages(
    extracted: dict,
    pages_to_update: list,
    file_path: Path,
    context: dict,
) -> bool:
    """Step 2b — validate and accumulate trial and event page entries.
    Trials: one file per company, multiple NCT IDs accumulated onto one entry.
    Events: always a new page.
    Returns False if pages_to_update is still empty (caller should return early).
    """
    from agents.state import get_nct_action, mark_nct_processed

    for nct_id in extracted.get("trial_ids", []):
        if not (nct_id.startswith("NCT") and len(nct_id) == 11):
            logger.warning(f"STEP2 | SKIP ENTITY | Malformed trial ID: '{nct_id}'")
            continue

        primary_sponsor = next(
            (c for c in extracted.get("companies_mentioned", [])
             if c in COMPANIES or c.lower() in COMPANIES),
            None,
        )
        if primary_sponsor and primary_sponsor not in COMPANIES:
            primary_sponsor = primary_sponsor.lower()

        if not primary_sponsor:
            logger.warning(
                f"STEP2 | SKIP TRIAL | {nct_id} — no tracked company identified as sponsor"
            )
            continue

        if context.get("out_of_scope"):
            logger.info(
                f"STEP2 | SKIP TRIAL | {nct_id} — out of scope, company page only"
            )
            continue

        nct_action = get_nct_action(nct_id)
        mark_nct_processed(nct_id, primary_sponsor, extracted.get("event_date"))
        logger.debug(f"STEP2 | {nct_id} → action={nct_action}, sponsor={primary_sponsor}")

        trial_page_path = f"trials/{primary_sponsor}.md"
        existing = next(
            (p for p in pages_to_update if p["path"] == trial_page_path), None
        )

        if existing is None:
            pages_to_update.append({
                "path":    trial_page_path,
                "type":    "trial",
                "entity":  primary_sponsor,
                "current": read_wiki_page(trial_page_path),
                "nct_ids": [{"nct_id": nct_id, "action": nct_action}],
            })
        else:
            existing["nct_ids"].append({"nct_id": nct_id, "action": nct_action})
            logger.debug(f"STEP2 | Accumulated {nct_id} onto {trial_page_path}")

    if extracted.get("requires_new_event_page") and extracted.get("suggested_event_slug"):
        event_path = f"events/{extracted['suggested_event_slug']}.md"
        pages_to_update.append({
            "path":   event_path,
            "type":   "event",
            "entity": extracted["suggested_event_slug"],
            "current": "",
        })
        logger.debug(f"STEP2 | Queued event: {event_path}")

    if not pages_to_update:
        logger.info(f"STEP2 | NO PAGES | No tracked entities in {file_path.name}")
        return False

    return True


def build_trial_context(page: dict) -> str:
    """Build the trial-specific NCT instruction block for Step 3 prompts.
    Returns an empty string for all non-trial page types.
    """
    if page["type"] != "trial":
        return ""

    nct_details = page.get("nct_ids", [])
    new_ncts    = [n["nct_id"] for n in nct_details if n["action"] == "new"]
    update_ncts = [n["nct_id"] for n in nct_details if n["action"] == "update"]

    return f"""
Trial page instructions (determined by processing state — do not override):
- NCT IDs to ADD as new entries: {new_ncts if new_ncts else "none"}
- NCT IDs to UPDATE existing entries: {update_ncts if update_ncts else "none"}
- For ADD: create a new section under the correct status group (Active / Completed / Terminated)
  and add a new row to the summary table.
- For UPDATE: find the existing section by NCT ID and update status, result, and completion date.
  Do NOT add a duplicate section. Do NOT remove any other existing trial entries.
"""


def write_wiki_pages(
    pages_to_update: list,
    extracted: dict,
    file_path: Path,
    doc_type: str,
    system_prompt: str,
    template_caches: dict,
) -> list[str]:
    """Step 3 — write or update each wiki page identified in Step 2.
    One LLM call per page. Uses cached template if available, falls back to
    building the prompt inline (notebook mode).
    Returns the list of wiki page paths written.
    """
    updated_paths = []

    clinical_block = ""
    if extracted.get("clinical_findings"):
        cf = extracted["clinical_findings"]
        clinical_block = f"""
Clinical findings to include verbatim in the Clinical evidence section:
- Study design: {cf.get('study_design')}
- Sample size: {cf.get('sample_size')}
- Comparator: {cf.get('comparator')}
- Primary outcome: {cf.get('primary_outcome')}
- Primary result: {cf.get('primary_result')}
- Secondary results: {cf.get('secondary_results', [])}
- Safety: {cf.get('safety_note')}
- Conclusions (verbatim): {cf.get('conclusions_verbatim')}
- Journal: {cf.get('journal')}, {cf.get('publication_year')}
- Industry sponsored: {cf.get('industry_sponsored')}

These numbers MUST appear in the Clinical evidence section exactly as stated.
Do not paraphrase the primary result or conclusions.
"""

    for page in pages_to_update:
        trial_context = build_trial_context(page)

        step3_prompt = f"""{trial_context}
{clinical_block}
Write the updated wiki page for: {page['path']}
Page type: {page['type']}
Entity: {page['entity']}

Extracted signals from the new document:
{json.dumps(extracted, indent=2)}

Current page content (empty if new page):
---
{page['current'] if page['current'] else '[NEW PAGE — write from scratch using the template above]'}
---

Source document: {file_path} (type: {doc_type})

Rules:
- Follow the page template exactly for this page type
- If the page exists: UPDATE it — preserve all existing content, only add or change what this document affects
- If new page: write complete page from scratch
- Timeline section is append-only — add new rows at the top, never delete existing rows
- End with a ## Sources section listing the raw file path
- For all_drugs_mentioned in the extracted signals: drugs with is_tracked=true have canonical wiki
  pages — use [[drug_name]] link syntax for those only. Write is_tracked=false drugs as plain text.
- last_updated: always use the source document date, never a date from within the document body
- Write ONLY the markdown content — no preamble, no explanation
"""

        # use cached template if available (production), otherwise build inline (notebook)
        cache_name = template_caches.get(page["type"])
        if cache_name:
            config = types.GenerateContentConfig(
                cached_content=cache_name,
                temperature=0.2,
            )
        else:
            page_template = load_page_template(page["type"])
            config = types.GenerateContentConfig(
                system_instruction=system_prompt + "\n\n" + page_template,
                temperature=0.2,
            )

        start = time.time()
        step3_response = client.models.generate_content(
            model=FLASH_MODEL,
            contents=step3_prompt,
            config=config,
        )
        logger.info(f"STEP3 | API call took {time.time() - start:.1f}s for {page['type']}")

        write_wiki_page(page["path"], step3_response.text)
        updated_paths.append(page["path"])
        logger.info(f"STEP3 | WROTE | {page['path']}")

    return updated_paths


def compile_document(
    file_path: Path,
    context: dict,
    extraction_caches: dict | None = None,
    template_caches: dict | None = None,
) -> list[str]:
    """3-step compiler chain: extract → validate → write.

    Args:
        file_path:         Path to the raw source file.
        context:           Dict with keys: doc_type, company, drug.
        extraction_caches: Dict of doc_type → cache name (built by orchestrator).
                           If None or key missing, system prompt is built inline.
        template_caches:   Dict of page_type → cache name (built by orchestrator).
                           If None or key missing, template is loaded inline.

    Returns:
        List of wiki page paths that were written.
    """
    from agents.state import update_index_py

    extraction_caches = extraction_caches or {}
    template_caches   = template_caches   or {}

    doc_type  = context["doc_type"]
    file_name = file_path.name

    logger.info(
        f"COMPILE | START | {file_name} | doc_type={doc_type} | "
        f"company={context.get('company')} | drug={context.get('drug')}"
    )

    # pre-process document
    raw_content = preprocess_document(file_path, doc_type)

    # build system prompt once — used for Step 1 inline fallback and Step 3 inline fallback
    system_prompt = build_system_prompt()

    # ── STEP 1: Extract ───────────────────────────────────────────────────────
    # use cached system+extraction prompt if available, else pass system_prompt inline
    cache_name = extraction_caches.get(doc_type)
    step1_system = cache_name if cache_name else system_prompt

    try:
        extracted = compile_document_step1(
            file_path,
            context,
            raw_content,
            doc_type,
            step1_system,
        )
    except ValueError as e:
        logger.error(f"STEP1 | FAILED | {file_name}: {e}")
        raise

    # pubmed files never trigger event pages — override regardless of LLM output
    if doc_type == "pubmed":
        extracted["requires_new_event_page"] = False
        extracted["suggested_event_slug"]    = None
        extracted["event_type"]              = None
        extracted["event_summary"]           = None

    # ctgov event pages only make sense when a trial has reached a terminal status;
    # active/recruiting trials produce no discrete event — suppress regardless of LLM output
    if doc_type == "ctgov":
        _TERMINAL_STATUSES = {"COMPLETED", "TERMINATED", "WITHDRAWN"}
        try:
            _ctgov_status = json.loads(raw_content).get("overall_status", "")
        except (json.JSONDecodeError, AttributeError):
            _ctgov_status = ""
        if _ctgov_status.upper() not in _TERMINAL_STATUSES:
            extracted["requires_new_event_page"] = False
            extracted["suggested_event_slug"]    = None
            extracted["event_type"]              = None
            extracted["event_summary"]           = None
            logger.info(
                f"STEP2 | SKIP EVENT | {file_name} — overall_status={_ctgov_status!r} is not terminal"
            )

    # ── STEP 2: Collect pages ─────────────────────────────────────────────────
    pages_to_update = []
    collect_entity_pages(extracted, pages_to_update, context)
    has_work = collect_trial_and_event_pages(extracted, pages_to_update, file_path, context)

    if not has_work:
        logger.info(f"COMPILE | DONE | {file_name} — no tracked entities, nothing written")
        return []

    # ── STEP 3: Write pages ───────────────────────────────────────────────────
    updated_paths = write_wiki_pages(
        pages_to_update,
        extracted,
        file_path,
        doc_type,
        system_prompt,
        template_caches,
    )

    # update wiki navigation map — pure Python, no LLM
    if updated_paths:
        update_index_py(pages_to_update)

    logger.info(
        f"COMPILE | DONE | {file_name} → "
        f"{len(updated_paths)} pages written: {updated_paths}"
    )
    return updated_paths