param(
    [ValidatePattern('^[A-Za-z0-9]{15}([A-Za-z0-9]{3})?$')]
    [string]$RecordId,

    [ValidateRange(1, 30)]
    [int]$Days = 7,

    [ValidateRange(1, 200)]
    [int]$Limit = 25,

    [string]$SfPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$targetAlias = 'dev3'
$expectedOrgId = '00DWI00000DzbpZ2AR'
$expectedHost = 'equinix-ltc--dev3.sandbox.my.salesforce.com'
$workspaceRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
$bundledSf = Join-Path $workspaceRoot '.tools\sf-prefix\node_modules\.bin\sf.cmd'
$bundledNode = Join-Path $workspaceRoot '.tools\node-v24.18.0-win-x64'

if ($SfPath) {
    $sfExecutable = (Resolve-Path -LiteralPath $SfPath).Path
} elseif (Test-Path -LiteralPath $bundledSf) {
    $sfExecutable = $bundledSf
} else {
    $installedSf = Get-Command sf.cmd, sf -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $installedSf) { throw 'Salesforce CLI was not found. Pass -SfPath.' }
    $sfExecutable = $installedSf.Source
}
if (Test-Path -LiteralPath $bundledNode) {
    $env:PATH = $bundledNode + [IO.Path]::PathSeparator + $env:PATH
}

function Invoke-SfJson {
    param([string[]]$CliArguments)

    # All calls in this script use only "org display" or "data query".
    $raw = & $sfExecutable @CliArguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Salesforce CLI failed: $($CliArguments[0..1] -join ' ')"
    }
    $response = ($raw -join [Environment]::NewLine) | ConvertFrom-Json
    if ($response.status -ne 0) {
        throw "Salesforce query failed: $($response.message)"
    }
    return $response.result
}

function Invoke-ReadQuery {
    param([string]$Query)
    return Invoke-SfJson -CliArguments @('data', 'query', '--target-org', $targetAlias, '--query', $Query, '--json')
}

function Show-Rows {
    param([string]$Heading, [object[]]$Rows, [string[]]$Columns)
    Write-Output "`n$Heading"
    if (-not $Rows -or $Rows.Count -eq 0) {
        Write-Output '  No matching rows.'
        return
    }
    $Rows | Select-Object -Property $Columns | Format-Table -AutoSize |
        Out-String -Width 240 | Write-Output
}

# Check the alias and the org's own sandbox flag before any operational query.
# Never print the auth response: it contains an access token.
$org = Invoke-SfJson -CliArguments @('org', 'display', '--target-org', $targetAlias, '--json')
if ($org.id -ne $expectedOrgId -or $org.alias -ne $targetAlias -or
    ([uri]$org.instanceUrl).Host -ne $expectedHost) {
    throw 'The dev3 alias does not resolve to the pinned dev3 sandbox. No inspection queries were run.'
}
$organization = Invoke-ReadQuery -Query 'SELECT Id, IsSandbox FROM Organization LIMIT 1'
if ($organization.records.Count -ne 1 -or $organization.records[0].Id -ne $expectedOrgId -or
    $organization.records[0].IsSandbox -ne $true) {
    throw 'The connected Salesforce Organization record does not match the pinned dev3 sandbox.'
}
Write-Output "Verified ${targetAlias}: $expectedOrgId ($expectedHost), sandbox. Read-only inspection."

$jobs = Invoke-ReadQuery -Query "SELECT Id, ApexClass.Name, JobType, Status, NumberOfErrors, ExtendedStatus, CreatedDate, CompletedDate FROM AsyncApexJob WHERE CreatedDate = LAST_N_DAYS:$Days AND (Status = 'Failed' OR NumberOfErrors > 0) ORDER BY CreatedDate DESC LIMIT $Limit"
$jobRows = @($jobs.records | ForEach-Object {
    [pscustomobject]@{
        Id = $_.Id; Class = $_.ApexClass.Name; JobType = $_.JobType; Status = $_.Status
        Errors = $_.NumberOfErrors; Detail = $_.ExtendedStatus; CreatedDate = $_.CreatedDate
    }
})
Show-Rows -Heading "Recent failed async jobs (last $Days days)" -Rows $jobRows -Columns @('Id','Class','JobType','Status','Errors','Detail','CreatedDate')

$queues = Invoke-ReadQuery -Query "SELECT Id, SourceRecordid__c, Source__c, Status__c, Error_Message__c, CreatedDate, LastModifiedDate FROM Booking_Calculation_Queue__c WHERE LastModifiedDate = LAST_N_DAYS:$Days AND Status__c IN ('FAILED','IN PROGRESS') ORDER BY LastModifiedDate DESC LIMIT $Limit"
Show-Rows -Heading 'Failed or in-progress booking queues' -Rows @($queues.records) -Columns @('Id','SourceRecordid__c','Source__c','Status__c','Error_Message__c','LastModifiedDate')

$transactions = Invoke-ReadQuery -Query "SELECT Id, Primary_Key__c, Job_Name__c, Apex_Class_Name__c, Status__c, CreatedDate FROM Transaction_Log__c WHERE CreatedDate = LAST_N_DAYS:$Days AND Status__c IN ('Failed','Exception','Error') ORDER BY CreatedDate DESC LIMIT $Limit"
Show-Rows -Heading 'Failed transaction logs' -Rows @($transactions.records) -Columns @('Id','Primary_Key__c','Job_Name__c','Apex_Class_Name__c','Status__c','CreatedDate')

$integrations = Invoke-ReadQuery -Query "SELECT Id, Record_ID__c, Integration_Config_Name__c, Transaction_Status__c, HTTP_Status_Code__c, CreatedDate FROM Integration_Log__c WHERE CreatedDate = LAST_N_DAYS:$Days AND Transaction_Status__c IN ('Failed','Exception','Error') ORDER BY CreatedDate DESC LIMIT $Limit"
Show-Rows -Heading 'Failed integration logs' -Rows @($integrations.records) -Columns @('Id','Record_ID__c','Integration_Config_Name__c','Transaction_Status__c','HTTP_Status_Code__c','CreatedDate')

if ($RecordId) {
    # Salesforce's 18-character ID includes a case checksum. Preserve it exactly.
    $recordIdSql = $RecordId
    $prefix = $recordIdSql.Substring(0, 3)
    $typeResult = Invoke-ReadQuery -Query "SELECT QualifiedApiName FROM EntityDefinition WHERE KeyPrefix = '$prefix' LIMIT 10"
    $types = @($typeResult.records | ForEach-Object { $_.QualifiedApiName })
    Write-Output "`nExact record: $recordIdSql; possible object type(s): $($types -join ', ')"

    $inspectableTypes = @('Quote','Order','OrderItem','Opportunity','Asset',
        'FulfillmentPlan','FulfillmentOrder','FulfillmentOrderLineItem',
        'FulfillmentStep','FulfillmentAsset','Job_Queue__c')
    $matchedType = @($types | Where-Object { $_ -in $inspectableTypes }) | Select-Object -First 1
    if ($matchedType) {
        $target = Invoke-ReadQuery -Query "SELECT Id FROM $matchedType WHERE Id = '$recordIdSql' LIMIT 1"
        Write-Output "Record exists in $matchedType`: $(@($target.records).Count -eq 1)"
    }

    $recordQueues = Invoke-ReadQuery -Query "SELECT Id, SourceRecordid__c, Source__c, Status__c, Error_Message__c, CreatedDate, LastModifiedDate FROM Booking_Calculation_Queue__c WHERE SourceRecordid__c = '$recordIdSql' ORDER BY CreatedDate DESC LIMIT $Limit"
    Show-Rows -Heading 'Booking queues for exact record' -Rows @($recordQueues.records) -Columns @('Id','Status__c','Error_Message__c','CreatedDate','LastModifiedDate')

    # Different integrations use either Primary_Key__c or Job_Name__c for a record ID.
    $recordTransactions = Invoke-ReadQuery -Query "SELECT Id, Primary_Key__c, Job_Name__c, Apex_Class_Name__c, Status__c, CreatedDate FROM Transaction_Log__c WHERE Primary_Key__c = '$recordIdSql' OR Job_Name__c = '$recordIdSql' ORDER BY CreatedDate DESC LIMIT $Limit"
    Show-Rows -Heading 'Transaction logs for exact record' -Rows @($recordTransactions.records) -Columns @('Id','Primary_Key__c','Job_Name__c','Apex_Class_Name__c','Status__c','CreatedDate')

    $recordIntegrations = Invoke-ReadQuery -Query "SELECT Id, Record_ID__c, Integration_Config_Name__c, Transaction_Status__c, HTTP_Status_Code__c, CreatedDate FROM Integration_Log__c WHERE Record_ID__c = '$recordIdSql' ORDER BY CreatedDate DESC LIMIT $Limit"
    Show-Rows -Heading 'Integration logs for exact record' -Rows @($recordIntegrations.records) -Columns @('Id','Record_ID__c','Integration_Config_Name__c','Transaction_Status__c','HTTP_Status_Code__c','CreatedDate')
}
