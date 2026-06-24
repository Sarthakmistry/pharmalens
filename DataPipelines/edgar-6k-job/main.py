"""
PharmaLens — 6-K Press Release Ingestion Script
Pulls 6-K reports and their attached press releases for tracked foreign-listed pharma companies via edgartools.

Foreign filers (Novo Nordisk, Roche, AstraZeneca, Novartis, Sanofi, GSK, Takeda, Bayer)
file 6-K instead of 8-K. Structure is nearly identical: thin SEC wrapper + EX-99.1 press release.
Eisai is excluded per project scope decision.

Scope:
  - Form type : 6-K only
  - Extraction: Exhibit 99.1 (Press Release) text — 6-K wrapper is boilerplate, exhibit is the signal
  - Output    : raw/edgar/{company-slug}/6K/{YYYY-MM-DD}-6K-{accession}.txt
  - Cadence   : Event-driven (monthly or weekly via Cloud Scheduler)

Output file shape per filing:
  ---
  company:           Novo Nordisk
  cik:               353278
  company_slug:      novo-nordisk
  form:              6-K
  filing_date:       2025-11-07
  accession_number:  0000353278-25-000123
  has_press_release: true
  ---

  ## Exhibit EX-99.1 - Press Release
  [Cleaned text of the press release attachment]

Usage:
  # Local testing
  python pull_6k.py --local-out ./output
  python pull_6k.py --local-out ./output --seed
  python pull_6k.py --local-out ./output --company novo-nordisk

  # GCS production
  python pull_6k.py
  python pull_6k.py --seed

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

from bs4 import BeautifulSoup
from edgar import Company, set_identity
from google.cloud import storage

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

set_identity("PharmaLens pharmalens@youremail.com")

# Foreign filers: all submit 6-K to SEC.
# Eisai excluded per project scope decision.
# ⚠ = CIK not yet verified — confirm with: Company(CIK).name in a Python shell
COMPANIES: dict[str, int] = {
    "novo-nordisk":  353278,
    "roche":         889131,   
    "astrazeneca":   901832,
    "novartis":      1114448,   # confirmed
    "sanofi":        1121404,
    "gsk":           1131399,
    "takeda":        1395064,   # confirmed
    "bayer":         1144145,   
}

GCS_BUCKET_NAME = os.environ.get("GCS_BUCKET", "pharmalens-raw")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pharmalens.6k")


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
        f"form:              6-K\n"
        f"filing_date:       {filing_date}\n"
        f"accession_number:  {accession}\n"
        f"has_press_release: {'true' if has_press_release else 'false'}\n"
        f"---\n\n"
    )


def clean_html_text(html_data: bytes | str) -> str:
    """Safely decode and strip HTML from SEC exhibit files."""
    if isinstance(html_data, str):
        html_content = html_data
    else:
        html_content = html_data.decode("utf-8", errors="ignore")

    soup = BeautifulSoup(html_content, "html.parser")
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r'\n{3,}', '\n\n', text)


# ---------------------------------------------------------------------------
# Extraction Logic
# ---------------------------------------------------------------------------

def extract_press_release(filing) -> tuple[str, bool]:
    """
    Search 6-K attachments for a Press Release (usually EX-99.1 or EX-99.2).

    6-K wrappers are thin boilerplate — the real content is always in the exhibit.
    We apply the same matching logic as the 8-K pipeline.

    Returns (formatted_text, found_boolean).
    """
    try:
        attachments = filing.attachments
        target_att = None

        for att in attachments:
            doc_name = str(att.document).lower() if att.document else ""
            desc = str(att.description).lower() if att.description else ""

            # Match EX-99 variations in filename
            is_99_doc = any(x in doc_name for x in ['ex99-1', 'ex99_1', 'ex-99', 'ex991', 'ex99-2'])

            # Match 99.1 / 99.2 / 99-1 in SEC description column
            is_99_desc = any(x in desc for x in ['99.1', '99.2', '99-1'])

            # Match explicit press release keywords
            is_pr_text = any(x in desc for x in ['press release', 'earnings release', 'news release'])

            # Readable file formats only — skip XBRL/XML data files
            is_readable = doc_name.endswith(('.htm', '.html', '.txt'))

            if (is_99_doc or is_99_desc or is_pr_text) and is_readable:
                target_att = att
                break

        if not target_att:
            # Some 6-Ks don't have a separate exhibit — fall back to primary document
            log.info("    PR Exhibit: not found. Attempting primary document fallback.")
            return _fallback_primary_doc(filing)

        raw_bytes = target_att.download()
        clean_text = clean_html_text(raw_bytes)

        log.info(
            "    PR Exhibit: extracted %s - %s (%d chars)",
            target_att.document, target_att.description, len(clean_text),
        )

        heading = f"## Exhibit {target_att.document} - {target_att.description}\n\n"
        return heading + clean_text, True

    except Exception as e:
        log.warning("    PR Exhibit extraction failed: %s", e)
        return "", False


def _fallback_primary_doc(filing) -> tuple[str, bool]:
    """
    Last-resort fallback: use the 6-K's primary document text directly.
    This fires when there's no separate EX-99.1 — uncommon but happens
    for foreign filers that embed the press release in the main form body.
    """
    try:
        main_text = filing.text()
        if not main_text:
            log.info("    Primary doc fallback: no text returned.")
            return "", False

        clean = strip_ansi(main_text)
        log.info("    Primary doc fallback: %d chars", len(clean))
        return "## 6-K Primary Document\n\n" + clean, False  # has_press_release=False
    except Exception as e:
        log.warning("    Primary doc fallback failed: %s", e)
        return "", False


def extract_6k_content(filing) -> tuple[str, bool]:
    """
    Extract press release content from a 6-K filing.

    Unlike 8-K, we skip pulling the 6-K wrapper body — it's boilerplate
    ('Pursuant to the requirements of the Securities Exchange Act of 1934...')
    and adds no signal. We go straight to the exhibit.
    """
    return extract_press_release(filing)


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

def fetch_and_deposit_6k(
    slug: str,
    cik: int,
    since_date: str,
    local_out: Path | None,
    gcs_client,
) -> int:
    """
    Fetch all 6-K filings for one company filed on or after since_date.
    """
    log.info("── %s (CIK %d)", slug, cik)

    company = Company(cik)
    filings = company.get_filings(form="6-K").filter(date=f"{since_date}:")

    if not filings or len(filings) == 0:
        log.info("  No new 6-K filings since %s", since_date)
        return 0

    uploaded = 0

    for filing in filings:
        filing_date = str(filing.filing_date)
        accession   = str(filing.accession_number)

        filename  = f"{filing_date}-6K-{accession[-10:]}.txt"
        blob_path = f"raw/edgar/{slug}/6K/{filename}"

        log.info("  filing %s | → %s", filing_date, filename)

        try:
            body, has_pr = extract_6k_content(filing)

            if not body:
                log.warning("  [skip] no extractable content for %s %s", slug, filing_date)
                continue

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
        description="PharmaLens — 6-K Ingestion"
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
        log.info("SEED MODE — pulling 6-Ks since %s", since_date)
    else:
        since_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        log.info("MONTHLY MODE — pulling 6-Ks since %s", since_date)

    # ── Company filter ───────────────────────────────────────────────────────
    target = COMPANIES
    if args.companies:
        target = {k: v for k, v in COMPANIES.items() if k in args.companies}
        log.info("Filtered to: %s", list(target.keys()))

    # ── Main loop ────────────────────────────────────────────────────────────
    total = 0
    for slug, cik in target.items():
        count = fetch_and_deposit_6k(
            slug       = slug,
            cik        = cik,
            since_date = since_date,
            local_out  = local_out,
            gcs_client = gcs_client,
        )
        total += count
        time.sleep(1)

    dest = str(local_out.resolve()) if local_out else f"gs://{GCS_BUCKET_NAME}/raw/edgar/"
    log.info("Done. %d 6-K files deposited to %s", total, dest)


if __name__ == "__main__":
    main()