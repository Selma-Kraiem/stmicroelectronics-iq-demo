[CmdletBinding()]
param(
    [string]$SubscriptionId = '00000000-0000-0000-0000-000000000000',
    [string]$TenantId = '11111111-1111-1111-1111-111111111111',
    [string]$ResourceGroup = 'rg-st-iq-demo',
    [string]$Location = 'swedencentral',
    [string]$EnvironmentName = 'st-iq-demo',
    [string]$Prefix = 'stiqdemo',
    [switch]$CreateResourceGroup,
    [switch]$SkipSeed
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

az account set --subscription $SubscriptionId
if ($LASTEXITCODE -ne 0) {
    throw "Could not select Azure subscription '$SubscriptionId'."
}
if ($CreateResourceGroup) {
    $existingGroup = az group show --subscription $SubscriptionId --name $ResourceGroup `
        --query location -o tsv 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $existingGroup) {
        az group create --subscription $SubscriptionId --name $ResourceGroup --location $Location `
            --tags scenario=stmicroelectronics-iq-demo customer=STMicroelectronics `
            managedBy=scripts dataClassification=synthetic-and-public --only-show-errors | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create resource group '$ResourceGroup'."
        }
    }
}

& "$PSScriptRoot\preflight.ps1" -SubscriptionId $SubscriptionId -TenantId $TenantId `
    -ResourceGroup $ResourceGroup -Location $Location -Prefix $Prefix
if ($LASTEXITCODE -ne 0) {
    throw 'Preflight failed. Infrastructure was not changed.'
}

$principalId = az ad signed-in-user show --query id -o tsv
$env:AZURE_PRINCIPAL_ID = $principalId
$deploymentName = "st-iq-{0}" -f (Get-Date -Format 'yyyyMMddHHmmss')

Write-Host "Deploying scenario-tagged resources to $ResourceGroup..." -ForegroundColor Cyan
$deployment = az deployment group create --subscription $SubscriptionId --resource-group $ResourceGroup `
    --name $deploymentName --template-file '.\infra\main.bicep' `
    --parameters '.\infra\main.bicepparam' "principalId=$principalId" `
    "prefix=$Prefix" "location=$Location" `
    --query '{outputs:properties.outputs,state:properties.provisioningState}' -o json | ConvertFrom-Json

if ($deployment.state -ne 'Succeeded') {
    throw "Infrastructure deployment ended in state '$($deployment.state)'."
}

$outputs = $deployment.outputs
$accountId = $outputs.FOUNDRY_ACCOUNT_ID.value
$projectId = $outputs.AZURE_AI_PROJECT_ID.value
$projectPrincipal = $outputs.PROJECT_MANAGED_IDENTITY_PRINCIPAL_ID.value
$searchPrincipal = $outputs.SEARCH_MANAGED_IDENTITY_PRINCIPAL_ID.value
$searchId = az search service show --subscription $SubscriptionId --resource-group $ResourceGroup `
    --name $outputs.AZURE_SEARCH_NAME.value --query id -o tsv
$registryId = az acr show --subscription $SubscriptionId --resource-group $ResourceGroup `
    --name $outputs.AZURE_CONTAINER_REGISTRY_NAME.value --query id -o tsv
$storageId = az storage account show --subscription $SubscriptionId --resource-group $ResourceGroup `
    --name $outputs.AZURE_STORAGE_ACCOUNT_NAME.value --query id -o tsv

function Ensure-Role {
    param(
        [string]$AssigneeObjectId,
        [string]$RoleName,
        [string]$RoleDefinitionId,
        [string]$Scope
    )
    $existing = az role assignment list --subscription $SubscriptionId --scope $Scope `
        --query "[?principalId=='$AssigneeObjectId' && contains(roleDefinitionId, '$RoleDefinitionId')] | [0].id" -o tsv
    if ($LASTEXITCODE -ne 0) {
        throw "Could not inspect $RoleName assignments on $Scope."
    }
    if (-not $existing) {
        az role assignment create --subscription $SubscriptionId --assignee-object-id $AssigneeObjectId `
            --assignee-principal-type ServicePrincipal --role $RoleDefinitionId --scope $Scope `
            --only-show-errors | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not assign $RoleName on $Scope."
        }
    }
    Write-Host "  ensured $RoleName on $Scope"
}

Write-Host 'Applying generated-identity RBAC...' -ForegroundColor Cyan
Ensure-Role $projectPrincipal 'Foundry User' '53ca6127-db72-4b80-b1b0-d745d6d5456d' $accountId
Ensure-Role $projectPrincipal 'Search Service Contributor' '7ca78c08-252a-4471-8644-bb5ff32d4ba0' $searchId
Ensure-Role $projectPrincipal 'Search Index Data Contributor' '8ebe5a00-799e-43f5-93ac-243d3dce84a7' $searchId
Ensure-Role $projectPrincipal 'Search Index Data Reader' '1407120a-92aa-4202-b7e9-c0e197c71c8f' $searchId
Ensure-Role $projectPrincipal 'Storage Blob Data Contributor' 'ba92f5b4-2d11-453d-a403-e96b0029c9fe' $storageId
Ensure-Role $projectPrincipal 'Container Registry Repository Reader' 'b93aa761-3e63-49ed-ac28-beffa264f7ac' $registryId
Ensure-Role $searchPrincipal 'Cognitive Services User' 'a97b65f3-24c7-4388-baec-2e87135dc908' $accountId

$selected = $false
azd env select $EnvironmentName --no-prompt 2>$null
if ($LASTEXITCODE -eq 0) {
    $selected = $true
}
if (-not $selected) {
    azd env new $EnvironmentName --subscription $SubscriptionId --location $Location --no-prompt
}

$envValues = @{
    AZURE_SUBSCRIPTION_ID = $SubscriptionId
    AZURE_TENANT_ID = $TenantId
    AZURE_RESOURCE_GROUP = $ResourceGroup
    AZURE_LOCATION = $Location
    AZURE_AI_PROJECT_ID = $projectId
    AZURE_AI_PROJECT_ENDPOINT = $outputs.AZURE_AI_PROJECT_ENDPOINT.value
    FOUNDRY_PROJECT_ENDPOINT = $outputs.AZURE_AI_PROJECT_ENDPOINT.value
    AZURE_OPENAI_ENDPOINT = $outputs.AZURE_OPENAI_ENDPOINT.value
    AZURE_AI_MODEL_DEPLOYMENT_NAME = 'gpt-5.4-mini'
    AZURE_SEARCH_ENDPOINT = $outputs.AZURE_SEARCH_ENDPOINT.value
    AZURE_SEARCH_NAME = $outputs.AZURE_SEARCH_NAME.value
    AZURE_CONTAINER_REGISTRY_NAME = $outputs.AZURE_CONTAINER_REGISTRY_NAME.value
    AZURE_CONTAINER_REGISTRY_ENDPOINT = $outputs.AZURE_CONTAINER_REGISTRY_ENDPOINT.value
    AZURE_STORAGE_ACCOUNT_NAME = $outputs.AZURE_STORAGE_ACCOUNT_NAME.value
    APPLICATIONINSIGHTS_RESOURCE_ID = $outputs.APPLICATIONINSIGHTS_RESOURCE_ID.value
    APPLICATIONINSIGHTS_NAME = "$Prefix-appinsights"
    LOG_ANALYTICS_NAME = $outputs.LOG_ANALYTICS_NAME.value
    FOUNDRY_ACCOUNT_ID = $outputs.FOUNDRY_ACCOUNT_ID.value
    FOUNDRY_ACCOUNT_NAME = $outputs.FOUNDRY_ACCOUNT_NAME.value
    FOUNDRY_PROJECT_NAME = $outputs.FOUNDRY_PROJECT_NAME.value
    RESOURCE_PREFIX = $Prefix
    CONTAINER_APPS_ENVIRONMENT_NAME = "$Prefix-web-env"
    AZURE_SEARCH_INDEX_NAME = 'st-iq-knowledge'
    KNOWLEDGE_SOURCE_NAME = 'st-iq-index-source'
    KNOWLEDGE_BASE_NAME = 'st-iq-knowledge-base'
    WEB_KNOWLEDGE_SOURCE_NAME = 'st-iq-web-source'
    WEB_KNOWLEDGE_BASE_NAME = 'st-iq-web-base'
}
foreach ($item in $envValues.GetEnumerator()) {
    azd env set $item.Key $item.Value | Out-Null
}
if (-not $SkipSeed) {
    & "$PSScriptRoot\seed-data.ps1"
}

Write-Host "`nInfrastructure is ready." -ForegroundColor Green
Write-Host "Foundry project: $($outputs.AZURE_AI_PROJECT_ENDPOINT.value)"
Write-Host "Search: $($outputs.AZURE_SEARCH_ENDPOINT.value)"
Write-Host 'Next: .\scripts\deploy-agent.ps1'
