// Guide row 6. One NCC FOLI only, although the active Flow accepts a String collection.
// Active dmuat v3 publishes IN_STAGING, creates a Transaction_Log__c, and stamps status.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean activeFlowVersionReviewed = false;
Boolean dso003DuplicateRiskReviewed = false;
Boolean dso056CortexOutcomeAbsentConfirmed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact 18-character FulfillmentOrderLineItem Id');
Id lineId = (Id) recordIdText;
if (lineId.getSObjectType() != FulfillmentOrderLineItem.SObjectType)
    throw new IllegalArgumentException('Id is not a FulfillmentOrderLineItem');
List<FulfillmentOrderLineItem> lines = [
    SELECT
        Id,
        FulfillmentOrderId,
        FulfillmentOrder.OrderId,
        OrderItemId,
        Product_SKU__c,
        Status__c,
        Activity_Number__c,
        ActivityNumber__c,
        Order_Id__c,
        Customer_Order_Number__c
    FROM FulfillmentOrderLineItem
    WHERE Id = :lineId
    LIMIT 1
];
if (lines.size() != 1)
    throw new IllegalArgumentException('FOLI missing');
FulfillmentOrderLineItem line = lines[0];
if (line.Product_SKU__c != 'NCC.TSPEC' || line.Status__c != 'Awaiting Cortex Update')
    throw new IllegalArgumentException('Selected FOLI is not an awaiting NCC line');
if (
    line.FulfillmentOrderId == null ||
    line.FulfillmentOrder.OrderId == null ||
    line.OrderItemId == null
)
    throw new IllegalArgumentException('FOLI is missing its FulfillmentOrder, Order, or OrderItem');
if (String.isBlank(line.Activity_Number__c) && String.isBlank(line.ActivityNumber__c))
    throw new IllegalArgumentException(
        'Both Activity Number fields are blank; inspect DSO056 lookup key'
    );
if (
    line.Order_Id__c != String.valueOf(line.FulfillmentOrder.OrderId) ||
    String.isBlank(line.Customer_Order_Number__c)
)
    throw new IllegalArgumentException(
        'NCC Flow event Order_Id__c or Customer_Order_Number__c is missing or inconsistent'
    );
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT flow=Publish_NCC_In_Staging_Flow input=recordIds[String collection of one] foli=' +
        line.Id +
        ' order=' +
        line.FulfillmentOrder.OrderId +
        ' ActivityNumber__c=' +
        line.ActivityNumber__c +
        ' Activity_Number__c=' +
        line.Activity_Number__c +
        ' status=' +
        line.Status__c +
        ' action=one IN_STAGING event, one log, status stamp dryRun=' +
        dryRun
);
if (!dryRun) {
    if (
        !activeFlowVersionReviewed ||
        !dso003DuplicateRiskReviewed ||
        !dso056CortexOutcomeAbsentConfirmed
    )
        throw new IllegalArgumentException(
            'Review active Flow, DSO003 outgoing duplicate risk, and DSO056/Cortex outcome first'
        );
    Flow.Interview.createInterview(
            'Publish_NCC_In_Staging_Flow',
            new Map<String, Object>{ 'recordIds' => new List<String>{ recordIdText } }
        )
        .start();
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY SUBMITTED NCC IN_STAGING foli=' +
            lineId +
            '; verify DSO003, Transaction_Log__c, and DSO056/Cortex acknowledgement'
    );
}
