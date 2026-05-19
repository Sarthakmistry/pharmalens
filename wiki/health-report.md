# Wiki health report
Generated: 2026-05-02 02:32  |  Pages checked: 107

## Structural issues (31)

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
- **Page:** `drugs/nivolumab.md`
- **Detail:** nivolumab in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/osimertinib.md`
- **Detail:** osimertinib in drugs.json but no wiki page exists yet

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

### missing_drug_page
- **Page:** `drugs/bevacizumab.md`
- **Detail:** bevacizumab in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/cetuximab.md`
- **Detail:** cetuximab in drugs.json but no wiki page exists yet

### missing_drug_page
- **Page:** `drugs/lecanemab.md`
- **Detail:** lecanemab in drugs.json but no wiki page exists yet

### missing_company_page
- **Page:** `companies/merck.md`
- **Detail:** merck in companies.json but no wiki page exists yet

### missing_company_page
- **Page:** `companies/astrazeneca.md`
- **Detail:** astrazeneca in companies.json but no wiki page exists yet

### missing_company_page
- **Page:** `companies/johnson-and-johnson.md`
- **Detail:** johnson-and-johnson in companies.json but no wiki page exists yet

### missing_company_page
- **Page:** `companies/gilead.md`
- **Detail:** gilead in companies.json but no wiki page exists yet

### missing_company_page
- **Page:** `companies/gsk.md`
- **Detail:** gsk in companies.json but no wiki page exists yet

### missing_company_page
- **Page:** `companies/takeda.md`
- **Detail:** takeda in companies.json but no wiki page exists yet

### missing_company_page
- **Page:** `companies/eisai.md`
- **Detail:** eisai in companies.json but no wiki page exists yet

### missing_indication_hub
- **Page:** `indications/type2-diabetes/_index.md`
- **Detail:** No _index.md for indication type2-diabetes

### missing_indication_hub
- **Page:** `indications/alzheimers/_index.md`
- **Detail:** No _index.md for indication alzheimers

### missing_indication_hub
- **Page:** `indications/hf-htn/_index.md`
- **Detail:** No _index.md for indication hf-htn

### missing_indication_hub
- **Page:** `indications/oncology-nsclc/_index.md`
- **Detail:** No _index.md for indication oncology-nsclc

### missing_indication_hub
- **Page:** `indications/oncology-breast/_index.md`
- **Detail:** No _index.md for indication oncology-breast

### missing_indication_hub
- **Page:** `indications/oncology-crc/_index.md`
- **Detail:** No _index.md for indication oncology-crc

## Semantic issues (5)

### contradiction
- **Page:** `companies/eli-lilly.md`
- **Detail:** The company page lists 'donanemab' in 'blockbuster_drugs'. However, the corresponding drug page 'drugs/donanemab.md' indicates its status is 'phase3' and it received a negative approval recommendation from EMA's CHMP, which contradicts the definition of a blockbuster drug.
- **Action:** Remove 'donanemab' from the 'blockbuster_drugs' list in the frontmatter of 'companies/eli-lilly.md'.

### stale_entity
- **Page:** `companies/abbvie.md`
- **Detail:** The page has a 'last_updated' date of '2025-07-31', but a document for a later event on '2025-10-03' ('2025-10-03-abbvie-eps-guidance-update.md') was successfully ingested on 2026-05-02. The page has not been updated to reflect this new information.
- **Action:** Update 'companies/abbvie.md' with information from the October 3, 2025 event and update the 'last_updated' timestamp.

### missing_backlink
- **Page:** `companies/abbvie.md`
- **Detail:** An event page 'events/2025-10-03-abbvie-eps-guidance-update.md' exists, but the main company page does not reference this event in its 'Earnings intelligence' section or other relevant fields.
- **Action:** Add a reference to the '2025-10-03' guidance update event on the 'companies/abbvie.md' page.

### thin_indication_hub
- **Page:** `indications/glp1-obesity/_index.md`
- **Detail:** The wiki contains at least three drugs associated with the 'glp1-obesity' indication ('semaglutide', 'dulaglutide', 'tirzepatide'). The central indication hub page is likely incomplete as it may not link to all relevant drugs.
- **Action:** Audit 'indications/glp1-obesity/_index.md' and ensure it links to all drugs with the 'glp1-obesity' indication.

### suggested_new_page
- **Page:** `analysis/ira-drug-price-negotiation-impact.md`
- **Detail:** Multiple drug pages (e.g., 'drugs/empagliflozin.md', 'drugs/sitagliptin.md', 'drugs/pembrolizumab.md') mention the impact of the Inflation Reduction Act (IRA) drug price negotiation. There is no central page to synthesize this cross-cutting theme.
- **Action:** Create a new analysis page to track and summarize the impact of the IRA price negotiations on all affected drugs and companies in the wiki.

## Suggested new pages

- Multiple drug pages (e.g., 'drugs/empagliflozin.md', 'drugs/sitagliptin.md', 'drugs/pembrolizumab.md') mention the impact of the Inflation Reduction Act (IRA) drug price negotiation. There is no central page to synthesize this cross-cutting theme.