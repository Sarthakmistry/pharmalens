### Drug page (`wiki/drugs/{inn}.md`)
```yaml
---
drug: {inn}
brand_names: [Brand1, Brand2]
company: {company-slug}
indications: [indication-slug-1, indication-slug-2]
drug_class: GLP-1 receptor agonist
status: approved | phase3 | phase2 | discontinued
fda_approval_date: YYYY-MM-DD
patent_expiry: YYYY-MM-DD
black_box_warning: true | false
blockbuster: true | false
management_sentiment: bullish | bearish | neutral | null
sentiment_score: 4/5
last_earnings_signal: "YYYY-QN — one sentence summary"
reimbursement_flag: true | false
latest_event: "YYYY-MM-DD — one sentence description"
trials: [NCT00000001, NCT00000002]
last_updated: YYYY-MM-DD
---
```

## {Drug name}

**Company:** [[{company-slug}]] | **Class:** {drug_class} | **Status:** {status}

### Approved indications
- {Indication 1} — approved {date}
- {Indication 2} — approved {date}

### Pipeline
- {Indication in trial} — Phase {N}, NCT{id}, {status}

### Management sentiment
This section is generated programmatically from canonical signal data after
you write the rest of the page — do not write a "### Management sentiment"
heading or any paragraphs here. If you see one in the "current page content"
you were given, leave it exactly where it is; it will be replaced
automatically. No separate ask is needed from you for this — the per-drug
commentary you write into all_drugs_mentioned[].commentary during extraction
is what populates this section.

### Clinical evidence
This section is generated programmatically from a canonical, append-only log
after you write the rest of the page — do not write a "### Clinical
evidence" heading or any paragraphs here. If you see one in the "current
page content" you were given, leave it exactly where it is; it will be
replaced automatically. When clinical-finding signals are present in this
batch, you will be asked separately (after a delimiter) for ONLY the new
paragraph(s) for those findings — never asked to reproduce past findings.

### Competitive position
{One paragraph on how this drug sits relative to others in its indication class.
Which drugs compete directly? What is the differentiation?}

### Timeline
This section is generated programmatically from canonical signal data after
you write the rest of the page — do not write a "### Timeline" heading or
table. If you see one in the "current page content" you were given, leave it
exactly where it is; it will be replaced automatically.

### Sources
- `raw/{path/to/source/document}`