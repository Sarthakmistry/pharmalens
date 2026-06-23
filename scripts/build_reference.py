"""
scripts/build_reference.py
Automated reference data refresh for PharmaLens.

Discovers drugs for each tracked company using three free public APIs
and writes candidate entries to reference/drugs_proposed.json for review.
After human review, run with --merge to promote candidates into drugs.json.

Data sources (no API key required):
  OpenFDA          https://api.fda.gov/drug/
  RxNorm           https://rxnav.nlm.nih.gov/REST/
  ClinicalTrials   https://clinicaltrials.gov/api/v2/

What stays manual:
  reference/companies.json   — which companies to track (business decision)
  reference/indications.json — therapeutic area slugs (product decision)

Usage:
  python3 scripts/build_reference.py            # discover → write drugs_proposed.json
  python3 scripts/build_reference.py --merge    # promote proposed → drugs.json
  python3 scripts/build_reference.py --company eli-lilly   # single company
"""

import json
import sys
import time
import argparse
from pathlib import Path

import requests

BASE_DIR      = Path(__file__).parent.parent
REFERENCE_DIR = BASE_DIR / "reference"
DRUGS_FILE    = REFERENCE_DIR / "drugs.json"
PROPOSED_FILE = REFERENCE_DIR / "drugs_proposed.json"

COMPANIES   = json.loads((REFERENCE_DIR / "companies.json").read_text())
INDICATIONS = json.loads((REFERENCE_DIR / "indications.json").read_text())

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "PharmaLens/1.0 (research; contact: pharmalens@iu.edu)"


# ── indication mapping ────────────────────────────────────────────────────────
# Two structured RxClass endpoints replace fragile label-text keyword scanning:
#   Stage 1 — ATC prefix table (WHO classification, deterministic)
#   Stage 2 — MEDRT may_treat conditions matched to indications.json MeSH terms
#              (best for oncology where ATC L01 is too coarse to pick a slug)

# ATC prefix table — longest prefix wins, checked top to bottom.
# Extend this list as indications.json grows; nothing else needs to change.
_ATC_PREFIX_MAP: list[tuple[str, str | list]] = [
    ("A10BJ", ["glp1-obesity", "type2-diabetes"]),  # GLP-1 analogues
    ("A10BX", "type2-diabetes"),                    # other glucose-lowering excl. insulins
    ("A10B",  "type2-diabetes"),                    # blood glucose lowering drugs
    ("A10A",  "type2-diabetes"),                    # insulins
    ("A10",   "type2-diabetes"),                    # all diabetes drugs (fallback)
    ("A08",   "glp1-obesity"),                      # anti-obesity drugs
    ("N06DA", "alzheimers"),                        # acetylcholinesterase inhibitors
    ("N06D",  "alzheimers"),                        # anti-dementia drugs
    ("C01",   "hf-htn"),
    ("C03",   "hf-htn"),
    ("C07",   "hf-htn"),
    ("C08",   "hf-htn"),
    ("C09",   "hf-htn"),
    # L01 (antineoplastics) left as None — ATC can't distinguish cancer types;
    # Stage 2 MEDRT fills in the specific oncology slug.
    ("L01",   None),
]

# MeSH/alias lookup built from indications.json for Stage 2 matching
_SLUG_MESH: dict[str, set[str]] = {}
for _slug, _data in INDICATIONS.items():
    _terms: set[str] = set()
    if _data.get("mesh"):
        _terms.add(_data["mesh"].lower())
    for _alias in _data.get("aliases", []):
        _terms.add(_alias.lower())
    if _data.get("ctgov_condition"):
        _terms.add(_data["ctgov_condition"].lower())
    _SLUG_MESH[_slug] = _terms


def _atc_to_slugs(atc_code: str) -> list[str]:
    """Longest-prefix ATC match → indication slug(s)."""
    atc_upper = atc_code.upper()
    for prefix, slug in _ATC_PREFIX_MAP:
        if atc_upper.startswith(prefix):
            if slug is None:
                return []
            return [slug] if isinstance(slug, str) else slug
    return []


def _condition_to_slug(condition: str) -> str | None:
    """Match a MEDRT condition string against indications.json MeSH/aliases."""
    cond_lower = condition.lower()
    for slug, terms in _SLUG_MESH.items():
        if any(term in cond_lower or cond_lower in term for term in terms):
            return slug
    return None


def rxnorm_indications(rxcui: str) -> tuple[list[str], bool]:
    """
    Derive indication slugs from RxCUI using two structured RxClass endpoints.
    Returns (matched_slugs, had_unmatched).

    Stage 1 — ATC prefix table: deterministic, covers diabetes/obesity/CNS/cardio.
    Stage 2 — MEDRT may_treat: MeSH-matched, covers specific oncology cancer types
              and anything ATC is too coarse to resolve.
    """
    slugs: set[str] = set()

    # Stage 1: ATC
    try:
        r = _SESSION.get(
            "https://rxnav.nlm.nih.gov/REST/rxclass/class/byRxcui.json",
            params={"rxcui": rxcui, "relaSource": "ATC"},
            timeout=10,
        )
        r.raise_for_status()
        for item in r.json().get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", []):
            atc_code = item.get("rxclassMinConceptItem", {}).get("classId", "")
            slugs.update(_atc_to_slugs(atc_code))
        time.sleep(0.2)
    except requests.RequestException:
        pass

    # Stage 2: MEDRT may_treat
    try:
        r = _SESSION.get(
            "https://rxnav.nlm.nih.gov/REST/rxclass/class/byRxcui.json",
            params={"rxcui": rxcui, "relaSource": "MEDRT", "rela": "may_treat"},
            timeout=10,
        )
        r.raise_for_status()
        for item in r.json().get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", []):
            condition = item.get("rxclassMinConceptItem", {}).get("className", "")
            slug = _condition_to_slug(condition)
            if slug:
                slugs.add(slug)
        time.sleep(0.2)
    except requests.RequestException:
        pass

    matched = sorted(slugs)
    return matched, len(matched) == 0


# ── RxNorm API ────────────────────────────────────────────────────────────────

def _label_text_fallback(label_text: str) -> tuple[list[str], bool]:
    """Last-resort indication mapping from raw label text for drugs with no RxCUI.
    Always sets had_unmatched=True so the entry is flagged for human review."""
    text_lower = label_text.lower()
    matched = set()
    for slug, terms in _SLUG_MESH.items():
        if any(term in text_lower for term in terms):
            matched.add(slug)
    return sorted(matched), True   # always flag — label text matching is unreliable


# ── RxNorm API ────────────────────────────────────────────────────────────────

def rxnorm_lookup(drug_name: str) -> dict | None:
    """
    Look up a drug name in RxNorm. Returns dict with:
      rxcui, inn, brand_names
    Returns None if not found.
    """
    try:
        r = _SESSION.get(
            "https://rxnav.nlm.nih.gov/REST/rxcui.json",
            params={"name": drug_name, "search": "1"},
            timeout=10,
        )
        r.raise_for_status()
        rxcui = r.json().get("idGroup", {}).get("rxnormId", [None])[0]
        if not rxcui:
            return None

        # get properties — canonical name (INN)
        props_r = _SESSION.get(
            f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/properties.json",
            timeout=10,
        )
        props_r.raise_for_status()
        props = props_r.json().get("properties", {})
        inn = props.get("name", drug_name).lower()

        # get related brand names (term type BN = brand name)
        related_r = _SESSION.get(
            f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/related.json",
            params={"tty": "BN"},
            timeout=10,
        )
        related_r.raise_for_status()
        concept_groups = related_r.json().get("relatedGroup", {}).get("conceptGroup", [])
        brand_names = []
        for group in concept_groups:
            for concept in group.get("conceptProperties", []):
                brand_names.append(concept["name"])

        time.sleep(0.25)  # be polite to the NLM API
        return {"rxcui": rxcui, "inn": inn, "brand_names": brand_names}

    except (requests.RequestException, KeyError, IndexError):
        return None


# ── OpenFDA: approved drugs per company ──────────────────────────────────────

def openfda_approved_drugs(company_slug: str, company_data: dict) -> list[dict]:
    """
    Query OpenFDA drug labels for all drugs manufactured/marketed by this company.
    Returns a list of raw drug dicts: {inn, brand_names, indications_text, approval_date}.

    Uses the company's full_name and its aliases to maximize recall.
    """
    full_name = company_data.get("full_name", "")
    candidates: dict[str, dict] = {}  # keyed by inn to deduplicate

    search_names = [full_name] + company_data.get("aliases", [])[:2]

    for name in search_names:
        try:
            r = _SESSION.get(
                "https://api.fda.gov/drug/label.json",
                params={
                    "search": f'openfda.manufacturer_name:"{name}"',
                    "limit": 100,
                },
                timeout=15,
            )
            if r.status_code == 404:
                continue
            r.raise_for_status()
            results = r.json().get("results", [])

            for result in results:
                openfda = result.get("openfda", {})
                generic_names = openfda.get("generic_name", [])
                brand_names   = openfda.get("brand_name", [])

                if not generic_names:
                    continue

                inn = generic_names[0].lower().strip()
                indication_text = " ".join(
                    result.get("indications_and_usage", [])
                )

                if inn not in candidates:
                    candidates[inn] = {
                        "inn": inn,
                        "brand_names": list({b.title() for b in brand_names}),
                        "indications_text": indication_text,
                        "approval_date": None,  # enriched separately if needed
                    }
                else:
                    # merge brand names
                    existing = set(candidates[inn]["brand_names"])
                    candidates[inn]["brand_names"] = list(
                        existing | {b.title() for b in brand_names}
                    )

            time.sleep(0.5)

        except requests.RequestException:
            continue

    return list(candidates.values())


# ── ClinicalTrials.gov v2: pipeline drugs ─────────────────────────────────────

def ctgov_pipeline_drugs(company_slug: str, company_data: dict) -> list[dict]:
    """
    Query ClinicalTrials.gov for Phase 2/3/4 interventional trials sponsored
    by this company. Returns investigational drug names not yet FDA-approved.

    These are pipeline candidates — will lack RxCUI and brand names until approved.
    """
    full_name = company_data.get("full_name", "")
    pipeline: dict[str, dict] = {}

    try:
        r = _SESSION.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params={
                "query.spons": full_name,
                "filter.advanced": (
                    "AREA[Phase]PHASE2 OR AREA[Phase]PHASE3 OR AREA[Phase]PHASE4"
                ),
                "filter.studyType": "INTERVENTIONAL",
                "format": "json",
                "pageSize": 200,
                "fields": (
                    "protocolSection.identificationModule,"
                    "protocolSection.armsInterventionsModule,"
                    "protocolSection.conditionsModule,"
                    "protocolSection.designModule"
                ),
            },
            timeout=20,
        )
        r.raise_for_status()
        studies = r.json().get("studies", [])

        for study in studies:
            proto = study.get("protocolSection", {})
            arms  = proto.get("armsInterventionsModule", {})
            conds = proto.get("conditionsModule", {})

            for intervention in arms.get("interventions", []):
                if intervention.get("type") not in ("DRUG", "BIOLOGICAL"):
                    continue
                name = intervention.get("name", "").strip()
                if not name or len(name) < 3:
                    continue

                name_lower = name.lower()
                if name_lower not in pipeline:
                    pipeline[name_lower] = {
                        "name": name,
                        "conditions": conds.get("conditions", []),
                    }

        time.sleep(0.5)

    except requests.RequestException:
        pass

    return list(pipeline.values())


# ── entry builder ─────────────────────────────────────────────────────────────

def build_drug_entry(
    inn: str,
    brand_names: list[str],
    company_slug: str,
    indications_text: str,
    rxnorm_data: dict | None,
) -> dict:
    """
    Assemble a drugs.json-compatible entry from collected data.
    Fields match the existing schema exactly so the pipeline can use it unchanged.

    Indication mapping priority:
      1. RxClass ATC codes (structured, WHO-maintained) — if RxCUI available
      2. RxClass MEDRT may_treat conditions (MeSH-matched) — if RxCUI available
      3. Keyword scan of FDA label text — fallback when no RxCUI
    """
    rxcui       = rxnorm_data["rxcui"] if rxnorm_data else None
    rx_brands   = rxnorm_data["brand_names"] if rxnorm_data else []
    merged_brands = list({b.title() for b in brand_names + rx_brands})

    if rxcui:
        indication_slugs, had_unmatched = rxnorm_indications(rxcui)
    else:
        # fallback: keyword scan of label text (less reliable, flags for review)
        indication_slugs, had_unmatched = _label_text_fallback(indications_text)

    return {
        "inn":                  inn,
        "rxcui":                rxcui,
        "brand_names":          merged_brands,
        "ndc_product":          [],
        "fda_approval_date":    None,   # TODO: enrich from OpenFDA drugsfda endpoint
        "patent_expiry":        None,   # TODO: enrich from FDA Orange Book
        "black_box_warning":    False,  # TODO: check boxed_warning field in label
        "black_box_summary":    None,
        "company":              company_slug,
        "indications":          indication_slugs,
        "_indications_unmatched": had_unmatched,  # flag for human review
        "drug_class":           None,   # TODO: enrich from RxNorm drug class API
        "mechanism":            None,
        "administration_routes": [],
        "biosimilar_risk":      None,
        "biosimilar_note":      None,
        "blockbuster":          None,
        "revenue_note":         None,
        "aliases":              merged_brands,  # start with brand names as aliases
        "_source":              "auto",         # marks as auto-generated for review
    }


# ── main discovery loop ───────────────────────────────────────────────────────

def discover(target_company: str | None = None) -> dict:
    """
    Run full discovery for all tracked companies (or one if target_company set).
    Returns proposed drug entries keyed by INN.
    """
    existing_drugs = json.loads(DRUGS_FILE.read_text()) if DRUGS_FILE.exists() else {}
    proposed: dict[str, dict] = {}

    companies_to_run = (
        {target_company: COMPANIES[target_company]}
        if target_company
        else COMPANIES
    )

    for slug, data in companies_to_run.items():
        print(f"\n── {slug} ──────────────────────────────────")

        # approved drugs via OpenFDA
        approved = openfda_approved_drugs(slug, data)
        print(f"  OpenFDA: {len(approved)} approved drug(s) found")

        for drug in approved:
            inn = drug["inn"]
            if inn in existing_drugs:
                print(f"    SKIP (already tracked): {inn}")
                continue

            rx = rxnorm_lookup(inn)
            entry = build_drug_entry(
                inn=inn,
                brand_names=drug["brand_names"],
                company_slug=slug,
                indications_text=drug["indications_text"],
                rxnorm_data=rx,
            )
            proposed[inn] = entry
            flag = " ⚠ indication unmatched" if entry["_indications_unmatched"] else ""
            print(f"    NEW: {inn} → {entry['indications']}{flag}")

        # pipeline drugs via ClinicalTrials (not yet in OpenFDA)
        pipeline = ctgov_pipeline_drugs(slug, data)
        print(f"  ClinicalTrials: {len(pipeline)} pipeline drug(s) found")

        existing_inns = set(existing_drugs) | set(proposed)
        for drug in pipeline:
            name_lower = drug["name"].lower()
            if name_lower in existing_inns:
                continue
            # try RxNorm — pipeline drugs may not resolve, that's expected
            rx = rxnorm_lookup(drug["name"])
            if rx:
                inn = rx["inn"]
                if inn in existing_inns or inn in proposed:
                    continue
                entry = build_drug_entry(
                    inn=inn,
                    brand_names=[],
                    company_slug=slug,
                    indications_text=" ".join(drug["conditions"]),
                    rxnorm_data=rx,
                )
            else:
                # no RxNorm match — record raw name as placeholder
                inn = name_lower
                entry = build_drug_entry(
                    inn=inn,
                    brand_names=[],
                    company_slug=slug,
                    indications_text=" ".join(drug["conditions"]),
                    rxnorm_data=None,
                )
                entry["_pipeline_only"] = True  # no RxCUI — needs manual review

            proposed[inn] = entry
            print(f"    PIPELINE: {inn}")

    return proposed


def merge(proposed: dict) -> None:
    """
    Promote proposed entries into drugs.json.
    Skips entries still flagged as _indications_unmatched — those need human review.
    Removes internal _ prefixed audit fields before writing.
    """
    existing = json.loads(DRUGS_FILE.read_text()) if DRUGS_FILE.exists() else {}

    added, skipped = 0, 0
    for inn, entry in proposed.items():
        if entry.get("_indications_unmatched") or entry.get("_pipeline_only"):
            print(f"  SKIP (needs review): {inn}")
            skipped += 1
            continue
        # strip internal audit fields
        clean = {k: v for k, v in entry.items() if not k.startswith("_")}
        existing[inn] = clean
        added += 1

    DRUGS_FILE.write_text(json.dumps(existing, indent=2))
    print(f"\nMerged {added} entries into drugs.json ({skipped} skipped — review drugs_proposed.json)")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PharmaLens reference data builder")
    parser.add_argument("--merge",   action="store_true", help="Promote proposed → drugs.json")
    parser.add_argument("--company", help="Run for a single company slug only")
    args = parser.parse_args()

    if args.merge:
        if not PROPOSED_FILE.exists():
            print("No drugs_proposed.json found. Run without --merge first.")
            sys.exit(1)
        proposed = json.loads(PROPOSED_FILE.read_text())
        merge(proposed)
    else:
        proposed = discover(target_company=args.company)
        PROPOSED_FILE.write_text(json.dumps(proposed, indent=2))
        print(f"\n── Summary ──────────────────────────────────")
        print(f"  {len(proposed)} new drug(s) written to reference/drugs_proposed.json")
        needs_review = sum(
            1 for e in proposed.values()
            if e.get("_indications_unmatched") or e.get("_pipeline_only")
        )
        print(f"  {needs_review} need manual review before merge")
        print(f"\nNext step:")
        print(f"  1. Review reference/drugs_proposed.json")
        print(f"  2. python3 scripts/build_reference.py --merge")
