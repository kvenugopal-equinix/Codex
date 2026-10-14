// Guide row 7. Active dmuat v3 resets the exact input FOLI before publishing IN_PROVISIONING.
// Its event identifies this FOLI and has subtype BMMR; the Flow does not find a sibling.
// To follow guide row 7's NCC routing, supply the NCC FOLI and review its BMMR sibling.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
String expectedStatusText = 'REPLACE_WITH_CURRENT_STATUS';
Boolean activeFlowVersionReviewed = false;
Boolean sourceSnapshotCaptured = false;
Boolean resetImpactApproved = false;
Boolean selectedNccAndBmmrSiblingReviewed = false;
Boolean dso003DuplicateRiskReviewed = false;
Boolean dso056CortexOutcomeAbsentConfirmed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact 18-character FulfillmentOrderLineItem Id');
Id lineId = (Id) recordIdText;
if (lineId.getSObjectType() != FulfillmentOrderLineItem.SObjectType)
    throw new IllegalArgumentException('Id is not a FulfillmentOrderLineItem');
if (String.isBlank(expectedStatusText) || expectedStatusText == 'REPLACE_WITH_CURRENT_STATUS')
    throw new IllegalArgumentException('Supply the exact current FOLI status');
List<FulfillmentOrderLineItem> lines = [
    SELECT
        Id,
        FulfillmentOrderId,
        FulfillmentOrder.OrderId,
        OrderItemId,
        Product_SKU__c,
        Status__c,
        Activity_Number__c,
        ActivityNumber__c,
        ActivityType__c,
        ActivitySubType__c,
        Group__c,
        Fulfilment_Owner__c,
        Commit_Date__c,
        Revised_Commit_Date__c,
        Unique_Space_Id__c,
        Cabinet_Number__c,
        Cabinet_Unique_Space_Id__c,
        SystemName__c,
        Dispatch_Date__c,
        Schedule_Start_Date__c,
        Schedule_End_Date__c,
        Serial_Number__c,
        Activity_Creation_Completed__c,
        Is_Primary__c,
        PONR_Flag__c
    FROM FulfillmentOrderLineItem
    WHERE Id = :lineId
    LIMIT 1
];
if (lines.size() != 1)
    throw new IllegalArgumentException('FOLI missing');
FulfillmentOrderLineItem line = lines[0];
if (
    line.FulfillmentOrderId == null ||
    line.FulfillmentOrder.OrderId == null ||
    line.OrderItemId == null
)
    throw new IllegalArgumentException('FOLI is missing its FulfillmentOrder, Order, or OrderItem');
if (line.Product_SKU__c != 'NCC.TSPEC')
    throw new IllegalArgumentException(
        'Guide row 7 requires the exact NCC FOLI, not the BMMR FOLI'
    );
if (
    line.Status__c != expectedStatusText ||
    line.Status__c == 'Closed' ||
    line.Status__c == 'Resolved'
)
    throw new IllegalArgumentException('FOLI status changed or is terminal; inspect before replay');
if (String.isBlank(line.Activity_Number__c) && String.isBlank(line.ActivityNumber__c))
    throw new IllegalArgumentException(
        'Both Activity Number fields are blank; inspect DSO056 lookup key'
    );
Id parentOrderId = line.FulfillmentOrder.OrderId;
Id parentOrderItemId = line.OrderItemId;
List<FulfillmentOrderLineItem> siblings = [
    SELECT Id, Status__c, Activity_Number__c
    FROM FulfillmentOrderLineItem
    WHERE
        OrderItemId = :parentOrderItemId
        AND FulfillmentOrder.OrderId = :parentOrderId
        AND Product_SKU__c = 'BMMR.TSPEC'
    LIMIT 2
];
if (siblings.size() != 1)
    throw new IllegalArgumentException(
        'Cannot identify exactly one BMMR sibling on the same OrderItem and Order'
    );
List<String> clearFields = new List<String>{
    'ActivityNumber__c',
    'ActivityType__c',
    'ActivitySubType__c',
    'Status__c',
    'Group__c',
    'Fulfilment_Owner__c',
    'Commit_Date__c',
    'Revised_Commit_Date__c',
    'Unique_Space_Id__c',
    'Cabinet_Number__c',
    'Cabinet_Unique_Space_Id__c',
    'SystemName__c',
    'Dispatch_Date__c',
    'Schedule_Start_Date__c',
    'Schedule_End_Date__c',
    'Serial_Number__c'
};
List<String> populatedFieldsToClear = new List<String>();
for (String fieldName : clearFields)
    if (line.get(fieldName) != null && String.isNotBlank(String.valueOf(line.get(fieldName))))
        populatedFieldsToClear.add(fieldName);
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT flow=Publish_BMMR_Provisioning_Flow input=recordId[String] foli=' +
        line.Id +
        ' order=' +
        line.FulfillmentOrder.OrderId +
        ' ActivityNumber__c=' +
        line.ActivityNumber__c +
        ' Activity_Number__c=' +
        line.Activity_Number__c +
        ' status=' +
        line.Status__c +
        ' bmmrSibling=' +
        siblings[0].Id +
        ' siblingStatus=' +
        siblings[0].Status__c +
        ' clearFieldList=[' +
        String.join(clearFields, ',') +
        '] currentlyPopulatedToClear=[' +
        String.join(populatedFieldsToClear, ',') +
        '] flagsBefore={Activity_Creation_Completed__c:' +
        line.Activity_Creation_Completed__c +
        ',Is_Primary__c:' +
        line.Is_Primary__c +
        ',PONR_Flag__c:' +
        line.PONR_Flag__c +
        '}' +
        ' flagsAfter={Activity_Creation_Completed__c:false,Is_Primary__c:true,PONR_Flag__c:false}' +
        ' action=reset input FOLI, one IN_PROVISIONING event, one log, status stamp dryRun=' +
        dryRun
);
if (!dryRun) {
    if (
        !activeFlowVersionReviewed ||
        !sourceSnapshotCaptured ||
        !resetImpactApproved ||
        !selectedNccAndBmmrSiblingReviewed ||
        !dso003DuplicateRiskReviewed ||
        !dso056CortexOutcomeAbsentConfirmed
    )
        throw new IllegalArgumentException(
            'Review Flow version, FOLI snapshot and reset impact, DSO003 duplicate risk, and DSO056/Cortex outcome first'
        );
    Flow.Interview.createInterview(
            'Publish_BMMR_Provisioning_Flow',
            new Map<String, Object>{ 'recordId' => recordIdText }
        )
        .start();
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY SUBMITTED BMMR IN_PROVISIONING foli=' +
            lineId +
            '; verify FOLI reset, event, Transaction_Log__c, and Cortex acknowledgement'
    );
}
