// Guide row 10. Active dmuat v5 publishes one IN_STAGING event for the exact input FOLI.
// Only ActivityType__c='Provisioning' takes the destructive Nullify_FOLI_Subflow branch.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean activeFlowVersionReviewed = false;
Boolean sourceSnapshotCaptured = false;
Boolean resetImpactApproved = false;
Boolean dso003DuplicateRiskReviewed = false;
Boolean dso056CortexOutcomeAbsentConfirmed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact 18-character FulfillmentOrderLineItem Id');
Id lineId = (Id) recordIdText;
if (lineId.getSObjectType() != FulfillmentOrderLineItem.SObjectType)
    throw new IllegalArgumentException('Id is not a FulfillmentOrderLineItem');
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
if (line.Status__c != 'Awaiting Cortex Update')
    throw new IllegalArgumentException('Selected FOLI is not Awaiting Cortex Update');
if (String.isBlank(line.Activity_Number__c) && String.isBlank(line.ActivityNumber__c))
    throw new IllegalArgumentException(
        'Both Activity Number fields are blank; inspect DSO056 lookup key'
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
Boolean willNullify = line.ActivityType__c == 'Provisioning';
if (willNullify)
    for (String fieldName : clearFields)
        if (line.get(fieldName) != null && String.isNotBlank(String.valueOf(line.get(fieldName))))
            populatedFieldsToClear.add(fieldName);
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT flow=Publish_FOLI_Event_Flow input=recordId[String] foli=' +
        line.Id +
        ' order=' +
        line.FulfillmentOrder.OrderId +
        ' ActivityNumber__c=' +
        line.ActivityNumber__c +
        ' Activity_Number__c=' +
        line.Activity_Number__c +
        ' sku=' +
        line.Product_SKU__c +
        ' status=' +
        line.Status__c +
        ' willNullify=' +
        willNullify +
        ' clearFieldList=' +
        (willNullify ? '[' + String.join(clearFields, ',') + ']' : 'none') +
        ' currentlyPopulatedToClear=[' +
        String.join(populatedFieldsToClear, ',') +
        '] flagsBefore={Activity_Creation_Completed__c:' +
        line.Activity_Creation_Completed__c +
        ',Is_Primary__c:' +
        line.Is_Primary__c +
        ',PONR_Flag__c:' +
        line.PONR_Flag__c +
        '}' +
        ' flagsAfter=' +
        (willNullify
            ? '{Activity_Creation_Completed__c:false,Is_Primary__c:true,PONR_Flag__c:false}'
            : 'unchanged') +
        ' action=one IN_STAGING event, one log, status stamp dryRun=' +
        dryRun
);
if (!dryRun) {
    if (
        !activeFlowVersionReviewed ||
        !dso003DuplicateRiskReviewed ||
        !dso056CortexOutcomeAbsentConfirmed
    )
        throw new IllegalArgumentException(
            'Review Flow version, DSO003 duplicate risk, and DSO056/Cortex outcome first'
        );
    if (willNullify && (!sourceSnapshotCaptured || !resetImpactApproved))
        throw new IllegalArgumentException(
            'Provisioning branch requires FOLI snapshot and review of all field resets'
        );
    Flow.Interview.createInterview(
            'Publish_FOLI_Event_Flow',
            new Map<String, Object>{ 'recordId' => recordIdText }
        )
        .start();
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY SUBMITTED generic IN_STAGING foli=' +
            lineId +
            '; verify FOLI branch, event, Transaction_Log__c, and Cortex acknowledgement'
    );
}
