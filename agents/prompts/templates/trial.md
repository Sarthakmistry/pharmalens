### Trial page (`wiki/trials/{nct_id}.md`)
```yaml
---
trial_id: NCT00000000
title: Brief descriptive title
phase: 2 | 3 | 4
status: recruiting | active | completed | terminated | withdrawn
primary_sponsor: {company-slug}
co_sponsors: [{other-slug}]
drugs: [{inn-or-name}]
indications: [{indication-slug}]
enrollment: 0000
primary_endpoint: One sentence description
primary_completion_date: YYYY-MM-DD
has_results: true | false
primary_result_value: "97.6% local control at 2 years"
last_updated: YYYY-MM-DD
---
```

## {Trial title}

**Phase:** {N} | **Status:** {status} | **Sponsor:** [[{company-slug}]]

### Design
{One paragraph: what is being studied, in which patients, what is the comparator.}

### Primary endpoint
{Endpoint name and timeframe. Include result value if available.}

### Results summary
{If has_results is true: key efficacy and safety findings in 2-3 sentences.
If false: leave blank.}

### Sources
- `raw/ctgov/{date}/{nct_id}.json`

---