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
| Date | Event | Signal |
|---|---|---|
| YYYY-MM-DD | Description | [[event-slug]] |

### Sources
- `raw/edgar/{company-slug}/`

---