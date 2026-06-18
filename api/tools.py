"""
api/tools.py
Wiki read/list helpers and yfinance stock price lookup.
These are called both by FastAPI route handlers and by the Q&A agent tool loop.
"""

import re
import yfinance as yf
import yaml
from agents.wiki_gcs import read_wiki, list_wiki, search_wiki as _search_wiki


def normalize_status(raw: str) -> str:
    """Canonical form: lowercase, spaces/commas/hyphens → underscore, collapsed."""
    return re.sub(r"[\s,\-]+", "_", (raw or "").strip().lower()).strip("_")


def parse_company_trials(slug: str) -> list[dict]:
    """Parse wiki/trials/{slug}.md into a list of trial dicts (frontmatter only),
    sorted newest primary_completion_date first. Shared by the FastAPI route and
    the Q&A agent's get_company_trials tool — both need the same structured data,
    not the raw markdown (which is too large for the agent's tool-result budget)."""
    content = read_wiki(f"trials/{slug}.md")
    if not content:
        return []
    blocks = re.split(r"^---$", content, flags=re.MULTILINE)
    trials = []
    for block in blocks:
        try:
            meta = yaml.safe_load(block.strip())
        except yaml.YAMLError:
            continue
        if not isinstance(meta, dict) or "trial_id" not in meta:
            continue
        # YAML parses unquoted dates as datetime.date — normalize to str for
        # consistent sorting/serialization (mixed str/date entries otherwise
        # break both the sort comparison and json.dumps).
        for date_field in ("primary_completion_date", "last_updated"):
            if meta.get(date_field) is not None:
                meta[date_field] = str(meta[date_field])
        raw_phase = str(meta.get("phase") or "?").strip()
        meta["phase_display"] = f"Phase {raw_phase}" if raw_phase != "?" else "Phase unspecified"
        meta["is_active"] = normalize_status(str(meta.get("status") or "")) in {
            "recruiting", "active", "not_yet_recruiting",
            "enrolling_by_invitation", "approved_for_marketing",
            "active_not_recruiting",
        }
        trials.append(meta)
    trials.sort(key=lambda t: t.get("primary_completion_date") or "", reverse=True)
    return trials


def read_wiki_page(page_path: str) -> str:
    """Read a wiki page. Returns an error string if the path doesn't exist."""
    content = read_wiki(page_path)
    if not content:
        return f"Page not found: {page_path}"
    stripped = content.strip()
    if stripped.startswith("```markdown"):
        stripped = stripped[len("```markdown"):].strip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()
        content = stripped
    return content


def list_wiki_pages(prefix: str = "") -> list[str]:
    """List .md pages under wiki/<prefix>."""
    pages = list_wiki(prefix)
    if not pages:
        return [f"Directory not found: {prefix}"] if prefix else []
    return pages


def search_wiki(query: str, prefix: str = "") -> list[dict]:
    """Full-text search across wiki files. Returns [{path, snippet}] up to 20 matches."""
    return _search_wiki(query, prefix)


def get_stock_price(ticker: str) -> dict:
    """Return current price, change, and % change for a ticker via yfinance."""
    try:
        t = yf.Ticker(ticker.upper())
        fi = t.fast_info
        price = fi.last_price
        prev = fi.previous_close
        change = price - prev if price and prev else 0.0
        change_pct = (change / prev * 100) if prev else 0.0
        return {
            "ticker": ticker.upper(),
            "price": round(price, 2) if price else None,
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "price": None, "error": str(e)}
