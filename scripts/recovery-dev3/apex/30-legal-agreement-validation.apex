// SRE row 20. Active autolaunched flow input: recordId (String Quote Id).
// Flow calls EQXQuoteAgiloftAgreementValidator, which performs an external callout.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean agiloftProductOrderableConfirmed = false;
Boolean noOrderAlreadyCreatedConfirmed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact Quote Id');
Id quoteId = (Id) recordIdText;
if (quoteId.getSObjectType() != Quote.SObjectType)
    throw new IllegalArgumentException('Id is not a Quote');
List<Quote> quotes = [
    SELECT Id, Status, Valid_Agreements__c, OpportunityId, Interface_Error_Message__c
    FROM Quote
    WHERE Id = :quoteId
    LIMIT 1
];
if (
    quotes.size() != 1 ||
    quotes[0].Status != 'Customer Accepted' ||
    quotes[0].Valid_Agreements__c == true ||
    quotes[0].OpportunityId == null
)
    throw new IllegalArgumentException(
        'Quote missing or not Customer Accepted with unvalidated agreements'
    );
List<Order> orders = [
    SELECT Id, Status
    FROM Order
    WHERE QuoteId = :quoteId OR Quote__c = :quoteId
    LIMIT 10
];
if (!orders.isEmpty())
    throw new IllegalArgumentException('Order already exists for this Quote');
Integer contractCount = [SELECT COUNT() FROM Quote_agiloft_contracts__c WHERE Quote__c = :quoteId];
List<Transaction_Log__c> logs = [
    SELECT Id, Status__c, CreatedDate
    FROM Transaction_Log__c
    WHERE
        Apex_Class_Name__c = 'EQXQuoteAgiloftAgreementValidator'
        AND Primary_Key__c = :recordIdText
    ORDER BY CreatedDate DESC
    LIMIT 10
];
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT row20 quote=' +
        quoteId +
        ' contracts=' +
        contractCount +
        ' priorValidationLogs=' +
        logs +
        ' existingOrders=' +
        orders.size() +
        ' action=Agiloft legal validation flow dryRun=' +
        dryRun
);
if (!dryRun) {
    if (!agiloftProductOrderableConfirmed || !noOrderAlreadyCreatedConfirmed)
        throw new IllegalArgumentException(
            'Verify Agiloft productOrderable=true and no existing downstream Order'
        );
    Flow.Interview flow = Flow.Interview.createInterview(
        'EQX_Quote_Legal_Agreement_Validation_Flow',
        new Map<String, Object>{ 'recordId' => recordIdText }
    );
    flow.start();
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY SUBMITTED Agiloft legal validation for Quote ' +
            quoteId +
            '; verify Valid_Agreements__c and logs'
    );
}
