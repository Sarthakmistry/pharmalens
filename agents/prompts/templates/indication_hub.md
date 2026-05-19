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

### Companies
| Company | Drugs | Latest event |
|---|---|---|
| [[novo-nordisk]] | semaglutide, liraglutide | {latest event} |

### Recent events
| Date | Event | Signal |
|---|---|---|
| YYYY-MM-DD | {description} | [[event-slug]] |

### Active trials
| Trial | Drug | Phase | Status |
|---|---|---|---|
| [[NCT00000000]] | [[semaglutide]] | 3 | Recruiting |