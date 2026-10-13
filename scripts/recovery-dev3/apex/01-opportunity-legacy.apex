// One Opportunity co-existence event. Edit the 18-character Id.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean consumerConfirmedMissing = false; // Set true only after checking the legacy consumer.

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact 18-character Opportunity Id');
Id sourceId = (Id) recordIdText;
if (sourceId.getSObjectType() != Opportunity.SObjectType)
    throw new IllegalArgumentException('Id is not an Opportunity');
List<Opportunity> rows = [SELECT Id, Name, StageName FROM Opportunity WHERE Id = :sourceId LIMIT 1];
if (rows.size() != 1)
    throw new IllegalArgumentException('Opportunity missing');
List<Opportunity_Management_Settings__mdt> settings = [
    SELECT Pause_CoExistence_Platform_Event__c
    FROM Opportunity_Management_Settings__mdt
    WHERE DeveloperName = 'OpportunitySettings'
    LIMIT 1
];
if (settings.size() != 1 || settings[0].Pause_CoExistence_Platform_Event__c)
    throw new IllegalArgumentException('Co-existence publisher is unconfigured or paused');
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT opportunity=' +
        rows[0].Id +
        ' stage=' +
        rows[0].StageName +
        ' action=publish Sync_Opportunity__e dryRun=' +
        dryRun
);
if (!dryRun) {
    if (!consumerConfirmedMissing)
        throw new IllegalArgumentException(
            'Confirm the consumer has not applied this Opportunity before republishing'
        );
    OpportunitySyncInvokerController.invokeOpportunitySync(sourceId);
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY SUBMITTED legacy Opportunity event for ' +
            sourceId +
            '; verify consumer acknowledgement'
    );
}
