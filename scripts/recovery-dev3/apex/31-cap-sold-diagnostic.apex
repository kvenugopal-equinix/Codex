// SRE row 19. EQXCapStatusChangeService is an inbound REST endpoint for VDC.
// Diagnostic only: VDC must resend its original SOLD event with authoritative CAP/Design IDs.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean vdcResendCoordinated = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact Quote Id');
Id quoteId = (Id) recordIdText;
if (quoteId.getSObjectType() != Quote.SObjectType)
    throw new IllegalArgumentException('Id is not a Quote');
List<Quote> quotes = [
    SELECT Id, Status, Interface_Error_Message__c, Valid_Agreements__c, VDC_Design_Status__c
    FROM Quote
    WHERE Id = :quoteId
    LIMIT 1
];
if (quotes.size() != 1)
    throw new IllegalArgumentException('Quote missing');
List<QuoteLineItem> lines = [
    SELECT Id, Capacity_Id__c, Capacity_Status__c, Design_Id__c, Design_Status__c
    FROM QuoteLineItem
    WHERE QuoteId = :quoteId
    LIMIT 100
];
if (lines.size() == 100)
    throw new IllegalArgumentException('At least 100 Quote lines; inspect full scope');
Integer soldCapacity = 0;
Integer soldDesign = 0;
for (QuoteLineItem line : lines) {
    if (line.Capacity_Status__c == 'SOLD')
        soldCapacity++;
    if (line.Design_Status__c == 'SOLD')
        soldDesign++;
}
// The deployed REST service creates Transaction_Log__c with blank primary keys, so these
// recent class logs cannot be attributed to this Quote without inspecting the request body.
List<Transaction_Log__c> recentUnattributedLogs = [
    SELECT Id, Status__c, CreatedDate
    FROM Transaction_Log__c
    WHERE Apex_Class_Name__c = 'EQXCapStatusChangeService'
    ORDER BY CreatedDate DESC
    LIMIT 10
];
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT row19 quote=' +
        quoteId +
        ' status=' +
        quotes[0].Status +
        ' error=' +
        quotes[0].Interface_Error_Message__c +
        ' quoteLines=' +
        lines.size() +
        ' capacitySold=' +
        soldCapacity +
        ' designSold=' +
        soldDesign +
        ' recentUnattributedRestLogs=' +
        recentUnattributedLogs +
        ' dryRun=' +
        dryRun
);
if (!dryRun) {
    if (!vdcResendCoordinated)
        throw new IllegalArgumentException('Coordinate authoritative SOLD resend with VDC');
    throw new IllegalArgumentException(
        'No safe Salesforce-only replay: VDC must resend the original /capStatusChange event'
    );
}
