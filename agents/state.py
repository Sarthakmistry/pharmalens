"""
agents/state.py
Single source of truth for all processing state in PharmaLens.

Tracks:
  1. Raw files processed (all source types)
  2. NCT IDs seen (to determine new vs update for trial entries)

State is stored in agents/processing_state.json
No index.md — wiki navigation uses build_wiki_map() at query time.
"""

import json
from pathlib import Path
from datetime import datetime
from agents.logger import get_logger

logger = get_logger("pharmalens.state")

try:
    BASE_DIR = Path(__file__).parent.parent
except NameError:
    BASE_DIR = Path.cwd().parent  # notebook fallback

STATE_FILE = BASE_DIR / "agents" / "processing_state.json"
RAW_DIR    = BASE_DIR / "raw"
WIKI_DIR   = BASE_DIR / "wiki"


# ── load / save ───────────────────────────────────────────────────────────────

def _load() -> dict:
    """Load state. Uses GCS when GCS_MODE=true, otherwise reads local JSON file."""
    from agents.wiki_gcs import _gcs_enabled, load_state
    if _gcs_enabled():
        return load_state()
    if not STATE_FILE.exists():
        return {
            "processed_files": {},
            "processed_nct_ids": {},
            "last_lint_run": None,
        }
    try:
        return json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        logger.warning("STATE | state file corrupted — starting fresh")
        return {"processed_files": {}, "processed_nct_ids": {}}


def _save(state: dict):
    """Persist state. Uses GCS when GCS_MODE=true, otherwise writes local JSON file atomically."""
    from agents.wiki_gcs import _gcs_enabled, save_state
    if _gcs_enabled():
        save_state(state)
        return
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.rename(STATE_FILE)


# ── file tracking ─────────────────────────────────────────────────────────────

def is_file_processed(file_path: Path) -> bool:
    """Check if a raw file has already been processed."""
    return str(file_path) in _load()["processed_files"]


def mark_file_processed(
    file_path: Path,
    doc_type: str,
    status: str,
    company: str | None = None,
    drug: str | None = None,
):
    """
    Record a raw file as processed.
    Call this after compile_document() succeeds or fails.
    Stores content_hash so get_unprocessed_files() can skip unchanged files on re-encounter.
    """
    from agents.gcs import get_content_hash
    state = _load()
    state["processed_files"][str(file_path)] = {
        "processed_at": datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "doc_type": doc_type,
        "company": company,
        "drug": drug,
        "status": status,
        "content_hash": get_content_hash(file_path, BASE_DIR),
    }
    _save(state)


SKIP_FILES = {".gitkeep", ".DS_Store", ".DS_store"}

def get_unprocessed_files() -> list[Path]:
    """
    Diff local + GCS raw/ listing against state file.
    Returns files that are new OR whose content has changed since last processing.

    Hash-based delta detection:
      - If a file was processed before and its content_hash matches the current
        file, skip it — no reprocessing needed.
      - If the hash differs (content updated), include it for reprocessing.
      - Entries without a stored hash (pre-hash era) are treated as done.

    ctgov cross-folder dedup:
      Same trial JSON under a different date folder (e.g. 2026-04-06 vs 2026-05-06)
      is matched by (company, filename). If hashes match, skip; if hashes differ,
      the content changed and the trial should be reprocessed.
    """
    from agents.gcs import list_raw_blobs, get_content_hash
    processed = _load()["processed_files"]

    # build (company, filename) → stored_hash for ctgov cross-folder dedup
    processed_ctgov_keys: dict[tuple[str, str], str | None] = {}
    for p, meta in processed.items():
        parts = Path(p).parts
        if "ctgov" in parts:
            idx = list(parts).index("ctgov")
            if idx + 2 < len(parts):
                key = (parts[idx + 1], Path(p).name)
                processed_ctgov_keys[key] = meta.get("content_hash")

    skipped_unchanged = 0
    reprocess_changed = 0
    result = []

    for f in list_raw_blobs(BASE_DIR):
        if str(f) in processed:
            stored_hash = processed[str(f)].get("content_hash")
            if stored_hash is None:
                # pre-hash era entry — treat as done to avoid mass reprocessing
                continue
            current_hash = get_content_hash(f, BASE_DIR)
            if current_hash == stored_hash:
                skipped_unchanged += 1
                continue
            # content changed since last run — reprocess
            reprocess_changed += 1
            logger.info(f"STATE | content changed, reprocessing: {f.name}")
        elif "ctgov" in f.parts:
            idx = list(f.parts).index("ctgov")
            if idx + 2 < len(f.parts):
                key = (f.parts[idx + 1], f.name)
                if key in processed_ctgov_keys:
                    stored_hash = processed_ctgov_keys[key]
                    if stored_hash is None:
                        # pre-hash era — treat cross-folder duplicate as done
                        continue
                    current_hash = get_content_hash(f, BASE_DIR)
                    if current_hash == stored_hash:
                        skipped_unchanged += 1
                        continue
                    reprocess_changed += 1
                    logger.info(f"STATE | ctgov content changed (new folder), reprocessing: {f.name}")

        result.append(f)

    if skipped_unchanged:
        logger.info(f"STATE | skipped {skipped_unchanged} unchanged file(s) (hash match)")
    if reprocess_changed:
        logger.info(f"STATE | queued {reprocess_changed} file(s) for reprocessing (content changed)")
    return result


def reset_timeout_files() -> list[Path]:
    """
    Remove timeout entries from processed_files so they are picked up on the next run.
    Returns the list of paths that were reset.
    """
    state = _load()
    to_reset = [
        path for path, meta in state["processed_files"].items()
        if meta.get("status", "").startswith("timeout:")
    ]
    for path in to_reset:
        del state["processed_files"][path]
    if to_reset:
        _save(state)
        logger.info(f"STATE | reset {len(to_reset)} timeout file(s) for retry")
    return [Path(p) for p in to_reset]


# Errors that are structural bugs — retrying won't help.
_PERMANENT_ERRORS = (
    "'str' object has no attribute 'get'",
    "'NoneType' object is not iterable",
    "unhashable type: 'dict'",
)


def reset_failed_files() -> list[Path]:
    """
    Remove all non-success entries (429s, 499s, timeouts, transient errors)
    so they are retried on the next run.
    Skips entries whose errors are known structural bugs — retrying those
    would just produce the same failure.
    Returns the list of paths that were reset.
    """
    state = _load()
    to_reset = []
    for path, meta in state["processed_files"].items():
        status = meta.get("status", "")
        if status in ("success", "ok"):
            continue
        if any(bug in status for bug in _PERMANENT_ERRORS):
            continue
        to_reset.append(path)

    for path in to_reset:
        del state["processed_files"][path]
    if to_reset:
        _save(state)
        logger.info(f"STATE | reset {len(to_reset)} failed file(s) for retry")
    return [Path(p) for p in to_reset]


# ── lint scheduling ───────────────────────────────────────────────────────────

def should_run_lint() -> bool:
    """Return True if lint has never run or last ran more than 7 days ago."""
    last = _load().get("last_lint_run")
    if not last:
        return True
    try:
        delta = datetime.now() - datetime.fromisoformat(last)
        return delta.days >= 7
    except ValueError:
        return True


def mark_lint_run() -> None:
    """Record the current timestamp as the last lint run."""
    state = _load()
    state["last_lint_run"] = datetime.now().isoformat()
    _save(state)


# ── NCT ID tracking ───────────────────────────────────────────────────────────

def is_nct_processed(nct_id: str) -> bool:
    """Check if an NCT ID has ever been processed."""
    return nct_id in _load()["processed_nct_ids"]


def get_nct_action(nct_id: str) -> str:
    """
    Returns 'new' or 'update'.
    Used by compiler Step 2 to tell Step 3 whether to add or update a trial entry.
    """
    return "update" if is_nct_processed(nct_id) else "new"


def mark_nct_processed(nct_id: str, primary_sponsor: str, first_seen: str | None = None):
    """
    Record an NCT ID as seen. Only records on first encounter.
    Subsequent calls for the same NCT ID are no-ops.
    """
    state = _load()
    if nct_id not in state["processed_nct_ids"]:
        state["processed_nct_ids"][nct_id] = {
            "first_seen": first_seen or datetime.now().strftime("%Y-%m-%d"),
            "primary_sponsor": primary_sponsor,
        }
        _save(state)


# ── wiki navigation (replaces index.md) ──────────────────────────────────────

def build_wiki_map() -> str:
    """
    Build a navigation map of all current wiki pages for the Q&A agent.
    Generated fresh at query time (from GCS or local filesystem).
    """
    from agents.wiki_gcs import list_wiki
    all_pages = list_wiki()

    section_prefixes = {
        "Drugs":       "drugs/",
        "Companies":   "companies/",
        "Indications": "indications/",
        "Trials":      "trials/",
        "Events":      "events/",
    }

    lines = ["Available wiki pages:\n"]
    for section, prefix in section_prefixes.items():
        pages = [p for p in all_pages if p.startswith(prefix)]
        if pages:
            lines.append(f"## {section}")
            for p in pages:
                lines.append(f"  - {p}")
            lines.append("")

    return "\n".join(lines)


# ── reporting helpers ─────────────────────────────────────────────────────────

def get_summary() -> dict:
    """
    Return a summary of current processing state.
    Useful for debugging and status checks.
    """
    state = _load()
    files = state["processed_files"]
    ncts  = state["processed_nct_ids"]

    by_status = {}
    by_doc_type = {}
    for meta in files.values():
        s = meta.get("status", "unknown")
        d = meta.get("doc_type", "unknown")
        by_status[s]    = by_status.get(s, 0) + 1
        by_doc_type[d]  = by_doc_type.get(d, 0) + 1

    return {
        "total_files_processed": len(files),
        "by_status": by_status,
        "by_doc_type": by_doc_type,
        "total_nct_ids_seen": len(ncts),
        "state_file": str(STATE_FILE),
    }


def print_summary():
    """Log a human-readable processing summary at INFO level."""
    s = get_summary()
    logger.info("STATE | ── processing summary ──────────────────────────")
    logger.info(f"STATE | state file:       {s['state_file']}")
    logger.info(f"STATE | files processed:  {s['total_files_processed']}")
    logger.info(f"STATE | NCT IDs tracked:  {s['total_nct_ids_seen']}")
    logger.info(f"STATE | by doc type:      {s['by_doc_type']}")
    logger.info(f"STATE | by status:        {s['by_status']}")
    logger.info("STATE | ────────────────────────────────────────────────")


def export_to_csv(output_path: Path | None = None):
    """
    Export processed files to CSV for easy inspection in Excel/Sheets.
    Useful for sharing status with your DE teammate.
    """
    import csv
    output_path = output_path or BASE_DIR / "agents" / "processing_log.csv"

    state = _load()
    files = state["processed_files"]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "file_path", "processed_at", "doc_type",
            "company", "drug", "status"
        ])
        writer.writeheader()
        for file_path, meta in sorted(files.items()):
            writer.writerow({
                "file_path":    file_path,
                "processed_at": meta.get("processed_at", ""),
                "doc_type":     meta.get("doc_type", ""),
                "company":      meta.get("company", ""),
                "drug":         meta.get("drug", ""),
                "status":       meta.get("status", ""),
            })

    logger.info(f"STATE | exported {len(files)} records → {output_path}")



# ── index updater (replaces LLM-based _update_index) ─────────────────────────

INDEX_SECTIONS = {
    "drug":           "## Drugs",
    "company":        "## Companies",
    "indication_hub": "## Indications",
    "trial":          "## Trials",
    "event":          "## Events",
}

def update_index_py(pages_to_update: list[dict]):
    """
    Update wiki/index.md purely in Python after each compiler run.
    Only adds new entries — never removes or duplicates existing ones.

    pages_to_update: list of {path, type, entity} dicts from compile_document()
    Each entry gets one line in the relevant section of index.md.
    """
    index_path = WIKI_DIR / "index.md"
    today = datetime.now().strftime("%Y-%m-%d")

    # read existing index — empty string if first run
    existing = index_path.read_text() if index_path.exists() else ""

    # collect new lines per section — skip anything already in index
    additions: dict[str, list[str]] = {}

    for page in pages_to_update:
        path   = page["path"]
        ptype  = page["type"]
        entity = page["entity"]

        # skip if this page path already appears in index
        if f"[[{path}]]" in existing:
            continue

        section = INDEX_SECTIONS.get(ptype)
        if not section:
            continue

        line = f"- [[{path}]] — {entity} (last updated: {today})"
        additions.setdefault(section, []).append(line)

    if not additions:
        return  # nothing new to add

    # ensure all section headers exist in the file
    lines = existing.splitlines() if existing else []
    existing_headers = set(lines)

    for header in INDEX_SECTIONS.values():
        if header not in existing_headers:
            lines.extend(["", header, ""])

    # insert new lines immediately after their section header
    result = []
    i = 0
    while i < len(lines):
        result.append(lines[i])
        for section, new_lines in additions.items():
            if lines[i].strip() == section:
                result.extend(new_lines)
        i += 1

    WIKI_DIR.mkdir(parents=True, exist_ok=True)
    index_path.write_text("\n".join(result))

    total_added = sum(len(v) for v in additions.values())
    logger.info(f"INDEX | added {total_added} new entries to index.md")


# ── CLI for inspection ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"

    if cmd == "summary":
        print_summary()

    elif cmd == "export":
        export_to_csv()

    elif cmd == "unprocessed":
        files = get_unprocessed_files()
        logger.info(f"STATE | {len(files)} unprocessed files:")
        for f in files:
            logger.info(f"STATE |   {f}")

    elif cmd == "ncts":
        state = _load()
        ncts = state["processed_nct_ids"]
        logger.info(f"STATE | {len(ncts)} NCT IDs tracked:")
        for nct_id, meta in sorted(ncts.items()):
            logger.info(
                f"STATE |   {nct_id} | sponsor: {meta['primary_sponsor']} "
                f"| first seen: {meta['first_seen']}"
            )

    elif cmd == "reset":
        confirm = input("Reset all processing state? This cannot be undone. (yes/no): ")
        if confirm.lower() == "yes":
            STATE_FILE.unlink(missing_ok=True)
            logger.info("STATE | reset complete — state file deleted")
        else:
            logger.info("STATE | reset cancelled")

    else:
        logger.warning(f"STATE | unknown command '{cmd}'")
        logger.info("STATE | usage: python state.py [summary | export | unprocessed | ncts | reset]")