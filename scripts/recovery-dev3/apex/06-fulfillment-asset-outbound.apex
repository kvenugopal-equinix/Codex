// One technical FulfillmentAsset outbound Integration Procedure call.
Boolean dryRun = true;
String expectedOrgId = '00DWI00000DzbpZ2AR';
Boolean expectedSandbox = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean destinationConfirmedMissing = false;

if (UserInfo.getOrganizationId() != (Id) expectedOrgId) throw new IllegalArgumentException('Wrong Salesforce org');
if ([SELECT IsSandbox FROM Organization LIMIT 1].IsSandbox != expectedSandbox) throw new IllegalArgumentException('Wrong sandbox/production environment');
if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply one exact 18-character FulfillmentAsset Id');
Id assetId = (Id) recordIdText;
if (assetId.getSObjectType() != FulfillmentAsset.SObjectType) throw new IllegalArgumentException('Id is not a FulfillmentAsset');
List<FulfillmentAsset> rows = [SELECT Id, Name FROM FulfillmentAsset WHERE Id = :assetId LIMIT 1];
if (rows.size() != 1) throw new IllegalArgumentException('FulfillmentAsset missing');
List<Integration_Log__c> recent = [SELECT Id, Transaction_Status__c, Request_Payload__c, CreatedDate FROM Integration_Log__c WHERE Integration_Config_Name__c = 'FulfillmentAsset Sync' ORDER BY CreatedDate DESC LIMIT 100];
for (Integration_Log__c logRow : recent) if (logRow.Request_Payload__c != null && logRow.Request_Payload__c.contains(recordIdText)) System.debug(LoggingLevel.WARN, 'RECOVERY MATCHED FulfillmentAsset integration log=' + logRow.Id + ' status=' + logRow.Transaction_Status__c);
if ([SELECT COUNT() FROM AsyncApexJob WHERE ApexClass.Name = 'AssetIntegrationQueueable' AND Status IN ('Holding','Queued','Preparing','Processing')] > 0) throw new IllegalArgumentException('Asset integration queueables are active; inspect concurrency first');
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT FulfillmentAsset=' + assetId + ' action=SyncFulfillAsset_Technical dryRun=' + dryRun);
if (!dryRun) {
    if (!destinationConfirmedMissing) throw new IllegalArgumentException('Confirm technical FulfillmentAsset is absent downstream before replay');
    Integer jobsBefore = Limits.getQueueableJobs();
    AssetTriggerHandler.enqueueIntegrationProcedure(new Set<Id>{ assetId }, 'FulfillmentAsset');
    if (Limits.getQueueableJobs() <= jobsBefore) throw new IllegalArgumentException('FulfillmentAsset queueable was not submitted');
    System.debug(LoggingLevel.WARN, 'RECOVERY SUBMITTED FulfillmentAsset outbound for ' + assetId + '; verify Integration_Log__c and destination');
}
