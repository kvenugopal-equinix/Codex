// SRE row 11. Active autolaunched flow inputs: OutcomeId (String), status (String).
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID'; // ApprovalOutcome__c Id.
String expectedQuoteIdText = 'REPLACE_WITH_18_CHAR_QUOTE_ID';
String requestedDecision = 'REPLACE_WITH_Approve_OR_Reject';
Integer expectedRelevantOutcomeCount = -1;
Boolean approvalDecisionVerified = false;
Boolean allRelevantOutcomesReviewed = false;

if (
    recordIdText.length() != 18 ||
    recordIdText == 'REPLACE_WITH_18_CHAR_ID' ||
    expectedQuoteIdText.length() != 18 ||
    expectedQuoteIdText == 'REPLACE_WITH_18_CHAR_QUOTE_ID'
)
    throw new IllegalArgumentException('Supply exact Outcome and Quote IDs');
Id outcomeId = (Id) recordIdText;
Id quoteId = (Id) expectedQuoteIdText;
if (
    outcomeId.getSObjectType() != ApprovalOutcome__c.SObjectType ||
    quoteId.getSObjectType() != Quote.SObjectType
)
    throw new IllegalArgumentException('Wrong ID types');
if (requestedDecision != 'Approve' && requestedDecision != 'Reject')
    throw new IllegalArgumentException('Set requestedDecision to Approve or Reject');
List<ApprovalOutcome__c> rows = [
    SELECT Id, Status__c, Quote__c, QuoteVersion__c, Sequence__c, ParentRecordId__c
    FROM ApprovalOutcome__c
    WHERE Id = :outcomeId
    LIMIT 1
];
if (
    rows.size() != 1 ||
    rows[0].Quote__c != quoteId ||
    rows[0].Status__c != 'Received' ||
    String.isNotBlank(rows[0].ParentRecordId__c)
)
    throw new IllegalArgumentException('Outcome missing, not root, or no longer Received');
List<Quote> quotes = [SELECT Id, Status, Revision__c FROM Quote WHERE Id = :quoteId LIMIT 1];
if (
    quotes.size() != 1 ||
    quotes[0].Status != 'Pending Approval' ||
    rows[0].QuoteVersion__c != quotes[0].Revision__c
)
    throw new IllegalArgumentException('Quote/revision is not pending approval for this Outcome');
Decimal revision = quotes[0].Revision__c;
List<ApprovalOutcome__c> children = [
    SELECT Id, Status__c, Quote__c, QuoteVersion__c, Sequence__c
    FROM ApprovalOutcome__c
    WHERE ParentRecordId__c = :recordIdText
    LIMIT 200
];
if (children.size() == 200)
    throw new IllegalArgumentException('At least 200 child outcomes; inspect full scope');
for (ApprovalOutcome__c child : children)
    if (child.Quote__c != quoteId || child.QuoteVersion__c != revision)
        throw new IllegalArgumentException(
            'Selected outcome has a child outside the current Quote revision; inspect flow impact'
        );
// The active flow also queries same-sequence Received roots, then may mark next-sequence
// or level-3 Pending Submission roots Received. Preview the whole current revision.
List<ApprovalOutcome__c> relevantOutcomes = [
    SELECT Id, Status__c, Sequence__c, Approval_Code__c, FastTrackFlag__c, ParentRecordId__c
    FROM ApprovalOutcome__c
    WHERE Quote__c = :quoteId AND QuoteVersion__c = :revision
    LIMIT 200
];
if (relevantOutcomes.size() == 200)
    throw new IllegalArgumentException(
        'At least 200 current-revision outcomes; inspect full scope'
    );
List<ApprovalOutcome__c> sameSequenceReceivedRoots = new List<ApprovalOutcome__c>();
List<ApprovalOutcome__c> nextSequencePendingRoots = new List<ApprovalOutcome__c>();
List<ApprovalOutcome__c> level3PendingRoots = new List<ApprovalOutcome__c>();
for (ApprovalOutcome__c related : relevantOutcomes) {
    if (String.isNotBlank(related.ParentRecordId__c))
        continue;
    if (
        related.Id != outcomeId &&
        related.Status__c == 'Received' &&
        related.Sequence__c == rows[0].Sequence__c
    )
        sameSequenceReceivedRoots.add(related);
    if (related.Status__c == 'Pending Submission' && related.Sequence__c == rows[0].Sequence__c + 1)
        nextSequencePendingRoots.add(related);
    if (related.Status__c == 'Pending Submission' && related.Sequence__c == 3)
        level3PendingRoots.add(related);
}
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT row11 outcome=' +
        outcomeId +
        ' quote=' +
        quoteId +
        ' revision=' +
        revision +
        ' sequence=' +
        rows[0].Sequence__c +
        ' decision=' +
        requestedDecision +
        ' directChildren=' +
        children +
        ' currentRevisionOutcomeCount=' +
        relevantOutcomes.size() +
        ' sameSequenceReceivedRoots=' +
        sameSequenceReceivedRoots +
        ' nextSequencePendingRoots=' +
        nextSequencePendingRoots +
        ' level3PendingRoots=' +
        level3PendingRoots +
        ' dryRun=' +
        dryRun
);
if (!dryRun) {
    if (
        !approvalDecisionVerified ||
        !allRelevantOutcomesReviewed ||
        expectedRelevantOutcomeCount != relevantOutcomes.size()
    )
        throw new IllegalArgumentException(
            'Verify the approval decision and all current-revision outcomes, including peer and future sequences'
        );
    Flow.Interview flow = Flow.Interview.createInterview(
        'EQX_Update_Outcome_Status',
        new Map<String, Object>{ 'OutcomeId' => recordIdText, 'status' => requestedDecision }
    );
    flow.start();
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY SUBMITTED outcome flow; verify root/child statuses and Quote before row12'
    );
}
