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
clinical_findings:
  study_design: RCT | single-arm | observational | meta-analysis
  sample_size: 302
  comparator: placebo
  primary_outcome: overall survival
  primary_result: "HR 0.72 (95% CI 0.60–0.87); p=0.0006"
  secondary_results: "PFS improved (HR 0.65); ORR 45% vs 22%"
  safety_note: "Grade ≥3 AEs in 58% vs 49%"
  conclusions_verbatim: "Verbatim conclusion sentence from abstract"
  journal: "N Engl J Med"
  publication_year: 2024
  industry_sponsored: true
last_updated: YYYY-MM-DD
---
```

RULE: Populate clinical_findings only when has_results is true AND pubmed_results data is present.
      Set all clinical_findings fields to null when has_results is false or pubmed_results is absent.
RULE: primary_result_value must be null (the YAML null, not the string "None") whenever no real
      result text is available. Never write the literal word "None" or "N/A" as a quoted string.

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