// Requeue one known Dead Letter row, preserving its original payload.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
String expectedHandler = 'REPLACE_WITH_HANDLER_CLASS';
String expectedAction = 'REPLACE_WITH_ACTION';
String expectedRelatedId = ''; // Optional exact parent Id, if the job has one.
Boolean rootCauseFixed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply one exact 18-character Job_Queue__c Id');
if (expectedHandler.startsWith('REPLACE_') || expectedAction.startsWith('REPLACE_')) throw new IllegalArgumentException('Supply the exact expected handler and action');
Id jobId = (Id) recordIdText;
if (jobId.getSObjectType() != Job_Queue__c.SObjectType) throw new IllegalArgumentException('Id is not a Job_Queue__c row');
List<Job_Queue__c> rows = [SELECT Id, Status__c, Handler_Class__c, Action__c, Related_Record_Id__c, Attempt_Count__c, Max_Attempts__c, Scheduled_At__c, Payload__c FROM Job_Queue__c WHERE Id = :jobId LIMIT 1];
if (rows.size() != 1 || rows[0].Status__c != 'Dead Letter') throw new IllegalArgumentException('Job missing or no longer Dead Letter');
if (rows[0].Handler_Class__c != expectedHandler || rows[0].Action__c != expectedAction) throw new IllegalArgumentException('Handler/action mismatch');
if (String.isNotBlank(expectedRelatedId) && rows[0].Related_Record_Id__c != expectedRelatedId) throw new IllegalArgumentException('Related record mismatch');
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT job=' + jobId + ' handler=' + rows[0].Handler_Class__c + ' action=' + rows[0].Action__c + ' related=' + rows[0].Related_Record_Id__c + ' attempts=' + rows[0].Attempt_Count__c + '/' + rows[0].Max_Attempts__c + ' action=requeue preserving payload dryRun=' + dryRun);
if (!dryRun) {
    if (!rootCauseFixed) throw new IllegalArgumentException('Confirm root cause is fixed before resetting attempts');
    Job_Queue__c locked = [SELECT Id, Status__c, Handler_Class__c, Action__c, Related_Record_Id__c FROM Job_Queue__c WHERE Id = :jobId FOR UPDATE];
    if (locked.Status__c != 'Dead Letter' || locked.Handler_Class__c != expectedHandler || locked.Action__c != expectedAction || (String.isNotBlank(expectedRelatedId) && locked.Related_Record_Id__c != expectedRelatedId)) throw new IllegalArgumentException('Job changed after preflight');
    JobQueueService.requeue(jobId, System.now());
    System.debug(LoggingLevel.WARN, 'RECOVERY SUBMITTED Job_Queue__c requeue=' + jobId + '; verify handler outcome');
}
