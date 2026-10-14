// SRE rows 16, 17, 21. Read-only Quote/line diagnosis; UI and external corrections are manual.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean uiAndExternalCorrectionsReviewed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact Quote Id');
Id quoteId = (Id) recordIdText;
if (quoteId.getSObjectType() != Quote.SObjectType)
    throw new IllegalArgumentException('Id is not a Quote');
List<Quote> quotes = [
    SELECT Id, Status, Quote_Type__c, ExpirationDate, Email, OpportunityId
    FROM Quote
    WHERE Id = :quoteId
    LIMIT 1
];
if (quotes.size() != 1)
    throw new IllegalArgumentException('Quote missing');
List<QuoteLineItem> lines = [
    SELECT
        Id,
        Action_Code__c,
        ConstraintEngineNodeStatus__c,
        Asset_Number__c,
        Subscription_Number__c,
        Coterminus__c,
        Product_SKU__c
    FROM QuoteLineItem
    WHERE QuoteId = :quoteId
    LIMIT 200
];
if (lines.size() == 200)
    throw new IllegalArgumentException('At least 200 Quote lines; inspect full scope');
Integer cotermMissingReference = 0;
Integer updateAction = 0;
Integer updateNonUserConstraint = 0;
for (QuoteLineItem line : lines) {
    if (
        line.Coterminus__c == true &&
        (String.isBlank(line.Asset_Number__c) || String.isBlank(line.Subscription_Number__c))
    ) {
        cotermMissingReference++;
        System.debug(
            LoggingLevel.WARN,
            'ROW16 coterm line missing asset/subscription reference=' + line.Id
        );
    }
    if (line.Action_Code__c == 'Update') {
        updateAction++;
        if (
            String.isBlank(line.ConstraintEngineNodeStatus__c) ||
            !line.ConstraintEngineNodeStatus__c.contains('User')
        ) {
            updateNonUserConstraint++;
            System.debug(
                LoggingLevel.WARN,
                'ROW17 Update line has no visible User constraint marker=' + line.Id
            );
        }
    }
}
Boolean expired = quotes[0].ExpirationDate == null || quotes[0].ExpirationDate <= Date.today();
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT rows16/17/21 quote=' +
        quoteId +
        ' status=' +
        quotes[0].Status +
        ' lines=' +
        lines.size() +
        ' cotermMissingReferences=' +
        cotermMissingReference +
        ' updateActions=' +
        updateAction +
        ' updateNoUserMarker=' +
        updateNonUserConstraint +
        ' expiration=' +
        quotes[0].ExpirationDate +
        ' expirationInvalid=' +
        expired +
        ' Quote.EmailPresent=' +
        String.isNotBlank(quotes[0].Email) +
        ' dryRun=' +
        dryRun
);
if (!dryRun) {
    if (!uiAndExternalCorrectionsReviewed)
        throw new IllegalArgumentException(
            'Review OSM coterm API, attribute values, popup To Email, CRD, and expiration logic'
        );
    throw new IllegalArgumentException(
        'No safe generic Apex replay: correct OSM/API, configurator attributes, or Send to Customer UI after review'
    );
}
