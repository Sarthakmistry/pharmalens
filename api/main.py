"""
api/main.py
PharmaLens FastAPI backend.

Routes
------
GET  /api/indications              — list all indication slugs + display names
GET  /api/companies                — list all companies with tickers
GET  /api/stocks                   — live stock prices for every company (ticker bar)
GET  /api/indication/{slug}        — indication wiki content + structured meta
GET  /api/company/{slug}           — company wiki content + meta + live stock
POST /api/ask                      — Q&A agent, streams SSE

Start:
    uvicorn api.main:app --reload --port 8000
"""

from . import bootstrap  # must run before any google-genai import  # noqa: F401

import json
from pathlib import Path

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .agent import run_agent
from .tools import get_stock_price, read_wiki_page

load_dotenv()

# ── paths + reference data ────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent
REFERENCE_DIR = BASE_DIR / "reference"
WIKI_DIR = BASE_DIR / "wiki"

INDICATIONS: dict = json.loads((REFERENCE_DIR / "indications.json").read_text())
COMPANIES: dict = json.loads((REFERENCE_DIR / "companies.json").read_text())

# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="PharmaLens API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── helpers ───────────────────────────────────────────────────────────────────


def _strip_code_fence(content: str) -> str:
    """Remove ```markdown … ``` wrapper the compiler sometimes adds."""
    s = content.strip()
    if s.startswith("```markdown"):
        s = s[len("```markdown"):].strip()
        if s.endswith("```"):
            s = s[:-3].strip()
    return s


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Split YAML frontmatter from body. Returns ({}, full_content) if none."""
    content = _strip_code_fence(content)
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return meta, parts[2].strip()
    return {}, content


# ── routes ────────────────────────────────────────────────────────────────────


@app.get("/api/indications")
def get_indications() -> list[dict]:
    """All indication slugs with display names and reference metadata."""
    result = []
    for slug, ref_meta in INDICATIONS.items():
        wiki_path = WIKI_DIR / "indications" / slug / "_index.md"
        display_name = slug.replace("-", " ").title()
        if wiki_path.exists():
            fm, _ = _parse_frontmatter(wiki_path.read_text())
            display_name = fm.get("display_name", display_name)
        result.append({"slug": slug, "display_name": display_name, **ref_meta})
    return result


@app.get("/api/companies")
def get_companies() -> list[dict]:
    """All company slugs with tickers and active indication mapping."""
    return [{"slug": slug, **meta} for slug, meta in COMPANIES.items()]


@app.get("/api/stocks")
def get_stocks() -> list[dict]:
    """Live stock prices for every tracked company (for the ticker bar)."""
    result = []
    for slug, meta in COMPANIES.items():
        ticker = meta.get("ticker", "")
        if not ticker:
            continue
        stock = get_stock_price(ticker)
        result.append(
            {
                "slug": slug,
                "full_name": meta["full_name"],
                **stock,
            }
        )
    return result


@app.get("/api/indication/{slug}")
def get_indication(slug: str) -> dict:
    """
    Structured data for one indication.
    Returns reference metadata merged with wiki frontmatter, plus the wiki body.
    """
    if slug not in INDICATIONS:
        raise HTTPException(status_code=404, detail=f"Indication '{slug}' not found")

    wiki_path = WIKI_DIR / "indications" / slug / "_index.md"
    if wiki_path.exists():
        fm, wiki_body = _parse_frontmatter(wiki_path.read_text())
        meta = {**INDICATIONS[slug], **fm}
    else:
        meta = INDICATIONS[slug]
        wiki_body = ""

    return {"slug": slug, "meta": meta, "wiki": wiki_body}


@app.get("/api/company/{slug}")
def get_company(slug: str) -> dict:
    """
    Structured data for one company.
    Returns reference metadata, wiki body, and a live stock quote.
    """
    if slug not in COMPANIES:
        raise HTTPException(status_code=404, detail=f"Company '{slug}' not found")

    company_meta = COMPANIES[slug]
    wiki_path = WIKI_DIR / "companies" / f"{slug}.md"
    if wiki_path.exists():
        _, wiki_body = _parse_frontmatter(wiki_path.read_text())
    else:
        wiki_body = ""

    ticker = company_meta.get("ticker", "")
    stock = get_stock_price(ticker) if ticker else {}

    # Build drug → [indication slugs] map by scanning each active indication's wiki
    drug_indications: dict[str, list[str]] = {}
    company_drugs = set(company_meta.get("drugs", []))
    for ind_slug in company_meta.get("indications_active", []):
        ind_path = WIKI_DIR / "indications" / ind_slug / "_index.md"
        if not ind_path.exists():
            continue
        fm, _ = _parse_frontmatter(ind_path.read_text())
        for drug in [*fm.get("drugs_approved", []), *fm.get("drugs_pipeline", [])]:
            if drug in company_drugs:
                drug_indications.setdefault(drug, []).append(ind_slug)

    return {
        "slug": slug,
        "meta": company_meta,
        "wiki": wiki_body,
        "stock": stock,
        "drug_indications": drug_indications,
    }


@app.get("/api/company/{slug}/trials")
def get_company_trials(slug: str) -> dict:
    """
    Parse the per-company trials wiki and return structured trial data.
    Includes stats (active, completed 90d, with results) and phase distribution.
    """
    import re
    from datetime import date, timedelta

    if slug not in COMPANIES:
        raise HTTPException(status_code=404, detail=f"Company '{slug}' not found")

    trial_path = WIKI_DIR / "trials" / f"{slug}.md"
    if not trial_path.exists():
        return {"trials": [], "stats": {"active": 0, "completed_90d": 0, "with_results": 0}, "phases": []}

    content = trial_path.read_text()
    blocks = re.split(r"^---$", content, flags=re.MULTILINE)

    _ACTIVE_STATUSES = {"recruiting", "active", "not yet recruiting", "enrolling by invitation", "approved for marketing"}

    trials = []
    for block in blocks:
        try:
            meta = yaml.safe_load(block.strip())
        except yaml.YAMLError:
            continue
        if not isinstance(meta, dict) or "trial_id" not in meta:
            continue
        # normalise phase to a display string
        raw_phase = str(meta.get("phase") or "?").strip()
        meta["phase_display"] = f"Phase {raw_phase}" if raw_phase != "?" else "Phase unspecified"
        meta["is_active"] = str(meta.get("status") or "").lower() in _ACTIVE_STATUSES
        trials.append(meta)

    today = date.today()
    cutoff = (today - timedelta(days=90)).isoformat()

    active_trials     = [t for t in trials if t["is_active"]]
    completed_90d     = [t for t in trials if not t["is_active"]
                         and str(t.get("primary_completion_date") or "") >= cutoff]
    with_results      = [t for t in trials if t.get("has_results")]

    # Phase distribution for chart
    phase_order = {"1": 0, "1/2": 1, "2": 2, "2/3": 3, "3": 4, "4": 5, "?": 6}
    phase_map: dict[str, dict] = {}
    for t in trials:
        pd = t["phase_display"]
        raw = str(t.get("phase") or "?").strip()
        if pd not in phase_map:
            phase_map[pd] = {"phase": pd, "sort": phase_order.get(raw, 7), "active": 0, "completed": 0}
        if t["is_active"]:
            phase_map[pd]["active"] += 1
        else:
            phase_map[pd]["completed"] += 1

    phases = sorted(phase_map.values(), key=lambda x: x["sort"])

    return {
        "trials": trials,
        "stats": {
            "active":        len(active_trials),
            "completed_90d": len(completed_90d),
            "with_results":  len(with_results),
        },
        "phases": phases,
    }


# ── Q&A agent (SSE) ───────────────────────────────────────────────────────────


class AskRequest(BaseModel):
    question: str
    indication: str | None = None
    company: str | None = None


@app.post("/api/ask")
async def ask(body: AskRequest) -> StreamingResponse:
    """
    Run the PharmaLens Q&A agent and stream events as SSE.

    Event types:
      tool_call   — agent is about to call a tool
      tool_result — tool returned (first 300 chars shown)
      text        — model text chunk
      done        — stream complete; full_text contains the assembled answer
    """

    async def event_stream():
        async for event in run_agent(body.question, body.indication, body.company):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
