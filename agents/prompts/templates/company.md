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
This section is generated programmatically from a canonical, append-only log
after you write the rest of the page — do not write a "### Earnings
intelligence" heading or any paragraphs here. If you see one in the "current
page content" you were given, leave it exactly where it is; it will be
replaced automatically. When financial-filing signals are present in this
batch, you will be asked separately (after a delimiter) for ONLY the new
paragraph(s) for those signals — never asked to reproduce past quarters.

### Pipeline
- {Drugs not yet approved — phase, indication, expected milestones.}

### Recent events
This section is generated programmatically from canonical signal data after
you write the rest of the page — do not write a "### Recent events" heading,
table, or any rows. If you see one in the "current page content" you were
given, leave it exactly where it is; it will be replaced automatically.

RULE: Only include earnings intelligence and sources from documents filed BY this company (i.e. where the file path contains this company's slug). Do NOT add intelligence from another company's filings even if this company is mentioned as a collaborator, licensee, or partner in that document. Cross-company mentions belong only on that other company's page.

### Sources
- `raw/edgar/{company-slug}/`

---