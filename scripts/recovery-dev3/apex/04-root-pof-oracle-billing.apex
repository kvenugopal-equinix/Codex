// One root POF on one Order. Oracle may have succeeded even when Salesforce logging failed.
Boolean dryRun = true;
String expectedOrgId = '00DWI00000DzbpZ2AR';
Boolean expectedSandbox = true;
String orderIdText = 'REPLACE_WITH_18_CHAR_ID';
String recordIdText = 'REPLACE_WITH_18_CHAR_ID'; // Root OrderItem/POF Id.
Boolean oracleConfirmedMissing = false; // Check the actual Oracle subscription/order first.

if (UserInfo.getOrganizationId() != (Id) expectedOrgId) throw new IllegalArgumentException('Wrong Salesforce org');
if ([SELECT IsSandbox FROM Organization LIMIT 1].IsSandbox != expectedSandbox) throw new IllegalArgumentException('Wrong sandbox/production environment');
if (orderIdText.length() != 18 || orderIdText == 'REPLACE_WITH_18_CHAR_ID' || recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply exact 18-character Order and root POF Ids');
Id orderId = (Id) orderIdText;
Id pofId = (Id) recordIdText;
if (orderId.getSObjectType() != Order.SObjectType || pofId.getSObjectType() != OrderItem.SObjectType) throw new IllegalArgumentException('Wrong ID types');
List<OrderItem> rows = [SELECT Id, OrderId, Status, Root_Line_Flag__c, Billing_Triggered__c, Expected_Billing_Date_Time__c, SPC_Billing_Exception__c FROM OrderItem WHERE Id = :pofId LIMIT 1];
if (rows.size() != 1 || rows[0].OrderId != orderId || rows[0].Root_Line_Flag__c != true) throw new IllegalArgumentException('POF missing, wrong Order, or not root');
if (rows[0].Status != 'Closed' || rows[0].Billing_Triggered__c == true || rows[0].SPC_Billing_Exception__c == 'Yes') throw new IllegalArgumentException('POF is not eligible for billing replay');
if (rows[0].Expected_Billing_Date_Time__c == null || rows[0].Expected_Billing_Date_Time__c > System.now()) throw new IllegalArgumentException('Expected billing date has not arrived');
List<Transaction_Log__c> logs = [SELECT Id, Status__c, CreatedDate, Error_Message__c FROM Transaction_Log__c WHERE Apex_Class_Name__c = 'OracleCloudIntegrationController' AND Primary_Key__c = :recordIdText ORDER BY CreatedDate DESC LIMIT 10];
for (Transaction_Log__c logRow : logs) if (logRow.Status__c == 'Success') throw new IllegalArgumentException('A prior Oracle billing log says Success: ' + logRow.Id);
List<AsyncApexJob> active = [SELECT Id, Status FROM AsyncApexJob WHERE ApexClass.Name = 'OracleCloudIntegrationQueueable' AND Status IN ('Holding','Queued','Preparing','Processing') LIMIT 10];
if (!active.isEmpty()) throw new IllegalArgumentException('Oracle queueable jobs are active; resolve concurrent work first');
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT rootPOF=' + pofId + ' order=' + orderId + ' billingLogs=' + logs + ' action=one Oracle queueable dryRun=' + dryRun);
if (!dryRun) {
    if (!oracleConfirmedMissing) throw new IllegalArgumentException('Confirm Oracle has no successful result for this root POF');
    Id asyncId = System.enqueueJob(new OracleCloudIntegrationQueueable(new Set<Id>{ orderId }, new Set<Id>{ pofId }));
    System.debug(LoggingLevel.WARN, 'RECOVERY SUBMITTED Oracle billing queueable=' + asyncId + ' rootPOF=' + pofId + '; verify Oracle acknowledgement');
}
