# Opportunity to Asset recovery pack

This pack was traced from live `dev3` Salesforce metadata on 2026-10-13. It is an **analysis-based set of manual Apex recovery drafts**, for one failed record and one failed stage at a time after the source issue is fixed. It does not replay an entire Opportunity journey. The templates default to `dryRun = true` and require an exact 18-character Salesforce ID. They run in the org where you are already logged in through Salesforce Inspector. Some paths may not execute in production without deployed metadata, permissions, or interface validation. No production data was changed while building this pack.

## Find the failed stage

In Salesforce Inspector **Data Export**, query the affected Opportunity, Quote, Order, root OrderItem (POF), fulfillment record, or Asset and its latest error/job records. Use the table below to select **one failed stage**. Check the receiving system's acknowledgement before retrying a timeout or a request with no Salesforce log.

| Stage / failure | Apex template | Replay boundary |
| --- | --- | --- |
| Opportunity coexistence event to legacy consumer | [`01-opportunity-legacy.apex`](apex/01-opportunity-legacy.apex) | One Opportunity; confirm the consumer did not already apply it. |
| Quote booking calculation | [`02-quote-booking.apex`](apex/02-quote-booking.apex) | One eligible Quote; creates one new booking queue row. |
| Quote synced to Opportunity | [`14-quote-sync-to-opportunity.apex`](apex/14-quote-sync-to-opportunity.apex) | One eligible Quote; checks current synced Quote and primary revision. |
| Quote line custom fields to Opportunity products | [`16-quote-lines-to-opportunity-products.apex`](apex/16-quote-lines-to-opportunity-products.apex) | One syncing Draft Quote with linked Opportunity lines; may overwrite mapped fields. |
| Quote VDC capacity/design | [`10-quote-vdc.apex`](apex/10-quote-vdc.apex) | One root Quote POF; response can stamp several Quote lines. |
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
| FulfillmentAsset technical outbound | [`06-fulfillment-asset-outbound.apex`](apex/06-fulfillment-asset-outbound.apex) | One FulfillmentAsset; confirm absence/failure downstream. |
| FulfillmentAsset event outbound | [`18-fulfillment-asset-event.apex`](apex/18-fulfillment-asset-event.apex) | One `Publish_Asset__e` with explicit CREATE/UPDATE and original-value check. |
| Failed queue job | [`07-job-queue-dead-letter.apex`](apex/07-job-queue-dead-letter.apex) | One Dead Letter row with exact handler/action and repaired root cause. |

Read [the Apex notes](apex/README.md) for VDC, Caplogix, and fulfillment event details, and [RISKS.md](RISKS.md) for stages where re-running the originating action can duplicate a Quote line, Order line, order placement, contract, billing transaction, or Asset.

## Run a template from Salesforce Inspector

Each `.apex` file is one complete anonymous Apex script. In the Salesforce org where you are **already logged in**:

1. Confirm Inspector shows the intended Salesforce org, then open its **Apex Execute** or **Apex Runner** screen. Open the chosen `.apex` file in GitHub, use **Raw / Copy raw contents**, and paste the whole script.
2. Replace the 18-character record ID placeholder(s) and any interface or event choice required near the top. Leave `dryRun = true`, then click **Execute**. Read `RECOVERY PREFLIGHT` in the execution log and resolve any guard failure.
3. After checking the existing work and downstream acknowledgement, change `dryRun` to `false` and set the script's named confirmation flags for the reviewed incident. Execute once and verify the resulting job, record, event, or external acknowledgement before another attempt.

There is no alias, org ID, sandbox flag, CLI, or environment setup in these Apex files. The browser's logged-in Salesforce session determines the org. Before production use, recheck the referenced class/Flow contracts, field permissions, and active configuration against the deployed version. See [the Apex notes](apex/README.md) for stage-specific inputs and limits.

If your Inspector shows **REST Explorer** but no Apex editor, it is the Reloaded variant. Its [Execute Anonymous API template](https://tprouvot.github.io/Salesforce-Inspector-reloaded/rest-explorer/) needs URL-encoded Apex: open the optional [offline builder](inspector-reloaded-builder.html), load the edited `.apex` file, and paste the generated **GET endpoint** into REST Explorer. Enable a log for your user first; require `compiled: true` and `success: true` in the response, then read `RECOVERY PREFLIGHT` in [Logs Viewer](https://tprouvot.github.io/Salesforce-Inspector-reloaded/logs-viewer/). This uses the same logged-in Salesforce session.

## Limits of general replay

The current dev3 metadata has no safe general replay method for Quote product configuration after a CPQ save, portal order line creation, external order placement after an ambiguous callout, Agiloft agreement recreation, or arbitrary fulfillment failures. These require record-specific reconciliation and a targeted repair. Do not toggle Quote or Order status solely to fire their event subscribers. `PlaceOrderAsyncReplayService` has no callable implementation in dev3. A completed booking queue, accepted event, or enqueued job is only an intermediate state.

The 18 templates compiled in dev3 with placeholder IDs before the org/sandbox guard lines were removed; their recovery logic was unchanged. Those checks stopped before DML or callouts. One fulfillment activity event dry run with an existing dev3 line completed with zero DML, callouts, or queued jobs. No recovery replay was submitted.
