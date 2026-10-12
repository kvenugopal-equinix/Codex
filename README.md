# Production and DMUAT attribute comparison

[Download the Excel report](Prod-DMUAT-Attribute-Comparison.xlsx)

Refreshed from both orgs on **October 12, 2026, 04:01:38–04:03:41 UTC**. Production uses `equinix-ltc-prod`; `dmuat` points to the `ltcsit1` sandbox.

| Catalog object | Production | DMUAT | Only Production | Only DMUAT | Changed matched records |
|---|---:|---:|---:|---:|---:|
| Attribute definitions | 1,823 | 1,940 | 0 | 117 | 10 |
| Picklists | 268 | 298 | 0 | 30 | 0 |
| Picklist values | 2,084 | 2,216 | 2 | 134 | 83 |
| Product classifications | 279 | 307 | 0 | 28 | 0 |
| Classification attribute assignments | 5,258 | 5,793 | 0 | 535 | 174 |
| Products | 295 | 336 | 1 | 42 | 3 |

Attribute categories are identical (7 each). Both orgs have zero direct product attribute assignments and zero units of measure.

## Since prior snapshot

Compared with September 24, DMUAT has **two new attribute definition Codes and one removed Code**, for a net increase of one definition:

- **FC Carrier Id** (`EQX_Attr_FCCarrierId`) is a new Text attribute assigned to Network Cable Connection (`NCC.TSPEC`).
- **Custom Mesh** now uses `EQX_Attr_Custom_Mesh`, replacing the removed `Custom_Mesh` record on Space (`COLO.SPCE`). It uses a new picklist; its definition default is `No`, while its assignment default remains `-`.

Both new Codes are absent from current Production. DMUAT now has **1,940 definitions, including 117 absent from Production**. These are current Production-versus-DMUAT totals; the two additions above describe changes within DMUAT since the prior snapshot.

## Product detail

The workbook includes all **337 distinct products** across the two orgs, with SKU, product code, family, active and assetizable status, classifications, and attribute differences.

- 294 products match by unique SKU.
- 209 matched products have differences in shared attribute fields, picklist contents or active assignment sets; 85 have no compared attribute change. These counts include descriptive and sequence changes, not tested runtime failures.
- 8 matched products have different active attribute sets; 208 have settings differences, with 7 products in both groups.
- DMUAT has 42 additional products (39 active). Production has one unmatched inactive product, Trouble.

Examples: Network Cable Connection has 137 active attributes in Production and 172 in DMUAT; Colocation Cabinet has 19 versus 49; Power Installation Fee has 6 versus 8, with Circuit Current Type and Distribution Type added in DMUAT. Metro Connect Port has no classification or active assignments in Production and 85 active attributes in DMUAT.

## Workbook contents

- **Summary**: counts, sources and scope.
- **Changed settings**: 288 changed fields across 270 matched catalog records.
- **Missing records**: 3 Production-only and 886 DMUAT-only catalog records, including definitions without product assignments.
- **Product details**: complete product comparison and related attribute-change counts.
- **Product attributes**: added/missing active attributes by product.
- **Product settings**: changed values by product and true DMUAT-only eligibility flags.
- **Field availability**: 9 fields available only in DMUAT exports.
- **Method and checks**: matching rules, reconciliations and limitations.

## Method and limits

**Product attributes** and **Product settings** include side-by-side Production and DMUAT values for **Is Required (assignment)**, **Is Hidden**, **Is Capacity Impacting**, and **Is Read Only**. Required, Hidden and Read Only come from `ProductClassificationAttr`; Capacity Impacting comes from `AttributeDefinition.isCapacityImpacting__c`. Definition-level Required is a separate setting. Missing source records appear as `n.a.`, with assignment-status columns explaining the absence.

Records match by validated business keys, with lookup IDs resolved to those keys. All 20 exports reconcile to their query totals; all 18 compared object/org reconciliations pass. No ambiguous matches or unresolved references were found.

Catalog comparison includes active and inactive records; product attribute coverage uses active assignments. Fields available in only one org are reported separately and excluded from shared-field change counts. DMUAT has 68 true inflight-eligibility and 10 true MACD-eligibility assignments across six DMUAT-only products; these do not change the 209/85 split among matched products.

This is a static comparison of records and fields visible to the connected users over the export interval. Configuration rules, pricing procedures, permissions and actual configurator behavior were not tested. Product metadata comparison is limited to the catalog fields included in the workbook. No Salesforce records or metadata were changed.

Only the report and this summary are published here. Credentials and raw exports are excluded.
