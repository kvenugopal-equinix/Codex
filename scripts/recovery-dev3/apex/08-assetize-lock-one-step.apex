// One FulfillmentStep lock retry. Calls the batch's public one-scope execute, not its org-wide start().
Boolean dryRun = true;
String expectedOrgId = '00DWI00000DzbpZ2AR';
Boolean expectedSandbox = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';

if (UserInfo.getOrganizationId() != (Id) expectedOrgId) throw new IllegalArgumentException('Wrong Salesforce org');
if ([SELECT IsSandbox FROM Organization LIMIT 1].IsSandbox != expectedSandbox) throw new IllegalArgumentException('Wrong sandbox/production environment');
if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply one exact 18-character FulfillmentStep Id');
Id stepId = (Id) recordIdText;
if (stepId.getSObjectType() != FulfillmentStep.SObjectType) throw new IllegalArgumentException('Id is not a FulfillmentStep');
List<FulfillmentStep> rows = [SELECT Id, Name, StepType, State, ExecutionMessage, FulfillmentPlanId, FulfillmentPlan.State, LastModifiedDate FROM FulfillmentStep WHERE Id = :stepId LIMIT 1];
if (rows.size() != 1) throw new IllegalArgumentException('FulfillmentStep missing');
FulfillmentStep step = rows[0];
if (step.StepType != 'StagedAssetize' || !new Set<String>{'Failed','FatallyFailed'}.contains(step.State)) throw new IllegalArgumentException('Step is not a failed Assetize step');
if (!new Set<String>{'NotStarted','InProgress'}.contains(step.FulfillmentPlan.State)) throw new IllegalArgumentException('Fulfillment plan is not active');
if (step.ExecutionMessage == null || !step.ExecutionMessage.containsIgnoreCase('UNABLE_TO_LOCK_ROW')) throw new IllegalArgumentException('Failure is not a row lock');
if (step.LastModifiedDate > System.now().addMinutes(-15)) throw new IllegalArgumentException('Step is too recent to retry');
Datetime since = System.now().addDays(-7);
Integer retries = [SELECT COUNT() FROM Transaction_Log__c WHERE Apex_Class_Name__c = 'FulfillmentStepAssetizeRetryBatch' AND Primary_Key__c = :recordIdText AND Status__c = 'Retry' AND CreatedDate >= :since];
if (retries >= 3) throw new IllegalArgumentException('Assetize retry cap reached within seven days');
if ([SELECT COUNT() FROM AsyncApexJob WHERE ApexClass.Name = 'FulfillmentStepAssetizeRetryBatch' AND Status IN ('Holding','Queued','Preparing','Processing')] > 0) throw new IllegalArgumentException('Assetize batch is active; avoid racing it');
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT step=' + step.Id + ' state=' + step.State + ' plan=' + step.FulfillmentPlanId + ' retriesIn7Days=' + retries + ' action=set Ready through existing retry logic dryRun=' + dryRun);
if (!dryRun) {
    // execute() uses no BatchableContext; the exact-ID eligibility checks above replace start().
    new FulfillmentStepAssetizeRetryBatch().execute(null, new List<FulfillmentStep>{ step });
    System.debug(LoggingLevel.WARN, 'RECOVERY SUBMITTED scoped Assetize retry step=' + step.Id + '; verify State and Transaction_Log__c');
}
