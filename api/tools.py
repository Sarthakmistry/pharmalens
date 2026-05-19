"""
api/tools.py
Wiki read/list helpers and yfinance stock price lookup.
These are called both by FastAPI route handlers and by the Q&A agent tool loop.
"""

from pathlib import Path
import yfinance as yf

BASE_DIR = Path(__file__).parent.parent
WIKI_DIR = BASE_DIR / "wiki"


def read_wiki_page(page_path: str) -> str:
    """Read a wiki page. Returns an error string if the path doesn't exist."""
    full_path = WIKI_DIR / page_path
    if not full_path.exists():
        return f"Page not found: {page_path}"
    content = full_path.read_text()
    # Strip markdown code-fence wrapper that the compiler sometimes emits
    stripped = content.strip()
    if stripped.startswith("```markdown"):
        stripped = stripped[len("```markdown"):].strip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].strip()
        content = stripped
    return content


def list_wiki_pages(prefix: str = "") -> list[str]:
    """List .md pages under wiki/<prefix>, excluding .gitkeep and checkpoint dirs."""
    search_dir = WIKI_DIR / prefix if prefix else WIKI_DIR
    if not search_dir.exists():
        return [f"Directory not found: {prefix}"]
    pages = []
    for p in search_dir.rglob("*.md"):
        if ".ipynb_checkpoints" in p.parts:
            continue
        pages.append(str(p.relative_to(WIKI_DIR)))
    return sorted(pages)


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
