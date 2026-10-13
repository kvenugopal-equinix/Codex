// One Order Caplogix request. OrderCFRRequest can send one callout per required root.
Boolean dryRun = true;
String expectedOrgId = '00DWI00000DzbpZ2AR';
Boolean expectedSandbox = true;
String orderIdText = 'REPLACE_WITH_18_CHAR_ID';
String interfaceName = 'INT049_CRM_CONF_VALIDSER_CAPLX';
Boolean externalOutcomeConfirmedAbsent = false;
Boolean affectedOrderHierarchyReviewed = false;
Boolean eachCfrRootConfirmedAbsent = false; // Required for OrderCFRRequest fan-out.
Boolean fullOrderHierarchyReviewed = false; // Other interfaces send the full Order hierarchy.

if (UserInfo.getOrganizationId() != (Id) expectedOrgId) throw new IllegalArgumentException('Wrong Salesforce org');
if ([SELECT IsSandbox FROM Organization LIMIT 1].IsSandbox != expectedSandbox) throw new IllegalArgumentException('Wrong sandbox/production environment');
if (orderIdText.length() != 18 || orderIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply one exact 18-character Order Id');
Id orderId = (Id) orderIdText;
if (orderId.getSObjectType() != Order.SObjectType) throw new IllegalArgumentException('Id is not an Order');
List<Order> orders = [SELECT Id, Status, Order_Creation_Completed__c FROM Order WHERE Id = :orderId LIMIT 1];
if (orders.size() != 1 || orders[0].Order_Creation_Completed__c != true) throw new IllegalArgumentException('Order missing or creation incomplete');
Set<String> allowed = new Set<String>{ 'INT049_CRM_CONF_VALIDSER_CAPLX','OrderCFRRequest','OrderNetworkCFR','INT3239_LTC_CRM_ORDER_BOOKSER_CAPLX','INT3240_LTC_CRM_CANCELSERV_CAPLX','INT3241_LTC_CRM_ORDERCOMPSER_CAPLX' };
if (!allowed.contains(interfaceName)) throw new IllegalArgumentException('Order Caplogix interface is not in the reviewed allowlist');
List<CaplogixInterfaceDetailsLookup__mdt> configs = [SELECT NamedCredentials__c, EndPoint__c FROM CaplogixInterfaceDetailsLookup__mdt WHERE DeveloperName = :interfaceName LIMIT 1];
if (configs.size() != 1 || String.isBlank(configs[0].NamedCredentials__c) || String.isBlank(configs[0].EndPoint__c)) throw new IllegalArgumentException('Caplogix Order endpoint not configured');
List<OrderItem> roots = new List<OrderItem>();
if (interfaceName == 'OrderCFRRequest') {
    roots = [SELECT Id, Root_Line_Item_Id__c FROM OrderItem WHERE OrderId = :orderId AND Root_Line__c = true AND CFR_Status__c = 'Required'];
    if (roots.isEmpty()) throw new IllegalArgumentException('OrderCFRRequest has no Required root lines; service would do nothing');
    if (roots.size() > 100) throw new IllegalArgumentException('OrderCFRRequest has over 100 roots; exceeds single-transaction callout limit');
    for (OrderItem root : roots) if (root.Root_Line_Item_Id__c == null) throw new IllegalArgumentException('Required CFR root is missing Root_Line_Item_Id__c: ' + root.Id);
}
List<AsyncApexJob> active = [SELECT Id, Status FROM AsyncApexJob WHERE ApexClass.Name = 'CaplogixAsyncJobOrder' AND Status IN ('Holding','Queued','Preparing','Processing') LIMIT 10];
if (!active.isEmpty()) throw new IllegalArgumentException('Caplogix Order jobs are active; inspect concurrency first');
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT order=' + orderId + ' status=' + orders[0].Status + ' interface=' + interfaceName + ' CFR required roots=' + roots + ' action=Caplogix async request dryRun=' + dryRun);
if (!dryRun) {
    if (!externalOutcomeConfirmedAbsent) throw new IllegalArgumentException('Confirm this Caplogix interface has no successful external outcome for this Order before replay');
    if (!affectedOrderHierarchyReviewed) throw new IllegalArgumentException('Review all Order lines and actions affected by this interface before submitting');
    if (interfaceName == 'OrderCFRRequest' && !eachCfrRootConfirmedAbsent) throw new IllegalArgumentException('Confirm external absence for EVERY required CFR root before fan-out');
    if (interfaceName != 'OrderCFRRequest' && !fullOrderHierarchyReviewed) throw new IllegalArgumentException('Review every Order line in the generated Caplogix hierarchy and confirm the requested scope');
    String result = CaplogixIntegrationServiceOrder.sendRequest(orderId, interfaceName, true);
    System.debug(LoggingLevel.WARN, 'RECOVERY SUBMITTED Caplogix Order interface=' + interfaceName + ' order=' + orderId + ' enqueueResult=' + result + '; verify all external acknowledgements');
}
