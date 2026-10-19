# Production and DMUAT attribute comparison

[Download the Excel report](Prod-DMUAT-Attribute-Comparison.xlsx)

Refreshed from both orgs on **October 19, 2026, 04:41:25–04:41:39 UTC**. Production uses `equinix-ltc-prod`; `dmuat` points to the `ltcsit1` sandbox.

**All 324 matched product SKUs have the same active attribute-code sets.** DMUAT has 39 attribute definitions absent from Production at catalog level; these are not missing active attributes on the matched products. Settings or picklist contents differ on 28 matched products.

| Catalog object | Production | DMUAT | Only Production | Only DMUAT | Changed matched records |
|---|---:|---:|---:|---:|---:|
| Attribute definitions | 1,901 | 1,940 | 0 | 39 | 2 |
| Picklists | 298 | 298 | 0 | 0 | 0 |
| Picklist values | 2,222 | 2,268 | 1 | 47 | 81 |
| Product classifications | 302 | 307 | 0 | 5 | 0 |
| Classification attribute assignments | 5,752 | 5,790 | 0 | 38 | 29 |
| Products | 325 | 336 | 1 | 12 | 0 |

Attribute categories are identical (7 each). Both orgs have zero direct product attribute assignments and zero units of measure. Counts include active and inactive catalog records.

## Since prior snapshot

Compared with **October 12, 2026**, DMUAT has **no new or removed attribute definition Codes and no added classification-to-attribute pairs**. It has three removed pairs and 16 changed assignments. Its product count remains 336.

- The removed assignments are IBX on the BMMR classification, and Circuit Type and Circuit Usable kVA on the Power Installation Fee classification. These same three assignments were removed from Production.
- DMUAT assignment changes include Siebel mappings, Power Installation Fee sequence values, and the Smart Hands Services Z-End Connector default changing from `Please Select` to `-`. Internet Billing Type became capacity impacting at definition level.
- DMUAT gained 52 picklist value records: 51 in EIA Bandwidth and one in Z-End Connector. One existing Geo Scope value changed its Code from `Non-Geo` to `Non‑Geo` (a nonbreaking hyphen). That rename appears as one removed and one added business key, not a deleted and recreated record.
- Production gained 78 definitions, 23 classifications, 30 products and 497 classification-to-attribute pairs; three pairs were removed. FC Carrier Id (`EQX_Attr_FCCarrierId`) and Custom Mesh (`EQX_Attr_Custom_Mesh`) are now present in both orgs. The number of DMUAT definition Codes absent from Production fell from 117 to 39.

These changes describe each org over time. The table above compares the two current org snapshots.

## Product detail

The workbook includes all **337 distinct products**, their catalog details and attribute differences.

- 324 products match by unique SKU; all have equal active attribute-code sets and equal exported product metadata.
- 28 matched products have settings or picklist-content differences; 296 have no compared attribute change. Counts include descriptive and sequence changes.
- DMUAT has 12 additional products, nine active. Production has one unmatched inactive product, Trouble.
- The **Product attributes** sheet has 33 active-assignment rows, all on DMUAT-only products: Cooling (3), Fabric One (7), Fabric One Addon (6) and Liquid Cooling Circuit (17). Fabric One Addon itself is inactive; assignment activity and product activity are shown separately.

Network Cable Connection (`NCC.TSPEC`) now has 172 active attributes in each org; Colocation Cabinet (`COLO.CAB.TSPEC`) has 49 in each; Power Installation Fee (`COLO.PWR.INST.FEE`) has six in each.

Current flag differences are two definition-level Capacity Impacting differences, four assignment-level Hidden differences, two assignment-level Required differences and zero Read Only differences. DMUAT requires Resolution Hours on Premier Support Service and Cabinet Arrival Date on Cabinet, and hides Overage Charge on four MPC products where Production does not.

## Workbook contents

- **Summary**: counts, sources and scope.
- **Changed settings**: 122 changed fields across 112 matched catalog records.
- **Missing records**: two Production-only and 141 DMUAT-only catalog records, including definitions without product assignments.
- **Product details**: complete comparison of 337 products and related attribute-change counts.
- **Product attributes**: 33 active-assignment rows on products present only in DMUAT; no active attribute-code gaps on matched SKUs.
- **Product settings**: 211 changed field or picklist-content rows across 28 matched products.
- **Field availability**: five fields available only in DMUAT exports.
- **Method and checks**: matching rules, reconciliations and limitations.

## Method and limits

**Product attributes** and **Product settings** show both orgs' **Is Required (assignment)**, **Is Hidden**, **Is Capacity Impacting**, and **Is Read Only**. Required, Hidden and Read Only come from `ProductClassificationAttr`; Capacity Impacting comes from `AttributeDefinition.isCapacityImpacting__c`. Definition-level Required is separate. Missing sources appear as `n.a.`, with assignment-status columns; a definition flag can still exist when a product or assignment is absent.

Business keys identify records and resolve lookup IDs. All 20 exports and 18 object/org reconciliations pass. No ambiguous matches, unresolved references, classification parent links, direct product assignments or contextual overrides were found.

Catalog comparison includes active and inactive records; product attribute coverage uses assignments whose Status is Active, without filtering out inactive products or definitions. Fields available in only one org are reported separately and excluded from shared-field change counts. The five DMUAT-only exported fields have no populated values in this snapshot. Inflight and MACD eligibility fields are now available in both org exports and are compared as shared fields.

This is a static comparison of records and fields visible to the connected users over the export interval. Configuration rules, pricing procedures, permissions and actual configurator behavior were not tested. Product metadata comparison is limited to the catalog fields included in the workbook. This refresh changed no Salesforce records or metadata.

Only the report and this summary are published here. Credentials and raw exports are excluded.
