// Re-publish ONE FulfillmentOrderLineItem activity event using active Flow v30's payload.
// The downstream subscriber is external/unverified; this template does not identify it as Jarvis.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
String eventStatus = 'CREATE'; // Set explicitly to CREATE or UPDATE from the missing event.
String originalChangedFieldsJson = 'REPLACE_WITH_ORIGINAL_CHANGED_FIELDS_JSON'; // Required for UPDATE only.
Boolean externalConsumerConfirmedMissing = false;
Boolean currentValuesMatchMissingEvent = false; // Confirm original event/history matches current line values.

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact 18-character FulfillmentOrderLineItem Id');
Id lineId = (Id) recordIdText;
if (lineId.getSObjectType() != FulfillmentOrderLineItem.SObjectType)
    throw new IllegalArgumentException('Id is not a FulfillmentOrderLineItem');
if (eventStatus != 'CREATE' && eventStatus != 'UPDATE')
    throw new IllegalArgumentException('Choose exact missing event status: CREATE or UPDATE');
List<FulfillmentOrderLineItem> lines = [
    SELECT
        Id,
        Activity_Creation_Completed__c,
        ActivityNumber__c,
        ActivityType__c,
        ActivitySubType__c,
        Commit_Date_Change_Reason__c,
        Commit_Date__c,
        FulfillmentAssetId,
        Group__c,
        Revised_Commit_Date__c,
        Status__c,
        OrderItemId,
        FulfillmentOrderId,
        FulfillmentOrder.OrderId,
        FulfillmentOrder.Order.Order_Number__c
    FROM FulfillmentOrderLineItem
    WHERE Id = :lineId
    LIMIT 1
];
if (lines.size() != 1 || lines[0].Activity_Creation_Completed__c != true)
    throw new IllegalArgumentException('Fulfillment activity missing or creation incomplete');
FulfillmentOrderLineItem line = lines[0];
if (
    line.OrderItemId == null ||
    line.FulfillmentOrderId == null ||
    line.FulfillmentOrder.OrderId == null
)
    throw new IllegalArgumentException('Linked OrderItem or FulfillmentOrder/Order is missing');
if (String.isBlank(line.ActivityNumber__c))
    throw new IllegalArgumentException('ActivityNumber__c missing');
String changedFieldsJson = '["activityCreatedFlag"]';
if (eventStatus == 'UPDATE') {
    if (
        String.isBlank(originalChangedFieldsJson) ||
        originalChangedFieldsJson == 'REPLACE_WITH_ORIGINAL_CHANGED_FIELDS_JSON'
    )
        throw new IllegalArgumentException(
            'UPDATE requires the exact original changedFields__c JSON from the missing event'
        );
    List<Object> fields = (List<Object>) JSON.deserializeUntyped(originalChangedFieldsJson);
    Set<String> allowed = new Set<String>{
        'Status',
        'Group',
        'Asset',
        'Revised Commit Date',
        'Fulfilment Owner',
        'Commit Date Change Reason',
        'Resolution Code',
        'Case Action',
        'Case Team',
        'Commit Date'
    };
    if (fields.isEmpty())
        throw new IllegalArgumentException('UPDATE changedFields__c cannot be empty');
    for (Object fieldName : fields)
        if (!(fieldName instanceof String) || !allowed.contains((String) fieldName))
            throw new IllegalArgumentException(
                'UPDATE has a field name outside active Flow v30 formula'
            );
    changedFieldsJson = originalChangedFieldsJson;
}
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT fulfillmentActivity=' +
        line.Id +
        ' orderItem=' +
        line.OrderItemId +
        ' order=' +
        line.FulfillmentOrder.OrderId +
        ' eventStatus=' +
        eventStatus +
        ' changedFields=' +
        changedFieldsJson +
        ' action=one Publish_Activity__e dryRun=' +
        dryRun
);
if (!dryRun) {
    if (!externalConsumerConfirmedMissing)
        throw new IllegalArgumentException(
            'Confirm the external activity consumer has no successful receipt for this exact event before republishing'
        );
    if (!currentValuesMatchMissingEvent)
        throw new IllegalArgumentException(
            'Confirm current activity values match the missing event payload using history or the original payload'
        );
    Publish_Activity__e evt = new Publish_Activity__e();
    evt.ActivitySubType__c = line.ActivitySubType__c;
    evt.ActivityType__c = line.ActivityType__c;
    evt.Commit_Date_Change_Reason__c = line.Commit_Date_Change_Reason__c;
    evt.Commit_Date__c = line.Commit_Date__c;
    if (line.FulfillmentAssetId != null)
        evt.Fulfillment_Asset_Id__c = String.valueOf(line.FulfillmentAssetId);
    evt.Fulfillment_order_line_Id__c = String.valueOf(line.Id);
    evt.Group__c = line.Group__c;
    evt.Revised_Commit_Date__c = line.Revised_Commit_Date__c;
    evt.Status__c = line.Status__c;
    evt.activityNumber__c = line.ActivityNumber__c;
    evt.changedFields__c = changedFieldsJson;
    evt.entityName__c = 'Activity';
    evt.eventstatus__c = eventStatus;
    evt.lineIntegrationId__c = String.valueOf(line.OrderItemId);
    evt.orderIntegrationId__c = String.valueOf(line.FulfillmentOrder.OrderId);
    evt.orderNumber__c = line.FulfillmentOrder.Order.Order_Number__c;
    evt.traceId__c =
        'manual-replay-' +
        String.valueOf(line.Id) +
        '-' +
        String.valueOf(System.now().getTime());
    Database.SaveResult receipt = EventBus.publish(evt);
    if (!receipt.isSuccess())
        throw new IllegalArgumentException(
            'Activity event publish failed: ' + receipt.getErrors()[0].getMessage()
        );
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY SUBMITTED Publish_Activity__e eventId=' +
            receipt.getId() +
            ' line=' +
            line.Id +
            '; verify external consumer acknowledgement'
    );
}
