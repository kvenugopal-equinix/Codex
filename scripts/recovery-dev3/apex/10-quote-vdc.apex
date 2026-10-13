// One Quote POF VDC capacity request. The async batch may update several response lines.
Boolean dryRun = true;
String expectedOrgId = '00DWI00000DzbpZ2AR';
Boolean expectedSandbox = true;
String quoteIdText = 'REPLACE_WITH_18_CHAR_ID';
String pofIdText = 'REPLACE_WITH_18_CHAR_ID'; // QuoteLineItem Id.
Boolean externalOutcomeConfirmedAbsent = false;

if (UserInfo.getOrganizationId() != (Id) expectedOrgId) throw new IllegalArgumentException('Wrong Salesforce org');
if ([SELECT IsSandbox FROM Organization LIMIT 1].IsSandbox != expectedSandbox) throw new IllegalArgumentException('Wrong sandbox/production environment');
if (quoteIdText.length() != 18 || pofIdText.length() != 18 || quoteIdText == 'REPLACE_WITH_18_CHAR_ID' || pofIdText == 'REPLACE_WITH_18_CHAR_ID') throw new IllegalArgumentException('Supply exact 18-character Quote and QuoteLineItem Ids');
Id quoteId = (Id) quoteIdText;
Id pofId = (Id) pofIdText;
if (quoteId.getSObjectType() != Quote.SObjectType || pofId.getSObjectType() != QuoteLineItem.SObjectType) throw new IllegalArgumentException('Wrong ID types');
List<QuoteLineItem> lines = [SELECT Id, QuoteId, Root_Line__c, Capacity_Status__c, Design_Status__c FROM QuoteLineItem WHERE Id = :pofId LIMIT 1];
if (lines.size() != 1 || lines[0].QuoteId != quoteId) throw new IllegalArgumentException('Quote POF missing or belongs to another Quote');
if (lines[0].Root_Line__c != true) throw new IllegalArgumentException('Selected QuoteLineItem is not a root POF in configured POF_Query');
if (String.isNotBlank(lines[0].Capacity_Status__c) || String.isNotBlank(lines[0].Design_Status__c)) throw new IllegalArgumentException('POF already has VDC capacity/design status; inspect before replay');
List<VDC_Quote_Query_Config__mdt> configs = [SELECT NamedCredentials__c, EndPoint__c FROM VDC_Quote_Query_Config__mdt WHERE DeveloperName = 'VDCAPI' LIMIT 1];
if (configs.size() != 1 || String.isBlank(configs[0].NamedCredentials__c)) throw new IllegalArgumentException('VDCAPI endpoint not configured');
List<AsyncApexJob> active = [SELECT Id, Status FROM AsyncApexJob WHERE ApexClass.Name = 'EQXCallVDCAsyncBatchCls' AND Status IN ('Holding','Queued','Preparing','Processing') LIMIT 10];
if (!active.isEmpty()) throw new IllegalArgumentException('VDC Quote batches are active; inspect concurrency first');
System.debug(LoggingLevel.WARN, 'RECOVERY PREFLIGHT quote=' + quoteId + ' pof=' + pofId + ' endpointKey=VDCAPI action=VDC async batch; response can stamp multiple QLIs dryRun=' + dryRun);
if (!dryRun) {
    if (!externalOutcomeConfirmedAbsent) throw new IllegalArgumentException('Confirm no successful VDC result exists for this POF before replay');
    EQXQuoteVDCService_Wrapper.InputWrapper input = new EQXQuoteVDCService_Wrapper.InputWrapper();
    input.recordId = quoteId;
    input.pofId = pofId;
    input.interfaceName = 'VDCAPI';
    input.isAsync = true;
    EQXQuoteVDCService_Wrapper.callVDC(new List<EQXQuoteVDCService_Wrapper.InputWrapper>{ input });
    System.debug(LoggingLevel.WARN, 'RECOVERY SUBMITTED Quote VDC batch quote=' + quoteId + ' pof=' + pofId + '; verify AsyncApexJob, VDC response, and all stamped lines');
}
