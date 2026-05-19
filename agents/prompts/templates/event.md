### Event page (`wiki/events/{date}-{slug}.md`)
```yaml
---
event_type: fda_approval | trial_completion | earnings_signal | news | ...
date: YYYY-MM-DD
drugs: [{inn}]
companies: [{company-slug}]
indications: [{indication-slug}]
signal: bullish | bearish | neutral
headline: One sentence headline
last_updated: YYYY-MM-DD
---
```

## {Headline}

**Date:** {date} | **Type:** {event_type} | **Signal:** {signal}

### Summary
{2-3 sentences of factual summary. What happened, which entities are affected,
and why it matters. No editorializing — state facts only.}

### Market implication
{One sentence on what this means for the drug or company's stock/valuation.
Base this on the facts, not speculation.}

### Affected entities
- Drug: [[{inn}]]
- Company: [[{company-slug}]]
- Indication: [[{indication-slug}/_index]]

### Sources
- `raw/{path/to/source/document}`

---