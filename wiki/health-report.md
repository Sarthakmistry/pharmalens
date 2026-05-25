# Wiki health report
Generated: 2026-05-24 13:33  |  Pages checked: 339

## Structural issues (13)

### missing_drug_page
- **Page:** `drugs/retatrutide.md`
- **Detail:** retatrutide in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/liraglutide.md`
- **Detail:** liraglutide in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/dapagliflozin.md`
- **Detail:** dapagliflozin in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/canagliflozin.md`
- **Detail:** canagliflozin in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/saxagliptin.md`
- **Detail:** saxagliptin in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/sacubitril-valsartan.md`
- **Detail:** sacubitril-valsartan in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/inclisiran.md`
- **Detail:** inclisiran in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/finerenone.md`
- **Detail:** finerenone in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/atezolizumab.md`
- **Detail:** atezolizumab in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/durvalumab.md`
- **Detail:** durvalumab in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/palbociclib.md`
- **Detail:** palbociclib in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/ribociclib.md`
- **Detail:** ribociclib in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/trastuzumab deruxtecan.md`
- **Detail:** trastuzumab deruxtecan in drugs.json but no wiki page exists yet

## Semantic issues (12)

### contradiction
- **Page:** `drugs/osimertinib.md`
- **Detail:** The 'blockbuster' field is 'false', but the company page 'companies/astrazeneca.md' lists 'osimertinib' in its 'blockbuster_drugs' list.
- **Action:** Verify the blockbuster status of osimertinib and align the 'blockbuster' field in 'drugs/osimertinib.md' with the company page, likely by changing it to 'true'.

### contradiction
- **Page:** `drugs/abemaciclib.md`
- **Detail:** The page's 'last_updated' date is '2026-04-07', but the 'latest_event' field contains a very old event from '2017-02-14'. A more recent event, like the '2025-Q1' earnings signal, is not reflected as the latest event.
- **Action:** Update the 'latest_event' field to reflect the most recent significant event for the drug, ensuring it is more current than 2017.

### contradiction
- **Page:** `drugs/cetuximab.md`
- **Detail:** The 'company' field lists only 'eli-lilly', but a source file referenced in the page body ('raw/ctgov/merck/...') indicates a relationship with Merck. This co-marketing relationship is not captured.
- **Action:** Update the 'company' field to be a list including both 'eli-lilly' and 'merck' and briefly explain the partnership in the page body.

### stale_entity
- **Page:** `companies/takeda.md`
- **Detail:** The page was last updated on '2026-04-07', but new clinical trial documents related to Takeda were ingested on '2026-05-24'.
- **Action:** Review the newly ingested documents and update the Takeda company page with any relevant information.

### stale_entity
- **Page:** `companies/gilead.md`
- **Detail:** The page was last updated on '2026-05-03' (per index.md), but new 8-K filings for Gilead were ingested on '2026-05-24'.
- **Action:** Review the ingested 8-K filings and update the Gilead company page with any new financial or event information.

### stale_entity
- **Page:** `companies/eli-lilly.md`
- **Detail:** The page was last updated on '2026-05-02' (per index.md), but new 8-K filings for Eli Lilly were ingested on '2026-05-24'.
- **Action:** Review the ingested 8-K filings and update the Eli Lilly company page with any new financial or event information.

### missing_backlink
- **Page:** `drugs/olaparib.md`
- **Detail:** The 'latest_event' field explicitly mentions 'Merck' and its role in an alliance for Lynparza, but the page body does not contain a markdown link '[[merck]]' to the Merck company page.
- **Action:** Add a link to '[[companies/merck.md]]' in the page body and clarify the alliance relationship with AstraZeneca.

### missing_backlink
- **Page:** `drugs/empagliflozin.md`
- **Detail:** The page contains a link '[[boehringer-ingelheim]]' to its parent company, but the corresponding company page 'companies/boehringer-ingelheim.md' does not exist.
- **Action:** Create a new company page for Boehringer Ingelheim to resolve the broken link.

### thin_hub
- **Page:** `indications/hf-htn/_index.md`
- **Detail:** The 'hf-htn' indication hub is thin because it is missing key drugs. Company pages for Novartis and AstraZeneca mention 'sacubitril-valsartan' and 'dapagliflozin' for this indication, but these drugs do not have pages and are thus not on the hub.
- **Action:** Create new drug pages for 'sacubitril-valsartan' and 'dapagliflozin' and link them from the 'indications/hf-htn/_index.md' page.

### suggested_new_page
- **Page:** `drugs/apixaban.md`
- **Detail:** Recent log entries from '2026-05-24' show that multiple PubMed abstracts for 'apixaban' have been ingested, but no corresponding drug page exists in the wiki.
- **Action:** Create a new drug page for 'apixaban' to synthesize the new information and begin tracking this entity.

### suggested_new_page
- **Page:** `topics/inflation-reduction-act.md`
- **Detail:** Multiple drug pages (empagliflozin, sitagliptin, pembrolizumab) mention significant impacts from the Inflation Reduction Act (IRA) Drug Price Negotiation Program. This recurring theme lacks a central tracking page.
- **Action:** Create a new synthesis page to track the IRA's impact, list affected drugs, and consolidate related events and sentiment.

### suggested_new_page
- **Page:** `drugs/dapagliflozin.md`
- **Detail:** The company page 'companies/astrazeneca.md' lists 'dapagliflozin' as a blockbuster drug for multiple indications, but no corresponding drug page exists.
- **Action:** Create a new drug page for 'dapagliflozin' to track this important asset and populate the 'hf-htn' and 'type2-diabetes' indication hubs.

## Suggested new pages

- Recent log entries from '2026-05-24' show that multiple PubMed abstracts for 'apixaban' have been ingested, but no corresponding drug page exists in the wiki.
- Multiple drug pages (empagliflozin, sitagliptin, pembrolizumab) mention significant impacts from the Inflation Reduction Act (IRA) Drug Price Negotiation Program. This recurring theme lacks a central tracking page.
- The company page 'companies/astrazeneca.md' lists 'dapagliflozin' as a blockbuster drug for multiple indications, but no corresponding drug page exists.