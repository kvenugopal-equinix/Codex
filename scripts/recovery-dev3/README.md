# Opportunity to Asset recovery pack

This pack was traced from live `dev3` Salesforce metadata on 2026-10-13. It is an **analysis-based set of manual Apex recovery drafts**, for one failed record and one failed stage at a time after the source issue is fixed. It does not replay an entire Opportunity journey. The templates default to `dryRun = true`, pin dev3 org `00DWI00000DzbpZ2AR`, and require an exact 18-character Salesforce ID. Some paths may not execute in production without deployed metadata, permissions, or interface validation. No production data was changed while building this pack.

## Find the failed stage

Run the read-only inspector with the exact Opportunity, Quote, Order, root OrderItem (POF), or Asset ID from the incident:

```powershell
./scripts/recovery-dev3/Inspect-RecoveryState.ps1 -RecordId <18-character-ID> -Days 3 -Limit 20
```

Follow the record links and inspect the latest Salesforce error, queue/job state, and the receiving system's acknowledgement. For a timeout or missing Salesforce log, check the receiving system before submitting another request.

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

## Run a template

From the workspace root in PowerShell, use the bundled Salesforce CLI:

```powershell
$node = '.tools/node-v24.18.0-win-x64/node.exe'
$sf = '.tools/sf-prefix/node_modules/@salesforce/cli/bin/run.js'
& $node $sf data query --target-org dev3 --query 'SELECT Id, IsSandbox FROM Organization LIMIT 1'
& $node $sf apex run --target-org dev3 --file scripts/recovery-dev3/apex/03-order-booking.apex
```

First edit the chosen file's `recordIdText` (and any second ID or interface key), leaving `dryRun = true`. Run it and read `RECOVERY PREFLIGHT` in the Apex log. Resolve any guard failure rather than bypassing it. Check the actual downstream system and existing work. For an authorized incident replay, change only that file's `dryRun` to `false` and set its named confirmation flag after the evidence is recorded. Submit once, save the job/log ID, and verify the downstream outcome before considering another attempt.

For production after deployment, query `Organization` using the production alias, then edit both `expectedOrgId` and `expectedSandbox` in the chosen copy. Recheck the class/Flow contracts, field permissions, and active configuration against the deployed production version first. A dev3 compile check does not prove the production path will execute.

## Limits of general replay

The current dev3 metadata has no safe general replay method for Quote product configuration after a CPQ save, portal order line creation, external order placement after an ambiguous callout, Agiloft agreement recreation, or arbitrary fulfillment failures. These require record-specific reconciliation and a targeted repair. Do not toggle Quote or Order status solely to fire their event subscribers. `PlaceOrderAsyncReplayService` has no callable implementation in dev3. A completed booking queue, accepted event, or enqueued job is only an intermediate state.

The Apex files have compile-checked in dev3 with their placeholder IDs. Those checks stopped before DML or callouts. One fulfillment activity event dry run with an existing dev3 line completed with zero DML, callouts, or queued jobs. No recovery replay was submitted.
