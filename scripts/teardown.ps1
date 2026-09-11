[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Confirmation,
    [string]$SubscriptionId = '00000000-0000-0000-0000-000000000000',
    [string]$ResourceGroup = 'rg-st-iq-demo',
    [string]$Prefix = 'stiqdemo'
)

$ErrorActionPreference = 'Stop'
$expected = 'DELETE stmicroelectronics-iq-demo'
if ($Confirmation -cne $expected) {
    throw "Refusing teardown. Pass -Confirmation '$expected'."
}

function ConvertFrom-JsonArray {
    param([string[]]$Json)

    $parsed = ($Json -join "`n") | ConvertFrom-Json
    foreach ($item in $parsed) {
        $item
    }
}

$allResourcesJson = az resource list --subscription $SubscriptionId `
    --resource-group $ResourceGroup -o json
$allResources = @(ConvertFrom-JsonArray -Json $allResourcesJson)
$storageSourceId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Storage/storageAccounts/${Prefix}data"
$systemTopicsJson = az eventgrid system-topic list --subscription $SubscriptionId `
    --resource-group $ResourceGroup -o json
$systemTopics = @(ConvertFrom-JsonArray -Json $systemTopicsJson)
$expectedSystemTopicIds = @($systemTopics | Where-Object {
    $_.source -ieq $storageSourceId
} | ForEach-Object { $_.id.ToLowerInvariant() })
$expectedGenerated = @($allResources | Where-Object {
    $resourceKey = "$($_.type)|$($_.name)"
    $isKnownChild = $resourceKey -in @(
        "Microsoft.CognitiveServices/accounts/projects|$Prefix-foundry/st-iq-demo",
        'microsoft.insights/actiongroups|Application Insights Smart Detection',
        "microsoft.alertsmanagement/smartDetectorAlertRules|Failure Anomalies - $Prefix-appinsights"
    )
    $isStorageSystemTopic = $_.type -ieq 'Microsoft.EventGrid/systemTopics' -and
        $_.id.ToLowerInvariant() -in $expectedSystemTopicIds
    $isKnownChild -or $isStorageSystemTopic
})
$scenarioResources = @($allResources | Where-Object {
    $_.tags.scenario -eq 'stmicroelectronics-iq-demo'
})
$resources = @($scenarioResources.id) + @($expectedGenerated.id)
if ($resources.Count -eq 0) {
    Write-Host 'No scenario-tagged resources found. The resource group was not deleted.'
    exit 0
}

$allowedIds = @($resources | ForEach-Object { $_.ToLowerInvariant() })
$foreign = @($allResources | Where-Object { $_.id.ToLowerInvariant() -notin $allowedIds })
if ($foreign.Count -gt 0) {
    throw "Refusing teardown because $($foreign.Count) resources in $ResourceGroup are not scenario-tagged."
}

Write-Host "Deleting $($resources.Count) scenario-tagged resources; resource group $ResourceGroup is preserved." -ForegroundColor Yellow
$ordered = $resources | Sort-Object Length -Descending
$failed = @()
foreach ($id in $ordered) {
    az resource delete --subscription $SubscriptionId --ids $id --only-show-errors
    if ($LASTEXITCODE -ne 0) {
        $failed += $id
    }
}
if ($failed.Count -gt 0) {
    throw "Teardown failed for $($failed.Count) resource(s): $($failed -join ', ')"
}
