"""
PharmaLens — 8-K Press Release Ingestion Script
Pulls 8-K reports and their attached press releases for tracked US-listed pharma companies via edgartools.

Scope:
  - Form type : 8-K only
  - Extraction: Main 8-K body + Exhibit 99.1/99.2 (Press Release) text
  - Output    : raw/edgar/{company-slug}/{YYYY-MM-DD}-8K-{accession}.txt
  - Cadence   : Event-driven (monthly or weekly via Cloud Scheduler)

Output file shape per filing:
  ---
  company:          Eli Lilly
  cik:              59478
  company_slug:     eli-lilly
  form:             8-K
  filing_date:      2025-11-07
  accession_number: 0000059478-25-000123
  has_press_release: true
  ---

  ## 8-K Main Body
  [prose text of the 8-K]

  ---

  ## Exhibit EX-99.1 - Press Release
  [Cleaned text of the press release attachment]

Usage:
  # Local testing
  python pull_8k.py --local-out ./output
  python pull_8k.py --local-out ./output --seed
  python pull_8k.py --local-out ./output --company eli-lilly

  # GCS production
  python pull_8k.py
  python pull_8k.py --seed

Environment:
  GOOGLE_APPLICATION_CREDENTIALS   Path to GCP service account key (local runs)
  GCS_BUCKET                        Override default bucket name
"""

import argparse
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

# NOTE: Requires beautifulsoup4 for parsing Exhibit HTML
from bs4 import BeautifulSoup
from edgar import Company, set_identity
from google.cloud import storage

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

set_identity("PharmaLens pharmalens@youremail.com")

COMPANIES: dict[str, int] = {
    "eli-lilly":             59478,
    "merck":                 310158,
    "pfizer":                78003,
    "johnson-and-johnson":   200406,
    "abbvie":                1551152,
    "amgen":                 318154,
    "gilead":                882184,
    "biogen":                875320,
    "regeneron":             872589,
    "vertex":                875320,
    "bristol-myers-squibb":  14272,
}

GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET", "sample-pharmalens")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pharmalens.8k")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_ansi(text: str) -> str:
    """Remove terminal colour/box-drawing codes embedded by edgartools Rich renderer."""
    return re.compile(r'\x1b\[[0-9;]*m').sub('', text)


def build_frontmatter(
    company_name: str,
    cik: int,
    slug: str,
    filing_date: str,
    accession: str,
    has_press_release: bool,
) -> str:
    return (
        f"---\n"
        f"company:           {company_name}\n"
        f"cik:               {cik}\n"
        f"company_slug:      {slug}\n"
        f"form:              8-K\n"
        f"filing_date:       {filing_date}\n"
        f"accession_number:  {accession}\n"
        f"has_press_release: {'true' if has_press_release else 'false'}\n"
        f"---\n\n"
    )

def clean_html_text(html_data: bytes | str) -> str:
    """Safely decode and strip HTML from SEC exhibit files."""
    
    # Check if the data is already a string
    if isinstance(html_data, str):
        html_content = html_data
    else:
        # If it's bytes, safely decode it
        html_content = html_data.decode("utf-8", errors="ignore")
        
    soup = BeautifulSoup(html_content, "html.parser")
    # Extract text and replace multiple newlines with double newlines
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r'\n{3,}', '\n\n', text)


# ---------------------------------------------------------------------------
# Extraction Logic
# ---------------------------------------------------------------------------

def extract_press_release(filing) -> tuple[str, bool]:
    """
    Search 8-K attachments for a Press Release (usually EX-99.1 or EX-99.2).
    Returns (formatted_text, found_boolean).
    """
    try:
        attachments = filing.attachments
        target_att = None
        
        for att in attachments:
            # Safely cast to string and lowercase
            doc_name = str(att.document).lower() if att.document else ""
            desc = str(att.description).lower() if att.description else ""
            
            # 1. Look for EX-99 variations in the filename (SEC uses dashes, rarely dots)
            is_99_doc = any(x in doc_name for x in ['ex99-1', 'ex99_1', 'ex-99', 'ex991', 'ex99-2'])
            
            # 2. Look for 99.1 or 99.2 in the SEC description column
            is_99_desc = any(x in desc for x in ['99.1', '99.2', '99-1'])
            
            # 3. Look for explicit keywords in the description
            is_pr_text = any(x in desc for x in ['press release', 'earnings release', 'news release'])
            
            # Match any of the above, AND ensure it's a readable text/html file (ignore XML data files)
            if (is_99_doc or is_99_desc or is_pr_text) and doc_name.endswith(('.htm', '.html', '.txt')):
                target_att = att
                break
                
        if not target_att:
            log.info("    PR Exhibit: not found in attachments")
            return "", False
            
        # Download returns raw bytes for the attachment
        raw_bytes = target_att.download()
        clean_text = clean_html_text(raw_bytes)
        
        log.info("    PR Exhibit: extracted %s - %s (%d chars)", 
                 target_att.document, target_att.description, len(clean_text))
                 
        heading = f"## Exhibit {target_att.document} - {target_att.description}\n\n"
        return heading + clean_text, True

    except Exception as e:
        log.warning("    PR Exhibit extraction failed: %s", e)
        return "", False


def extract_8k_content(filing) -> tuple[str, bool]:
    """
    Extract the main body of the 8-K and append the press release if it exists.
    """
    sections = []
    
    # ── Main 8-K Body ────────────────────────────────────────────────────────
    try:
        main_text = filing.text()
        if main_text:
            clean_main = strip_ansi(main_text)
            sections.append("## 8-K Main Body\n\n" + clean_main)
    except Exception as e:
        log.debug("    Main 8-K body extraction failed: %s", e)

    # ── Attached Press Release ───────────────────────────────────────────────
    pr_text, pr_found = extract_press_release(filing)
    if pr_text:
        sections.append(pr_text)

    return "\n\n---\n\n".join(sections), pr_found


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_local(local_out: Path, blob_path: str, content: str) -> bool:
    """Write content to a local directory mirroring the GCS path structure."""
    out_path = local_out / blob_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        log.info("  [skip] already exists: %s", out_path)
        return False
    out_path.write_text(content, encoding="utf-8")
    log.info("  [ok] %s", out_path)
    return True


def upload_to_gcs(gcs_client, bucket_name: str, blob_path: str, content: str) -> bool:
    """Upload content string to GCS."""
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(content, content_type="text/plain; charset=utf-8")
    log.info("  [ok] gs://%s/%s", bucket_name, blob_path)
    return True


# ---------------------------------------------------------------------------
# Per-company fetch loop
# ---------------------------------------------------------------------------

def fetch_and_deposit_8k(
    slug: str,
    cik: int,
    since_date: str,
    local_out: Path | None,
    gcs_client,
) -> int:
    """
    Fetch all 8-K filings for one company filed on or after since_date.
    """
    log.info("── %s (CIK %d)", slug, cik)

    company = Company(cik)
    filings = company.get_filings(form="8-K").filter(date=f"{since_date}:")

    if not filings or len(filings) == 0:
        log.info("  No new 8-K filings since %s", since_date)
        return 0

    uploaded = 0

    for filing in filings:
        filing_date = str(filing.filing_date)
        accession   = str(filing.accession_number)

        # 8-Ks don't map cleanly to quarters, so we use date and accession string
        filename  = f"{filing_date}-8K-{accession[-10:]}.txt"
        blob_path = f"raw/edgar/{slug}/8K/{filename}"

        log.info("  filing %s | → %s", filing_date, filename)

        try:
            body, has_pr = extract_8k_content(filing)

            frontmatter = build_frontmatter(
                company_name      = str(company.name),
                cik               = cik,
                slug              = slug,
                filing_date       = filing_date,
                accession         = accession,
                has_press_release = has_pr,
            )

            content = frontmatter + body

            if local_out:
                success = write_local(local_out, blob_path, content)
            else:
                success = upload_to_gcs(gcs_client, GCS_BUCKET_NAME, blob_path, content)

            uploaded += int(success)

        except Exception as e:
            log.error("  [!] failed for %s %s: %s", slug, filing_date, e)

        time.sleep(1)  # stay within SEC 10 req/s rate limit

    return uploaded


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PharmaLens — 8-K Ingestion"
    )
    parser.add_argument(
        "--local-out",
        metavar="DIR",
        help="Write files to a local directory instead of GCS.",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Pull 1-year lookback (initial corpus). Default: 30-day window.",
    )
    parser.add_argument(
        "--company",
        metavar="SLUG",
        action="append",
        dest="companies",
        help="Restrict to one company slug (repeatable). Default: all.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    # ── Output destination ───────────────────────────────────────────────────
    local_out  = Path(args.local_out) if args.local_out else None
    gcs_client = None

    if local_out:
        local_out.mkdir(parents=True, exist_ok=True)
        log.info("LOCAL MODE — output: %s", local_out.resolve())
    else:
        gcs_client = storage.Client()
        log.info("GCS MODE — bucket: gs://%s/", GCS_BUCKET_NAME)

    # ── Date window ──────────────────────────────────────────────────────────
    now = datetime.now()
    seed_mode = args.seed or os.environ.get("SEED", "").lower() == "true"
    if seed_mode:
        since_date = (now - timedelta(days=365)).strftime("%Y-%m-%d")
        log.info("SEED MODE — pulling 8-Ks since %s", since_date)
    else:
        since_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        log.info("MONTHLY MODE — pulling 8-Ks since %s", since_date)

    # ── Company filter ───────────────────────────────────────────────────────
    target = COMPANIES
    if args.companies:
        target = {k: v for k, v in COMPANIES.items() if k in args.companies}
        log.info("Filtered to: %s", list(target.keys()))

    # ── Main loop ────────────────────────────────────────────────────────────
    total = 0
    for slug, cik in target.items():
        count = fetch_and_deposit_8k(
            slug       = slug,
            cik        = cik,
            since_date = since_date,
            local_out  = local_out,
            gcs_client = gcs_client,
        )
        total += count
        time.sleep(1)

    dest = str(local_out.resolve()) if local_out else f"gs://{GCS_BUCKET_NAME}/raw/edgar/"
    log.info("Done. %d 8-K files deposited to %s", total, dest)


if __name__ == "__main__":
    main()