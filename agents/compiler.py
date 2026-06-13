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
from agents.cost import ledger

logger = get_logger("pharmalens.compiler")

# ── setup ─────────────────────────────────────────────────────────────────────

load_dotenv()  # must be before genai.Client()

client = genai.Client(http_options=types.HttpOptions(timeout=300_000))  # 300s in ms

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

    # keep interventions only if at least one component is DRUG or BIOLOGICAL.
    # InterventionType is a pipe-delimited string e.g. "DRUG | DRUG | OTHER"
    int_type = relevant.get("intervention_type")
    if int_type:
        types = [t.strip().upper() for t in str(int_type).split("|")]
        if not any(t in ("DRUG", "BIOLOGICAL") for t in types):
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
    from agents.gcs import read_blob
    raw = read_blob(file_path, BASE_DIR)

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


# ── ctgov pure-Python Step 1 ─────────────────────────────────────────────────

def extract_ctgov_python(preprocessed: dict) -> dict:
    """
    Pure-Python Step 1 replacement for ctgov files.
    Takes the preprocessed dict from preprocess_ctgov() (snake_case keys).

    For ctgov, Step 1 is almost entirely entity resolution against reference
    data — company from sponsor name, drugs from intervention name, indications
    from condition field. Python handles this accurately using the same alias
    maps the LLM would use, saving one LLM call per file.
    """
    # company: substring-match lead_sponsor against alias map
    sponsor = (preprocessed.get("lead_sponsor") or "").lower()
    company = next(
        (slug for alias, slug in ALIAS_TO_COMPANY.items() if alias in sponsor),
        None,
    )

    # drugs: split intervention_name by "|", match each segment against INN + brands
    intervention_str = str(preprocessed.get("intervention_name") or "")
    intervention_parts = [p.strip().lower() for p in intervention_str.split("|") if p.strip()]

    # terms that are definitely not drug names — skip them for untracked list
    _NON_DRUG_TERMS = {
        "placebo", "standard of care", "usual care", "best supportive care",
        "no intervention", "observation", "sham", "vehicle", "control",
        "lifestyle", "exercise", "diet", "surgery", "radiation",
    }

    matched_drugs: list[str] = []
    matched_part_indices: set[int] = set()
    for inn, info in DRUGS.items():
        brands = [b.lower() for b in info.get("brand_names", [])]
        for i, part in enumerate(intervention_parts):
            if inn in part or any(b in part for b in brands):
                if inn not in matched_drugs:
                    matched_drugs.append(inn)
                matched_part_indices.add(i)
                break

    # untracked: parts that didn't match any tracked drug and aren't noise
    untracked_names: list[str] = []
    for i, part in enumerate(intervention_parts):
        if i in matched_part_indices:
            continue
        if len(part) < 3:
            continue
        if any(noise in part for noise in _NON_DRUG_TERMS):
            continue
        untracked_names.append(part[0].upper() + part[1:])

    # indications: split conditions by "|", match each segment against alias map
    conditions_str = str(preprocessed.get("conditions") or "")
    condition_parts = [c.strip().lower() for c in conditions_str.split("|") if c.strip()]
    matched_indications: list[str] = []
    for part in condition_parts:
        for alias, slug in ALIAS_TO_INDICATION.items():
            if alias in part and slug not in matched_indications:
                matched_indications.append(slug)

    nct_id = preprocessed.get("nct_id")
    status  = (preprocessed.get("overall_status") or "").upper()
    _TERMINAL = {"COMPLETED", "TERMINATED", "WITHDRAWN"}
    requires_event = status in _TERMINAL and bool(company)
    event_type = {"COMPLETED": "trial_completion", "TERMINATED": "trial_termination"}.get(status)

    date = (
        preprocessed.get("primary_completion_date")
        or preprocessed.get("completion_date")
        or ""
    )[:10]
    if matched_drugs:
        drug_slug = matched_drugs[0]
    elif untracked_names:
        drug_slug = untracked_names[0].lower().replace(" ", "-")
    else:
        drug_slug = "unknown"
    slug = (
        f"{date}-{drug_slug}-{(nct_id or '').lower()}-{status.lower()}"
        if requires_event else None
    )

    key_facts = [f for f in [
        f"Phase: {preprocessed['phase']}"                       if preprocessed.get("phase") else None,
        f"Status: {status}",
        (f"Enrollment: {preprocessed['enrollment_count']} "
         f"({preprocessed.get('enrollment_type', '')})")        if preprocessed.get("enrollment_count") else None,
        f"Primary completion: {preprocessed['primary_completion_date']}"
                                                                if preprocessed.get("primary_completion_date") else None,
        f"Has results: {preprocessed['has_results']}"           if preprocessed.get("has_results") is not None else None,
    ] if f is not None]

    return {
        "all_drugs_mentioned": (
            [{"name": inn, "is_tracked": True} for inn in matched_drugs] +
            [{"name": name, "is_tracked": False} for name in untracked_names]
        ),
        "companies_mentioned":     [company] if company else [],
        "indications_mentioned":   matched_indications,
        "trial_ids":               [nct_id] if nct_id else [],
        "event_type":              event_type,
        "event_summary":           None,
        "sentiment":               None,
        "sentiment_reasoning":     None,
        "key_facts":               key_facts,
        "event_date":              date or None,
        "requires_new_event_page": requires_event,
        "suggested_event_slug":    slug,
        "clinical_findings":       None,
    }


# ── ctgov pre-LLM filter ─────────────────────────────────────────────────────

def _ctgov_passes_filter(parsed: dict) -> tuple[bool, str]:
    """
    Pure-Python gate applied before the Step 1 LLM call for ctgov files.
    Returns (True, "") to proceed, or (False, reason) to skip.

    Goal: keep ALL drug/biological trials from tracked companies — the ctgov
    pipeline is a company-level portfolio view, not drug-specific. Understanding
    a company's full pipeline (including untracked drugs and new indications)
    is the point.

    The only thing worth skipping: trials with NO drug or biological intervention
    at all (device studies, blood draws, behavioral/procedural arms).
    preprocess_ctgov() already nullifies intervention_type/name for those, so
    if both fields are absent from the preprocessed dict this trial has zero
    pharmaceutical signal.
    """
    if "intervention_type" not in parsed and "intervention_name" not in parsed:
        return False, (
            f"no drug/biological intervention "
            f"(status={parsed.get('overall_status')!r}, "
            f"conditions={parsed.get('conditions', [])[:2]})"
        )
    return True, ""


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
    ledger.record(step1_response.usage_metadata)

    try:
        return json.loads(step1_response.text)
    except json.JSONDecodeError:
        raise ValueError(
            f"Step 1 JSON parse failed for {file_path}. "
            f"Response was: {step1_response.text[:300]}"
        )


def collect_entity_pages(
    extracted: dict,
    pages_to_update: list,
    context: dict,
    file_path: Path,
    company_buffer: dict | None = None,
    drug_buffer: dict | None = None,
    indication_buffer: dict | None = None,
) -> bool:
    """Step 2a — validate extracted entities against reference data.
    Routes each entity to its batch buffer (if provided) or to pages_to_update.
    Buffered pages are written once at end-of-batch via flush_buffered_pages().
    Returns True if any tracked entity was found.
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
            "buffer":    drug_buffer,
        },
        {
            "reference": COMPANIES,
            "path_fn":   lambda e: f"companies/{e}.md",
            "type":      "company",
            "ref_name":  "reference/companies.json",
            "entities":  companies_mentioned,
            "buffer":    company_buffer,
        },
        {
            "reference": INDICATIONS,
            "path_fn":   lambda e: f"indications/{e}/_index.md",
            "type":      "indication_hub",
            "ref_name":  "reference/indications.json",
            "entities":  extracted.get("indications_mentioned", []),
            "buffer":    indication_buffer,
        },
    ]

    found_any = False
    signal = {
        "file_path": str(file_path),
        "doc_type":  context.get("doc_type", ""),
        "extracted": extracted,
    }

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
                found_any = True
                buf = config["buffer"]
                if buf is not None:
                    buf.setdefault(normalized, []).append(signal)
                    logger.info(
                        f"STEP2 | BUFFER {config['type'].upper()} | {normalized} — "
                        f"signal queued for batch flush"
                    )
                else:
                    page_path = config["path_fn"](normalized)
                    pages_to_update.append({
                        "path":                page_path,
                        "type":                config["type"],
                        "entity":              normalized,
                        "current":             read_wiki_page(page_path),
                        "all_drugs_mentioned": all_drugs,
                    })
            else:
                logger.warning(
                    f"STEP2 | SKIP ENTITY | '{entity}' not in {config['ref_name']}"
                )

    return found_any


def collect_trial_and_event_pages(
    extracted: dict,
    pages_to_update: list,
    file_path: Path,
    context: dict,
    trial_buffer: dict | None = None,
) -> bool:
    """Step 2b — validate and accumulate trial and event page entries.
    Trials: buffered per-company if trial_buffer provided; else accumulated onto pages_to_update.
    Events: always written per-file (each event has a unique slug).
    Returns True if any tracked entity was found.
    """
    from agents.state import get_nct_action, mark_nct_processed

    found_any = False

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

        found_any = True
        nct_action = get_nct_action(nct_id)
        mark_nct_processed(nct_id, primary_sponsor, extracted.get("event_date"))
        logger.debug(f"STEP2 | {nct_id} → action={nct_action}, sponsor={primary_sponsor}")

        if trial_buffer is not None:
            trial_buffer.setdefault(primary_sponsor, []).append({
                "nct_id":    nct_id,
                "action":    nct_action,
                "extracted": extracted,
                "file_path": str(file_path),
            })
            logger.info(
                f"STEP2 | BUFFER TRIAL | {primary_sponsor}/{nct_id} ({nct_action}) — "
                f"queued for batch flush"
            )
        else:
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
            "path":    event_path,
            "type":    "event",
            "entity":  extracted["suggested_event_slug"],
            "current": "",
        })
        logger.debug(f"STEP2 | Queued event: {event_path}")
        found_any = True

    return found_any


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
    All LLM calls fire in parallel (one thread per page), then results are
    written to disk in the main thread. Uses cached template if available.
    Returns the list of wiki page paths written.
    """
    import concurrent.futures as _cf

    if not pages_to_update:
        return []

    # build clinical block once — shared across all page prompts
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

    # pre-build (prompt, config) for every page — no LLM involved yet
    tasks: list[tuple[dict, str, types.GenerateContentConfig]] = []
    for page in pages_to_update:
        trial_context = build_trial_context(page)
        prompt = f"""{trial_context}
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
- For all_drugs_mentioned in the extracted signals: include ALL entries (both is_tracked=true and
  is_tracked=false) in the drugs frontmatter field. Use [[drug_name]] link syntax in body text for
  is_tracked=true drugs only. Write is_tracked=false drugs as plain text in the body.
- last_updated: always use the source document date, never a date from within the document body
- Write ONLY the markdown content — no preamble, no explanation
"""
        cache_name = template_caches.get(page["type"])
        if cache_name:
            config = types.GenerateContentConfig(cached_content=cache_name, temperature=0.2)
        else:
            page_template = load_page_template(page["type"])
            config = types.GenerateContentConfig(
                system_instruction=system_prompt + "\n\n" + page_template,
                temperature=0.2,
            )
        tasks.append((page, prompt, config))

    def _call_llm(task: tuple) -> tuple[dict, str, object, float]:
        page, prompt, config = task
        start = time.time()
        resp = client.models.generate_content(
            model=FLASH_MODEL, contents=prompt, config=config,
        )
        return page, resp.text, resp.usage_metadata, time.time() - start

    # fire all LLM calls in parallel — bounded by number of pages per file (≤5)
    with _cf.ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        results = list(pool.map(_call_llm, tasks, timeout=600))

    # write to disk and record usage in main thread (avoids any shared-state races)
    updated_paths = []
    for page, content, usage, elapsed in results:
        logger.info(f"STEP3 | API call took {elapsed:.1f}s for {page['type']}")
        ledger.record(usage)
        write_wiki_page(page["path"], content)
        updated_paths.append(page["path"])
        logger.info(f"STEP3 | WROTE | {page['path']}")

    return updated_paths


def flush_buffered_pages(
    company_buffer: dict,
    trial_buffer: dict,
    drug_buffer: dict,
    indication_buffer: dict,
    template_caches: dict,
) -> list[str]:
    """Flush all buffered signals — one LLM call per entity covering all accumulated signals.
    Handles company, trial, drug, and indication pages in a single parallel pass.
    Call once after the per-file loop. Returns list of wiki page paths written.
    """
    import concurrent.futures as _cf
    from agents.state import update_index_py

    if not any([company_buffer, trial_buffer, drug_buffer, indication_buffer]):
        return []

    system_prompt = build_system_prompt()
    tasks: list[tuple] = []

    def _signals_block(signals: list[dict]) -> str:
        return "\n\n".join(
            f"Signal {i + 1} (file: {s['file_path']}, type: {s['doc_type']}):\n"
            f"{json.dumps(s['extracted'], indent=2)}"
            for i, s in enumerate(signals)
        )

    def _make_config(page_type: str) -> types.GenerateContentConfig:
        cache_name = template_caches.get(page_type)
        if cache_name:
            return types.GenerateContentConfig(cached_content=cache_name, temperature=0.2)
        page_template = load_page_template(page_type)
        return types.GenerateContentConfig(
            system_instruction=system_prompt + "\n\n" + page_template, temperature=0.2,
        )

    # ── company ────────────────────────────────────────────────────────────────
    for slug, signals in company_buffer.items():
        page_path = f"companies/{slug}.md"
        current   = read_wiki_page(page_path)
        prompt = f"""Update the company wiki page for: {page_path}
Page type: company
Entity: {slug}

{len(signals)} document(s) processed in this batch run.

Current page content (empty if new page):
---
{current if current else '[NEW PAGE — write from scratch using the template above]'}
---

Signals to integrate (ordered as processed):
{_signals_block(signals)}

Rules:
- Integrate ALL signals above into the company page
- Follow the company template exactly
- Preserve all existing content — only add or update what these documents affect
- Timeline section is append-only — add new rows at the top, never delete existing rows
- End with a ## Sources section listing all raw file paths
- For all_drugs_mentioned: drugs with is_tracked=true get [[drug_name]] links; is_tracked=false as plain text
- last_updated: use the most recent event_date from the signals above
- Write ONLY the markdown content — no preamble, no explanation
"""
        tasks.append(("company", slug, page_path, prompt, _make_config("company"), signals))

    # ── trial ──────────────────────────────────────────────────────────────────
    for sponsor, entries in trial_buffer.items():
        page_path = f"trials/{sponsor}.md"
        current   = read_wiki_page(page_path)
        trials_block = "\n\n".join(
            f"Trial {i + 1}: {e['nct_id']} — action: {e['action']}\n"
            f"Source: {e['file_path']}\n"
            f"{json.dumps(e['extracted'], indent=2)}"
            for i, e in enumerate(entries)
        )
        new_ncts    = [e["nct_id"] for e in entries if e["action"] == "new"]
        update_ncts = [e["nct_id"] for e in entries if e["action"] == "update"]
        prompt = f"""Update the trial registry page for: {page_path}
Page type: trial
Entity: {sponsor}

{len(entries)} trial(s) to process from this batch run.
- NCT IDs to ADD as new entries: {new_ncts if new_ncts else 'none'}
- NCT IDs to UPDATE existing entries: {update_ncts if update_ncts else 'none'}

Current page content (empty if new page):
---
{current if current else '[NEW PAGE — write from scratch using the template above]'}
---

Trials (ordered as processed):
{trials_block}

Rules:
- action=new: add row to summary table + create section under correct status group (Active/Completed/Terminated)
- action=update: find existing section by NCT ID, update status/result/completion date — no duplicates
- Never remove existing trial entries
- Follow the trial template exactly
- End with a ## Sources section listing all NCT file paths
- Write ONLY the markdown content — no preamble, no explanation
"""
        tasks.append(("trial", sponsor, page_path, prompt, _make_config("trial"), entries))

    # ── drug ───────────────────────────────────────────────────────────────────
    for drug_slug, signals in drug_buffer.items():
        page_path = f"drugs/{drug_slug}.md"
        current   = read_wiki_page(page_path)
        prompt = f"""Update the drug wiki page for: {page_path}
Page type: drug
Entity: {drug_slug}

{len(signals)} document(s) processed in this batch run.

Current page content (empty if new page):
---
{current if current else '[NEW PAGE — write from scratch using the template above]'}
---

Signals to integrate (ordered as processed):
{_signals_block(signals)}

Rules:
- Integrate ALL signals above into the drug page
- Follow the drug template exactly
- Preserve all existing content — only add or update what these documents affect
- Timeline section is append-only — add new rows at the top, never delete existing rows
- Clinical evidence section: accumulate all study findings, newest first
- End with a ## Sources section listing all raw file paths
- Write ONLY the markdown content — no preamble, no explanation
"""
        tasks.append(("drug", drug_slug, page_path, prompt, _make_config("drug"), signals))

    # ── indication ─────────────────────────────────────────────────────────────
    for ind_slug, signals in indication_buffer.items():
        page_path = f"indications/{ind_slug}/_index.md"
        current   = read_wiki_page(page_path)
        prompt = f"""Update the indication hub page for: {page_path}
Page type: indication_hub
Entity: {ind_slug}

{len(signals)} document(s) processed in this batch run.

Current page content (empty if new page):
---
{current if current else '[NEW PAGE — write from scratch using the template above]'}
---

Signals to integrate (ordered as processed):
{_signals_block(signals)}

Rules:
- Integrate ALL signals above into the indication hub page
- Follow the indication_hub template exactly
- Preserve all existing content — only add or update what these documents affect
- Timeline section is append-only — add new rows at the top, never delete existing rows
- End with a ## Sources section listing all raw file paths
- Write ONLY the markdown content — no preamble, no explanation
"""
        tasks.append(("indication_hub", ind_slug, page_path, prompt, _make_config("indication_hub"), signals))

    def _call_llm(task: tuple) -> tuple | None:
        page_type, entity, page_path, prompt, config, signals = task
        start = time.time()
        try:
            resp = client.models.generate_content(model=FLASH_MODEL, contents=prompt, config=config)
            return page_type, entity, page_path, resp.text, resp.usage_metadata, time.time() - start, signals
        except Exception as exc:
            logger.error(f"FLUSH | ERROR | {page_type} {entity}: {exc}")
            return None

    logger.info(
        f"FLUSH | Firing {len(tasks)} page writes in parallel — "
        f"company={len(company_buffer)}, trial={len(trial_buffer)}, "
        f"drug={len(drug_buffer)}, indication={len(indication_buffer)}"
    )
    with _cf.ThreadPoolExecutor(max_workers=min(len(tasks), 20)) as pool:
        results = list(pool.map(_call_llm, tasks, timeout=600))

    updated_paths   = []
    pages_for_index = []
    for result in results:
        if result is None:
            continue
        page_type, entity, page_path, content, usage, elapsed, signals = result
        n = len(signals)
        logger.info(f"FLUSH | {page_type.upper()} | {entity} — {n} signal(s), API took {elapsed:.1f}s")
        ledger.record(usage)
        write_wiki_page(page_path, content)
        updated_paths.append(page_path)
        logger.info(f"FLUSH | WROTE | {page_path}")
        all_drugs = (
            signals[-1]["extracted"].get("all_drugs_mentioned", [])
            if isinstance(signals[-1], dict) and "extracted" in signals[-1]
            else []
        )
        pages_for_index.append({
            "path":                page_path,
            "type":                page_type,
            "entity":              entity,
            "all_drugs_mentioned": all_drugs,
        })

    if pages_for_index:
        update_index_py(pages_for_index)

    return updated_paths


def compile_document(
    file_path: Path,
    context: dict,
    extraction_caches: dict | None = None,
    template_caches: dict | None = None,
    company_buffer: dict | None = None,
    trial_buffer: dict | None = None,
    drug_buffer: dict | None = None,
    indication_buffer: dict | None = None,
) -> list[str]:
    """3-step compiler chain: extract → validate → write.

    When batch buffers are provided, entity pages are accumulated across files
    and written once at end-of-batch via flush_buffered_pages(). Only event
    pages (unique per slug) are written per-file.

    Returns list of wiki page paths written in this call (event pages only in batch mode).
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

    # ctgov pre-filter — skip irrelevant trials before any LLM call
    if doc_type == "ctgov":
        try:
            _parsed_ctgov = json.loads(raw_content)
        except (json.JSONDecodeError, AttributeError):
            _parsed_ctgov = {}
        _passes, _skip_reason = _ctgov_passes_filter(_parsed_ctgov)
        if not _passes:
            logger.info(f"COMPILE | PRE-FILTER SKIP | {file_name} — {_skip_reason}")
            return []

    # build system prompt once — used for Step 3 (and Step 1 for non-ctgov types)
    system_prompt = build_system_prompt()

    # ── STEP 1: Extract ───────────────────────────────────────────────────────
    if doc_type == "ctgov":
        extracted = extract_ctgov_python(_parsed_ctgov)
        logger.info(f"STEP1 | PYTHON | {file_name} — LLM call skipped")
    else:
        cache_name   = extraction_caches.get(doc_type)
        step1_system = cache_name if cache_name else system_prompt
        try:
            extracted = compile_document_step1(
                file_path, context, raw_content, doc_type, step1_system,
            )
        except ValueError as e:
            logger.error(f"STEP1 | FAILED | {file_name}: {e}")
            raise

    # pubmed files never trigger event pages
    if doc_type == "pubmed":
        extracted["requires_new_event_page"] = False
        extracted["suggested_event_slug"]    = None
        extracted["event_type"]              = None
        extracted["event_summary"]           = None

    # ctgov events only for terminal status trials
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
    found_entities = collect_entity_pages(
        extracted, pages_to_update, context, file_path,
        company_buffer, drug_buffer, indication_buffer,
    )
    found_trials = collect_trial_and_event_pages(
        extracted, pages_to_update, file_path, context, trial_buffer,
    )

    if not pages_to_update:
        if found_entities or found_trials:
            logger.info(f"COMPILE | DONE | {file_name} — all signals buffered, no per-file writes")
        else:
            logger.info(f"COMPILE | DONE | {file_name} — no tracked entities, nothing written")
        return []

    # ── STEP 3: Write event pages (only per-file pages remain) ───────────────
    updated_paths = write_wiki_pages(
        pages_to_update, extracted, file_path, doc_type, system_prompt, template_caches,
    )

    if updated_paths:
        update_index_py(pages_to_update)

    logger.info(
        f"COMPILE | DONE | {file_name} → "
        f"{len(updated_paths)} pages written: {updated_paths}"
    )
    return updated_paths