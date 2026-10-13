// One Quote Caplogix request. Choose the exact interface from the incident.
Boolean dryRun = true;
String expectedOrgId = '00DWI00000DzbpZ2AR';
Boolean expectedSandbox = true;
String quoteIdText = 'REPLACE_WITH_18_CHAR_ID';
String interfaceName = 'CheckCapacity';
String rootLineIdText = ''; // Required only for CFRRequest; exact QuoteLineItem Id.
Boolean externalOutcomeConfirmedAbsent = false;
Boolean affectedQuoteHierarchyReviewed = false;
Boolean fullQuoteHierarchyReviewed = false; // Most interfaces send the whole Quote hierarchy, not one QLI.

if (UserInfo.getOrganizationId() != (Id) expectedOrgId) throw new IllegalArgumentException('Wrong Salesforce org');
if ([SELECT IsSandbox FROM Organization LIMIT 1].IsSandbox != expectedSandbox) throw new IllegalArgumentException('Wrong sandbox/production environment');
if (quoteIdText.length() != 18 || quoteIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply one exact 18-character Quote Id');
Id quoteId = (Id) quoteIdText;
if (quoteId.getSObjectType() != Quote.SObjectType) throw new IllegalArgumentException('Id is not a Quote');
List<Quote> quotes = [SELECT Id, Status FROM Quote WHERE Id = :quoteId LIMIT 1];
if (quotes.size() != 1) throw new IllegalArgumentException('Quote missing');
Set<String> allowed = new Set<String>{ 'CheckCapacity','MACDCheckCapacity','ReserveCapacity','ReleaseCapacity','CFRRequest','CLXQuoteStatusUpdate' };
if (!allowed.contains(interfaceName)) throw new IllegalArgumentException('Quote Caplogix interface is not in the reviewed allowlist');
Id rootLineId = null;
if (interfaceName == 'CFRRequest') {
    if (rootLineIdText.length() != 18) throw new IllegalArgumentException('CFRRequest requires one exact 18-character root QuoteLineItem Id');
    rootLineId = (Id) rootLineIdText;
    if (rootLineId.getSObjectType() != QuoteLineItem.SObjectType) throw new IllegalArgumentException('CFR root ID is not a QuoteLineItem');
    List<QuoteLineItem> roots = [SELECT Id, QuoteId FROM QuoteLineItem WHERE Id = :rootLineId LIMIT 1];
    if (roots.size() != 1 || roots[0].QuoteId != quoteId) throw new IllegalArgumentException('CFR root line missing or belongs to another Quote');
} else if (String.isNotBlank(rootLineIdText)) {
    throw new IllegalArgumentException('rootLineIdText is only valid for CFRRequest');
}
List<CaplogixInterfaceDetailsLookup__mdt> configs = [SELECT NamedCredentials__c, EndPoint__c FROM CaplogixInterfaceDetailsLookup__mdt WHERE DeveloperName = :interfaceName LIMIT 1];
if (configs.size() != 1 || String.isBlank(configs[0].NamedCredentials__c) || String.isBlank(configs[0].EndPoint__c)) throw new IllegalArgumentException('Caplogix Quote endpoint not configured');
List<AsyncApexJob> active = [SELECT Id, Status FROM AsyncApexJob WHERE ApexClass.Name = 'CaplogixAsyncJob' AND Status IN ('Holding','Queued','Preparing','Processing') LIMIT 10];
if (!active.isEmpty()) throw new IllegalArgumentException('Caplogix Quote jobs are active; inspect concurrency first');
String tracePattern = '%' + quoteIdText;
List<Transaction_Log__c> logs = [SELECT Id, Status__c, Trace_ID__c, CreatedDate FROM Transaction_Log__c WHERE Trace_ID__c LIKE :tracePattern ORDER BY CreatedDate DESC LIMIT 10];
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT quote=' + quoteId + ' status=' + quotes[0].Status + ' interface=' + interfaceName + ' root=' + rootLineId + ' matchingLogs=' + logs + ' action=Caplogix async request dryRun=' + dryRun);
if (!dryRun) {
    if (!externalOutcomeConfirmedAbsent) throw new IllegalArgumentException('Confirm this Caplogix interface has no successful external outcome for this Quote/root before replay');
    if (!affectedQuoteHierarchyReviewed) throw new IllegalArgumentException('Review every Quote line affected by this interface before submitting');
    if (!fullQuoteHierarchyReviewed) throw new IllegalArgumentException('Review every Quote line in the generated Caplogix hierarchy and confirm the requested scope');
    String result = CaplogixIntegrationService.sendRequest(quoteId, interfaceName, true, rootLineId);
    System.debug(LoggingLevel.WARN, 'RECOVERY SUBMITTED Caplogix Quote interface=' + interfaceName + ' quote=' + quoteId + ' enqueueResult=' + result + '; verify external acknowledgement and line fields');
}
