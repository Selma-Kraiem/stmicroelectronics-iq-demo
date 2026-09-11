[CmdletBinding()]
param(
    [string]$SubscriptionId = '00000000-0000-0000-0000-000000000000',
    [string]$ResourceGroup = 'rg-st-iq-demo',
    [string]$EnvironmentName = 'st-iq-demo-v2',
    [Parameter(Mandatory)][string]$Confirmation
)

$ErrorActionPreference = 'Stop'
if ($Confirmation -ne 'DELETE st-iq-demo-v2') {
    throw "Refusing teardown. Pass -Confirmation 'DELETE st-iq-demo-v2'."
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot
. "$PSScriptRoot\common.ps1"

azd env select $EnvironmentName --no-prompt | Out-Null
Assert-NativeSuccess "Selecting V2 environment '$EnvironmentName'"
$values = azd env get-values -o json | ConvertFrom-Json
$searchToken = Get-AzureAccessToken 'https://search.azure.com'
$searchHeaders = @{ Authorization = "Bearer $searchToken" }
$searchEndpoint = $values.AZURE_SEARCH_ENDPOINT.TrimEnd('/')

foreach ($resource in @(
    @{ Kind = 'knowledgebases'; Name = 'st-iq-v2-knowledge-base' },
    @{ Kind = 'knowledgebases'; Name = 'st-iq-v2-web-base' },
    @{ Kind = 'knowledgesources'; Name = 'st-iq-v2-document-source' },
    @{ Kind = 'knowledgesources'; Name = 'st-iq-v2-web-source' },
    @{ Kind = 'indexes'; Name = 'st-iq-v2-documents' }
)) {
    $uri = "$searchEndpoint/$($resource.Kind)/$($resource.Name)?api-version=2026-05-01-preview"
    try {
        Invoke-RestMethod -Method Delete -Uri $uri -Headers $searchHeaders -TimeoutSec 120
        Write-Host "Deleted Search $($resource.Kind)/$($resource.Name)"
    }
    catch {
        if ($_.Exception.Response.StatusCode.value__ -ne 404) {
            throw
        }
    }
}

$app = az containerapp show --subscription $SubscriptionId --resource-group $ResourceGroup `
    --name 'st-iq-commander-v2' --query '{id:id,principalId:identity.userAssignedIdentities}' `
    -o json 2>$null | ConvertFrom-Json
$identityId = "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/Microsoft.ManagedIdentity/userAssignedIdentities/st-iq-commander-v2-identity"
$identityPrincipal = az identity show --subscription $SubscriptionId --resource-group $ResourceGroup `
    --name 'st-iq-commander-v2-identity' --query principalId -o tsv 2>$null
if ($identityPrincipal) {
    az role assignment delete --subscription $SubscriptionId `
        --assignee-object-id $identityPrincipal --only-show-errors
}
if ($app.id) {
    az resource delete --subscription $SubscriptionId --ids $app.id --only-show-errors
    Assert-NativeSuccess 'Deleting the V2 Container App'
}
az resource show --subscription $SubscriptionId --ids $identityId -o none 2>$null
if ($LASTEXITCODE -eq 0) {
    az resource delete --subscription $SubscriptionId --ids $identityId --only-show-errors
    Assert-NativeSuccess 'Deleting the V2 presenter identity'
}

$projectPrincipal = az resource show --subscription $SubscriptionId `
    --ids $values.AZURE_AI_PROJECT_ID --api-version 2025-06-01 `
    --query identity.principalId -o tsv 2>$null
if ($projectPrincipal) {
    az role assignment delete --subscription $SubscriptionId `
        --assignee-object-id $projectPrincipal --only-show-errors
}
az resource show --subscription $SubscriptionId --ids $values.AZURE_AI_PROJECT_ID `
    --api-version 2025-06-01 -o none 2>$null
if ($LASTEXITCODE -eq 0) {
    az resource delete --subscription $SubscriptionId --ids $values.AZURE_AI_PROJECT_ID `
        --api-version 2025-06-01 --only-show-errors
    Assert-NativeSuccess 'Deleting the isolated V2 Foundry project'
}

foreach ($repository in @('apps/st-iq-v2', 'agents/st-iq-v2')) {
    az acr repository show --name $values.AZURE_CONTAINER_REGISTRY_NAME `
        --repository $repository -o none 2>$null
    if ($LASTEXITCODE -eq 0) {
        az acr repository delete --name $values.AZURE_CONTAINER_REGISTRY_NAME `
            --repository $repository --yes --only-show-errors
        Assert-NativeSuccess "Deleting ACR repository $repository"
    }
}

Write-Host 'Deleted only V2 project, presenter/API, Search objects, and V2 image repositories.' `
    -ForegroundColor Green
