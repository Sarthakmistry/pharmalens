# Wiki health report
Generated: 2026-06-12 15:07  |  Pages checked: 1520

## Structural issues (0)

## Semantic issues (8)

### contradiction
- **Page:** `index.md`
- **Detail:** The main index file contains duplicate entries for '[[drugs/nivolumab.md]]' and '[[drugs/tirzepatide.md]]'.
- **Action:** Remove the duplicate lines for 'nivolumab.md' and 'tirzepatide.md' from index.md to ensure data integrity.

### contradiction
- **Page:** `drugs/donanemab.md`
- **Detail:** The 'last_updated' date in the frontmatter is '2024-05-20', which is before the date of the 'latest_event' ('2026-05-18'). This indicates the page metadata was not updated when the event was added.
- **Action:** Update the 'last_updated' field in the frontmatter to '2026-05-18' or a more recent date to reflect the latest information.

### contradiction
- **Page:** `drugs/nivolumab.md`
- **Detail:** The 'latest_event' field mentions a trial for 'alzheimers', but 'alzheimers' is not listed in the 'indications' array in the frontmatter.
- **Action:** Add 'alzheimers' to the 'indications' array in the frontmatter to reflect the drug's development pipeline.

### stale_entity
- **Page:** `drugs/atezolizumab.md`
- **Detail:** A new PubMed abstract for atezolizumab was ingested on 2026-06-12, but the page's last update was 2026-05-24 (per index.md). The page is stale and likely missing information from the new document.
- **Action:** Review the ingested document ('abstract-41999612.json') and update the 'drugs/atezolizumab.md' page, including its 'last_updated' timestamp.

### stale_entity
- **Page:** `companies/novartis.md`
- **Detail:** A new clinical trial document related to Novartis was ingested on 2026-06-08, but the company page was last updated on 2026-05-02 (per index.md). The page is stale.
- **Action:** Review the ingested document ('NCT04023552.json') and update the 'companies/novartis.md' page, then update its 'last_updated' timestamp in the page and in index.md.

### missing_backlink
- **Page:** `drugs/dapagliflozin.md`
- **Detail:** The page 'drugs/saxagliptin.md' contains a link to '[[dapagliflozin]]' in the context of a comparative study, but 'drugs/dapagliflozin.md' does not have a reciprocal link back to 'drugs/saxagliptin.md'.
- **Action:** Add a 'See also' section or an inline link in 'drugs/dapagliflozin.md' pointing to '[[drugs/saxagliptin.md]]' to improve navigation and contextual awareness.

### suggested_new_page
- **Page:** `drug-classes/cdk4-6-inhibitors.md`
- **Detail:** The wiki has multiple pages for drugs in the CDK4/6 inhibitor class, including 'ribociclib', 'palbociclib', and 'abemaciclib'. There is no central page to compare these related assets.
- **Action:** Create a new synthesis page at 'drug-classes/cdk4-6-inhibitors.md' to summarize, compare, and link to the individual drugs in this class.

### contradiction
- **Page:** `drugs/empagliflozin.md`
- **Detail:** The 'last_updated' date in the frontmatter is '2026-04-07', which is earlier than the 'latest_event' date of '2026-05-18'.
- **Action:** Update the 'last_updated' field in 'drugs/empagliflozin.md' to at least '2026-05-18' and sync the date with its entry in 'index.md'.

## Suggested new pages

- The wiki has multiple pages for drugs in the CDK4/6 inhibitor class, including 'ribociclib', 'palbociclib', and 'abemaciclib'. There is no central page to compare these related assets.