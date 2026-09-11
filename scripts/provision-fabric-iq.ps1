[CmdletBinding()]
param(
    [string]$SubscriptionId = '00000000-0000-0000-0000-000000000000',
    [string]$TenantId = '11111111-1111-1111-1111-111111111111',
    [string]$CapacityResourceGroup = 'rg-fabric-demo',
    [string]$CapacityName = 'fabric-demo-capacity',
    [string]$EnvironmentName = 'st-iq-public-demo',
    [string]$WorkspaceName = 'ST IQ Semiconductor Demo',
    [string]$ExpectedUserPrincipalName = 'presenter@contoso.onmicrosoft.com',
    [string]$ModelPath = '.\data\v1\fabric_iq\FabricIQ_Data_Model.md',
    [string]$OutputPath = '.foundry\results\fabric-iq-public-demo.json',
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$account = az account show --subscription $SubscriptionId -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) {
    throw "Cannot read Azure subscription '$SubscriptionId'."
}
if (
    $account.tenantId -ne $TenantId -or
    $account.user.name -ne $ExpectedUserPrincipalName
) {
    throw (
        "Fabric provisioning requires $ExpectedUserPrincipalName in " +
        "subscription $SubscriptionId."
    )
}
az account set --subscription $SubscriptionId
if ($LASTEXITCODE -ne 0) {
    throw "Cannot select Azure subscription '$SubscriptionId'."
}
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) {
    throw "Fabric ontology source file not found: $ModelPath"
}

$capacity = az resource show --subscription $SubscriptionId `
    --resource-group $CapacityResourceGroup --resource-type 'Microsoft.Fabric/capacities' `
    --name $CapacityName --api-version '2023-11-01' -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $capacity.properties.administration.members) {
    throw "Fabric capacity '$CapacityName' is unavailable or has no administrators."
}
if ($capacity.properties.state -ne 'Active') {
    throw "Fabric capacity '$CapacityName' must be Active; current state: $($capacity.properties.state)."
}

$capacityId = $capacity.properties.capacityId
if (-not $capacityId) {
    $fabricToken = az account get-access-token --resource https://api.fabric.microsoft.com `
        --tenant $TenantId --query accessToken -o tsv
    if ($LASTEXITCODE -ne 0 -or -not $fabricToken) {
        throw 'Cannot acquire a delegated Microsoft Fabric token.'
    }
    $fabricCapacity = Invoke-RestMethod -Method Get `
        -Uri "https://api.fabric.microsoft.com/v1/capacities" `
        -Headers @{ Authorization = 'Bear' + 'er ' + $fabricToken } |
        Select-Object -ExpandProperty value |
        Where-Object displayName -eq $CapacityName |
        Select-Object -First 1
    $capacityId = $fabricCapacity.id
}
if (-not $capacityId) {
    throw "Fabric capacity GUID for '$CapacityName' was not resolved."
}

Write-Host "Provisioning Fabric IQ on active capacity $CapacityName ($capacityId)..." `
    -ForegroundColor Cyan
$arguments = @(
    'run', '--extra', 'cloud', 'python', '.\scripts\provision_fabric_iq.py',
    '--tenant-id', $TenantId,
    '--capacity-id', $capacityId,
    '--workspace-name', $WorkspaceName,
    '--model-path', $ModelPath,
    '--output', $OutputPath
)
if ($VerifyOnly) {
    $arguments += '--skip-seed'
}
uv @arguments
if ($LASTEXITCODE -ne 0) {
    throw (
        "Fabric provisioning did not reach live ontology MCP readiness. " +
        "See $OutputPath for the exact blocker."
    )
}

$result = Get-Content -LiteralPath $OutputPath -Raw | ConvertFrom-Json
azd env select $EnvironmentName --no-prompt | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Azure Developer CLI environment '$EnvironmentName' does not exist."
}
$fabricValues = @{
    FABRIC_WORKSPACE_ID            = $result.workspace.id
    FABRIC_LAKEHOUSE_ITEM_ID       = $result.lakehouse.id
    FABRIC_ONTOLOGY_ITEM_ID        = $result.ontology.id
    FABRIC_IQ_MCP_ENDPOINT         = $result.ontologyMcpEndpoint
    FABRIC_IQ_TOOL_NAME            = $result.toolName
    FABRIC_IQ_TOOL_ARGUMENTS_JSON  = ($result.toolArguments | ConvertTo-Json -Compress)
}
foreach ($entry in $fabricValues.GetEnumerator()) {
    if (-not $entry.Value) {
        throw "Fabric live verification returned no value for '$($entry.Key)'."
    }
    azd env set $entry.Key ([string]$entry.Value) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not persist non-secret Fabric setting '$($entry.Key)' to azd."
    }
}

Write-Host "`nFabric IQ workspace, Lakehouse, Delta tables, and ontology are live." `
    -ForegroundColor Green
