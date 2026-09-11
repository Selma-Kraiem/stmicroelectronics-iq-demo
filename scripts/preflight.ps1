[CmdletBinding()]
param(
    [string]$SubscriptionId = '00000000-0000-0000-0000-000000000000',
    [string]$TenantId = '11111111-1111-1111-1111-111111111111',
    [string]$ResourceGroup = 'rg-st-iq-demo',
    [string]$Location = 'swedencentral',
    [string]$Prefix = 'stiqdemo'
)

$ErrorActionPreference = 'Stop'
$script:Failures = 0

function Write-Check {
    param(
        [ValidateSet('PASS', 'WARN', 'FAIL')]
        [string]$Status,
        [string]$Name,
        [string]$Detail
    )
    $color = switch ($Status) {
        'PASS' { 'Green' }
        'WARN' { 'Yellow' }
        'FAIL' { 'Red' }
    }
    Write-Host "[$Status] $Name - $Detail" -ForegroundColor $color
    if ($Status -eq 'FAIL') {
        $script:Failures++
    }
}

function ConvertFrom-JsonArray {
    param([string[]]$Json)

    $parsed = ($Json -join "`n") | ConvertFrom-Json
    foreach ($item in $parsed) {
        $item
    }
}

Write-Host 'STMicroelectronics IQ demo preflight' -ForegroundColor Cyan
Write-Host 'No resources are changed by this command.'

foreach ($command in @('az', 'azd', 'uv', 'git')) {
    if (Get-Command $command -ErrorAction SilentlyContinue) {
        Write-Check PASS "Tool: $command" 'available'
    }
    else {
        Write-Check FAIL "Tool: $command" 'not found on PATH'
    }
}

if ($script:Failures -gt 0) {
    exit 1
}

$account = az account show --subscription $SubscriptionId -o json | ConvertFrom-Json
if ($account.state -eq 'Enabled' -and $account.tenantId -eq $TenantId) {
    Write-Check PASS 'Azure account' "$($account.name) / $($account.user.name)"
}
else {
    Write-Check FAIL 'Azure account' 'subscription or tenant does not match the fixed demo scope'
}

$userId = az ad signed-in-user show --query id -o tsv
$owner = az role assignment list --subscription $SubscriptionId --assignee $userId --all `
    --query "[?roleDefinitionName=='Owner'] | [0].roleDefinitionName" -o tsv
if ($owner -eq 'Owner') {
    Write-Check PASS 'Subscription authorization' 'current user has an effective Owner assignment'
}
else {
    Write-Check FAIL 'Subscription authorization' 'Owner is required to provision RBAC and demo resources'
}

$group = az group show --subscription $SubscriptionId --name $ResourceGroup -o json | ConvertFrom-Json
if ($group.location -eq $Location) {
    Write-Check PASS 'Resource group' "$ResourceGroup exists in $Location"
}
else {
    Write-Check FAIL 'Resource group' "$ResourceGroup is in $($group.location), expected $Location"
}

$existingJson = az resource list --subscription $SubscriptionId --resource-group $ResourceGroup -o json
$existing = @(ConvertFrom-JsonArray -Json $existingJson)
$storageSourceId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.Storage/storageAccounts/${Prefix}data"
$systemTopicsJson = az eventgrid system-topic list --subscription $SubscriptionId `
    --resource-group $ResourceGroup -o json
$systemTopics = @(ConvertFrom-JsonArray -Json $systemTopicsJson)
$expectedSystemTopicIds = @($systemTopics | Where-Object {
    $_.source -ieq $storageSourceId
} | ForEach-Object { $_.id.ToLowerInvariant() })
$expectedPlatformResources = @(
    "Microsoft.CognitiveServices/accounts/projects|$Prefix-foundry/st-iq-demo",
    'microsoft.insights/actiongroups|Application Insights Smart Detection',
    "microsoft.alertsmanagement/smartDetectorAlertRules|Failure Anomalies - $Prefix-appinsights"
)
$foreign = @($existing | Where-Object {
    $resourceKey = "$($_.type)|$($_.name)"
    $isStorageSystemTopic = $_.type -ieq 'Microsoft.EventGrid/systemTopics' -and
        $_.id.ToLowerInvariant() -in $expectedSystemTopicIds
    $_.tags.scenario -ne 'stmicroelectronics-iq-demo' -and
    $resourceKey -notin $expectedPlatformResources -and
    -not $isStorageSystemTopic
})
if ($foreign.Count -eq 0) {
    Write-Check PASS 'Deployment scope' "$($existing.Count) existing resources; all are empty or scenario-tagged"
}
else {
    Write-Check FAIL 'Deployment scope' "$($foreign.Count) untagged or foreign resources exist in $ResourceGroup"
}

foreach ($provider in @(
    'Microsoft.CognitiveServices',
    'Microsoft.Search',
    'Microsoft.ContainerRegistry',
    'Microsoft.App',
    'Microsoft.ManagedIdentity'
)) {
    $state = az provider show --subscription $SubscriptionId --namespace $provider --query registrationState -o tsv
    if ($state -eq 'Registered') {
        Write-Check PASS "Provider: $provider" 'registered'
    }
    else {
        Write-Check FAIL "Provider: $provider" "state is $state"
    }
}

$quotaQuery = "{model:[?name.value=='OpenAI.GlobalStandard.gpt-5.4-mini'] | [0], embedding:[?name.value=='OpenAI.GlobalStandard.text-embedding-3-small'] | [0]}"
$quotaJson = az cognitiveservices usage list --subscription $SubscriptionId --location $Location `
    --query $quotaQuery -o json 2>$null
if ($LASTEXITCODE -eq 0) {
    $quota = $quotaJson | ConvertFrom-Json
}
else {
    $quota = $null
    Write-Check FAIL 'Foundry quota query' 'Azure CLI could not read regional model quota'
}

$modelAvailable = if ($quota -and $quota.model) {
    [double]$quota.model.limit - [double]$quota.model.currentValue
}
$embeddingAvailable = if ($quota -and $quota.embedding) {
    [double]$quota.embedding.limit - [double]$quota.embedding.currentValue
}
if ($null -ne $modelAvailable -and $modelAvailable -ge 10) {
    Write-Check PASS 'gpt-5.4-mini quota' "$modelAvailable capacity units available"
}
else {
    Write-Check FAIL 'gpt-5.4-mini quota' 'at least 10 GlobalStandard capacity units are required'
}
if ($null -ne $embeddingAvailable -and $embeddingAvailable -ge 10) {
    Write-Check PASS 'Embedding quota' "$embeddingAvailable capacity units available"
}
else {
    Write-Check FAIL 'Embedding quota' 'at least 10 GlobalStandard capacity units are required'
}

$webFeature = az feature show --subscription $SubscriptionId --namespace Microsoft.Search `
    --name WebKnowledgeSourceDisabled --query properties.state -o tsv 2>$null
if ($webFeature -eq 'Registered') {
    Write-Check WARN 'Web Knowledge Source standby fallback' `
        'disabled by subscription feature WebKnowledgeSourceDisabled; Web IQ is the primary live source'
}
else {
    Write-Check PASS 'Web Knowledge Source standby fallback' 'subscription access is not disabled'
}

$webIqConnectionId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.CognitiveServices/accounts/$Prefix-foundry/projects/st-iq-demo/connections/st-iq-webiq-mcp"
$webIqConnection = az rest --method get `
    --url "https://management.azure.com${webIqConnectionId}?api-version=2026-05-01" `
    --query "properties.{authType:authType,category:category,target:target}" -o json 2>$null
if ($LASTEXITCODE -eq 0) {
    $webIqConnection = $webIqConnection | ConvertFrom-Json
}
else {
    $webIqConnection = $null
}
if (
    $webIqConnection -and
    $webIqConnection.authType -eq 'CustomKeys' -and
    $webIqConnection.category -eq 'RemoteTool' -and
    $webIqConnection.target -eq 'https://api.microsoft.ai/v3/mcp'
) {
    Write-Check PASS 'Web IQ MCP' 'secure Foundry project connection is configured'
}
else {
    Write-Check WARN 'Web IQ MCP' 'run setup-webiq.ps1 with an authorized API key before deploying the agent'
}

Write-Check PASS 'Demo scope' `
    'Fabric IQ is excluded; Work IQ requires a separate delegated-user readiness check'
$sharePointRoot = az rest --method get `
    --url 'https://graph.microsoft.com/v1.0/sites/contoso.sharepoint.com:/' `
    --query 'id' -o tsv 2>$null
if ($sharePointRoot) {
    Write-Check WARN 'SharePoint Knowledge' `
        'tenant root is reachable; configure the permission-trimmed remote SharePoint source with setup-sharepoint-foundry-iq.ps1'
}
else {
    Write-Check WARN 'SharePoint Knowledge' `
        'delegated Graph access or an approved populated site is required for optional synchronization'
}

if ($script:Failures -gt 0) {
    Write-Host "`nPreflight failed with $script:Failures blocking issue(s)." -ForegroundColor Red
    exit 1
}

Write-Host "`nCore Azure preflight passed. WARN items are optional integration prerequisites." -ForegroundColor Green
exit 0
