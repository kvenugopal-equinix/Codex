// SRE row 15. The active screen flow passes RETRY_CHARGE_LINES to this deployed handler.
// One Quote may contain many cancellation lines; the handler queues a billing callout and fee-line DML.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Integer expectedEligibleLineCount = -1;
Integer expectedExistingChargeLineCount = -1;
String expectedEligibleLineIdsCsv = 'REPLACE_WITH_SORTED_ELIGIBLE_LINE_IDS';
String expectedExistingChargeLineIdsCsv = 'REPLACE_WITH_SORTED_EXISTING_CHARGE_LINE_IDS';
Boolean billingAssetPresentConfirmed = false;
Boolean feeMappingsAndExistingChargesReviewed = false;
Boolean quoteTypeAndChangeScopeReviewed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException('Supply one exact Quote Id');
Id quoteId = (Id) recordIdText;
if (quoteId.getSObjectType() != Quote.SObjectType)
    throw new IllegalArgumentException('Id is not a Quote');
List<Quote> quotes = [
    SELECT
        Id,
        Status,
        Quote_Type__c,
        Interface_Error_Message__c,
        Total_Calculated_ETF__c,
        QuoteAccount.MDM_ID__c
    FROM Quote
    WHERE Id = :quoteId
    LIMIT 1
];
if (
    quotes.size() != 1 ||
    quotes[0].QuoteAccount == null ||
    String.isBlank(quotes[0].QuoteAccount.MDM_ID__c)
)
    throw new IllegalArgumentException('Quote missing or account MDM ID absent');
List<QuoteLineItem> lines = [
    SELECT
        Id,
        QuoteAction.Type,
        QuoteAction.SourceAsset.Asset_Number__c,
        QuoteAction.SourceAsset.Is_Billable__c,
        QuoteAction.SourceAsset.Smart_SKU__c,
        Product2.StockKeepingUnit,
        Product2.Termination_Fee_Applicable__c,
        Is_Billable__c
    FROM QuoteLineItem
    WHERE
        QuoteId = :quoteId
        AND QuoteActionId != NULL
        AND Product2.Termination_Fee_Applicable__c = TRUE
    LIMIT 200
];
if (lines.size() == 200)
    throw new IllegalArgumentException(
        'At least 200 termination-capable lines; inspect full scope'
    );
Set<Id> eligibleIds = new Set<Id>();
Set<String> skus = new Set<String>();
for (QuoteLineItem line : lines)
    if (
        line.QuoteAction != null &&
        line.QuoteAction.Type == 'Cancel' &&
        line.QuoteAction.SourceAsset != null &&
        line.QuoteAction.SourceAsset.Is_Billable__c == true
    ) {
        eligibleIds.add(line.Id);
        if (String.isNotBlank(line.Product2.StockKeepingUnit))
            skus.add(line.Product2.StockKeepingUnit);
        if (String.isNotBlank(line.QuoteAction.SourceAsset.Smart_SKU__c))
            skus.add(line.QuoteAction.SourceAsset.Smart_SKU__c);
    }
if (eligibleIds.isEmpty())
    throw new IllegalArgumentException('No billable cancellation lines eligible for fee retry');
List<String> eligibleIdTexts = new List<String>();
for (Id eligibleId : eligibleIds)
    eligibleIdTexts.add(String.valueOf(eligibleId));
eligibleIdTexts.sort();
String eligibleLineIdsCsv = String.join(eligibleIdTexts, ',');
List<String> skuTexts = new List<String>();
skuTexts.addAll(skus);
skuTexts.sort();
List<ProductCharge__mdt> mappings = [
    SELECT Product_SKU__c, Fee_SKU__c
    FROM ProductCharge__mdt
    WHERE Product_SKU__c IN :skus AND Termination_Fee__c = TRUE
];
List<Charge_Lines__c> charges = [
    SELECT Id, Quote_Line_Item__c, NET_price__c, List_Price__c
    FROM Charge_Lines__c
    WHERE Quote__c = :quoteId
    LIMIT 200
];
if (charges.size() == 200)
    throw new IllegalArgumentException('At least 200 existing charge lines; inspect full scope');
List<String> existingChargeIdTexts = new List<String>();
for (Charge_Lines__c charge : charges)
    existingChargeIdTexts.add(String.valueOf(charge.Id));
existingChargeIdTexts.sort();
String existingChargeLineIdsCsv = String.join(existingChargeIdTexts, ',');
Integer positivePricedCharges = 0;
Integer zeroOrBlankCharges = 0;
for (Charge_Lines__c charge : charges) {
    if (
        charge.NET_price__c != null &&
        charge.NET_price__c > 0 &&
        charge.List_Price__c != null &&
        charge.List_Price__c > 0
    )
        positivePricedCharges++;
    else
        zeroOrBlankCharges++;
}
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT row15 quote=' +
        quoteId +
        ' status=' +
        quotes[0].Status +
        ' quoteType=' +
        quotes[0].Quote_Type__c +
        ' calculatedETF=' +
        quotes[0].Total_Calculated_ETF__c +
        ' eligibleLineCount=' +
        eligibleIds.size() +
        ' eligibleLineIdsCsv=' +
        eligibleLineIdsCsv +
        ' baseSkusCsv=' +
        String.join(skuTexts, ',') +
        ' metadataMappings=' +
        mappings.size() +
        ' existingChargeLineCount=' +
        charges.size() +
        ' existingChargeLineIdsCsv=' +
        existingChargeLineIdsCsv +
        ' positivePricedCharges=' +
        positivePricedCharges +
        ' zeroOrBlankCharges=' +
        zeroOrBlankCharges +
        ' dryRun=' +
        dryRun
);
if (!dryRun) {
    if (
        !billingAssetPresentConfirmed ||
        !feeMappingsAndExistingChargesReviewed ||
        !quoteTypeAndChangeScopeReviewed ||
        expectedEligibleLineCount != eligibleIds.size() ||
        expectedExistingChargeLineCount != charges.size() ||
        expectedEligibleLineIdsCsv != eligibleLineIdsCsv ||
        expectedExistingChargeLineIdsCsv != existingChargeLineIdsCsv
    )
        throw new IllegalArgumentException(
            'Confirm Quote type/change scope, OSM assets, SKU mappings, exact eligible line IDs, and existing fee-line IDs/state'
        );
    QuoteChangeOrderPostProcessHandler.processQuote(
        quoteId,
        QuoteChangeOrderPostProcessHandler.RETRY_CHARGE_LINES,
        null,
        null
    );
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY SUBMITTED fee-line retry for Quote ' +
            quoteId +
            '; inspect queueable, billing response, and Charge_Lines__c'
    );
}
