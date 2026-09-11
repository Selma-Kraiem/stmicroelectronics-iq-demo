[CmdletBinding()]
param(
    [string]$SubscriptionId = '00000000-0000-0000-0000-000000000000',
    [string]$TenantId = '11111111-1111-1111-1111-111111111111',
    [string]$ResourceGroup = 'rg-st-iq-demo',
    [string]$Location = 'swedencentral',
    [string]$EnvironmentName = 'st-iq-demo-v2',
    [string]$BaseEnvironmentName = 'st-iq-demo',
    [switch]$SkipBuild,
    [switch]$SkipSeed,
    [string]$Image
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot
. "$PSScriptRoot\common.ps1"

& "$repoRoot\scripts\preflight.ps1" -SubscriptionId $SubscriptionId -TenantId $TenantId `
    -ResourceGroup $ResourceGroup -Location $Location
if ($LASTEXITCODE -ne 0) {
    throw 'Preflight failed. V2 infrastructure was not changed.'
}

azd env select $BaseEnvironmentName --no-prompt | Out-Null
Assert-NativeSuccess "Selecting base environment '$BaseEnvironmentName'"
$base = azd env get-values -o json | ConvertFrom-Json
$principalId = az ad signed-in-user show --query id -o tsv
Assert-NativeSuccess 'Resolving the signed-in user'

$registryId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.ContainerRegistry/registries/$($base.AZURE_CONTAINER_REGISTRY_NAME)"
if (-not $SkipBuild) {
    $tag = Get-Date -Format 'yyyyMMddHHmmss'
    Write-Host "Building immutable V2 presenter/API image..." -ForegroundColor Cyan
    $Image = New-V2AcrImage -RegistryId $registryId -Repository 'apps/st-iq-v2' `
        -Tag $tag -Dockerfile 'v2/Dockerfile'
}
if (-not $Image -or $Image -notmatch '@sha256:[0-9a-f]{64}$') {
    throw 'V2 setup requires an immutable ACR image digest.'
}

$apiKeyBytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Fill($apiKeyBytes)
$apiKey = [Convert]::ToBase64String($apiKeyBytes)
$parameterFile = Join-Path ([IO.Path]::GetTempPath()) "st-iq-v2-$([guid]::NewGuid()).json"
try {
    @{
        '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
        contentVersion = '1.0.0.0'
        parameters = @{
            location = @{ value = $Location }
            containerImage = @{ value = $Image }
            operationalApiKey = @{ value = $apiKey }
            principalId = @{ value = $principalId }
        }
    } | ConvertTo-Json -Depth 8 | Set-Content -Path $parameterFile -Encoding utf8

    Write-Host "Deploying isolated V2 resources to $ResourceGroup..." -ForegroundColor Cyan
    $deployment = az deployment group create --subscription $SubscriptionId `
        --resource-group $ResourceGroup --name "st-iq-v2-$(Get-Date -Format 'yyyyMMddHHmmss')" `
        --template-file '.\infra\v2.bicep' --parameters "@$parameterFile" `
        --query '{outputs:properties.outputs,state:properties.provisioningState}' -o json |
        ConvertFrom-Json
    Assert-NativeSuccess 'Deploying V2 infrastructure'
}
finally {
    if (Test-Path $parameterFile) {
        Remove-Item $parameterFile -Force
    }
}
if ($deployment.state -ne 'Succeeded') {
    throw "V2 infrastructure deployment ended in '$($deployment.state)'."
}

azd env select $EnvironmentName --no-prompt 2>$null
if ($LASTEXITCODE -ne 0) {
    azd env new $EnvironmentName --subscription $SubscriptionId --location $Location --no-prompt
    Assert-NativeSuccess "Creating V2 environment '$EnvironmentName'"
}

$outputs = $deployment.outputs
$envValues = @{
    AZURE_SUBSCRIPTION_ID = $SubscriptionId
    AZURE_TENANT_ID = $TenantId
    AZURE_RESOURCE_GROUP = $ResourceGroup
    AZURE_LOCATION = $Location
    AZURE_AI_PROJECT_ID = $outputs.FOUNDRY_V2_PROJECT_ID.value
    AZURE_AI_PROJECT_ENDPOINT = $outputs.FOUNDRY_V2_PROJECT_ENDPOINT.value
    FOUNDRY_PROJECT_ENDPOINT = $outputs.FOUNDRY_V2_PROJECT_ENDPOINT.value
    AZURE_OPENAI_ENDPOINT = $base.AZURE_OPENAI_ENDPOINT
    AZURE_AI_MODEL_DEPLOYMENT_NAME = $base.AZURE_AI_MODEL_DEPLOYMENT_NAME
    AZURE_SEARCH_ENDPOINT = $outputs.V2_SEARCH_ENDPOINT.value
    AZURE_CONTAINER_REGISTRY_NAME = $base.AZURE_CONTAINER_REGISTRY_NAME
    AZURE_CONTAINER_REGISTRY_ENDPOINT = $base.AZURE_CONTAINER_REGISTRY_ENDPOINT
    FOUNDRY_ACCOUNT_ID = $base.FOUNDRY_ACCOUNT_ID
    APPLICATIONINSIGHTS_RESOURCE_ID = $base.APPLICATIONINSIGHTS_RESOURCE_ID
    V2_APP_URL = $outputs.V2_APP_URL.value
    V2_APP_IMAGE = $Image
    V2_OPERATIONAL_CONNECTION_ID = $outputs.V2_OPERATIONAL_CONNECTION_ID.value
    V2_SEARCH_INDEX_NAME = 'st-iq-v2-documents'
    V2_KNOWLEDGE_SOURCE_NAME = 'st-iq-v2-document-source'
    V2_KNOWLEDGE_BASE_NAME = 'st-iq-v2-knowledge-base'
    V2_WEB_SOURCE_NAME = 'st-iq-v2-web-source'
    V2_WEB_BASE_NAME = 'st-iq-v2-web-base'
}
foreach ($item in $envValues.GetEnumerator()) {
    azd env set $item.Key $item.Value | Out-Null
}

if (-not $SkipSeed) {
    foreach ($item in $envValues.GetEnumerator()) {
        Set-Item -Path "Env:$($item.Key)" -Value $item.Value
    }
    & '.\.venv\Scripts\python.exe' '.\scripts\v2\seed-search.py'
    Assert-NativeSuccess 'Seeding V2 Foundry IQ sources'
}

$url = $outputs.V2_APP_URL.value
Write-Host "Waiting for $url/health..." -ForegroundColor Cyan
$health = $null
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    try {
        $health = Invoke-RestMethod "$url/health" -TimeoutSec 10
        if ($health.status -eq 'ok') {
            break
        }
    }
    catch {
        Start-Sleep -Seconds 5
    }
}
if (-not $health -or $health.status -ne 'ok') {
    throw 'The V2 presenter/API Container App did not become healthy.'
}

$telemetry = Invoke-RestMethod `
    "$url/operational/telemetry/api/v2/telemetry/lots/CAT-26-0813-A" `
    -Headers @{ 'X-STIQ-API-Key' = $apiKey; 'X-Correlation-ID' = 'setup-v2' }
if ($telemetry.provenance -ne 'deterministic synthetic data') {
    throw 'The authenticated Manufacturing Telemetry API contract did not validate.'
}
$apiKey = $null

Write-Host "`nV2 infrastructure, document-only Foundry IQ, and operational APIs are ready." `
    -ForegroundColor Green
Write-Host "Presenter Chat: $url/v2/chat"
Write-Host "Presenter Tasks: $url/v2/tasks"
Write-Host "Foundry project: $($outputs.FOUNDRY_V2_PROJECT_ENDPOINT.value)"
Write-Host 'Next: .\scripts\v2\deploy-agents.ps1'
