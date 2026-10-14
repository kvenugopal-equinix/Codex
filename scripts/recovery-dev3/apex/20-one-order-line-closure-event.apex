// One OrderItemUpdateEvent__e LineClosure replay. Request_ID__c is the last CLOSED
// FulfillmentOrderLineItem Id, not the OrderItem or Order Id.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean closureImpactReviewed = false;
Boolean missingClosureOutcomeConfirmed = false;
Boolean lastClosedActivityVerified = false; // Required when multiple FOLIs exist; LastModifiedDate is only a proxy.

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact 18-character FulfillmentOrderLineItem Id');
Id activityId = (Id) recordIdText;
if (activityId.getSObjectType() != FulfillmentOrderLineItem.SObjectType)
    throw new IllegalArgumentException('Id is not a FulfillmentOrderLineItem');
List<FulfillmentOrderLineItem> selected = [
    SELECT
        Id,
        Status__c,
        OrderItemId,
        OrderItemId__c,
        ActivityNumber__c,
        FulfillmentOrder.OrderId,
        LastModifiedDate
    FROM FulfillmentOrderLineItem
    WHERE Id = :activityId
    LIMIT 1
];
if (selected.size() != 1 || selected[0].Status__c != 'Closed')
    throw new IllegalArgumentException('Fulfillment activity is missing or not Closed');
FulfillmentOrderLineItem activity = selected[0];
String orderItemIdText = activity.OrderItemId == null
    ? activity.OrderItemId__c
    : String.valueOf(activity.OrderItemId);
if (String.isBlank(orderItemIdText))
    throw new IllegalArgumentException('Activity has no linked OrderItem');
Id orderItemId = (Id) orderItemIdText;
if (orderItemId.getSObjectType() != OrderItem.SObjectType)
    throw new IllegalArgumentException('Activity link is not an OrderItem');
List<OrderItem> items = [
    SELECT Id, OrderId, Status, Offering_Closed__c, Product_SKU__c, Asset__c, OrderAction.Type
    FROM OrderItem
    WHERE Id = :orderItemId
    LIMIT 1
];
if (items.size() != 1 || items[0].OrderId != activity.FulfillmentOrder.OrderId)
    throw new IllegalArgumentException('Activity and OrderItem do not belong to the same Order');
if (items[0].Status != 'In Fulfillment')
    throw new IllegalArgumentException('OrderItem is not an open In Fulfillment line');
if (activity.LastModifiedDate > System.now().addMinutes(-10))
    throw new IllegalArgumentException('Activity closed too recently; wait for normal processing');

List<FulfillmentOrderLineItem> siblings = [
    SELECT Id, Status__c, LastModifiedDate
    FROM FulfillmentOrderLineItem
    WHERE OrderItemId = :orderItemId OR OrderItemId__c = :orderItemIdText
    ORDER BY LastModifiedDate DESC, Id DESC
    LIMIT 101
];
if (siblings.isEmpty() || siblings.size() > 100)
    throw new IllegalArgumentException('Inspect all linked activities manually');
for (FulfillmentOrderLineItem sibling : siblings)
    if (sibling.Status__c != 'Closed')
        throw new IllegalArgumentException('Another linked activity is not Closed: ' + sibling.Id);
if (siblings[0].Id != activityId)
    throw new IllegalArgumentException('Select the last closed activity for this OrderItem');
List<OrderItem> openChildren = [
    SELECT Id, Status, Asset__c
    FROM OrderItem
    WHERE OrderId = :items[0].OrderId AND ParentOrderItemId = :orderItemId AND Status != 'Closed'
    LIMIT 101
];
if (openChildren.size() > 100)
    throw new IllegalArgumentException('More than 100 open child OrderItems; inspect manually');
for (OrderItem child : openChildren)
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY OPEN CHILD orderItem=' +
            child.Id +
            ' status=' +
            child.Status +
            ' asset=' +
            child.Asset__c
    );

List<Transaction_Log__c> recent = [
    SELECT Id, Status__c, Error_Message__c, CreatedDate
    FROM Transaction_Log__c
    WHERE Job_Name__c = 'Order Product Line Closure' AND Primary_Key__c = :recordIdText
    ORDER BY CreatedDate DESC
    LIMIT 10
];
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT lastClosedFOLI=' +
        activityId +
        ' activityNumber=' +
        activity.ActivityNumber__c +
        ' orderItem=' +
        orderItemId +
        ' order=' +
        items[0].OrderId +
        ' linkedClosedActivities=' +
        siblings.size() +
        ' sourceAsset=' +
        items[0].Asset__c +
        ' orderAction=' +
        items[0].OrderAction.Type +
        ' openChildOrderItems=' +
        openChildren.size() +
        ' priorFailureLogs=' +
        recent.size() +
        ' requestType=LineClosure dryRun=' +
        dryRun
);
for (Transaction_Log__c logRow : recent)
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY LINE CLOSURE LOG=' + logRow.Id + ' status=' + logRow.Status__c
    );

if (!dryRun) {
    if (!closureImpactReviewed || !missingClosureOutcomeConfirmed)
        throw new IllegalArgumentException(
            'Review the OrderItem and child line effects, and confirm line closure did not complete'
        );
    if (siblings.size() > 1 && !lastClosedActivityVerified)
        throw new IllegalArgumentException(
            'Verify actual closure order from activity history before choosing the last FOLI'
        );
    Database.SaveResult receipt = EventBus.publish(
        new OrderItemUpdateEvent__e(Request_ID__c = recordIdText, Request_Type__c = 'LineClosure')
    );
    if (!receipt.isSuccess())
        throw new IllegalArgumentException(
            'LineClosure event rejected: ' + receipt.getErrors()[0].getMessage()
        );
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY SUBMITTED LineClosure event=' +
            receipt.getId() +
            ' FOLI=' +
            activityId +
            '; verify OrderItem status and downstream logs'
    );
}
