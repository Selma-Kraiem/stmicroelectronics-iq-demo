[CmdletBinding()]
param(
    [string]$SubscriptionId = '00000000-0000-0000-0000-000000000000',
    [string]$TenantId = '11111111-1111-1111-1111-111111111111',
    [string]$ResourceGroup = 'rg-st-iq-demo',
    [string]$Location = 'swedencentral',
    [string]$EnvironmentName = 'st-iq-public-demo',
    [string]$Prefix = 'stiqdemo',
    [switch]$SkipSeed
)

$ErrorActionPreference = 'Stop'

az account set --subscription $SubscriptionId
if ($LASTEXITCODE -ne 0) {
    throw "Could not select target subscription '$SubscriptionId'."
}

foreach ($provider in @(
    'Microsoft.CognitiveServices',
    'Microsoft.Search',
    'Microsoft.ContainerRegistry',
    'Microsoft.App',
    'Microsoft.ManagedIdentity',
    'Microsoft.OperationalInsights',
    'Microsoft.Storage'
)) {
    $state = az provider show --subscription $SubscriptionId --namespace $provider `
        --query registrationState -o tsv
    if ($state -ne 'Registered') {
        az provider register --subscription $SubscriptionId --namespace $provider `
            --wait --only-show-errors
        if ($LASTEXITCODE -ne 0) {
            throw "Could not register provider '$provider'."
        }
    }
}

& "$PSScriptRoot\setup.ps1" -SubscriptionId $SubscriptionId -TenantId $TenantId `
    -ResourceGroup $ResourceGroup -Location $Location -EnvironmentName $EnvironmentName `
    -Prefix $Prefix -CreateResourceGroup -SkipSeed:$SkipSeed
