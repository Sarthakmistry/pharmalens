"""
agents/wiki_gcs.py
Wiki file adapter for PharmaLens.

When GCS_MODE=true (production / Cloud Run), wiki pages and the processing
state file live in a bucket we own — separate from the raw input data bucket
(pharmalens-raw, owned by the data-engineering side) so the two have independent
failure domains, retention policies, and IAM. Raw input reads still go through
agents/gcs.py against GCS_BUCKET; this module writes the compiled output to
WIKI_BUCKET:
  gs://<WIKI_BUCKET>/wiki/<page_path>
  gs://<WIKI_BUCKET>/state/processing_state.json

When GCS_MODE is unset or false (local dev), all operations fall back to the
local wiki/ and agents/ directories — no code changes needed for dev workflow.

Environment variables (all optional in dev):
  GCS_MODE    = true            → use GCS storage
  WIKI_BUCKET = pharmalens-wiki  → output bucket name (default: pharmalens-wiki)
"""

import os
from pathlib import Path

from agents.logger import get_logger

logger = get_logger("pharmalens.wiki_gcs")

try:
    BASE_DIR = Path(__file__).parent.parent
except NameError:
    BASE_DIR = Path.cwd().parent

LOCAL_WIKI_DIR = BASE_DIR / "wiki"
WIKI_GCS_PREFIX = "wiki"
STATE_GCS_KEY = "state/processing_state.json"
LOCK_GCS_KEY = "state/compiler.lock"
# Task timeout on the Cloud Run job is 1 day — a lock older than this can only
# mean the process that held it died without releasing it, so treat it as stale.
LOCK_STALE_AFTER_SECONDS = 20 * 3600


def _gcs_enabled() -> bool:
    return os.environ.get("GCS_MODE", "").lower() in ("true", "1", "yes")


def _bucket_name() -> str:
    return os.environ.get("WIKI_BUCKET", "pharmalens-wiki")


def _client():
    from google.cloud import storage
    return storage.Client()


# ── wiki reads / writes ───────────────────────────────────────────────────────

def read_wiki(page_path: str) -> str:
    """Read a wiki page. Returns '' if not found."""
    if _gcs_enabled():
        try:
            blob = _client().bucket(_bucket_name()).blob(f"{WIKI_GCS_PREFIX}/{page_path}")
            if blob.exists():
                return blob.download_as_text(encoding="utf-8")
            return ""
        except Exception as e:
            logger.warning(f"WIKI | GCS read failed for {page_path}: {e}")
            return ""
    full_path = LOCAL_WIKI_DIR / page_path
    return full_path.read_text() if full_path.exists() else ""


def write_wiki(page_path: str, content: str) -> str:
    """Write a wiki page. Returns page_path."""
    if _gcs_enabled():
        try:
            blob = _client().bucket(_bucket_name()).blob(f"{WIKI_GCS_PREFIX}/{page_path}")
            blob.upload_from_string(content, content_type="text/markdown; charset=utf-8")
            logger.debug(f"WIKI | written gs://{_bucket_name()}/{WIKI_GCS_PREFIX}/{page_path}")
        except Exception as e:
            logger.error(f"WIKI | GCS write failed for {page_path}: {e}")
            raise
    else:
        full_path = LOCAL_WIKI_DIR / page_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)
    return page_path


def list_wiki(prefix: str = "") -> list[str]:
    """Return sorted list of .md page paths relative to the wiki root."""
    if _gcs_enabled():
        try:
            gcs_prefix = f"{WIKI_GCS_PREFIX}/{prefix}" if prefix else f"{WIKI_GCS_PREFIX}/"
            pages = []
            for blob in _client().list_blobs(_bucket_name(), prefix=gcs_prefix):
                if blob.name.endswith(".md"):
                    rel = blob.name[len(WIKI_GCS_PREFIX) + 1:]
                    pages.append(rel)
            return sorted(pages)
        except Exception as e:
            logger.warning(f"WIKI | GCS list failed: {e}")
            return []
    search_dir = LOCAL_WIKI_DIR / prefix if prefix else LOCAL_WIKI_DIR
    if not search_dir.exists():
        return []
    return sorted(
        str(p.relative_to(LOCAL_WIKI_DIR))
        for p in search_dir.rglob("*.md")
        if ".ipynb_checkpoints" not in p.parts
    )


def search_wiki(query: str, prefix: str = "") -> list[dict]:
    """Full-text search across wiki pages. Returns [{path, snippet}] up to 20 matches."""
    query_lower = query.lower()
    results: list[dict] = []

    if _gcs_enabled():
        try:
            gcs_prefix = f"{WIKI_GCS_PREFIX}/{prefix}" if prefix else f"{WIKI_GCS_PREFIX}/"
            for blob in _client().list_blobs(_bucket_name(), prefix=gcs_prefix):
                if not blob.name.endswith(".md"):
                    continue
                try:
                    content = blob.download_as_text(encoding="utf-8")
                except Exception:
                    continue
                if query_lower not in content.lower():
                    continue
                rel = blob.name[len(WIKI_GCS_PREFIX) + 1:]
                _append_snippet(results, rel, content, query_lower)
                if len(results) >= 20:
                    break
        except Exception as e:
            logger.warning(f"WIKI | GCS search failed: {e}")
        return results

    # local fallback
    search_dir = LOCAL_WIKI_DIR / prefix if prefix else LOCAL_WIKI_DIR
    if not search_dir.exists():
        return []
    for p in sorted(search_dir.rglob("*.md")):
        if ".ipynb_checkpoints" in p.parts:
            continue
        try:
            content = p.read_text()
        except Exception:
            continue
        if query_lower not in content.lower():
            continue
        rel = str(p.relative_to(LOCAL_WIKI_DIR))
        _append_snippet(results, rel, content, query_lower)
        if len(results) >= 20:
            break
    return results


def _append_snippet(results: list[dict], rel: str, content: str, query_lower: str) -> None:
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if query_lower in line.lower():
            start = max(0, i - 1)
            end = min(len(lines), i + 3)
            snippet = "\n".join(lines[start:end]).strip()
            results.append({"path": rel, "snippet": snippet[:400]})
            return


# ── state file (GCS-backed when GCS_MODE=true) ───────────────────────────────

def load_state() -> dict:
    """Load processing state JSON. Returns empty state if not found."""
    empty: dict = {"processed_files": {}, "processed_nct_ids": {}, "last_lint_run": None}
    if _gcs_enabled():
        try:
            import json
            blob = _client().bucket(_bucket_name()).blob(STATE_GCS_KEY)
            if blob.exists():
                return json.loads(blob.download_as_text(encoding="utf-8"))
            return empty
        except Exception as e:
            logger.warning(f"STATE | GCS load failed: {e}")
            return empty
    return empty  # caller handles local fallback via STATE_FILE


def save_state(state: dict) -> None:
    """Persist processing state JSON to GCS. No-op when GCS_MODE is not set."""
    if not _gcs_enabled():
        return  # caller handles local write via STATE_FILE
    import json
    try:
        blob = _client().bucket(_bucket_name()).blob(STATE_GCS_KEY)
        blob.upload_from_string(
            json.dumps(state, indent=2),
            content_type="application/json; charset=utf-8",
        )
        logger.debug(f"STATE | saved to gs://{_bucket_name()}/{STATE_GCS_KEY}")
    except Exception as e:
        logger.error(f"STATE | GCS save failed: {e}")
        raise


# ── run lock (prevents overlapping pipeline runs, e.g. Scheduler firing while a
#    manual/backlog run is still in progress) ─────────────────────────────────

def acquire_lock() -> bool:
    """Try to acquire the pipeline run lock. Returns True if acquired.
    Returns False if another run already holds a fresh (non-stale) lock.
    No-op (always succeeds) when GCS_MODE is not set — local dev has no
    concurrent-run risk worth guarding against."""
    if not _gcs_enabled():
        return True
    import json
    import time
    blob = _client().bucket(_bucket_name()).blob(LOCK_GCS_KEY)
    if blob.exists():
        try:
            data = json.loads(blob.download_as_text(encoding="utf-8"))
            age = time.time() - data.get("started_at", 0)
            if age < LOCK_STALE_AFTER_SECONDS:
                logger.warning(f"LOCK | held by another run, age {age:.0f}s — refusing to start")
                return False
            logger.warning(f"LOCK | found stale lock (age {age:.0f}s) — overriding")
        except Exception as e:
            logger.warning(f"LOCK | unreadable lock file, overriding: {e}")
    blob.upload_from_string(
        json.dumps({"started_at": time.time()}),
        content_type="application/json; charset=utf-8",
    )
    return True


def release_lock() -> None:
    """Release the pipeline run lock. No-op when GCS_MODE is not set."""
    if not _gcs_enabled():
        return
    try:
        blob = _client().bucket(_bucket_name()).blob(LOCK_GCS_KEY)
        if blob.exists():
            blob.delete()
    except Exception as e:
        logger.warning(f"LOCK | release failed: {e}")
