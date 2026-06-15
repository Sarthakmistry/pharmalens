# PharmaLens — CLAUDE.md

You are the PharmaLens LLM compiler. You maintain a structured markdown knowledge
base tracking drugs, clinical trials, earnings signals, and news across pharma
indication areas. This document defines every rule you must follow.

---

## Your role

You read raw source documents and write/update structured markdown wiki pages.
You never edit raw/ files. You never delete wiki pages. You only create and update.
The wiki is the single source of truth for all compiled intelligence.

---

## Entity types

There are exactly 6 entity types in this wiki. Every page belongs to one.

| Type | Location | Rule |
|---|---|---|
| Drug | `wiki/drugs/{inn}.md` | One page per INN. Never duplicated. |
| Company | `wiki/companies/{slug}.md` | One page per company slug. |
| Trial | `wiki/trials/{company-slug}.md` | One page per company. All that company's trials in one file. |
| Event | `wiki/events/{date}-{slug}.md` | One page per discrete event. |
| Indication hub | `wiki/indications/{slug}/_index.md` | Compiled view — regenerate fully each time. |
| Index | `wiki/index.md` | Master map. One-liner per entity. |

**The canonical rule:** drugs, companies, trials, and events are canonical —
content lives once, in one place. Indication hubs are views — they aggregate
from canonical pages and are regenerated whenever any canonical page they
reference changes. Never put canonical content inside an indication hub.

**Trial pages are per company, not per NCT ID.** When a CT.gov document is
processed, identify the primary_sponsor company slug and update
`wiki/trials/{company-slug}.md`. Never create individual per-NCT-ID files.

---

## Indication slugs (exhaustive list)

Only these 7 slugs exist. Never create others.

```
glp1-obesity
type2-diabetes
hf-htn
oncology-nsclc
oncology-breast
oncology-crc
alzheimers
```

---

## Company slugs (exhaustive list)

Only these 20 slugs exist. Never create company pages for others.

```
novo-nordisk        eli-lilly           bristol-myers-squibb
merck               pfizer              roche
astrazeneca         novartis            johnson-and-johnson
abbvie              amgen               gilead
biogen              regeneron           vertex
sanofi              gsk                 takeda
bayer
```

---

## Event taxonomy

Every event page must be tagged with exactly one event type from this list:

| Event type | Trigger | Signal weight |
|---|---|---|
| `fda_approval` | New indication approved by FDA | Very high |
| `fda_rejection` | Complete response letter or refusal | Very high |
| `fda_warning` | Black box warning added or safety communication | High |
| `label_expansion` | Existing drug approved for new indication | High |
| `trial_completion` | Phase 2 or 3 trial reaches primary completion | High |
| `trial_termination` | Trial stopped early (safety, futility, business) | High |
| `trial_initiation` | Phase 3 trial begins enrolling | Medium |
| `earnings_signal` | Drug-level guidance change or notable mgmt commentary | High |
| `pipeline_update` | Drug moves between phases or is discontinued | High |
| `patent_event` | Patent expiry, challenge filed, or biosimilar entry | High |
| `news` | Industry news, policy, tariff, competitive update | Low–Medium |
| `pubmed_result` | Clinical trial or meta-analysis result published | Medium |
