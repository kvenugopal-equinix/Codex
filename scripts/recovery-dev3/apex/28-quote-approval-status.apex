// SRE row 12. Active autolaunched flow input is ObjectId (String), meaning Quote Id.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
String expectedResolvedStatus = 'REPLACE_WITH_Approved_OR_Rejected';
Integer expectedCurrentRevisionOutcomeCount = -1;
Boolean approvalResultsReviewed = false;
Boolean quoteStatusChangeReviewed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact Quote Id');
Id quoteId = (Id) recordIdText;
if (quoteId.getSObjectType() != Quote.SObjectType)
    throw new IllegalArgumentException('Id is not a Quote');
if (expectedResolvedStatus != 'Approved' && expectedResolvedStatus != 'Rejected')
    throw new IllegalArgumentException('Set expectedResolvedStatus to Approved or Rejected');
List<Quote> quotes = [
    SELECT Id, Status, Revision__c, ExpirationDate
    FROM Quote
    WHERE Id = :quoteId
    LIMIT 1
];
if (quotes.size() != 1 || quotes[0].Status != 'Pending Approval')
    throw new IllegalArgumentException('Quote missing or no longer Pending Approval');
Decimal revision = quotes[0].Revision__c;
List<ApprovalOutcome__c> outcomes = [
    SELECT Id, Status__c, Approval_Code__c, ParentRecordId__c
    FROM ApprovalOutcome__c
    WHERE Quote__c = :quoteId AND QuoteVersion__c = :revision
    LIMIT 200
];
if (outcomes.isEmpty() || outcomes.size() == 200)
    throw new IllegalArgumentException('Current-revision outcomes missing or scope too large');
for (ApprovalOutcome__c outcome : outcomes)
    if (outcome.Status__c != expectedResolvedStatus)
        throw new IllegalArgumentException(
            'Outcome ' + outcome.Id + ' is ' + outcome.Status__c + ', not ' + expectedResolvedStatus
        );
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT row12 quote=' +
        quoteId +
        ' revision=' +
        revision +
        ' currentStatus=' +
        quotes[0].Status +
        ' expectedOutcomes=' +
        expectedResolvedStatus +
        ' outcomeCount=' +
        outcomes.size() +
        ' expiration=' +
        quotes[0].ExpirationDate +
        ' dryRun=' +
        dryRun
);
if (!dryRun) {
    if (
        !approvalResultsReviewed ||
        !quoteStatusChangeReviewed ||
        expectedCurrentRevisionOutcomeCount != outcomes.size()
    )
        throw new IllegalArgumentException(
            'Confirm all approval outcomes and downstream Quote status/expiration changes'
        );
    Flow.Interview flow = Flow.Interview.createInterview(
        'EQX_Update_Quote_Status',
        new Map<String, Object>{ 'ObjectId' => recordIdText }
    );
    flow.start();
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY SUBMITTED Quote approval-status flow; requery Quote and approval outcomes'
    );
}
