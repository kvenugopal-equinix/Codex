// One Quote booking calculation. A NEW queue row is inserted only when dryRun=false.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply one exact 18-character Quote Id');
Id sourceId = (Id) recordIdText;
if (sourceId.getSObjectType() != Quote.SObjectType) throw new IllegalArgumentException('Id is not a Quote');
List<Quote> rows = [SELECT Id, Status, Quote_Number__c FROM Quote WHERE Id = :sourceId LIMIT 1];
if (rows.size() != 1) throw new IllegalArgumentException('Quote missing');
List<Opportunity_Management_Settings__mdt> settings = [SELECT Quote_Booking_Trigger_Statuses__c, Skip_Quote_Booking_Process__c, Quote_Id_s_To_Skip_Booking_Process__c FROM Opportunity_Management_Settings__mdt WHERE DeveloperName = 'OpportunitySettings' LIMIT 1];
if (settings.size() != 1 || settings[0].Skip_Quote_Booking_Process__c) throw new IllegalArgumentException('Quote booking is unconfigured or paused');
Set<String> eligible = new Set<String>();
if (String.isNotBlank(settings[0].Quote_Booking_Trigger_Statuses__c)) for (String item : settings[0].Quote_Booking_Trigger_Statuses__c.split(',')) eligible.add(item.trim());
if (!eligible.contains(rows[0].Status)) throw new IllegalArgumentException('Quote status is not configured for booking');
if (String.isNotBlank(settings[0].Quote_Id_s_To_Skip_Booking_Process__c) && settings[0].Quote_Id_s_To_Skip_Booking_Process__c.contains(recordIdText)) throw new IllegalArgumentException('Quote appears in booking skip list');
List<Booking_Calculation_Queue__c> history = [SELECT Id, Status__c, Error_Message__c, CreatedDate FROM Booking_Calculation_Queue__c WHERE SourceRecordid__c = :recordIdText ORDER BY CreatedDate DESC LIMIT 10];
for (Booking_Calculation_Queue__c prior : history) if (prior.Status__c == 'NEW' || prior.Status__c == 'IN PROGRESS') throw new IllegalArgumentException('Booking is already queued or running: ' + prior.Id);
if (!history.isEmpty() && history[0].Status__c == 'COMPLETED') throw new IllegalArgumentException('Latest booking completed; inspect result before another run');
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT quote=' + sourceId + ' status=' + rows[0].Status + ' recentQueues=' + history + ' action=NEW booking queue dryRun=' + dryRun);
if (!dryRun) {
    Booking_Calculation_Queue__c row = BookingQueueUtils.markNEW(new Booking_Calculation_Queue__c(SourceRecordid__c = recordIdText));
    Map<Id, Booking_Calculation_Queue__c> saved = BookingQueueUtils.saveAll(new List<Booking_Calculation_Queue__c>{ row });
    if (!saved.containsKey(sourceId) || saved.get(sourceId).Id == null) throw new IllegalArgumentException('Booking queue insert failed');
    Id asyncId = System.enqueueJob(new BookingProcessQueueable(saved.get(sourceId).Id));
    System.debug(LoggingLevel.WARN, 'RECOVERY SUBMITTED quote booking queue=' + saved.get(sourceId).Id + ' async=' + asyncId);
}
