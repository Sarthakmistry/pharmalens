"""
scripts/run_enriched.py

Run the compiler pipeline on the 101 ctgov files enriched by the DE job
(files listed in gs://pharmalens-raw/logs/ctgov_enriched.md).

Reads the log to get exact GCS paths, then compiles only those files —
skipping the full get_unprocessed_files() scan that would pick up thousands
of other ctgov files.

Usage:
    python scripts/run_enriched.py                # run all 101 enriched files
    python scripts/run_enriched.py --dry-run      # list files, no compilation
"""

import argparse
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
    classify_document,
    get_company_from_path,
    build_system_prompt,
    load_prompt,
    load_page_template,
    flush_buffered_pages,
    compile_document,
)
from agents.state import mark_file_processed

logger = get_logger("pharmalens.run_enriched")


def load_enriched_paths() -> list[Path]:
    """Download ctgov_enriched.md from GCS and extract the 101 file paths."""
    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket("pharmalens-raw")
    text = bucket.blob("logs/ctgov_enriched.md").download_as_text()

    # Lines like: - `raw/ctgov/roche/2026-04-07/NCT04338269.json` | NCT...
    paths = []
    for m in re.finditer(r"`(raw/ctgov/[^`]+\.json)`", text):
        paths.append(BASE_DIR / m.group(1))
    return paths


def build_caches() -> tuple[dict, dict]:
    """Build extraction + template Gemini caches for this run."""
    from google import genai
    from google.genai import types

    client = genai.Client()
    FLASH_MODEL = "gemini-2.5-flash"
    system_prompt = build_system_prompt()

    def make_cache(content: str, label: str) -> str:
        cache = client.caches.create(
            model=FLASH_MODEL,
            config=types.CreateCachedContentConfig(
                system_instruction=content,
                ttl="108000s",
            ),
        )
        logger.info(f"CACHE | '{label}' → {cache.name} ({cache.usage_metadata.total_token_count} tokens)")
        return cache.name

    extraction_caches = {
        "ctgov": make_cache(system_prompt + load_prompt("ctgov"), "extraction_ctgov"),
    }
    template_caches = {}
    for page_type in ["drug", "company", "trial", "event", "indication_hub"]:
        try:
            template_caches[page_type] = make_cache(
                system_prompt + load_page_template(page_type),
                f"template_{page_type}",
            )
        except ValueError as e:
            logger.warning(f"CACHE | Skipping template_{page_type}: {e}")

    return extraction_caches, template_caches


def run(dry_run: bool = False) -> None:
    paths = load_enriched_paths()
    logger.info(f"Loaded {len(paths)} enriched file paths from GCS log")

    if dry_run:
        for p in paths:
            print(p)
        return

    extraction_caches, template_caches = build_caches()

    company_buffer:    dict = {}
    trial_buffer:      dict = {}
    drug_buffer:       dict = {}
    indication_buffer: dict = {}

    ok: list[tuple] = []
    errors: list[tuple[Path, str]] = []
    rate_limit_hits: list[tuple[Path, str]] = []

    for i, file_path in enumerate(paths, 1):
        doc_type = classify_document(file_path)
        company  = get_company_from_path(file_path)
        parts    = file_path.parts
        date_idx = next((j for j, p in enumerate(parts) if re.match(r"\d{4}-\d{2}-\d{2}", p)), None)
        file_date = parts[date_idx] if date_idx is not None else None

        context = {
            "doc_type":  doc_type,
            "company":   company,
            "drug":      None,
            "file_date": file_date,
        }

        logger.info(f"[{i}/{len(paths)}] {file_path.name} | {company}")
        try:
            compile_document(
                file_path, context, extraction_caches, template_caches,
                company_buffer, trial_buffer, drug_buffer, indication_buffer,
            )
            ok.append((file_path, doc_type, company, None))
        except Exception as e:
            err_str = str(e)
            logger.error(f"ERROR | {file_path.name}: {err_str[:200]}")
            if "429" in err_str or "quota" in err_str.lower() or "rate" in err_str.lower():
                rate_limit_hits.append((file_path, err_str[:300]))
                logger.warning(f"RATE LIMIT | {file_path.name} — sleeping 30s before continuing")
                time.sleep(30)
            errors.append((file_path, err_str[:200]))

    logger.info(f"Per-file loop done. {len(ok)} ok, {len(errors)} errors, {len(rate_limit_hits)} rate-limit hits")

    # Flush all buffered entity + trial pages in one parallel pass
    total_signals = sum(
        len(v) for buf in (company_buffer, trial_buffer, drug_buffer, indication_buffer)
        for v in buf.values()
    )
    if total_signals:
        logger.info(f"FLUSH | {total_signals} signals across buffers — writing wiki pages...")
        try:
            flush_buffered_pages(
                company_buffer, trial_buffer, drug_buffer, indication_buffer,
                template_caches,
            )
            for file_path, doc_type, company, drug in ok:
                mark_file_processed(file_path, doc_type, "ok", company, drug)
            logger.info("FLUSH | done — all files marked processed")
        except Exception as e:
            logger.error(f"FLUSH | FAILED: {e}")
    else:
        logger.info("No buffered signals to flush")

    # Summary
    print(f"\n{'='*60}")
    print(f"Run complete: {len(ok)} compiled, {len(errors)} errors")
    if rate_limit_hits:
        print(f"\nRATE LIMIT HITS ({len(rate_limit_hits)}):")
        for path, msg in rate_limit_hits:
            print(f"  {path.name}: {msg}")
    if errors:
        print(f"\nERRORS ({len(errors)}):")
        for path, msg in errors:
            print(f"  {path.name}: {msg}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run compiler on DE-enriched ctgov files")
    parser.add_argument("--dry-run", action="store_true", help="List files without compiling")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
