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
{One paragraph summary of how management has discussed this drug in recent 
earnings calls. Include quarter, directional language, and any guidance changes.}

### Clinical evidence
{If this document contains PubMed results: write one paragraph summarizing 
the key finding, effect size, and study design from this specific paper.
If existing page already has clinical evidence: APPEND the new finding 
as a new sentence — do not erase existing evidence.
Never write "no evidence available" — leave the section blank if this 
document contains no clinical data.}

### Competitive position
{One paragraph on how this drug sits relative to others in its indication class.
Which drugs compete directly? What is the differentiation?}

### Timeline
| Date | Event | Type |
|---|---|---|
| YYYY-MM-DD | Description | [[event-slug]] |

### Sources
- `raw/{path/to/source/document}`