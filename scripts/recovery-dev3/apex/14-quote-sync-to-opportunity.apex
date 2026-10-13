// Sync one eligible Quote to its Opportunity without toggling Quote status.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean correctPrimaryRevisionConfirmed = false;
Boolean replaceExistingSyncedQuoteConfirmed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply one exact 18-character Quote Id');
Id quoteId = (Id) recordIdText;
if (quoteId.getSObjectType() != Quote.SObjectType) throw new IllegalArgumentException('Id is not a Quote');
List<Quote> quotes = [SELECT Id, Status, OpportunityId, Primary_Quote_Flag__c, IsSyncing, Quote_Number__c FROM Quote WHERE Id = :quoteId LIMIT 1];
if (quotes.size() != 1 || quotes[0].OpportunityId == null) throw new IllegalArgumentException('Quote missing or not related to an Opportunity');
Quote target = quotes[0];
List<Opportunity> opportunities = [SELECT Id, StageName, SyncedQuoteId FROM Opportunity WHERE Id = :target.OpportunityId LIMIT 1];
if (opportunities.size() != 1) throw new IllegalArgumentException('Opportunity missing');
Opportunity opportunity = opportunities[0];
if (opportunity.SyncedQuoteId == quoteId) throw new IllegalArgumentException('Quote is already the synced Quote');
List<Quote> siblings = [SELECT Id, Status, Primary_Quote_Flag__c FROM Quote WHERE OpportunityId = :target.OpportunityId LIMIT 200];
if (siblings.size() == 200) throw new IllegalArgumentException('At least 200 related Quotes; inspect manually before replay');
List<Opportunity_Management_Settings__mdt> settings = [SELECT Quote_Manual_Sync_Trigger_Statuses__c FROM Opportunity_Management_Settings__mdt WHERE DeveloperName = 'OpportunitySettings' LIMIT 1];
if (settings.size() != 1) throw new IllegalArgumentException('Quote sync settings missing');
Set<String> allowedStatuses = new Set<String>();
if (String.isNotBlank(settings[0].Quote_Manual_Sync_Trigger_Statuses__c)) {
    for (String statusValue : settings[0].Quote_Manual_Sync_Trigger_Statuses__c.split(',')) allowedStatuses.add(statusValue.trim());
}
if (!allowedStatuses.contains(target.Status)) throw new IllegalArgumentException('Quote status is not in the configured manual sync statuses');
Integer primaryCount = 0;
for (Quote sibling : siblings) if (sibling.Primary_Quote_Flag__c == true) primaryCount++;
if (siblings.size() > 1 && (target.Primary_Quote_Flag__c != true || primaryCount != 1)) throw new IllegalArgumentException('Multiple Quotes exist; target must be the sole primary Quote');
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT quote=' + quoteId + ' quoteStatus=' + target.Status + ' opportunity=' + opportunity.Id + ' relatedQuotes=' + siblings.size() + ' currentSyncedQuote=' + opportunity.SyncedQuoteId + ' dryRun=' + dryRun);
if (!dryRun) {
    if (siblings.size() > 1 && !correctPrimaryRevisionConfirmed) throw new IllegalArgumentException('Confirm the target is the correct primary revision');
    if (opportunity.SyncedQuoteId != null && !replaceExistingSyncedQuoteConfirmed) throw new IllegalArgumentException('Confirm replacement of the existing SyncedQuoteId');
    QuoteTriggerHelperSales.markQuotesSyncedWithOppty(new List<Id>{ quoteId });
    Opportunity afterSync = [SELECT SyncedQuoteId FROM Opportunity WHERE Id = :opportunity.Id LIMIT 1];
    if (afterSync.SyncedQuoteId != quoteId) throw new IllegalArgumentException('Quote sync did not update Opportunity; inspect validation or DML errors');
    System.debug(LoggingLevel.WARN, 'RECOVERY COMPLETED Quote→Opportunity sync quote=' + quoteId + ' opportunity=' + opportunity.Id);
}
