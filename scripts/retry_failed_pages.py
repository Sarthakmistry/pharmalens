"""
scripts/retry_failed_pages.py

Retry the 5 wiki pages that failed during the enriched-run flush:
  - trials/sanofi.md          (44 signals, timeout)
  - companies/regeneron.md    (429)
  - drugs/bevacizumab.md      (429)
  - drugs/nivolumab.md        (499 CANCELLED)
  - indications/oncology-nsclc/_index.md (429)

Strategy:
  1. Re-run compile_document on only the source files for those entities
     (sanofi + roche + regeneron from the enriched log)
  2. Strip buffers to only the 5 failed entities
  3. Flush each entity one at a time (sequential, not parallel) with 30s backoff
     so transient 429s don't abort the whole batch
"""

import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from agents.logger import get_logger
from agents.compiler import (
    get_company_from_path,
    build_system_prompt,
    load_prompt,
    load_page_template,
    compile_document,
    flush_buffered_pages,
)
from agents.state import mark_file_processed

logger = get_logger("pharmalens.retry_pages")

# Only these entities need to be written
FAILED_TRIALS      = {"sanofi"}
FAILED_COMPANIES   = {"regeneron"}
FAILED_DRUGS       = {"bevacizumab", "nivolumab"}
FAILED_INDICATIONS = {"oncology-nsclc"}

# Companies whose enriched source files feed those entities
RELEVANT_COMPANIES = {"sanofi", "roche", "regeneron"}


def load_enriched_paths() -> list[Path]:
    from google.cloud import storage
    client = storage.Client()
    text = client.bucket("pharmalens-raw").blob("logs/ctgov_enriched.md").download_as_text()
    paths = []
    for m in re.finditer(r"`(raw/ctgov/[^`]+\.json)`", text):
        p = BASE_DIR / m.group(1)
        if get_company_from_path(p) in RELEVANT_COMPANIES:
            paths.append(p)
    logger.info(f"Loaded {len(paths)} source files for {RELEVANT_COMPANIES}")
    return paths


def build_caches() -> tuple[dict, dict]:
    from google import genai
    from google.genai import types
    gc = genai.Client()
    FLASH = "gemini-2.5-flash"
    sp = build_system_prompt()

    def cache(content, label):
        c = gc.caches.create(
            model=FLASH,
            config=types.CreateCachedContentConfig(system_instruction=content, ttl="108000s"),
        )
        logger.info(f"CACHE | {label} → {c.name}")
        return c.name

    ext = {"ctgov": cache(sp + load_prompt("ctgov"), "extraction_ctgov")}
    tpl = {}
    for pt in ["drug", "company", "trial", "event", "indication_hub"]:
        try:
            tpl[pt] = cache(sp + load_page_template(pt), f"template_{pt}")
        except ValueError as e:
            logger.warning(f"CACHE | skip {pt}: {e}")
    return ext, tpl


def flush_one(buf_name: str, buffer: dict, template_caches: dict, sleep_after: int = 15) -> bool:
    """Flush a single-entity buffer with retry. Returns True on success."""
    slug = next(iter(buffer))
    empty = {"company": {}, "trial": {}, "drug": {}, "indication_hub": {}}

    for attempt in range(1, 4):
        try:
            if buf_name == "company":
                flush_buffered_pages(buffer, {}, {}, {}, template_caches)
            elif buf_name == "trial":
                flush_buffered_pages({}, buffer, {}, {}, template_caches)
            elif buf_name == "drug":
                flush_buffered_pages({}, {}, buffer, {}, template_caches)
            elif buf_name == "indication_hub":
                flush_buffered_pages({}, {}, {}, buffer, template_caches)
            logger.info(f"RETRY | WROTE | {buf_name}/{slug} (attempt {attempt})")
            time.sleep(sleep_after)
            return True
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower() or "CANCELLED" in err or "timed out" in err.lower():
                wait = 45 * attempt
                logger.warning(f"RETRY | {buf_name}/{slug} attempt {attempt} — rate limit/timeout, sleeping {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"RETRY | {buf_name}/{slug} attempt {attempt} — non-retryable: {err[:200]}")
                return False

    logger.error(f"RETRY | {buf_name}/{slug} — all 3 attempts failed")
    return False


def run() -> None:
    paths = load_enriched_paths()
    extraction_caches, template_caches = build_caches()

    company_buffer:    dict = {}
    trial_buffer:      dict = {}
    drug_buffer:       dict = {}
    indication_buffer: dict = {}
    ok: list[tuple] = []

    for i, file_path in enumerate(paths, 1):
        from agents.compiler import classify_document
        doc_type = classify_document(file_path)
        company  = get_company_from_path(file_path)
        parts    = file_path.parts
        date_idx = next((j for j, p in enumerate(parts) if re.match(r"\d{4}-\d{2}-\d{2}", p)), None)
        file_date = parts[date_idx] if date_idx is not None else None
        context = {"doc_type": doc_type, "company": company, "drug": None, "file_date": file_date}

        logger.info(f"[{i}/{len(paths)}] {file_path.name} | {company}")
        try:
            compile_document(
                file_path, context, extraction_caches, template_caches,
                company_buffer, trial_buffer, drug_buffer, indication_buffer,
            )
            ok.append((file_path, doc_type, company, None))
        except Exception as e:
            err = str(e)
            logger.error(f"ERROR | {file_path.name}: {err[:200]}")
            if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                logger.warning("Rate limit — sleeping 30s")
                time.sleep(30)

    logger.info(f"Per-file loop: {len(ok)} ok, {len(paths)-len(ok)} errors")

    # Strip buffers to only the failed entities
    for slug in list(company_buffer):
        if slug not in FAILED_COMPANIES:
            del company_buffer[slug]
    for slug in list(trial_buffer):
        if slug not in FAILED_TRIALS:
            del trial_buffer[slug]
    for slug in list(drug_buffer):
        if slug not in FAILED_DRUGS:
            del drug_buffer[slug]
    for slug in list(indication_buffer):
        if slug not in FAILED_INDICATIONS:
            del indication_buffer[slug]

    logger.info(f"Filtered to: trials={list(trial_buffer)}, companies={list(company_buffer)}, "
                f"drugs={list(drug_buffer)}, indications={list(indication_buffer)}")

    # Flush each entity separately and sequentially with backoff
    results = {}

    for slug, sigs in trial_buffer.items():
        logger.info(f"Flushing trial/{slug} ({len(sigs)} signals)...")
        results[f"trials/{slug}.md"] = flush_one("trial", {slug: sigs}, template_caches, sleep_after=20)

    for slug, sigs in company_buffer.items():
        logger.info(f"Flushing company/{slug} ({len(sigs)} signals)...")
        results[f"companies/{slug}.md"] = flush_one("company", {slug: sigs}, template_caches)

    for slug, sigs in drug_buffer.items():
        logger.info(f"Flushing drug/{slug} ({len(sigs)} signals)...")
        results[f"drugs/{slug}.md"] = flush_one("drug", {slug: sigs}, template_caches)

    for slug, sigs in indication_buffer.items():
        logger.info(f"Flushing indication/{slug} ({len(sigs)} signals)...")
        results[f"indications/{slug}/_index.md"] = flush_one("indication_hub", {slug: sigs}, template_caches)

    print(f"\n{'='*60}")
    print("Retry results:")
    for page, success in results.items():
        print(f"  {'OK  ' if success else 'FAIL'} {page}")

    if all(results.values()):
        print("\nAll pages written successfully.")
    else:
        print(f"\nStill failing: {[p for p, s in results.items() if not s]}")


if __name__ == "__main__":
    run()
