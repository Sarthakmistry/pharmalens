# PharmaLens

**Pharma intelligence platform that tracks drugs, clinical trials, earnings signals, and news across indication areas.**

PharmaLens automatically compiles raw data from multiple sources into a structured markdown wiki, surfaced through a dashboard UI and a Q&A agent. Built on Andrej Karpathy's LLM-as-wiki-compiler pattern — no RAG, no vector database.

---

## Architecture

```
Raw data sources
    ↓
Orchestrator (pure Python)
    ↓
Compiler (3-step LLM chain)     ←  Gemini 2.5 Flash via Vertex AI
    ↓
Structured markdown wiki
    ↓
Q&A Agent + FastAPI + Streamlit dashboard
```

**The wiki is the single source of truth.** Raw documents land in `raw/`, the compiler processes them into structured markdown pages in `wiki/`, and the Q&A agent navigates those pages at query time.

---

## Data Scope

**7 indication areas**

| Slug | Display Name |
|---|---|
| `glp1-obesity` | GLP-1 / Obesity |
| `type2-diabetes` | Type 2 Diabetes |
| `hf-htn` | Heart Failure / Hypertension |
| `oncology-nsclc` | Oncology — NSCLC |
| `oncology-breast` | Oncology — Breast Cancer |
| `oncology-crc` | Oncology — Colorectal Cancer |
| `alzheimers` | Alzheimer's Disease |

**20 tracked companies** — novo-nordisk, eli-lilly, bristol-myers-squibb, merck, pfizer, roche, astrazeneca, novartis, johnson-and-johnson, abbvie, amgen, gilead, biogen, regeneron, vertex, sanofi, gsk, takeda, eisai, bayer

**27 tracked drugs (INN)** — semaglutide, tirzepatide, retatrutide, pembrolizumab, nivolumab, osimertinib, lecanemab, donanemab, and 19 more

**4 data sources**

| Source | Scope | Refresh |
|---|---|---|
| CT.gov | Phase 2/3/4 trials, 5-year lookback | Monthly |
| PubMed | RCTs, meta-analyses, systematic reviews | Weekly |
| EDGAR | 8-K, earnings calls, 10-K | Per event / quarterly |
| News (RSS + NewsAPI) | Pharma news by indication | Daily |

---

## Project Structure

```
pharmalens/
├── .env                          ← credentials (never commit)
├── .gitignore
├── requirements.txt
├── agents/
│   ├── compiler.py               ← 3-step LLM chain
│   ├── orchestrator.py           ← pipeline coordinator (no LLM)
│   ├── state.py                  ← all tracking: files, NCT IDs, wiki map
│   ├── lint.py                   ← weekly wiki health check
│   ├── pubmed_scraper.py         ← NCBI E-utilities scraper
│   ├── processing_state.json     ← auto-generated state file
│   └── prompts/
│       ├── CLAUDE.md             ← base schema (~550 tokens)
│       ├── compiler_ctgov.txt
│       ├── compiler_edgar.txt
│       ├── compiler_genepool.txt
│       ├── compiler_pubmed.txt
│       └── templates/
│           ├── drug.md
│           ├── company.md
│           ├── trial.md
│           ├── event.md
│           └── indication_hub.md
├── reference/
│   ├── drugs.json                ← 27 drugs: INN, brands, aliases, indications
│   ├── indications.json          ← 7 indications: ICD-10, aliases, MeSH
│   └── companies.json            ← 20 companies: ticker, EDGAR CIK, aliases
├── raw/
│   ├── ctgov/{company}/{YYYY-MM-DD}/NCT*.json
│   ├── edgar/{company}/{YYYY-QN}/earnings.txt
│   ├── edgar/{company}/{YYYY-MM-DD}/8K.htm
│   ├── genepool/{YYYY-MM-DD}/article.json
│   └── pubmed/{drug}/{YYYY-MM-DD}/abstract-{pmid}.json
├── wiki/
│   ├── drugs/{inn}.md
│   ├── companies/{slug}.md
│   ├── trials/{company-slug}.md  ← one file per company, all trials
│   ├── events/{date}-{slug}.md
│   └── indications/{slug}/_index.md
└── logs/
    └── compiler.log              ← rotating, 10MB × 7 backups
```

---

## Compiler Chain

The compiler processes one raw file at a time in three steps:

```
Step 1 — Extract   (1 LLM call)
  Read preprocessed document
  Identify drugs, companies, indications, trial IDs
  Classify event type and sentiment
  Return structured JSON

Step 2 — Validate  (pure Python, no LLM)
  Validate extracted entities against reference files
  Determine which wiki pages need updating
  Check NCT ID status (new vs update) via state.py

Step 3 — Write     (1 LLM call per page)
  Write or update each wiki page using page-type template
  Trials: one file per company, NCT IDs accumulated
  Events: new page only for high-signal events
```

**Caching:** System prompt (4,012 tokens) and extraction/template prompts are cached via Gemini context caching. Caches are built once per pipeline run in the orchestrator and passed through context — saving ~70% of token costs on repeated calls.

**Pre-processing:** CT.gov and PubMed JSON files are parsed and stripped to ~15 relevant fields before the LLM call. Edgar HTML filings are stripped with BeautifulSoup. Long documents use 70/30 start/end truncation to preserve the highest-signal sections.

---

## Wiki Page Types

| Type | Location | Rule |
|---|---|---|
| Drug | `wiki/drugs/{inn}.md` | One page per INN, never duplicated |
| Company | `wiki/companies/{slug}.md` | One page per company slug |
| Trial | `wiki/trials/{company-slug}.md` | One page per company — all trials in one file |
| Event | `wiki/events/{date}-{slug}.md` | One page per discrete event |
| Indication hub | `wiki/indications/{slug}/_index.md` | Compiled view, regenerated on updates |

**Trial pages are per company, not per NCT ID.** `wiki/trials/novo-nordisk.md` contains all Novo Nordisk trials grouped by status (Active / Completed / Terminated) with a summary table. This keeps the wiki at 20 trial files regardless of how many trials are tracked.

---

## Key Design Decisions

| Decision | Chosen | Rejected | Reason |
|---|---|---|---|
| Trial pages | One file per company | One file per NCT ID | Scales to hundreds of trials without wiki sprawl |
| NCT tracking | state.py Python dict | Regex scan of wiki | Deterministic, no dependency on wiki formatting |
| File tracking | processing_state.json | Regex parsing log.md | Reliable, queryable, no fragile regex |
| index.md | Replaced by build_wiki_map() | LLM-maintained file | Always accurate, zero maintenance |
| CT.gov Step 1 | Pure Python extraction | LLM extraction | CT.gov is structured data — LLM adds no value |
| HTML stripping | BeautifulSoup | Pass raw HTML to LLM | iXBRL files are thousands of lines of tag noise |
| EDGAR download | Primary .htm only | full-submission.txt | Bundle is 2,848 lines of XBRL boilerplate |

---

## Requirements

```
google-genai>=1.10.0
schedule>=1.2.0
python-dotenv>=1.0.0
pandas>=2.0.0
requests>=2.31.0
fastapi>=0.110.0
uvicorn>=0.29.0
streamlit>=1.35.0
yfinance>=0.2.40
beautifulsoup4
```

---

## Contributing

This is a academic project built at Indiana University by me and Sarthak Mistry.

---

*PharmaLens — Indiana University · Mohit Mahajan · Sarthak Mistry · 2026*
