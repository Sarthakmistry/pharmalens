"""
agents/gcs.py
Hybrid file adapter for PharmaLens.

Sources files from local raw/ AND the pharmalens-raw GCS bucket.
Local files take priority — a path present in both places is read locally.
Blob names in the bucket mirror the local raw/ structure exactly, e.g.:
  raw/edgar/eli-lilly/8k/2025-08-07-8K.txt
  raw/ctgov/eli-lilly/2026-04-06/NCT02451943.json

All other pipeline logic (classify_document, get_company_from_path, state tracking)
is unchanged — it receives Path objects constructed the same way in both cases.
"""

import base64
import hashlib
import os
from pathlib import Path
from google.cloud import storage

from agents.logger import get_logger

logger = get_logger("pharmalens.gcs")

SKIP_FILES = {".gitkeep", ".DS_Store", ".DS_store"}

# populated during list_raw_blobs() — GCS md5 hashes come free from the listing API
_blob_hash_cache: dict[str, str] = {}  # str(path) → hex md5


def _client() -> storage.Client:
    return storage.Client()


def _bucket_name() -> str:
    return os.environ.get("GCS_BUCKET", "pharmalens-raw")


def get_content_hash(file_path: Path, base_dir: Path) -> str | None:
    """Return hex MD5 for a file.
    GCS blobs: served from cache populated during list_raw_blobs().
    Local files: computed on demand (only called when needed for comparison).
    Returns None if file is neither cached nor locally readable.
    """
    key = str(file_path)
    if key in _blob_hash_cache:
        return _blob_hash_cache[key]
    if file_path.exists():
        return hashlib.md5(file_path.read_bytes()).hexdigest()
    return None


def list_raw_blobs(base_dir: Path) -> list[Path]:
    """
    Return paths for all raw files — local raw/ first, then any GCS blobs
    not already present locally. Deduplicates by path string so a file that
    exists in both places is only returned once (local copy wins).
    Populates _blob_hash_cache with GCS md5 hashes for use by get_content_hash().
    """
    global _blob_hash_cache
    _blob_hash_cache = {}

    seen: set[str] = set()
    paths: list[Path] = []

    # local files first
    raw_dir = base_dir / "raw"
    if raw_dir.exists():
        for p in raw_dir.rglob("*"):
            if p.is_file() and p.name not in SKIP_FILES:
                seen.add(str(p))
                paths.append(p)
        logger.info(f"GCS | found {len(paths)} local file(s) in raw/")

    # GCS — add any blobs not covered by a local file
    gcs_count = 0
    client = _client()
    for blob in client.list_blobs(_bucket_name(), prefix="raw/"):
        name = blob.name
        if name.endswith("/") or Path(name).name in SKIP_FILES:
            continue
        p = base_dir / name
        if str(p) not in seen:
            seen.add(str(p))
            paths.append(p)
            gcs_count += 1
        # cache GCS hash regardless of local/remote — used by get_content_hash()
        if blob.md5_hash:
            _blob_hash_cache[str(p)] = base64.b64decode(blob.md5_hash).hex()
    logger.info(f"GCS | found {gcs_count} additional blob(s) in gs://{_bucket_name()}/raw/")

    return paths


def read_blob(file_path: Path, base_dir: Path) -> str:
    """
    Read file content — uses local file if it exists, otherwise downloads from GCS.
    """
    if file_path.exists():
        return file_path.read_text(errors="replace")

    blob_name = str(file_path.relative_to(base_dir))
    client = _client()
    blob = client.bucket(_bucket_name()).blob(blob_name)
    return blob.download_as_bytes().decode("utf-8", errors="replace")
