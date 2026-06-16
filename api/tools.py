"""
api/tools.py
Wiki read/list helpers and yfinance stock price lookup.
These are called both by FastAPI route handlers and by the Q&A agent tool loop.
"""

import yfinance as yf
from agents.wiki_gcs import read_wiki, list_wiki, search_wiki as _search_wiki


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
