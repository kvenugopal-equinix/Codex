// One commercial Asset outbound Integration Procedure call.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean destinationConfirmedMissing = false;
Boolean responseInspectedAndFailed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply one exact 18-character Asset Id');
Id assetId = (Id) recordIdText;
if (assetId.getSObjectType() != Asset.SObjectType) throw new IllegalArgumentException('Id is not an Asset');
List<Asset> rows = [SELECT Id, Name, Send_To_External__c, Skip_Outbound_Sync__c, API_Response__c FROM Asset WHERE Id = :assetId LIMIT 1];
if (rows.size() != 1) throw new IllegalArgumentException('Asset missing');
if (rows[0].Skip_Outbound_Sync__c == true) throw new IllegalArgumentException('Asset outbound is explicitly skipped');
List<Integration_Log__c> recent = [SELECT Id, Transaction_Status__c, Request_Payload__c, CreatedDate FROM Integration_Log__c WHERE Integration_Config_Name__c = 'Asset Sync' ORDER BY CreatedDate DESC LIMIT 100];
for (Integration_Log__c logRow : recent) if (logRow.Request_Payload__c != null && logRow.Request_Payload__c.contains(recordIdText)) System.debug(LoggingLevel.WARN, 'RECOVERY MATCHED Asset integration log=' + logRow.Id + ' status=' + logRow.Transaction_Status__c);
if ([SELECT COUNT() FROM AsyncApexJob WHERE ApexClass.Name = 'AssetIntegrationQueueable' AND Status IN ('Holding','Queued','Preparing','Processing')] > 0) throw new IllegalArgumentException('Asset integration queueables are active; inspect concurrency first');
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT Asset=' + assetId + ' sendFlag=' + rows[0].Send_To_External__c + ' action=SyncAsset_Commercial dryRun=' + dryRun);
if (!dryRun) {
    if (!destinationConfirmedMissing) throw new IllegalArgumentException('Confirm commercial Asset is absent downstream before replay');
    if (String.isNotBlank(rows[0].API_Response__c) && !responseInspectedAndFailed) throw new IllegalArgumentException('Inspect existing API response and confirm failure before replay');
    Integer jobsBefore = Limits.getQueueableJobs();
    AssetTriggerHandler.enqueueIntegrationProcedure(new Set<Id>{ assetId }, 'Asset');
    if (Limits.getQueueableJobs() <= jobsBefore) throw new IllegalArgumentException('Asset queueable was not submitted');
    System.debug(LoggingLevel.WARN, 'RECOVERY SUBMITTED Asset outbound for ' + assetId + '; verify Integration_Log__c and destination');
}
