### Company page (`wiki/companies/{slug}.md`)
```yaml
---
company: {slug}
full_name: Novo Nordisk A/S
ticker: NVO
exchange: NYSE
indications_active: [glp1-obesity, type2-diabetes]
blockbuster_drugs: [semaglutide, liraglutide]
pipeline_drugs: [retatrutide]
last_earnings_date: YYYY-MM-DD
last_updated: YYYY-MM-DD
---
```

## {Company full name}

**Ticker:** [[{Ticker}]] | **Exchange:** NYSE

### Drug portfolio by indication
{For each indication the company is active in, list their drugs and status.
Link to each drug page and indication hub.}

### Earnings intelligence
{Per-drug sentiment summary from most recent earnings call.
One paragraph per drug with notable management language.}

### Pipeline
- {Drugs not yet approved — phase, indication, expected milestones.}

### Recent events
| Date | Type | Event | Signal | Source |
|---|---|---|---|---|
| YYYY-MM-DD | sec | Description | Bullish | |
| YYYY-MM-DD | trial | Description | Bearish | |
| YYYY-MM-DD | research | Description | Neutral | PMID:12345678 |

RULE: The Type column must always be one of exactly three values — no other values allowed:
- `sec`      — source file is an EDGAR filing (doc_type = edgar_8k or edgar_10q)
- `trial`    — source file is a ClinicalTrials.gov record (doc_type = ctgov)
- `research` — source file is a PubMed abstract (doc_type = pubmed)

RULE: The Signal column must always be exactly one of: Bullish | Moderately Bullish | Neutral | Moderately Bearish | Bearish.
      Never put a wikilink or anything else in this column.

RULE: The Event description text must never embed the sentiment word (e.g. never write
      "Bullish pubmed result for..."). The sentiment belongs only in the Signal column.
      Write a plain factual description of what happened instead.

RULE: The Source column is PMID:{pmid} for research rows whenever the signal JSON has a
      non-null "pmid" field. Leave it blank for sec and trial rows, and for research rows
      with no pmid.

RULE: Only include events, earnings intelligence, and sources from documents filed BY this company (i.e. where the file path contains this company's slug). Do NOT add events or intelligence from another company's filings even if this company is mentioned as a collaborator, licensee, or partner in that document. Cross-company mentions belong only on that other company's page.

### Sources
- `raw/edgar/{company-slug}/`

---