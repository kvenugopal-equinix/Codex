// One Customer Accepted Quote through the active EQXQuotetoOrderWrapperFlow.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean existingOrderConfirmedAbsent = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply one exact 18-character Quote Id');
Id quoteId = (Id) recordIdText;
if (quoteId.getSObjectType() != Quote.SObjectType) throw new IllegalArgumentException('Id is not a Quote');
List<Quote> rows = [SELECT Id, Status, OpportunityId, Opportunity.StageName, Quote_To_Order_inSync__c, Valid_Agreements__c FROM Quote WHERE Id = :quoteId LIMIT 1];
if (rows.size() != 1 || rows[0].Status != 'Customer Accepted' || rows[0].Quote_To_Order_inSync__c != false) throw new IllegalArgumentException('Quote missing or not eligible for asynchronous Quote-to-Order');
if (rows[0].OpportunityId == null || new Set<String>{'Closed Won','Closed Lost','Discovery'}.contains(rows[0].Opportunity.StageName)) throw new IllegalArgumentException('Opportunity is not eligible for Quote-to-Order');
Integer agreementCount = [SELECT COUNT() FROM Quote_agiloft_contracts__c WHERE Quote__c = :quoteId];
if (rows[0].Valid_Agreements__c != true && agreementCount > 0) throw new IllegalArgumentException('Agreements do not satisfy current batch condition');
List<Order> existingOrders = [SELECT Id, Status, CreatedDate FROM Order WHERE QuoteId = :quoteId OR Quote__c = :quoteId ORDER BY CreatedDate DESC LIMIT 10];
if (!existingOrders.isEmpty()) throw new IllegalArgumentException('Order already exists for Quote; inspect rather than create another');
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT quote=' + quoteId + ' status=' + rows[0].Status + ' opportunity=' + rows[0].OpportunityId + ' agreements=' + agreementCount + ' existingOrders=' + existingOrders.size() + ' action=EQXQuotetoOrderWrapperFlow dryRun=' + dryRun);
if (!dryRun) {
    if (!existingOrderConfirmedAbsent) throw new IllegalArgumentException('Confirm no downstream Order already exists before invoking flow');
    Flow.Interview.EQXQuotetoOrderWrapperFlow flow = new Flow.Interview.EQXQuotetoOrderWrapperFlow(new Map<String, Object>{ 'QuoteId' => String.valueOf(quoteId) });
    flow.start();
    System.debug(LoggingLevel.WARN, 'RECOVERY SUBMITTED Quote-to-Order flow for ' + quoteId + '; verify Order, OrderItems, and downstream jobs');
}
