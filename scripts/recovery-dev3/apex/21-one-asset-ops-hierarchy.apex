// One commercial Asset OPS_Hierarchy job. A FulfillmentAsset Id runs diagnostics only:
// the deployed OPS_Hierarchy flow accepts Asset Ids and can requeue child sync jobs.
Boolean dryRun = true;
String recordIdText = 'REPLACE_WITH_18_CHAR_ID';
Boolean parentHierarchyReviewed = false;
Boolean previousJobOutcomeReviewed = false;
Boolean childRequeueImpactReviewed = false;
Boolean unresolvedHierarchyLogReviewed = false;

if (recordIdText.length() != 18 || recordIdText == 'REPLACE_WITH_18_CHAR_ID')
    throw new IllegalArgumentException(
        'Supply one exact 18-character Asset or FulfillmentAsset Id'
    );
Id recordId = (Id) recordIdText;

if (recordId.getSObjectType() == FulfillmentAsset.SObjectType) {
    List<FulfillmentAsset> technical = [
        SELECT
            Id,
            Asset_Number__c,
            Status,
            Root_Asset_Id__c,
            Parent_Asset_Id__c,
            ProductRootItemId__c,
            Commercial_Parent_Id__c,
            Order__c,
            Order_Item__c
        FROM FulfillmentAsset
        WHERE Id = :recordId
        LIMIT 1
    ];
    if (technical.size() != 1)
        throw new IllegalArgumentException('FulfillmentAsset missing');
    List<Asset> commercial = technical[0].Commercial_Parent_Id__c == null
        ? new List<Asset>()
        : [
              SELECT Id, Status, Root_Asset_Id__c, Parent_Asset_Id__c, ProductRootItemId__c
              FROM Asset
              WHERE Id = :technical[0].Commercial_Parent_Id__c
              LIMIT 1
          ];
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY DIAGNOSTIC technicalAsset=' +
            technical[0].Id +
            ' root=' +
            technical[0].Root_Asset_Id__c +
            ' parent=' +
            technical[0].Parent_Asset_Id__c +
            ' productRoot=' +
            technical[0].ProductRootItemId__c +
            ' commercialParent=' +
            technical[0].Commercial_Parent_Id__c +
            ' commercialRoot=' +
            (commercial.isEmpty() ? null : commercial[0].Root_Asset_Id__c) +
            ' order=' +
            technical[0].Order__c +
            ' orderItem=' +
            technical[0].Order_Item__c +
            ' dryRun=' +
            dryRun
    );
    if (!dryRun)
        throw new IllegalArgumentException(
            'No verified direct technical-asset hierarchy replay; review commercial parent and escalate'
        );
} else if (recordId.getSObjectType() == Asset.SObjectType) {
    List<Asset> rows = [
        SELECT
            Id,
            Asset_Number__c,
            Status,
            StockKeepingUnit,
            Root_Asset_Id__c,
            Parent_Asset_Id__c,
            ProductRootItemId__c
        FROM Asset
        WHERE Id = :recordId
        LIMIT 1
    ];
    if (rows.size() != 1)
        throw new IllegalArgumentException('Commercial Asset missing');
    Asset commercialAsset = rows[0];
    if (commercialAsset.Status != 'Active' || String.isNotBlank(commercialAsset.Root_Asset_Id__c))
        throw new IllegalArgumentException('Asset is not an Active missing-root candidate');
    if (String.isBlank(commercialAsset.Parent_Asset_Id__c))
        throw new IllegalArgumentException('Parent is unknown; root Asset needs asset-team review');
    Id parentId = (Id) commercialAsset.Parent_Asset_Id__c;
    if (parentId.getSObjectType() != Asset.SObjectType || parentId == recordId)
        throw new IllegalArgumentException('Parent_Asset_Id__c is not a distinct commercial Asset');
    List<Asset> parents = [
        SELECT Id, Status, StockKeepingUnit, Root_Asset_Id__c, ProductRootItemId__c
        FROM Asset
        WHERE Id = :parentId
        LIMIT 1
    ];
    if (
        parents.size() != 1 ||
        parents[0].Status != 'Active' ||
        String.isBlank(parents[0].Root_Asset_Id__c)
    )
        throw new IllegalArgumentException(
            'Parent hierarchy is not ready; repair the parent sequence first'
        );
    if (
        String.isNotBlank(commercialAsset.ProductRootItemId__c) &&
        String.isNotBlank(parents[0].ProductRootItemId__c) &&
        commercialAsset.ProductRootItemId__c != parents[0].ProductRootItemId__c
    )
        throw new IllegalArgumentException('Child and parent ProductRootItemId__c differ');

    List<Asset_Hierarchy_Map__mdt> mappings = [
        SELECT Product__c, Parent__c, Sequence__c
        FROM Asset_Hierarchy_Map__mdt
        WHERE Product__c = :commercialAsset.StockKeepingUnit
        LIMIT 51
    ];
    if (mappings.isEmpty() || mappings.size() > 50)
        throw new IllegalArgumentException('Inspect SKU hierarchy metadata manually');
    Set<Integer> sequences = new Set<Integer>();
    Boolean parentSkuMapped = false;
    for (Asset_Hierarchy_Map__mdt mapping : mappings) {
        if (mapping.Sequence__c != null)
            sequences.add(mapping.Sequence__c.intValue());
        if (mapping.Parent__c == parents[0].StockKeepingUnit)
            parentSkuMapped = true;
    }
    if (
        !parentSkuMapped ||
        sequences.size() != 1 ||
        !new Set<Integer>{ 1, 2, 3, 4 }.containsAll(sequences)
    )
        throw new IllegalArgumentException('SKU/parent sequence mapping is ambiguous or invalid');

    List<Integration_Job__c> jobs = [
        SELECT
            Id,
            Name,
            Status__c,
            External_Key__c,
            Target_Record_Id__c,
            Integration_Type__c,
            Target_Object__c,
            CreatedDate
        FROM Integration_Job__c
        WHERE Target_Record_Id__c = :recordIdText AND Integration_Type__c = 'OPS_Hierarchy'
        ORDER BY CreatedDate DESC
        LIMIT 21
    ];
    if (jobs.size() > 20)
        throw new IllegalArgumentException(
            'Too many prior OPS hierarchy jobs; investigate repeated failure'
        );
    for (Integration_Job__c job : jobs)
        if (job.Status__c == 'Pending' || job.Status__c == 'Running')
            throw new IllegalArgumentException(
                'An OPS hierarchy job is already Pending or Running'
            );
    if (!jobs.isEmpty() && jobs[0].Target_Object__c != 'Asset')
        throw new IllegalArgumentException('Latest OPS hierarchy job targets the wrong object');
    List<Transaction_Log__c> hierarchyLogs = [
        SELECT Id, Status__c, Error_Message__c, CreatedDate
        FROM Transaction_Log__c
        WHERE Primary_Key__c = :recordIdText AND Apex_Class_Name__c = 'Asset Product Hierarchy'
        ORDER BY CreatedDate DESC
        LIMIT 10
    ];
    if (
        [
            SELECT COUNT()
            FROM AsyncApexJob
            WHERE
                ApexClass.Name = 'OpsHierarchyRerunBatch'
                AND Status IN ('Holding', 'Queued', 'Preparing', 'Processing')
        ] > 0
    )
        throw new IllegalArgumentException('OPS hierarchy rerun batch is active');
    List<Asset> children = [
        SELECT Id, Status, Root_Asset_Id__c, Parent_Asset_Id__c
        FROM Asset
        WHERE Parent_Asset_Id__c = :recordIdText
        LIMIT 51
    ];
    List<FulfillmentAsset> technicalChildren = [
        SELECT Id, Status, Root_Asset_Id__c, Parent_Asset_Id__c
        FROM FulfillmentAsset
        WHERE Commercial_Parent_Id__c = :recordId
        LIMIT 51
    ];
    if (children.size() > 50 || technicalChildren.size() > 50)
        throw new IllegalArgumentException('Too many child assets for a one-Asset replay');
    for (Asset child : children)
        System.debug(
            LoggingLevel.WARN,
            'RECOVERY COMMERCIAL CHILD asset=' +
                child.Id +
                ' status=' +
                child.Status +
                ' root=' +
                child.Root_Asset_Id__c +
                ' parent=' +
                child.Parent_Asset_Id__c +
                ' parentStatus=' +
                commercialAsset.Status
        );
    for (FulfillmentAsset child : technicalChildren)
        System.debug(
            LoggingLevel.WARN,
            'RECOVERY TECHNICAL CHILD asset=' +
                child.Id +
                ' status=' +
                child.Status +
                ' root=' +
                child.Root_Asset_Id__c +
                ' parent=' +
                child.Parent_Asset_Id__c +
                ' commercialParentStatus=' +
                commercialAsset.Status
        );
    System.debug(
        LoggingLevel.WARN,
        'RECOVERY PREFLIGHT commercialAsset=' +
            recordId +
            ' sku=' +
            commercialAsset.StockKeepingUnit +
            ' sequence=' +
            sequences +
            ' parent=' +
            parentId +
            ' parentStatus=' +
            parents[0].Status +
            ' parentRoot=' +
            parents[0].Root_Asset_Id__c +
            ' productRoot=' +
            commercialAsset.ProductRootItemId__c +
            ' priorJobs=' +
            jobs.size() +
            ' latestStatus=' +
            (jobs.isEmpty() ? 'none' : jobs[0].Status__c) +
            ' latestHierarchyLog=' +
            (hierarchyLogs.isEmpty() ? 'none' : hierarchyLogs[0].Status__c) +
            ' commercialChildren=' +
            children.size() +
            ' technicalChildren=' +
            technicalChildren.size() +
            ' action=' +
            (jobs.isEmpty() ? 'Create_Integration_Job flow' : 'complete and copy latest job') +
            ' dryRun=' +
            dryRun
    );

    if (!dryRun) {
        if (!parentHierarchyReviewed || !previousJobOutcomeReviewed || !childRequeueImpactReviewed)
            throw new IllegalArgumentException(
                'Review parent hierarchy, prior job outcome, and possible child Asset/FulfillmentAsset resync'
            );
        if (
            !hierarchyLogs.isEmpty() &&
            hierarchyLogs[0].Status__c == 'In Processing' &&
            !unresolvedHierarchyLogReviewed
        )
            throw new IllegalArgumentException(
                'Inspect the unresolved hierarchy transaction log before creating another job'
            );
        if (jobs.isEmpty()) {
            Flow.Interview.createInterview(
                    'Create_Integration_Job',
                    new Map<String, Object>{
                        'IntegrationType' => 'OPS_Hierarchy',
                        'TargetObjectName' => 'Asset',
                        'TargetRecordId' => recordIdText
                    }
                )
                .start();
            System.debug(
                LoggingLevel.WARN,
                'RECOVERY SUBMITTED one OPS hierarchy flow for ' + recordId
            );
        } else {
            Savepoint sp = Database.setSavepoint();
            try {
                Integration_Job__c oldJob = [
                    SELECT
                        Id,
                        Name,
                        Status__c,
                        External_Key__c,
                        Target_Record_Id__c,
                        Integration_Type__c,
                        Target_Object__c
                    FROM Integration_Job__c
                    WHERE Id = :jobs[0].Id
                    LIMIT 1
                    FOR UPDATE
                ];
                if (oldJob.Status__c == 'Pending' || oldJob.Status__c == 'Running')
                    throw new IllegalArgumentException('Latest job became active; stop');
                oldJob.Status__c = 'Completed';
                update oldJob;
                Integration_Job__c newJob = new Integration_Job__c(
                    Name = oldJob.Name,
                    Status__c = 'Pending',
                    Execution_Start_Time__c = System.now().addMinutes(1),
                    External_Key__c = oldJob.External_Key__c,
                    Target_Record_Id__c = oldJob.Target_Record_Id__c,
                    Integration_Type__c = oldJob.Integration_Type__c,
                    Target_Object__c = oldJob.Target_Object__c
                );
                insert newJob;
                System.debug(
                    LoggingLevel.WARN,
                    'RECOVERY SUBMITTED one OPS hierarchy job=' + newJob.Id + ' asset=' + recordId
                );
            } catch (Exception e) {
                Database.rollback(sp);
                throw e;
            }
        }
        // The hierarchy flow may queue child OPS, commercial sync, and technical sync jobs.
    }
} else {
    throw new IllegalArgumentException('Id is neither Asset nor FulfillmentAsset');
}
