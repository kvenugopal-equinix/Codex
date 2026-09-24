# Production and DMUAT attribute comparison

[Download the Excel report](Prod-DMUAT-Attribute-Comparison.xlsx)

Snapshot collected on September 24, 2026, ending at 06:00 UTC. Production uses the existing `equinix-ltc-prod` connection. The requested `dmuat` alias points to the `ltcsit1` sandbox.

| Catalog object | Production | DMUAT | Only Production | Only DMUAT | Changed matched records |
|---|---:|---:|---:|---:|---:|
| Attribute definitions | 1,823 | 1,939 | 0 | 116 | 10 |
| Picklists | 268 | 297 | 0 | 29 | 0 |
| Picklist values | 2,084 | 2,209 | 2 | 127 | 83 |
| Product classifications | 279 | 307 | 0 | 28 | 0 |
| Classification attribute assignments | 5,258 | 5,789 | 4 | 535 | 152 |
| Products | 295 | 334 | 1 | 40 | 3 |

Attribute categories are identical (7 each). Both orgs have zero direct product attribute assignments and zero units of measure.

## Product detail

The workbook includes all 335 distinct products across the two orgs, with SKU, product code, family, active status, assetizable status, classifications, and attribute differences.

- 294 products match by unique SKU.
- 110 matched products have differences in shared attribute fields or active assignment sets. This includes descriptive text changes and picklist changes; it is not a count of tested runtime failures.
- 9 matched products have added or missing attributes; 107 have settings differences, with 6 products in both groups.
- DMUAT contains 40 additional products (39 active). Production has one unmatched inactive product, Trouble.

Examples:

- Colocation Cabinet: 19 to 49 active attribute assignments.
- Metro Connect Port: no classification or active assignments in Production; 85 active assignments in DMUAT.
- Power Installation Fee: Voltage, Breakered Amperage, Phase and IBX become required. Circuit Type and Circuit Usable kVA are absent from its DMUAT assignment set, while Circuit Current Type and Distribution Type are added.
- The EQX Location picklist changes Onsite to Onshore and OffSite to Offshore, affecting 15 matched products.

## Workbook contents

- **Summary**: counts, sources and scope.
- **Changed settings**: 265 changed fields across 248 matched catalog records.
- **Missing records**: 7 Production-only and 875 DMUAT-only catalog records.
- **Product details**: complete product comparison and counts of related attribute changes.
- **Product attributes**: added/missing attribute names and codes by product.
- **Product settings**: changed values by product, plus true DMUAT-only eligibility flags.
- **Field availability**: 11 fields available only in DMUAT exports and 2 nullability differences.
- **Method and checks**: matching rules, completeness reconciliations and limitations.

## Method and limits

Records match by validated business keys, with Salesforce lookup IDs resolved to those keys. No ambiguous matches or unresolved references were found. All 18 object/org record-count reconciliations passed. The workbook contains filterable tables and was checked against the source counts.

The comparison includes active and inactive catalog records. Product attribute coverage uses active assignments. Fields available in only one org are reported separately and excluded from shared-field change counts. DMUAT has 65 true inflight-eligibility and 11 true MACD-eligibility assignments across six DMUAT-only products, so these do not change the 110/184 split among matched products.

This is a static comparison of records and fields visible to the connected Salesforce users, collected over an export interval. Configuration rules, pricing procedures, permissions and actual configurator behavior were not tested. Product metadata comparison is limited to the catalog fields included in the workbook. No Salesforce records or metadata were changed.

Only the report and this summary are published here. Authentication credentials and raw connection exports are excluded.
