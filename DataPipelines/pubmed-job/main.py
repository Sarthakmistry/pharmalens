"""
PharmaLens — PubMed Ingestion Script
Pulls abstracts for tracked drugs via NCBI E-utilities (esearch + efetch).

Scope:
  - Article types: Clinical Trials and Meta-Analyses only
  - Lookback: 3 years from today
  - Output: raw/pubmed/{drug-slug}/abstract-{pmid}.json
  - Cadence: weekly (run via Cloud Scheduler on Mondays)

Output JSON shape per file:
  {
    "pmid": "33164953",
    "doi": "10.3233/NRE-203210",
    "pubmed_date": "2020-11-10",
    "publication_year": "2020",
    "title": "...",
    "journal": "NeuroRehabilitation",
    "journal_abbr": "NeuroRehabilitation",
    "publication_types": ["Journal Article", "Randomized Controlled Trial"],
    "abstract": {"BACKGROUND": "...", "METHODS": "...", "RESULTS": "..."},
    "mesh_major_topics": ["Stroke Rehabilitation", ...],
    "first_author": {"name": "Jane Smith", "affiliation": "Harvard Medical School"}
  }

Usage:
  python pubmed_ingest.py [--dry-run] [--drug semaglutide]

Environment:
  GCS_BUCKET        GCS bucket name
  NCBI_API_KEY      Optional but strongly recommended — raises rate limit
                    from 3 req/s to 10 req/s. Register free at:
                    https://www.ncbi.nlm.nih.gov/account/
"""

import argparse
import json
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path

import requests
from google.cloud import storage

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# INN drug names → company mapping (for logging / context only)
# Keys are the GCS path slugs used in raw/pubmed/{drug-slug}/
TRACKED_DRUGS: dict[str, str] = {
    # GLP-1 / Obesity
    "semaglutide": "novo-nordisk",
    "tirzepatide": "eli-lilly",
    "liraglutide": "novo-nordisk",
    "retatrutide": "eli-lilly",
    "cagrilintide": "novo-nordisk",
    # Oncology — immuno-oncology
    "pembrolizumab": "merck",
    "nivolumab": "bristol-myers-squibb",
    "atezolizumab": "roche-genentech",
    "durvalumab": "astrazeneca",
    "ipilimumab": "bristol-myers-squibb",
    "trastuzumab-deruxtecan": "astrazeneca",
    "osimertinib": "astrazeneca",
    # Cardiovascular
    "sacubitril-valsartan": "novartis",
    "inclisiran": "novartis",
    "dapagliflozin": "astrazeneca",
    "apixaban": "pfizer",
    # CNS / Alzheimer's
    "lecanemab": "biogen",
    "donanemab": "eli-lilly",
    "aducanumab": "biogen",
    # Rare disease
    "ivacaftor-tezacaftor-elexacaftor": "vertex",
    "dupilumab": "regeneron",
    "isatuximab": "sanofi",
    "ravulizumab": "regeneron",
}

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
LOOKBACK_DAYS_DEFAULT = 7
# Article type filters accepted by the NCBI publication type field
ARTICLE_TYPES = ["Clinical Trial", "Meta-Analysis"]
# Batch size for efetch (NCBI max is 10,000 but keep small to be polite)
EFETCH_BATCH = 100
# Throttle between API calls (seconds). With API key: can lower to 0.11.
REQUEST_DELAY = 0.34  # ~3 req/s, safe without API key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pharmalens.pubmed")


# ---------------------------------------------------------------------------
# NCBI helpers
# ---------------------------------------------------------------------------

def _ncbi_params(extra: dict) -> dict:
    """Base parameters shared by all NCBI E-utility calls."""
    params = {"retmode": "json", **extra}
    api_key = os.getenv("NCBI_API_KEY")
    if api_key:
        params["api_key"] = api_key
    return params


def esearch(drug: str, date_range: tuple[str, str]) -> list[str]:
    """
    Search PubMed for PMIDs matching a drug + article-type filters.

    date_range: ("YYYY/MM/DD", "YYYY/MM/DD")  — mindate / maxdate
    Returns list of PMID strings.
    """
    mindate, maxdate = date_range
    # Build the query: drug name AND (clinical trial OR meta-analysis)
    # using MeSH/PT (publication type) field tags
    pt_filter = " OR ".join(f'"{at}"[PT]' for at in ARTICLE_TYPES)
    query = f'"{drug}"[tiab] AND ({pt_filter})'

    params = _ncbi_params({
        "db": "pubmed",
        "term": query,
        "mindate": mindate,
        "maxdate": maxdate,
        "datetype": "pdat",   # publication date
        "retmax": 1000,       # upper bound per drug
        "usehistory": "y",    # server-side result set for follow-on efetch
    })

    url = f"{NCBI_BASE}/esearch.fcgi"
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    result = data.get("esearchresult", {})
    pmids = result.get("idlist", [])
    count = int(result.get("count", 0))
    log.info("  esearch: %s → %d hits (returning %d PMIDs)", drug, count, len(pmids))
    time.sleep(REQUEST_DELAY)
    return pmids


def efetch_abstracts(pmids: list[str]) -> list[dict]:
    """
    Fetch abstract XML for a batch of PMIDs and parse into dicts.

    Returns list of:
      {pmid, title, abstract, authors, journal, pub_date, doi, article_types}
    """
    if not pmids:
        return []

    records = []
    for i in range(0, len(pmids), EFETCH_BATCH):
        batch = pmids[i : i + EFETCH_BATCH]
        params = _ncbi_params({
            "db": "pubmed",
            "id": ",".join(batch),
            "rettype": "abstract",
            "retmode": "xml",
        })
        url = f"{NCBI_BASE}/efetch.fcgi"
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        records.extend(_parse_pubmed_xml(resp.text))
        time.sleep(REQUEST_DELAY)

    return records


def _parse_pubmed_xml(xml_text: str) -> list[dict]:
    """
    Parse a PubMed XML response into a list of record dicts.
    Uses stdlib xml.etree — no lxml dependency required.
    """
    import xml.etree.ElementTree as ET

    root = ET.fromstring(xml_text)
    records = []

    for article in root.findall(".//PubmedArticle"):
        try:
            rec = _extract_article(article)
            if rec:
                records.append(rec)
        except Exception as exc:
            pmid_el = article.find(".//PMID")
            pmid = pmid_el.text if pmid_el is not None else "unknown"
            log.warning("  parse error for PMID %s: %s", pmid, exc)

    return records


def _extract_article(article) -> dict | None:
    """Extract fields from a single <PubmedArticle> element."""

    def text(el):
        return "".join(el.itertext()).strip() if el is not None else ""

    # PMID
    pmid_el = article.find(".//PMID[@Version='1']") or article.find(".//PMID")
    pmid = text(pmid_el)
    if not pmid:
        return None

    # Title
    title = text(article.find(".//ArticleTitle"))

    # Abstract — preserve section labels as dict keys; unlabelled → "TEXT"
    abstract: dict[str, str] = {}
    for abs_el in article.findall(".//AbstractText"):
        label = (abs_el.get("Label") or "TEXT").upper()
        abstract[label] = text(abs_el)

    # Journal full name and abbreviation
    journal = text(article.find(".//Journal/Title"))
    journal_abbr = text(article.find(".//Journal/ISOAbbreviation"))

    # Publication date
    # Prefer structured Year/Month/Day; fall back to MedlineDate string.
    pubmed_date = ""
    publication_year = ""
    pub_date_el = article.find(".//PubDate")
    if pub_date_el is not None:
        year = text(pub_date_el.find("Year"))
        month = text(pub_date_el.find("Month"))
        day = text(pub_date_el.find("Day"))
        medline = text(pub_date_el.find("MedlineDate"))
        if year:
            publication_year = year
            # Normalise month name → zero-padded number if needed
            month_num = _month_to_num(month) if month else "01"
            day_num = day.zfill(2) if day else "01"
            pubmed_date = f"{year}-{month_num}-{day_num}"
        elif medline:
            # e.g. "2020 Nov-Dec" or "2020 Winter"
            publication_year = medline[:4]
            pubmed_date = medline  # keep raw string when no clean date available

    # DOI
    doi = ""
    for id_el in article.findall(".//ArticleIdList/ArticleId"):
        if id_el.get("IdType") == "doi":
            doi = text(id_el)
            break

    # Publication types
    publication_types = [
        text(pt) for pt in article.findall(".//PublicationTypeList/PublicationType")
    ]

    # MeSH major topics (starred descriptors — MajorTopicYN="Y")
    mesh_major_topics = []
    for descriptor in article.findall(".//MeshHeadingList/MeshHeading/DescriptorName"):
        if descriptor.get("MajorTopicYN") == "Y":
            mesh_major_topics.append(text(descriptor))

    # First author: name + affiliation
    first_author: dict[str, str] = {}
    first_author_el = article.find(".//AuthorList/Author")
    if first_author_el is not None:
        last = text(first_author_el.find("LastName"))
        fore = text(first_author_el.find("ForeName")) or text(first_author_el.find("Initials"))
        affil = text(first_author_el.find(".//AffiliationInfo/Affiliation"))
        first_author = {
            "name": f"{fore} {last}".strip() if fore else last,
            "affiliation": affil,
        }

    return {
        "pmid": pmid,
        "doi": doi,
        "pubmed_date": pubmed_date,
        "publication_year": publication_year,
        "title": title,
        "journal": journal,
        "journal_abbr": journal_abbr,
        "publication_types": publication_types,
        "abstract": abstract,
        "mesh_major_topics": mesh_major_topics,
        "first_author": first_author,
    }


def _month_to_num(month: str) -> str:
    """Convert month name or abbreviation to zero-padded number string."""
    months = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04",
        "may": "05", "jun": "06", "jul": "07", "aug": "08",
        "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }
    # Already numeric
    if month.isdigit():
        return month.zfill(2)
    return months.get(month[:3].lower(), "01")


# ---------------------------------------------------------------------------
# JSON serialisation
# ---------------------------------------------------------------------------

def render_json(record: dict) -> str:
    """Serialise a parsed PubMed record to the canonical JSON string."""
    return json.dumps(record, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# GCS upload
# ---------------------------------------------------------------------------

def gcs_blob_exists(bucket: storage.Bucket, blob_name: str) -> bool:
    return bucket.blob(blob_name).exists()


def upload_to_gcs(
    bucket: storage.Bucket,
    blob_name: str,
    content: str,
    dry_run: bool = False,
) -> bool:
    """Upload a string as a UTF-8 blob. Returns True if uploaded, False if skipped."""
    if gcs_blob_exists(bucket, blob_name):
        log.debug("  skip (exists): %s", blob_name)
        return False

    if dry_run:
        log.info("  [DRY RUN] would upload: %s", blob_name)
        return True

    blob = bucket.blob(blob_name)
    blob.upload_from_string(content, content_type="application/json; charset=utf-8")
    log.info("  uploaded: %s", blob_name)
    return True


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def date_range(days_back: int) -> tuple[str, str]:
    """Return (mindate, maxdate) covering the last `days_back` days."""
    today = date.today()
    mindate = (today - timedelta(days=days_back)).strftime("%Y/%m/%d")
    maxdate = today.strftime("%Y/%m/%d")
    return mindate, maxdate


def run(
    drugs: list[str] | None = None,
    dry_run: bool = False,
    local_out: Path | None = None,
    days_back: int = LOOKBACK_DAYS_DEFAULT,
) -> None:
    """
    Main entry point.

    Args:
        drugs:     Subset of drug slugs to process. None = all tracked drugs.
        dry_run:   Log what would be uploaded without touching GCS.
        local_out: If set, write files to this local directory instead of GCS
                   (useful for smoke-testing without GCP credentials).
    """
    target_drugs = drugs if drugs else list(TRACKED_DRUGS.keys())
    dr = date_range(days_back)
    log.info(
        "PharmaLens PubMed ingest | %d drugs | %s → %s | days_back=%d | dry_run=%s",
        len(target_drugs),
        *dr,
        days_back,
        dry_run,
    )

    # GCS client (skip if local_out mode)
    bucket = None
    if not local_out and not dry_run:
        gcs_client = storage.Client()
        bucket_name = os.environ["GCS_BUCKET"]
        bucket = gcs_client.bucket(bucket_name)
        log.info("GCS bucket: %s", bucket_name)

    total_new = 0
    total_skip = 0

    for drug_slug in target_drugs:
        log.info("── %s", drug_slug)

        # Use the INN name as the search term (spaces, not hyphens)
        drug_name = drug_slug.replace("-", " ")
        pmids = esearch(drug_name, dr)

        if not pmids:
            log.info("  no results")
            continue

        records = efetch_abstracts(pmids)
        log.info("  fetched %d abstracts", len(records))
        ingest_date = date.today().strftime("%Y-%m-%d")
        for rec in records:
            blob_name = f"raw/pubmed/{drug_slug}/{ingest_date}/abstract-{rec['pmid']}.json"
            content = render_json(rec)

            if local_out:
                # Local write mode
                
                out_path = local_out / drug_slug / ingest_date / f"abstract-{rec['pmid']}.json"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                if not out_path.exists():
                    out_path.write_text(content, encoding="utf-8")
                    log.info("  wrote: %s", out_path)
                    total_new += 1
                else:
                    total_skip += 1
            elif dry_run:
                uploaded = upload_to_gcs(bucket, blob_name, content, dry_run=True)
                total_new += int(uploaded)
                total_skip += int(not uploaded)
            else:
                uploaded = upload_to_gcs(bucket, blob_name, content)
                total_new += int(uploaded)
                total_skip += int(not uploaded)

    log.info(
        "Done. %d new files deposited, %d already existed (skipped).",
        total_new,
        total_skip,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PharmaLens — PubMed abstract ingestion"
    )
    parser.add_argument(
        "--drug",
        metavar="SLUG",
        action="append",
        dest="drugs",
        help="INN drug slug to process (repeatable). Default: all tracked drugs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be uploaded without writing to GCS.",
    )
    parser.add_argument(
        "--local-out",
        metavar="DIR",
        help="Write files to a local directory instead of GCS (for testing).",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=LOOKBACK_DAYS_DEFAULT,
        help="How many days back to pull. Default: 7 (weekly job). Use 365 for initial load.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    local_out = Path(args.local_out) if args.local_out else None
    run(drugs=args.drugs, dry_run=args.dry_run, local_out=local_out, days_back=args.days_back)