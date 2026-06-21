"""
scripts/backfill_company_events.py

One-time migration: parse the "### Recent events" markdown table already
sitting in each companies/{slug}.md page and write its rows into the new
canonical CSV store (agents/wiki_gcs.py:append_company_events).

Why this is needed: the compiler no longer asks the LLM to write the Recent
events table — it renders the table from the CSV on every flush instead (see
agents/compiler.py:_render_events_table). The CSV starts empty for every
company, so without this backfill the next real pipeline run would render an
empty/near-empty table and silently drop years of existing event history.

Safe to re-run: each row's dedup key is a content hash (date + event text), so
re-running this script against an unchanged page is a no-op.

Usage:
    python scripts/backfill_company_events.py            # local wiki/ dir
    GCS_MODE=true python scripts/backfill_company_events.py   # production bucket
"""

import hashlib
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from agents.logger import get_logger
from agents.wiki_gcs import read_wiki, list_wiki, append_company_events

logger = get_logger("pharmalens.backfill_events")

_VALID_TYPES = {"sec", "trial", "research"}


def _section_lines(body: str, heading: str) -> list[str]:
    """Lines belonging to a named ### heading, up to the next heading of equal
    or shallower depth. Mirrors frontend/src/parseWiki.js:sectionLines()."""
    lines = body.splitlines()
    start = next((i for i, l in enumerate(lines) if re.match(r"^#{1,4}\s", l) and heading in l), None)
    if start is None:
        return []
    level = len(re.match(r"^(#+)", lines[start]).group(1))
    end = len(lines)
    for i in range(start + 1, len(lines)):
        m = re.match(r"^(#+)\s", lines[i])
        if m and len(m.group(1)) <= level:
            end = i
            break
    return lines[start + 1:end]


def _parse_markdown_table(lines: list[str]) -> list[dict]:
    table_lines = [l for l in lines if l.strip().startswith("|")]
    if len(table_lines) < 2:
        return []
    headers = [h.strip() for h in table_lines[0].split("|") if h.strip()]
    rows = []
    for line in table_lines[2:]:  # skip header + separator row
        cells = [c.strip() for c in line.split("|") if c.strip() != ""]
        if not cells:
            continue
        row = dict(zip(headers, cells))
        rows.append(row)
    return rows


def _strip_wikilink(text: str) -> str:
    return re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", text or "").strip()


def parse_existing_events_table(company_md: str) -> list[dict]:
    """Extract rows from an already-written company page's Recent events table."""
    lines = _section_lines(company_md, "Recent events")
    rows = []
    for r in _parse_markdown_table(lines):
        event = _strip_wikilink(r.get("Event", ""))
        if not event:
            continue
        raw_type = (r.get("Type") or "").strip().lower()
        row_type = raw_type if raw_type in _VALID_TYPES else "sec"
        date = (r.get("Date") or "").strip()
        digest = hashlib.md5(f"{date}|{event}".encode()).hexdigest()[:10]
        rows.append({
            "date":      date,
            "type":      row_type,
            "event":     event,
            "signal":    _strip_wikilink(r.get("Signal", "")),
            "source":    _strip_wikilink(r.get("Source", "")),
            "file_path": f"backfill:{digest}",
        })
    return rows


def main():
    company_pages = [p for p in list_wiki("companies/") if p.endswith(".md")]
    logger.info(f"BACKFILL | Found {len(company_pages)} company page(s)")

    total_rows = 0
    for page_path in company_pages:
        slug = Path(page_path).stem
        content = read_wiki(page_path)
        if not content:
            continue
        rows = parse_existing_events_table(content)
        if not rows:
            logger.info(f"BACKFILL | {slug} — no Recent events table found, skipping")
            continue
        append_company_events(slug, rows)
        total_rows += len(rows)
        logger.info(f"BACKFILL | {slug} — {len(rows)} row(s) migrated")

    logger.info(f"BACKFILL | Done — {total_rows} total row(s) across {len(company_pages)} page(s)")


if __name__ == "__main__":
    main()
