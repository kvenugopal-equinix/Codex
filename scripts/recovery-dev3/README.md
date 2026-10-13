# Opportunity to Asset recovery pack

This pack was traced from live `dev3` Salesforce metadata on 2026-10-13. It is an **analysis-based set of manual Apex recovery drafts**, for one failed record and one failed stage at a time after the source issue is fixed. It does not replay an entire Opportunity journey. The templates default to `dryRun = true`, pin dev3 org `00DWI00000DzbpZ2AR`, and require an exact 18-character Salesforce ID. Some paths may not execute in production without deployed metadata, permissions, or interface validation. No production data was changed while building this pack.

## Find the failed stage

In Salesforce Inspector **Data Export**, query the affected Opportunity, Quote, Order, root OrderItem (POF), fulfillment record, or Asset and its latest error/job records. Use the table below to select **one failed stage**. Check the receiving system's acknowledgement before retrying a timeout or a request with no Salesforce log.

The separate [`Inspect-RecoveryState.ps1`](Inspect-RecoveryState.ps1) is an optional read-only dev3 diagnostic for PowerShell users. It is not required to run any `.apex` template in Inspector.

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

Every `.apex` file is one complete **Execute Anonymous** body. No Salesforce CLI, deployment, or PowerShell command is needed to run a recovery template. Use the Inspector variant installed in your browser:

| Extension | Where to run the template |
| --- | --- |
| **Salesforce Inspector Advanced** (has **Apex Runner**) | Copy the *raw contents* of one `.apex` file into Apex Runner and execute the entire body. |
| **Salesforce Inspector Reloaded** (has **REST Explorer**) | Use the offline [`inspector-reloaded-builder.html`](inspector-reloaded-builder.html) to URL-encode one `.apex` file. Copy its generated endpoint into REST Explorer, select **GET**, leave Body empty, and click **Send**. Reloaded's Execute Anonymous template uses the same Tooling API endpoint; the raw Apex body cannot be pasted into its request Body field. |

For Reloaded, download the folder, open the builder HTML locally, and load the chosen `.apex` file in it. If your extension has neither Apex Runner nor REST Explorer, it cannot execute these templates. The extension guides are [Advanced Apex Runner](https://dufoli.github.io/Salesforce-Inspector-Advanced/how-to/#apex-runner), [Reloaded REST Explorer](https://tprouvot.github.io/Salesforce-Inspector-reloaded/rest-explorer/), and [Reloaded Logs Viewer](https://tprouvot.github.io/Salesforce-Inspector-reloaded/logs-viewer/).

1. Open the **target org** in Salesforce and verify its domain. In Inspector **Data Export**, run `SELECT Id, IsSandbox FROM Organization LIMIT 1`. Copy the returned values into `expectedOrgId` and `expectedSandbox` in your working copy of the Apex. Production normally has `expectedSandbox = false`; use the value returned by the org. The shipped values are pinned to dev3 and intentionally stop in a different org.
2. Edit the exact 18-character record ID placeholder(s), interface/event choices, and any script-specific inputs. Keep `dryRun = true`. In Inspector Reloaded, enable a debug log for the executing user from its **User** tab before sending the request, then build the endpoint from the edited Apex in the offline builder. In Inspector Advanced, paste the edited Apex into Apex Runner.
3. Execute once. In Reloaded, require **both** `compiled: true` and `success: true` in the REST response; HTTP 200 alone does not mean the Apex ran successfully. Open Inspector **Logs Viewer** (or **Org → Logs** in versions with that menu), Preview the latest **Execute Anonymous** log, and search for `RECOVERY PREFLIGHT`. In Advanced, inspect the Apex Runner result and the matching debug log. Resolve guard failures instead of bypassing them.
4. Check the record state, existing jobs, and downstream acknowledgement. For an authorized incident replay after the source issue is fixed, change `dryRun` to `false` and set only the named confirmation flags supported by the evidence. In Reloaded, build and copy a **new** endpoint from that revised Apex. Submit once, retain the response/log or job ID, and verify the downstream outcome before another attempt.

Before production use, recheck the referenced class/Flow contracts, field permissions, and active configuration against the deployed version. A dev3 compile check does not prove a production replay will execute. See [the Apex notes](apex/README.md) for stage-specific inputs and limits.

## Limits of general replay

The current dev3 metadata has no safe general replay method for Quote product configuration after a CPQ save, portal order line creation, external order placement after an ambiguous callout, Agiloft agreement recreation, or arbitrary fulfillment failures. These require record-specific reconciliation and a targeted repair. Do not toggle Quote or Order status solely to fire their event subscribers. `PlaceOrderAsyncReplayService` has no callable implementation in dev3. A completed booking queue, accepted event, or enqueued job is only an intermediate state.

The Apex files have compile-checked in dev3 with their placeholder IDs. Those checks stopped before DML or callouts. One fulfillment activity event dry run with an existing dev3 line completed with zero DML, callouts, or queued jobs. No recovery replay was submitted.
