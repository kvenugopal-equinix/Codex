// One stale-asset Order header. The service's dryRun() writes a Transaction_Log__c;
// this template uses planFor() for a genuinely read-only preflight.
Boolean dryRun = true;
String orderIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean staleAssetFailureConfirmed = false;
Boolean destructiveRepairPlanReviewed = false;
Boolean previousRepairFailureResolved = false;

if (orderIdText.length() != 18 || orderIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact 18-character Order Id');
Id orderId = (Id) orderIdText;
if (orderId.getSObjectType() != Order.SObjectType)
    throw new IllegalArgumentException('Id is not an Order');
List<Order> orders = [
    SELECT Id, Order_Number__c, Status, StatusCode, Type
    FROM Order
    WHERE Id = :orderId
    LIMIT 1
];
if (orders.size() != 1)
    throw new IllegalArgumentException('Order missing');
Order ord = orders[0];
if (
    ord.StatusCode != 'Draft' ||
    !new Set<String>{ 'In Fulfillment', 'Configured' }.contains(ord.Status) ||
    ord.Type == 'New'
)
    throw new IllegalArgumentException('Order is outside the stale-asset repair batch scope');

List<OrderItem> lines = [
    SELECT Id, Status
    FROM OrderItem
    WHERE OrderId = :orderId
    LIMIT 201
];
if (lines.isEmpty() || lines.size() > 200)
    throw new IllegalArgumentException('Inspect line count manually before header repair');
for (OrderItem line : lines)
    if (line.Status != 'Closed')
        throw new IllegalArgumentException('At least one OrderItem is not Closed: ' + line.Id);

String repairJobName = 'repair ' + orderIdText;
List<Transaction_Log__c> recent = [
    SELECT Id, Status__c, Request_Body__c, CreatedDate
    FROM Transaction_Log__c
    WHERE Apex_Class_Name__c = 'EQXStaleAssetOrderRepair' AND Job_Name__c = :repairJobName
    ORDER BY CreatedDate DESC
    LIMIT 10
];
if (!recent.isEmpty() && recent[0].Status__c == 'Success')
    throw new IllegalArgumentException(
        'Latest repair log already says Success; investigate current state'
    );
String lastFailure = '';
if (
    !recent.isEmpty() &&
    recent[0].Status__c == 'Failed' &&
    String.isNotBlank(recent[0].Request_Body__c)
) {
    String body = recent[0].Request_Body__c;
    Integer startAt = body.indexOf('FAILED:');
    if (startAt >= 0) {
        String tail = body.substring(startAt);
        Integer endAt = tail.indexOf('\n');
        lastFailure = endAt >= 0 ? tail.substring(0, endAt) : tail;
    }
}
Integer activeJobs = [
    SELECT COUNT()
    FROM AsyncApexJob
    WHERE
        ApexClass.Name IN ('EQXStaleAssetOrderRepairBatch', 'EQXStaleAssetAssetizeQueueable')
        AND Status IN ('Holding', 'Queued', 'Preparing', 'Processing')
];
if (EQXStaleAssetOrderRepair.isWaitingToRetry(orderId, System.now()))
    throw new IllegalArgumentException('Order is still in the service retry window');

EQXStaleAssetRepairPlan plan = EQXStaleAssetOrderRepair.planFor(orderId);
if (plan == null)
    throw new IllegalArgumentException(
        'Service cannot plan this Order; inspect the actual closure error before manual repair'
    );
if (plan.orderId != orderId || plan.partial || !plan.headerNeedsClose || plan.restores.isEmpty())
    throw new IllegalArgumentException('Plan is not the all-lines-closed header repair');
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT Order=' +
        orderId +
        ' status=' +
        ord.Status +
        ' closedLines=' +
        lines.size() +
        ' sourceAssetsToRestore=' +
        plan.restores.size() +
        ' rootsToAssetize=' +
        plan.rootLinesToAssetize.size() +
        ' priorRepairLogs=' +
        recent.size() +
        ' activeJobs=' +
        activeJobs +
        ' dryRun=' +
        dryRun
);
for (String detail : plan.describe())
    System.debug(LoggingLevel.WARN, 'RECOVERY PLAN ' + detail);
if (String.isNotBlank(lastFailure))
    System.debug(LoggingLevel.WARN, 'RECOVERY PRIOR FAILURE ' + lastFailure);

if (!dryRun) {
    if (activeJobs > 0)
        throw new IllegalArgumentException('Stale-asset repair batch or assetization is active');
    if (!staleAssetFailureConfirmed || !destructiveRepairPlanReviewed)
        throw new IllegalArgumentException(
            'Confirm stale-asset validator failure and review every action, period, asset, and root in the plan'
        );
    if (String.isNotBlank(lastFailure) && !previousRepairFailureResolved)
        throw new IllegalArgumentException(
            'Resolve the prior repair failure and confirm its cause before another attempt'
        );
    EQXStaleAssetOrderRepair.Result result = EQXStaleAssetOrderRepair.run(orderId);
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY REPAIR RESULT success=' + result.success + ' report=' + result.report()
    );
    // A successful run queues root-line assetization. Verify that queueable and the final Order/Asset state.
}
