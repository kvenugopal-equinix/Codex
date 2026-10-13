// One Order POF VDC capacity request. Cabinet/Circuit/CPC requests route through a PC/SC sibling.
Boolean dryRun = true;
String orderIdText = 'REPLACE_WITH_18_CHAR_ID';
String pofIdText = 'REPLACE_WITH_18_CHAR_ID'; // OrderItem Id.
Boolean externalOutcomeConfirmedAbsent = false;
Boolean orderVdcPathVerified = false; // Resolve field visibility and validate deployed service before live dispatch.

if (
    orderIdText.length() != 18 ||
    pofIdText.length() != 18 ||
    orderIdText == 'REPLACE_WITH_18_CHAR_ID' ||
    pofIdText == 'REPLACE_WITH_18_CHAR_ID'
)
    throw new IllegalArgumentException('Supply exact 18-character Order and OrderItem Ids');
Id orderId = (Id) orderIdText;
Id pofId = (Id) pofIdText;
if (
    orderId.getSObjectType() != Order.SObjectType ||
    pofId.getSObjectType() != OrderItem.SObjectType
)
    throw new IllegalArgumentException('Wrong ID types');
// Tooling confirms this field exists in dev3, but the connected user cannot see it. Stop until access is verified.
if (!Schema.SObjectType.OrderItem.fields.getMap().containsKey('VDCCheckConfigStatus__c'))
    throw new IllegalArgumentException(
        'Order VDC blocked: OrderItem.VDCCheckConfigStatus__c is not visible to this user'
    );
List<SObject> lines = Database.query(
    'SELECT Id, OrderId, Product_SKU__c, ProductRootItemId__c, VDCCheckConfigStatus__c, Order.Parent_Order__c FROM OrderItem WHERE Id = :pofId LIMIT 1'
);
if (lines.size() != 1 || (Id) lines[0].get('OrderId') != orderId)
    throw new IllegalArgumentException('Order POF missing or belongs to another Order');
if (String.isNotBlank((String) lines[0].get('VDCCheckConfigStatus__c')))
    throw new IllegalArgumentException(
        'POF already has VDCCheckConfigStatus__c; inspect before replay'
    );
List<VDC_Endpoint_Config__mdt> configs = [
    SELECT Named_Credential__c, Endpoint_Path__c
    FROM VDC_Endpoint_Config__mdt
    WHERE DeveloperName = 'VDCCheckConfig'
    LIMIT 1
];
if (configs.size() != 1 || String.isBlank(configs[0].Named_Credential__c))
    throw new IllegalArgumentException('VDCCheckConfig endpoint not configured');
Set<String> childSkus = new Set<String>{
    'COLO.SPC.CAB',
    'COLO.SPCE.CAB',
    'COLO.PWR.AC.CRCT',
    'COLO.POW.CRCT',
    'COLO.SPCE.CPC'
};
if (childSkus.contains((String) lines[0].get('Product_SKU__c'))) {
    if (String.isBlank((String) lines[0].get('ProductRootItemId__c')))
        throw new IllegalArgumentException(
            'Child POF has no bundle reference; service would do nothing'
        );
    Set<String> pcSkus = new Set<String>();
    for (VDC_Root_Product_SKU__mdt sku : [
        SELECT ProductSKU__c
        FROM VDC_Root_Product_SKU__mdt
        LIMIT 200
    ])
        if (!childSkus.contains(sku.ProductSKU__c))
            pcSkus.add(sku.ProductSKU__c);
    String bundleRef = (String) lines[0].get('ProductRootItemId__c');
    List<SObject> pcLines = Database.query(
        'SELECT Id, Product_SKU__c, VDCCheckConfigStatus__c FROM OrderItem WHERE OrderId = :orderId AND ProductRootItemId__c = :bundleRef AND Product_SKU__c IN :pcSkus LIMIT 2'
    );
    if (pcLines.size() != 1)
        throw new IllegalArgumentException(
            'Cannot identify exactly one PC/SC sibling for child POF'
        );
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY ROUTE child=' +
            pofId +
            ' pc=' +
            pcLines[0].Id +
            ' pcStatus=' +
            pcLines[0].get('VDCCheckConfigStatus__c') +
            '; service may re-call VDC for PC and stamp sibling lines'
    );
}
System.debug(
    LoggingLevel.WARN,
    'RECOVERY PREFLIGHT order=' +
        orderId +
        ' pof=' +
        pofId +
        ' endpointKey=VDCCheckConfig action=VDC future/delayed queue; response can stamp multiple OrderItems dryRun=' +
        dryRun
);
if (!dryRun) {
    if (!orderVdcPathVerified)
        throw new IllegalArgumentException(
            'Order VDC path has not been validated after resolving field visibility'
        );
    if (!externalOutcomeConfirmedAbsent)
        throw new IllegalArgumentException(
            'Confirm no successful VDC result exists for this POF or its PC/SC sibling before replay'
        );
    EQXOrderVDCService.InputWrapper input = new EQXOrderVDCService.InputWrapper();
    input.orderId = orderId;
    input.pofId = pofId;
    input.endpointConfigKey = 'VDCCheckConfig';
    EQXOrderVDCService.callVDCForOrder(new List<EQXOrderVDCService.InputWrapper>{ input });
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY SUBMITTED Order VDC order=' +
            orderId +
            ' pof=' +
            pofId +
            '; verify Transaction_Log__c Trace_ID__c=OrderId and all stamped lines'
    );
}
