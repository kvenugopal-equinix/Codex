// Re-publish one missing Publish_Asset__e event from a completed FulfillmentAsset.
// This follows FulfillmentAssetEventTriggerHandler; it does not update the asset record.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
String eventStatus = 'REPLACE_WITH_CREATE_OR_UPDATE';
Boolean currentValuesMatchMissingEvent = false;
Boolean externalConsumerConfirmedMissing = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply one exact 18-character FulfillmentAsset Id');
Id assetId = (Id) recordIdText;
if (assetId.getSObjectType() != FulfillmentAsset.SObjectType) throw new IllegalArgumentException('Id is not a FulfillmentAsset');
if (eventStatus != 'CREATE' && eventStatus != 'UPDATE') throw new IllegalArgumentException('Choose the exact missing event type: CREATE or UPDATE');

List<FulfillmentAsset> rows = [
    SELECT Id, Asset_Creation_Completed__c, Asset_Number__c, Commercial_Parent_Id__c,
           Fulfillment_Activity__c, Serial_Number__c, Product_SKU__c, Order_Item__c,
           Status, Order_Number__c, Order__c
    FROM FulfillmentAsset WHERE Id = :assetId LIMIT 1
];
if (rows.size() != 1 || rows[0].Asset_Creation_Completed__c != true) throw new IllegalArgumentException('FulfillmentAsset missing or creation not completed');
FulfillmentAsset asset = rows[0];
String commercialAssetNumber = null;
if (String.isNotBlank(asset.Commercial_Parent_Id__c)) {
    String rawParent = asset.Commercial_Parent_Id__c.trim();
    Id commercialParentId = null;
    try { commercialParentId = Id.valueOf(rawParent); } catch (System.StringException ignored) {}
    if (commercialParentId == null) {
        commercialAssetNumber = rawParent;
    } else {
        List<Asset> commercialParents = [SELECT Id, Asset_Number__c FROM Asset WHERE Id = :commercialParentId WITH USER_MODE LIMIT 1];
        if (!commercialParents.isEmpty()) commercialAssetNumber = commercialParents[0].Asset_Number__c;
    }
}
String changedFields = eventStatus == 'CREATE' ? '["createdDate"]' : '["updated"]';
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT fulfillmentAsset=' + asset.Id + ' assetNumber=' + asset.Asset_Number__c + ' status=' + asset.Status + ' order=' + asset.Order__c + ' orderItem=' + asset.Order_Item__c + ' commercialAssetNumber=' + commercialAssetNumber + ' eventStatus=' + eventStatus + ' changedFields=' + changedFields + ' dryRun=' + dryRun);

if (!dryRun) {
    if (!currentValuesMatchMissingEvent) throw new IllegalArgumentException('Compare the original event/source history with current FulfillmentAsset values before replay');
    if (!externalConsumerConfirmedMissing) throw new IllegalArgumentException('Confirm the external subscriber has no successful receipt for this exact asset event');
    Publish_Asset__e evt = new Publish_Asset__e(
        assetId__c = asset.Id,
        assetNumber__c = asset.Asset_Number__c,
        changedFields__c = changedFields,
        entityName__c = 'FulfillmentAsset',
        eventstatus__c = eventStatus,
        traceId__c = UUID.randomUUID().toString(),
        technicalOrderLineIntegrationId__c = asset.Fulfillment_Activity__c,
        serialNumber__c = asset.Serial_Number__c,
        productSmartSKU__c = asset.Product_SKU__c,
        orderLineIntegrationId__c = asset.Order_Item__c,
        Status__c = asset.Status,
        commercialAssetNumber__c = commercialAssetNumber,
        orderNumber__c = asset.Order_Number__c,
        orderIntegrationId__c = asset.Order__c
    );
    Database.SaveResult receipt = EventBus.publish(evt);
    if (!receipt.isSuccess()) throw new IllegalArgumentException('FulfillmentAsset event publish failed: ' + receipt.getErrors()[0].getMessage());
    System.debug(LoggingLevel.WARN, 'RECOVERY SUBMITTED Publish_Asset__e eventId=' + receipt.getId() + ' fulfillmentAsset=' + assetId + '; verify external subscriber acknowledgement');
}
