"""
PharmaLens — 10-Q Ingestion Script
Pulls quarterly reports for tracked US-listed pharma companies via edgartools.

Scope:
  - Form type : 10-Q only (foreign filers use 20-F/6-K — separate pipeline)
  - Extraction: XBRL product-level revenue first, MD&A prose second
  - Output    : raw/edgar/{company-slug}/{YYYY}-Q{n}-10Q.txt
  - Cadence   : quarterly (run via Cloud Scheduler ~45 days after quarter end)

Output file shape per filing:
  ---
  company:          Eli Lilly
  cik:              59478
  company_slug:     eli-lilly
  form:             10-Q
  filing_date:      2025-11-07
  period_of_report: 2025-09-30
  accession_number: 0000059478-25-000123
  xbrl_available:   true
  ---

  ## Product Revenue (XBRL)
  Mounjaro: $7,409.0M (2025-09-30)
  Zepbound: $4,261.0M (2025-09-30)
  ...

  ## Key Financials (XBRL)
  Total Revenue: $19,292,000,000 (2025-09-30)
  Net Income: $6,636,000,000 (2025-09-30)
  ...

  ---

  ## Management Discussion & Analysis
  [prose text]

Usage:
  # Local testing (no GCS)
  python pull_10q.py --local-out ./output
  python pull_10q.py --local-out ./output --seed
  python pull_10q.py --local-out ./output --company eli-lilly

  # GCS production
  python pull_10q.py
  python pull_10q.py --seed

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

import pandas as pd
from edgar import Company, set_identity
from google.cloud import storage

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

set_identity("PharmaLens pharmalens@youremail.com")

# US-listed companies only.
# Foreign filers (Novo Nordisk, AstraZeneca, Novartis, Roche, Sanofi,
# GSK, Takeda, Eisai, Bayer) file 20-F / 6-K — handled separately.
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

# XBRL revenue concepts to try in order — companies use different tags
REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
]

# Key income statement concepts → human label for the output file
KEY_FINANCIALS: list[tuple[str, str]] = [
    ("Revenues",                          "Total Revenue"),
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "Total Revenue"),
    ("NetIncomeLoss",                     "Net Income"),
    ("ResearchAndDevelopmentExpense",     "R&D Expense"),
    ("SellingGeneralAndAdministrativeExpense", "SG&A Expense"),
    ("OperatingIncomeLoss",               "Operating Income"),
    ("EarningsPerShareDiluted",           "EPS Diluted"),
    ("GrossProfit",                       "Gross Profit"),
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("pharmalens.10q")

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
    period: str,
    xbrl_available: bool,
) -> str:
    return (
        f"---\n"
        f"company:          {company_name}\n"
        f"cik:              {cik}\n"
        f"company_slug:     {slug}\n"
        f"form:             10-Q\n"
        f"filing_date:      {filing_date}\n"
        f"period_of_report: {period}\n"
        f"accession_number: {accession}\n"
        f"xbrl_available:   {'true' if xbrl_available else 'false'}\n"
        f"---\n\n"
    )


def derive_quarter(period: str) -> tuple[int, int]:
    """
    Derive (year, quarter) from a period string like '2025-09-30'.
    Falls back to current date on parse failure.
    """
    try:
        dt = datetime.strptime(period[:10], "%Y-%m-%d")
        return dt.year, (dt.month - 1) // 3 + 1
    except Exception:
        now = datetime.now()
        return now.year, (now.month - 1) // 3 + 1


# ---------------------------------------------------------------------------
# XBRL extraction — structured financials
# ---------------------------------------------------------------------------

def extract_product_revenue(xbrl, current_period: str) -> str:
    """
    Query XBRL for product-level revenue (ProductOrServiceAxis dimension).

    Fixes applied vs naive approach:
    - Only shows the CURRENT period (not prior year comparatives) to avoid
      duplicate rows — prior year data comes from the previous filing.
    - Deduplicates by (label, period_end) keeping the highest value per drug,
      because XBRL tags the same drug multiple times across US/Intl/Total members.
    - Shows US and International split where available, otherwise Total only.

    Returns a formatted section string, or empty string if unavailable.
    """
    for concept in REVENUE_CONCEPTS:
        try:
            df = (
                xbrl.query()
                .by_concept(concept)
                .by_dimension("ProductOrServiceAxis")
                .to_dataframe("label", "value", "period_end", "concept")
            )
            if df.empty:
                continue

            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df = df.dropna(subset=["value"])
            if df.empty:
                continue

            # Filter to current period only — eliminates prior-year duplicate rows
            if current_period:
                period_df = df[df["period_end"] == current_period]
                if period_df.empty:
                    # Fallback: use the most recent period in the data
                    period_df = df[df["period_end"] == df["period_end"].max()]
                df = period_df

            # Deduplicate: keep only the maximum value per drug label.
            # XBRL tags Skyrizi-US, Skyrizi-International, Skyrizi-Total as
            # separate facts — we want Total (highest) per drug.
            df = (
                df.groupby("label", as_index=False)["value"]
                .max()
                .sort_values("value", ascending=False)
            )

            df["value_m"] = (df["value"] / 1e6).round(1)

            lines = [f"## Product Revenue (XBRL) — {current_period}\n"]
            for _, row in df.iterrows():
                lines.append(f"{row['label']}: ${row['value_m']}M")

            log.info(
                "    product revenue: %d unique products via %s", len(df), concept
            )
            return "\n".join(lines)

        except Exception as e:
            log.debug("    product revenue via %s failed: %s", concept, e)
            continue

    log.info("    product revenue: no dimensional XBRL data found")
    return ""


def extract_key_financials(xbrl, current_period: str) -> str:
    """
    Query XBRL for consolidated income statement figures.

    Shows current period only — no prior year comparatives, no duplicate rows.
    Uses undimensioned facts (by_dimension(None)) for consolidated totals.
    """
    seen_labels: set[str] = set()
    lines = [f"## Key Financials (XBRL) — {current_period}\n"]
    found = 0

    for concept, label in KEY_FINANCIALS:
        if label in seen_labels:
            continue
        try:
            df = (
                xbrl.query()
                .by_concept(concept)
                .by_dimension(None)
                .to_dataframe("label", "value", "period_end")
            )
            if df.empty:
                continue

            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df = df.dropna(subset=["value"])
            if df.empty:
                continue

            # Current period only
            if current_period:
                period_df = df[df["period_end"] == current_period]
                if not period_df.empty:
                    df = period_df
                else:
                    df = df[df["period_end"] == df["period_end"].max()]

            # Take the single best row (max value if multiple remain)
            best = df.loc[df["value"].idxmax()]
            value_m = best["value"] / 1e6
            lines.append(f"{label}: ${value_m:,.1f}M")
            seen_labels.add(label)
            found += 1

        except Exception as e:
            log.debug("    key financials %s failed: %s", concept, e)
            continue

    if found == 0:
        return ""

    log.info("    key financials: %d concepts extracted", found)
    return "\n".join(lines)


def extract_segment_revenue(xbrl, current_period: str) -> str:
    """
    Fallback: segment-level revenue (StatementBusinessSegmentsAxis).
    Used when ProductOrServiceAxis is not tagged — e.g. AbbVie tags by
    therapeutic area (Immunology, Oncology, Neuroscience) rather than drug name.
    """
    for concept in REVENUE_CONCEPTS:
        try:
            df = (
                xbrl.query()
                .by_concept(concept)
                .by_dimension("StatementBusinessSegmentsAxis")
                .to_dataframe("label", "value", "period_end")
            )
            if df.empty:
                continue

            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            df = df.dropna(subset=["value"])
            if df.empty:
                continue

            # Current period only
            if current_period:
                period_df = df[df["period_end"] == current_period]
                if not period_df.empty:
                    df = period_df

            # Deduplicate by label
            df = (
                df.groupby("label", as_index=False)["value"]
                .max()
                .sort_values("value", ascending=False)
            )
            df["value_m"] = (df["value"] / 1e6).round(1)

            lines = [f"## Segment Revenue (XBRL) — {current_period}\n"]
            for _, row in df.iterrows():
                lines.append(f"{row['label']}: ${row['value_m']}M")

            log.info("    segment revenue: %d segments found", len(df))
            return "\n".join(lines)

        except Exception as e:
            log.debug("    segment revenue via %s failed: %s", concept, e)
            continue

    return ""


# ---------------------------------------------------------------------------
# Prose extraction — MD&A and fallback text
# ---------------------------------------------------------------------------

def extract_mda(filing) -> str:
    try:
        tenq = filing.obj()

        # get_item_with_part returns str directly — args are "I", "2" not "part_i", "item_2"
        mda = tenq.get_item_with_part("I", "2")
        if mda and len(mda.strip()) > 200:
            clean = strip_ansi(mda)
            log.info("    MD&A: extracted via get_item_with_part (%d chars)", len(clean))
            return "## Management Discussion & Analysis\n\n" + clean

    except Exception as e:
        log.debug("    MD&A get_item_with_part failed: %s", e)

    # Fallback: access sections dict directly
    try:
        tenq = filing.obj()
        section = tenq.sections["part_i_item_2"]
        if section:
            text = section.text()
            clean = strip_ansi(text)
            if len(clean.strip()) > 200:
                log.info("    MD&A: extracted via sections dict (%d chars)", len(clean))
                return "## Management Discussion & Analysis\n\n" + clean

    except Exception as e:
        log.debug("    MD&A sections dict failed: %s", e)

    log.warning("    MD&A: section detection failed — compiler will rely on XBRL section only")
    return ""


# ---------------------------------------------------------------------------
# Master extraction — combines XBRL + prose
# ---------------------------------------------------------------------------

def extract_tenq_content(filing) -> tuple[str, bool]:
    """
    Extract all relevant content from a 10-Q filing.

    Strategy:
      1. XBRL product revenue  → deduplicated drug:$value for current period
      2. XBRL key financials   → consolidated income statement, current period
      3. XBRL segment revenue  → fallback if product axis not tagged
      4. MD&A prose            → narrative context, pricing, pipeline

    Returns (content_string, xbrl_available).
    """
    sections = []
    xbrl_available = False

    # Derive current period from filing metadata for XBRL filtering
    current_period = str(filing.period_of_report) if filing.period_of_report else ""

    # ── XBRL structured section ─────────────────────────────────────────────
    try:
        xbrl = filing.xbrl()

        if xbrl is not None:
            xbrl_available = True
            log.info("    XBRL: available | current period: %s", current_period)

            product_rev = extract_product_revenue(xbrl, current_period)
            if product_rev:
                sections.append(product_rev)

            key_fin = extract_key_financials(xbrl, current_period)
            if key_fin:
                sections.append(key_fin)

            # Segment fallback only if product axis found nothing
            if not product_rev:
                seg_rev = extract_segment_revenue(xbrl, current_period)
                if seg_rev:
                    sections.append(seg_rev)
        else:
            log.info("    XBRL: not available for this filing")

    except Exception as e:
        log.warning("    XBRL extraction failed: %s", e)

    # ── MD&A prose section ───────────────────────────────────────────────────
    mda = extract_mda(filing)
    if mda:
        sections.append(mda)

    return "\n\n---\n\n".join(sections), xbrl_available


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
    """Upload content string to GCS. No exists() check — objectCreator role only."""
    bucket = gcs_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(content, content_type="text/plain; charset=utf-8")
    log.info("  [ok] gs://%s/%s", bucket_name, blob_path)
    return True


# ---------------------------------------------------------------------------
# Per-company fetch loop
# ---------------------------------------------------------------------------

def fetch_and_deposit_10q(
    slug: str,
    cik: int,
    since_date: str,
    local_out: Path | None,
    gcs_client,
) -> int:
    """
    Fetch all 10-Q filings for one company filed on or after since_date,
    extract content, and deposit to raw/edgar/{slug}/{YYYY}-Q{n}-10Q.txt.
    """
    log.info("── %s (CIK %d)", slug, cik)

    company = Company(cik)
    filings = company.get_filings(form="10-Q").filter(date=f"{since_date}:")

    if not filings or len(filings) == 0:
        log.info("  No new 10-Q filings since %s", since_date)
        return 0

    uploaded = 0

    for filing in filings:
        filing_date = str(filing.filing_date)
        period      = str(filing.period_of_report) if filing.period_of_report else filing_date
        accession   = str(filing.accession_number)
        year, q     = derive_quarter(period)

        # §4.3 naming convention: YYYY-Q{n}-10Q.txt
        filename  = f"{year}-Q{q}-10Q.txt"
        blob_path = f"raw/edgar/{slug}/10Q/{filename}"

        log.info(
            "  filing %s | period %s | → %s",
            filing_date, period, filename,
        )

        try:
            body, xbrl_ok = extract_tenq_content(filing)

            frontmatter = build_frontmatter(
                company_name   = str(company.name),
                cik            = cik,
                slug           = slug,
                filing_date    = filing_date,
                accession      = accession,
                period         = period,
                xbrl_available = xbrl_ok,
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
        description="PharmaLens — 10-Q ingestion"
    )
    parser.add_argument(
        "--local-out",
        metavar="DIR",
        help=(
            "Write files to a local directory instead of GCS. "
            "Mirrors GCS path structure under DIR. "
            "No GCP credentials required."
        ),
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Pull 2-year lookback (initial corpus). Default: 120-day window.",
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
    if args.seed:
        since_date = (now - timedelta(days=365)).strftime("%Y-%m-%d")
        log.info("SEED MODE — pulling 10-Qs since %s", since_date)
    else:
        since_date = (now - timedelta(days=120)).strftime("%Y-%m-%d")
        log.info("QUARTERLY MODE — pulling 10-Qs since %s", since_date)

    # ── Company filter ───────────────────────────────────────────────────────
    target = COMPANIES
    if args.companies:
        target = {k: v for k, v in COMPANIES.items() if k in args.companies}
        log.info("Filtered to: %s", list(target.keys()))

    # ── Main loop ────────────────────────────────────────────────────────────
    total = 0
    for slug, cik in target.items():
        count = fetch_and_deposit_10q(
            slug       = slug,
            cik        = cik,
            since_date = since_date,
            local_out  = local_out,
            gcs_client = gcs_client,
        )
        total += count
        time.sleep(1)

    dest = str(local_out.resolve()) if local_out else f"gs://{GCS_BUCKET_NAME}/raw/edgar/"
    log.info("Done. %d 10-Q files deposited to %s", total, dest)


if __name__ == "__main__":
    main()