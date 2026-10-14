# Opportunity to Asset recovery pack

This pack was traced from live `dev3` Salesforce metadata on 2026-10-13 and active `dmuat` metadata on 2026-10-14. It contains **32 manual Apex templates** for one failed record and one failed stage at a time after the source issue is fixed. It does not replay an entire Opportunity journey. The templates default to `dryRun = true` and require an exact 18-character Salesforce ID. They run in the org where you are already logged in through Salesforce Inspector. Some paths may not execute in production without deployed metadata, permissions, or interface validation. No production data was changed while building this pack.

The [DMUAT recovery workbook](DMUAT-Recovery-Scripts-and-Test-Transactions.xlsx) contains the full text of all 32 templates, 73 dry-run test transactions (45 on October 13 and 28 on October 14), and prefilled Inspector scripts. Its **Dev Guide Coverage** tab maps 20 guide scenarios plus the Order Management reference to a tested script, diagnostic route, or external/manual boundary. The workbook includes DMUAT record IDs and recorded results. All 73 cases compiled; 47 reached the expected preflight or diagnostic output, 26 stopped at expected guards, and every run recorded zero DML, callouts, and queueables. The tests did not submit recovery actions.

## Find the failed stage

In Salesforce Inspector **Data Export**, query the affected Opportunity, Quote, Order, root OrderItem (POF), fulfillment record, or Asset and its latest error/job records. Use the table below to select **one failed stage**. Check the receiving system's acknowledgement before retrying a timeout or a request with no Salesforce log.

| Stage / failure | Apex template | Replay boundary |
| --- | --- | --- |
| Opportunity coexistence event to legacy consumer | [`01-opportunity-legacy.apex`](apex/01-opportunity-legacy.apex) | One Opportunity; confirm the consumer did not already apply it. |
| Quote booking calculation | [`02-quote-booking.apex`](apex/02-quote-booking.apex) | One eligible Quote; creates one new booking queue row. |
| Quote synced to Opportunity | [`14-quote-sync-to-opportunity.apex`](apex/14-quote-sync-to-opportunity.apex) | One eligible Quote; checks current synced Quote and primary revision. |
| Quote line custom fields to Opportunity products | [`16-quote-lines-to-opportunity-products.apex`](apex/16-quote-lines-to-opportunity-products.apex) | One syncing Draft Quote with linked Opportunity lines; may overwrite mapped fields. |
| Quote VDC capacity/design | [`10-quote-vdc.apex`](apex/10-quote-vdc.apex) | One root Quote POF with a SKU in `Root_Product_SKU__mdt`; response can stamp several Quote lines. |
| Quote Caplogix | [`12-caplogix-quote.apex`](apex/12-caplogix-quote.apex) | One Quote and an exact reviewed interface; CFR requires a root Quote line. |
| Quote to Order | [`09-quote-to-order.apex`](apex/09-quote-to-order.apex) | One accepted Quote with no existing linked Order. |
| Order booking calculation | [`03-order-booking.apex`](apex/03-order-booking.apex) | One complete Order with lines; creates one new booking queue row. |
| Order VDC | [`11-order-vdc.apex`](apex/11-order-vdc.apex) | One Order POF; **blocked for current dev3 user** by VDC status field visibility. |
| Order Caplogix | [`13-caplogix-order.apex`](apex/13-caplogix-order.apex) | One Order and exact reviewed interface; CFR may fan out to every required root. |
| Order decomposition into fulfillment | [`15-order-decomposition-one-pof.apex`](apex/15-order-decomposition-one-pof.apex) | One configured root POF with no existing step source; inspect partial fulfillment lines. |
| Fulfillment activity outbound (possible Jarvis route) | [`17-fulfillment-activity-event.apex`](apex/17-fulfillment-activity-event.apex) | One `Publish_Activity__e`; consumer identity and acknowledgement require external verification. |
| Oracle billing | [`04-root-pof-oracle-billing.apex`](apex/04-root-pof-oracle-billing.apex) | One closed root POF; confirm Oracle did not already receive it. |
| Fulfillment Assetize row lock | [`08-assetize-lock-one-step.apex`](apex/08-assetize-lock-one-step.apex) | One aged failed `StagedAssetize` step on an active plan, under its retry cap. |
| Asset commercial outbound | [`05-asset-outbound.apex`](apex/05-asset-outbound.apex) | One Asset; confirm absence/failure downstream. |
| FulfillmentAsset technical outbound | [`06-fulfillment-asset-outbound.apex`](apex/06-fulfillment-asset-outbound.apex) | One locally completed FulfillmentAsset; review any stored response and confirm absence/failure downstream. |
| FulfillmentAsset event outbound | [`18-fulfillment-asset-event.apex`](apex/18-fulfillment-asset-event.apex) | One `Publish_Asset__e` with explicit CREATE/UPDATE and original-value check. |
| Failed queue job | [`07-job-queue-dead-letter.apex`](apex/07-job-queue-dead-letter.apex) | One Dead Letter row with exact handler/action and repaired root cause. |

### Dev Guide additions

| Process | Apex template | Replay boundary |
| --- | --- | --- |
| Stale Order header closure | [`19-stale-order-header-closure.apex`](apex/19-stale-order-header-closure.apex) | One eligible stale-AssetAction Order. `planFor()` previews without writes; `run()` can delete AssetAction rows and queue assetization. |
| Closed fulfillment activity, open commercial Order line | [`20-one-order-line-closure-event.apex`](apex/20-one-order-line-closure-event.apex) | One last Closed FulfillmentOrderLineItem; verify all linked activities and downstream closure before publishing `LineClosure`. |
| Commercial Asset OPS hierarchy | [`21-one-asset-ops-hierarchy.apex`](apex/21-one-asset-ops-hierarchy.apex) | One parent-ready commercial Asset. Technical FulfillmentAsset input is diagnostic only; unresolved hierarchy logs and child job effects need review. |
| NCC in staging | [`22-ncc-in-staging.apex`](apex/22-ncc-in-staging.apex) | One NCC fulfillment line through the active Flow; confirm DSO003 send and DSO056/Cortex outcome are absent. |
| BMMR provisioning | [`23-bmmr-provisioning.apex`](apex/23-bmmr-provisioning.apex) | One reviewed NCC line and BMMR sibling; the active Flow resets fields before publishing. |
| Fiber Connect provisioning | [`24-fiber-connect-provisioning.apex`](apex/24-fiber-connect-provisioning.apex) | One fulfillment line; review its current field snapshot and reset impact before publishing. |
| Path provisioning | [`25-path-provisioning.apex`](apex/25-path-provisioning.apex) | One fulfillment line; confirm external history and reset impact. The deployed Path Flow logs under a Fiber Connect label. |
| Generic Cortex in staging | [`26-generic-cortex-in-staging.apex`](apex/26-generic-cortex-in-staging.apex) | One fulfillment line; field reset occurs only on the Provisioning branch and requires a separate review. |
| Approval outcome status | [`27-approval-outcome-status.apex`](apex/27-approval-outcome-status.apex) | One Received root outcome; preview children, current-sequence peers, and future approval sequences before invoking the active Flow. |
| Quote approval status | [`28-quote-approval-status.apex`](apex/28-quote-approval-status.apex) | One Pending Approval Quote whose current-revision outcomes have resolved; verify expected status and expiration effects. |
| Retry termination fee lines | [`29-retry-fee-lines.apex`](apex/29-retry-fee-lines.apex) | One Quote can retry many cancellation lines; review Quote type, full line/charge ID lists, OSM assets, fee mappings, and existing charges. |
| Legal agreement validation | [`30-legal-agreement-validation.apex`](apex/30-legal-agreement-validation.apex) | One accepted Quote with invalid agreements and no Order; confirm Agiloft `productOrderable` before the active Flow's callout. |
| CAP/Design SOLD status | [`31-cap-sold-diagnostic.apex`](apex/31-cap-sold-diagnostic.apex) | Diagnostic only. VDC must resend the authoritative SOLD event; there is no safe Salesforce-only replay. |
| Coterm, amendment attributes, or Send to Customer | [`32-quote-change-diagnostic.apex`](apex/32-quote-change-diagnostic.apex) | Diagnostic only. Resolve OSM, configurator, or UI/expiration source issues; the script has no replay path. |

Read [the Apex notes](apex/README.md) for VDC, Caplogix, and fulfillment event details, and [RISKS.md](RISKS.md) for stages where re-running the originating action can duplicate a Quote line, Order line, order placement, contract, billing transaction, or Asset.

## Run a template from Salesforce Inspector

Each `.apex` file is one complete anonymous Apex script. In the Salesforce org where you are **already logged in**:

1. Confirm Inspector shows the intended Salesforce org, then open its **Apex Execute** or **Apex Runner** screen. Open the chosen `.apex` file in GitHub, use **Raw / Copy raw contents**, and paste the whole script.
2. Replace the 18-character record ID placeholder(s) and any interface or event choice required near the top. Leave `dryRun = true`, then click **Execute**. Read `RECOVERY PREFLIGHT` in the execution log and resolve any guard failure.
3. For a script with a live replay path, after checking the existing work and downstream acknowledgement, change `dryRun` to `false` and set its named confirmation flags for the reviewed incident. Execute once and verify the resulting job, record, event, or external acknowledgement before another attempt. Scripts 31 and 32, and script 21 with a technical FulfillmentAsset ID, remain diagnostic only.

There is no alias, org ID, sandbox flag, CLI, or environment setup in these Apex files. The browser's logged-in Salesforce session determines the org. Before production use, recheck the referenced class/Flow contracts, field permissions, and active configuration against the deployed version. See [the Apex notes](apex/README.md) for stage-specific inputs and limits.

If your Inspector shows **REST Explorer** but no Apex editor, it is the Reloaded variant. Its [Execute Anonymous API template](https://tprouvot.github.io/Salesforce-Inspector-reloaded/rest-explorer/) needs URL-encoded Apex: open the optional [offline builder](inspector-reloaded-builder.html), load the edited `.apex` file, and paste the generated **GET endpoint** into REST Explorer. Enable a log for your user first; require `compiled: true` and `success: true` in the response, then read `RECOVERY PREFLIGHT` in [Logs Viewer](https://tprouvot.github.io/Salesforce-Inspector-reloaded/logs-viewer/). This uses the same logged-in Salesforce session.

## Limits of general replay

The current dev3 metadata has no safe general replay method for Quote product configuration after a CPQ save, portal order line creation, external order placement after an ambiguous callout, Agiloft agreement recreation, or arbitrary fulfillment failures. These require record-specific reconciliation and a targeted repair. Do not toggle Quote or Order status solely to fire their event subscribers. `PlaceOrderAsyncReplayService` has no callable implementation in dev3. A completed booking queue, accepted event, or enqueued job is only an intermediate state.

The Dev Guide's Customer Accepted Quote with **no interface message** had no exact script 09 replay candidate in DMUAT: all 34 matching Quotes had `Quote_To_Order_inSync__c=true`. Inspect the scheduled Quote-to-Order batch and any existing Order for that state. Script 09's earlier positive dry run used a Quote with an interface error and does not validate the no-message case.

The original 18 templates compiled in dev3 with placeholder IDs, and one fulfillment activity event dry run with an existing dev3 line completed without writes. Across both DMUAT validation rounds, all 32 templates compiled in 73 read-only cases with zero DML, callouts, or queued jobs. No recovery replay was submitted. The Dev Guide tests validate deployed DMUAT contracts, not production parity or external acknowledgements.
