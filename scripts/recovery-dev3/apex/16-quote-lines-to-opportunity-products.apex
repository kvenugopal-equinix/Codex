// Reapply custom-field mappings from one synced Quote's lines to its Opportunity products.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean overwriteConfirmed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply one exact 18-character Quote Id');
Id quoteId = (Id) recordIdText;
if (quoteId.getSObjectType() != Quote.SObjectType) throw new IllegalArgumentException('Id is not a Quote');

List<Quote> quotes = [SELECT Id, Status, IsSyncing, OpportunityId, Opportunity.SyncedQuoteId FROM Quote WHERE Id = :quoteId LIMIT 1];
if (quotes.size() != 1 || quotes[0].OpportunityId == null) throw new IllegalArgumentException('Quote missing or not linked to an Opportunity');
Quote q = quotes[0];
List<Quote_Sync_Setting__mdt> settings = [SELECT DeveloperName, Quote_Line_Sync_Direction__c FROM Quote_Sync_Setting__mdt LIMIT 2];
if (settings.size() != 1) throw new IllegalArgumentException('Expected exactly one Quote sync setting; deployed utility uses an unordered LIMIT 1');
String direction = settings[0].Quote_Line_Sync_Direction__c;
if (direction != 'Quote Line to Opp Product' && direction != 'Bi-Directional') throw new IllegalArgumentException('Current metadata does not enable Quote Line to Opportunity Product sync');
Integer activeMappings = [SELECT COUNT() FROM Quote_Sync_Custom_Mapping__mdt WHERE Active__c = true AND Object_Type__c = 'LineItem'];

List<QuoteLineItem> qlis = [SELECT Id, OpportunityLineItemId FROM QuoteLineItem WHERE QuoteId = :quoteId];
if (qlis.isEmpty()) throw new IllegalArgumentException('Quote has no lines to sync');
Set<Id> oliIds = new Set<Id>();
Integer unlinked = 0;
Integer duplicateLinks = 0;
for (QuoteLineItem qli : qlis) {
    if (qli.OpportunityLineItemId == null) {
        unlinked++;
    } else if (oliIds.contains(qli.OpportunityLineItemId)) {
        duplicateLinks++;
    } else {
        oliIds.add(qli.OpportunityLineItemId);
    }
}
List<OpportunityLineItem> olis = [SELECT Id, OpportunityId FROM OpportunityLineItem WHERE Id IN :oliIds];
Integer wrongOpportunity = 0;
for (OpportunityLineItem oli : olis) if (oli.OpportunityId != q.OpportunityId) wrongOpportunity++;
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT quote=' + quoteId + ' status=' + q.Status + ' isSyncing=' + q.IsSyncing + ' opportunity=' + q.OpportunityId + ' syncedQuote=' + q.Opportunity.SyncedQuoteId + ' direction=' + direction + ' activeMappings=' + activeMappings + ' quoteLines=' + qlis.size() + ' linkedOLIs=' + olis.size() + ' unlinkedQLIs=' + unlinked + ' duplicateLinks=' + duplicateLinks + ' wrongOpportunityLinks=' + wrongOpportunity + ' dryRun=' + dryRun);
if (q.Status != 'Draft' || q.IsSyncing != true || q.Opportunity.SyncedQuoteId != quoteId) throw new IllegalArgumentException('Quote is not the current syncing Draft Quote for this Opportunity');
if (unlinked > 0 || duplicateLinks > 0 || olis.size() != oliIds.size() || wrongOpportunity > 0) throw new IllegalArgumentException('Quote and Opportunity line links are incomplete or ambiguous; repair links before field sync');

if (!dryRun) {
    if (!overwriteConfirmed) throw new IllegalArgumentException('Compare mapped custom fields on the linked Quote and Opportunity lines and confirm Quote values should overwrite Opportunity values');
    QuoteLineItemSyncAsync.syncQuoteLineItems(new Set<Id>{ quoteId });
    System.debug(LoggingLevel.WARN, 'RECOVERY COMPLETED Quote-to-Opportunity product custom-field sync for ' + quoteId + '; compare mapped OLI values after commit');
}
