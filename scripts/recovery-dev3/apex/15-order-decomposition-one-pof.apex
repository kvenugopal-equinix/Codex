// One eligible root POF on one Order through the deployed decomposition service.
Boolean dryRun = true;
String orderIdText = 'REPLACE_WITH_18_CHAR_ID';
String pofIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean partialEffectsReviewed = false;

if (orderIdText.length() != 18 || orderIdText == 'REPLACE_WITH_18_CHAR_ID' || pofIdText.length() != 18 || pofIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply exact 18-character Order and root POF Ids');
Id orderId = (Id) orderIdText;
Id pofId = (Id) pofIdText;
if (orderId.getSObjectType() != Order.SObjectType || pofId.getSObjectType() != OrderItem.SObjectType) throw new IllegalArgumentException('Wrong ID types');

List<Order> orders = [SELECT Id, Status, AccountId FROM Order WHERE Id = :orderId LIMIT 1];
if (orders.size() != 1) throw new IllegalArgumentException('Order missing');
List<OrderItem> roots = [SELECT Id, OrderId, Status, CurrentApprovalLevel__c, ParentOrderItemId, Product2.StockKeepingUnit FROM OrderItem WHERE Id = :pofId LIMIT 1];
if (roots.size() != 1 || roots[0].OrderId != orderId || roots[0].ParentOrderItemId != null) throw new IllegalArgumentException('POF missing, on a different Order, or not root');
OrderItem pof = roots[0];
if (pof.Status != EQXOrderDecompositionConstants.OI_STATUS_CONFIGURED || pof.CurrentApprovalLevel__c != EQXOrderDecompositionConstants.POF_APPROVAL_LEVEL) throw new IllegalArgumentException('POF is not eligible for decomposition');

List<OrderItem> children = [SELECT Id, Status, OrderAction.Type FROM OrderItem WHERE OrderId = :orderId AND Root_Line_Item_Id__c = :pofId AND Status = 'Configured' LIMIT 201];
if (children.isEmpty()) throw new IllegalArgumentException('No configured child OrderItems under the POF; service would skip');
if (children.size() > 200) throw new IllegalArgumentException('More than 200 configured children; inspect this POF manually before replay');
Set<Id> sourceIds = new Set<Id>{ pofId };
for (OrderItem child : children) sourceIds.add(child.Id);
List<FulfillmentPlan> plans = [SELECT Id, State, SourceIdentifier, External_Id__c FROM FulfillmentPlan WHERE SourceIdentifier = :orderIdText ORDER BY CreatedDate DESC LIMIT 10];
List<FulfillmentStepSource> pofSources = [SELECT Id, SourceLineItemId FROM FulfillmentStepSource WHERE SourceLineItemId = :pofId LIMIT 20];
List<FulfillmentOrderLineItem> existingLines = [SELECT Id, OrderItemId, FulfillmentOrderId FROM FulfillmentOrderLineItem WHERE FulfillmentOrder.OrderId = :orderId AND OrderItemId IN :sourceIds LIMIT 201];
if (existingLines.size() > 200) throw new IllegalArgumentException('More than 200 existing fulfillment lines; inspect this POF manually before replay');
List<Transaction_Log__c> recent = [SELECT Id, Status__c, Error_Message__c, CreatedDate FROM Transaction_Log__c WHERE Apex_Class_Name__c = 'EQXOrderDecompositionService' AND Primary_Key__c = :orderIdText ORDER BY CreatedDate DESC LIMIT 10];
Integer activeJobs = [SELECT COUNT() FROM AsyncApexJob WHERE ApexClass.Name = 'EQXOrderDecompositionQueueable' AND Status IN ('Holding','Queued','Preparing','Processing')];
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT order=' + orderId + ' status=' + orders[0].Status + ' rootPOF=' + pofId + ' sku=' + pof.Product2.StockKeepingUnit + ' configuredChildren=' + children.size() + ' existingPlans=' + plans.size() + ' existingPofStepSources=' + pofSources.size() + ' existingFOLIs=' + existingLines.size() + ' decompositionLogs=' + recent.size() + ' activeJobs=' + activeJobs + ' dryRun=' + dryRun);
for (FulfillmentOrderLineItem line : existingLines) System.debug(LoggingLevel.WARN, 'RECOVERY EXISTING FOLI=' + line.Id + ' sourceOrderItem=' + line.OrderItemId);
for (Transaction_Log__c logRow : recent) System.debug(LoggingLevel.WARN, 'RECOVERY DECOMPOSITION LOG=' + logRow.Id + ' status=' + logRow.Status__c + ' error=' + logRow.Error_Message__c);
if (!pofSources.isEmpty()) throw new IllegalArgumentException('POF already has fulfillment step sources; inspect existing decomposition instead of replaying');
if (activeJobs > 0) throw new IllegalArgumentException('Decomposition queueable is active; resolve concurrent work first');

if (!dryRun) {
    if (!existingLines.isEmpty() && !partialEffectsReviewed) throw new IllegalArgumentException('Review existing fulfillment lines and confirm this POF needs partial completion');
    OrderDecompositionAPI.DecompositionResult result = OrderDecompositionAPI.decomposeOrder(String.valueOf(orderId), new List<Id>{ pofId });
    Boolean pofCompleted = false;
    for (OrderDecompositionAPI.POFResult one : result.pofResults) {
        System.debug(LoggingLevel.WARN, 'RECOVERY POF RESULT pof=' + one.pofId + ' status=' + one.status + ' error=' + one.error + ' warnings=' + one.warnings);
        if (one.pofId == String.valueOf(pofId) && one.status == 'Completed') pofCompleted = true;
    }
    System.debug(LoggingLevel.WARN, 'RECOVERY DECOMPOSITION RESULT order=' + orderId + ' status=' + result.status + ' pofCompleted=' + pofCompleted + ' message=' + result.message + ' errors=' + result.errors + '; verify FulfillmentPlan, FulfillmentOrder, FOLI, FulfillmentStep, and source links after commit');
    // Do not throw after invocation: that would roll back successful decomposition and its logs.
}
