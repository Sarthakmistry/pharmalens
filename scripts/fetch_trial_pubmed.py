"""
scripts/fetch_trial_pubmed.py

Fetch PubMed articles for trials that have submitted results to ClinicalTrials.gov
(has_results: true in wiki/trials/{company}.md).

Uses the NCT ID as the PubMed search term — sponsors register their results papers
in PubMed with the NCT ID, so this is high-precision with very little noise.

Output: raw/pubmed/{drug_slug}/{today}/abstract-{pmid}.json
        (same schema as existing pubmed raw files so the compiler handles them unchanged)

Usage:
    python3 scripts/fetch_trial_pubmed.py              # all companies
    python3 scripts/fetch_trial_pubmed.py --dry-run    # print what would be fetched
    python3 scripts/fetch_trial_pubmed.py --company takeda
"""

import argparse
import json
import re
import time
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
import yaml

BASE_DIR  = Path(__file__).parent.parent
WIKI_DIR  = BASE_DIR / "wiki"
RAW_DIR   = BASE_DIR / "raw" / "pubmed"
TODAY     = date.today().isoformat()

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "PharmaLens/1.0 (research; pharmalens@iu.edu)"

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


# ── helpers ───────────────────────────────────────────────────────────────────


def _normalize_drug_name(name: str) -> str:
    """Lower-case, strip special chars — matches existing pubmed folder naming."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def _already_fetched(pmid: str) -> bool:
    """Return True if this PMID already exists anywhere under raw/pubmed/."""
    return bool(list(RAW_DIR.rglob(f"abstract-{pmid}.json")))


def pubmed_search(nct_id: str) -> list[str]:
    """Return list of PMIDs that cite this NCT ID."""
    try:
        r = _SESSION.get(
            f"{EUTILS}/esearch.fcgi",
            params={"db": "pubmed", "term": nct_id, "retmode": "json", "retmax": 10},
            timeout=15,
        )
        r.raise_for_status()
        return r.json().get("esearchresult", {}).get("idlist", [])
    except requests.RequestException as e:
        print(f"    WARN esearch failed for {nct_id}: {e}")
        return []


def pubmed_fetch(pmid: str) -> dict | None:
    """
    Fetch full record for one PMID via efetch (XML).
    Returns dict matching existing raw schema or None on failure.
    """
    try:
        r = _SESSION.get(
            f"{EUTILS}/efetch.fcgi",
            params={"db": "pubmed", "id": pmid, "retmode": "xml", "rettype": "abstract"},
            timeout=20,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"    WARN efetch failed for PMID {pmid}: {e}")
        return None

    try:
        root = ET.fromstring(r.text)
        art  = root.find(".//MedlineCitation/Article")
        if art is None:
            return None

        # title
        title_el = art.find("ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""

        # journal
        journal_el   = art.find("Journal/Title")
        journal_abbr = art.find("Journal/ISOAbbreviation")
        journal      = journal_el.text.strip() if journal_el is not None else ""
        j_abbr       = journal_abbr.text.strip() if journal_abbr is not None else ""

        # pub date
        pub_year = ""
        pub_date = ""
        for date_path in ("Journal/JournalIssue/PubDate", "ArticleDate"):
            d = art.find(date_path)
            if d is not None:
                year  = d.findtext("Year", "")
                month = d.findtext("Month", "01")
                day   = d.findtext("Day", "01")
                if year:
                    pub_year = year
                    try:
                        month_num = time.strptime(month, "%b").tm_mon if not month.isdigit() else int(month)
                        pub_date  = f"{year}-{month_num:02d}-{int(day):02d}"
                    except Exception:
                        pub_date = year
                    break

        # abstract — may be structured (sections) or plain
        abstract_el = art.find("Abstract")
        abstract: dict | str = {}
        if abstract_el is not None:
            texts = abstract_el.findall("AbstractText")
            if len(texts) == 1 and not texts[0].get("Label"):
                abstract = texts[0].text or ""
            else:
                for t in texts:
                    label = t.get("Label", "TEXT")
                    abstract[label] = "".join(t.itertext()).strip()

        # publication types
        pub_types = [
            pt.text for pt in root.findall(".//PublicationTypeList/PublicationType")
            if pt.text
        ]

        # DOI
        doi = ""
        for loc in root.findall(".//ArticleIdList/ArticleId"):
            if loc.get("IdType") == "doi":
                doi = loc.text or ""
                break

        # MeSH major topics
        mesh = [
            mh.findtext("DescriptorName", "")
            for mh in root.findall(".//MeshHeadingList/MeshHeading")
            if mh.find("DescriptorName[@MajorTopicYN='Y']") is not None
        ]

        # first author
        first_author = ""
        author = root.find(".//AuthorList/Author")
        if author is not None:
            last  = author.findtext("LastName", "")
            first = author.findtext("ForeName", "")
            first_author = f"{last}, {first}".strip(", ")

        return {
            "pmid":              pmid,
            "doi":               doi,
            "pubmed_date":       pub_date,
            "publication_year":  pub_year,
            "title":             title,
            "journal":           journal,
            "journal_abbr":      j_abbr,
            "publication_types": pub_types,
            "abstract":          abstract,
            "mesh_major_topics": mesh,
            "first_author":      first_author,
        }

    except ET.ParseError as e:
        print(f"    WARN XML parse error for PMID {pmid}: {e}")
        return None


# ── trial scanner ─────────────────────────────────────────────────────────────


def collect_trials(company_filter: str | None = None) -> list[dict]:
    """
    Scan wiki/trials/ and return all trials with has_results: true.
    Each entry: {nct_id, company, drug_slug}
    """
    results = []
    pattern = f"{company_filter}.md" if company_filter else "*.md"

    for trial_file in sorted(WIKI_DIR.glob(f"trials/{pattern}")):
        company = trial_file.stem
        content = trial_file.read_text()
        blocks  = re.split(r"^---$", content, flags=re.MULTILINE)

        for block in blocks:
            try:
                meta = yaml.safe_load(block.strip())
            except yaml.YAMLError:
                continue
            if not isinstance(meta, dict) or "trial_id" not in meta:
                continue
            if not meta.get("has_results"):
                continue

            # derive drug slug from intervention_name if present, else fall back to company
            intervention = str(meta.get("intervention_name") or "").split("|")[0].strip()
            drug_slug = _normalize_drug_name(intervention) if intervention else company

            results.append({
                "nct_id":    meta["trial_id"],
                "company":   company,
                "drug_slug": drug_slug,
                "phase":     meta.get("phase"),
            })

    return results


# ── main ──────────────────────────────────────────────────────────────────────


def run(dry_run: bool = False, company_filter: str | None = None) -> None:
    trials = collect_trials(company_filter)
    print(f"Found {len(trials)} trials with has_results: true")

    fetched = skipped = failed = 0

    for trial in trials:
        nct_id  = trial["nct_id"]
        company = trial["company"]
        slug    = trial["drug_slug"]

        print(f"\n{nct_id} ({company}, Phase {trial['phase']}, drug: {slug})")

        if dry_run:
            print(f"  [dry-run] would search PubMed for {nct_id}")
            continue

        pmids = pubmed_search(nct_id)
        time.sleep(0.34)  # NCBI rate limit: 3 req/s without API key

        if not pmids:
            print(f"  No PubMed results")
            continue

        print(f"  Found PMIDs: {pmids}")

        out_dir = RAW_DIR / slug / TODAY
        out_dir.mkdir(parents=True, exist_ok=True)

        for pmid in pmids:
            if _already_fetched(pmid):
                print(f"  SKIP {pmid} (already on disk)")
                skipped += 1
                continue

            record = pubmed_fetch(pmid)
            time.sleep(0.34)

            if record is None:
                print(f"  FAIL {pmid}")
                failed += 1
                continue

            out_path = out_dir / f"abstract-{pmid}.json"
            out_path.write_text(json.dumps(record, indent=2))
            print(f"  SAVED {pmid} → {out_path.relative_to(BASE_DIR)}")
            fetched += 1

    if not dry_run:
        print(f"\n── Done ──────────────────────────────────")
        print(f"  Fetched: {fetched}  |  Skipped (dup): {skipped}  |  Failed: {failed}")
        print(f"\nNext step: run the compiler pipeline to process these files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch PubMed articles for trials with results")
    parser.add_argument("--dry-run",  action="store_true", help="Print what would be fetched without API calls")
    parser.add_argument("--company",  help="Limit to one company slug (e.g. takeda)")
    args = parser.parse_args()

    run(dry_run=args.dry_run, company_filter=args.company)
