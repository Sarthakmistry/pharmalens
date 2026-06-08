### Indication hub (`wiki/indications/{slug}/_index.md`)

This is a VIEW page. Regenerate it completely each time. Do not preserve old content.
```yaml
---
indication: {slug}
display_name: GLP-1 / Obesity
icd10: [E66, E66.0]
drugs_approved: [semaglutide, tirzepatide]
drugs_pipeline: [retatrutide]
companies_active: [novo-nordisk, eli-lilly]
active_trials: 12
last_updated: YYYY-MM-DD
---
```

## {Display name}

### Drugs in class
| Drug | Company | Status | Sentiment | Stock |
|---|---|---|---|---|
| [[semaglutide]] | [[novo-nordisk]] | Approved | Bullish | NVO |
| [[tirzepatide]] | [[eli-lilly]] | Approved | Bullish | LLY |

RULE: The Stock column must ALWAYS be filled with the company's stock ticker for every row.
Use these tickers (never leave Stock blank for these companies):
novo-nordisk=NVO, eli-lilly=LLY, bristol-myers-squibb=BMY, merck=MRK, pfizer=PFE,
roche=RHHBY, astrazeneca=AZN, novartis=NVS, johnson-and-johnson=JNJ, abbvie=ABBV,
amgen=AMGN, gilead=GILD, biogen=BIIB, regeneron=REGN, vertex=VRTX, sanofi=SNY,
gsk=GSK, takeda=TAK, eisai=ESALY, bayer=BAYRY.
For private companies (boehringer-ingelheim, eisai co-development partners, etc.) leave blank.

### Companies
| Company | Drugs | Latest event |
|---|---|---|
| [[novo-nordisk]] | semaglutide, liraglutide | {latest event} |

### Recent events
| Date | Event | Signal |
|---|---|---|
| YYYY-MM-DD | {description} | [[event-slug]] |

RULE: Recent events must ALWAYS be sorted by date descending (newest row first). When adding new events, insert at the top.

### Active trials
| Trial | Drug | Phase | Status |
|---|---|---|---|
| [[NCT00000000]] | [[semaglutide]] | 3 | Recruiting |