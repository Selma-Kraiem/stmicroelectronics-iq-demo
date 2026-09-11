[CmdletBinding()]
param(
    [string]$EnvironmentName = 'st-iq-demo',
    [SecureString]$ApiKey
)

$ErrorActionPreference = 'Stop'
$connectionName = 'st-iq-webiq-mcp'
$mcpEndpoint = 'https://api.microsoft.ai/v3/mcp'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

azd env select $EnvironmentName --no-prompt | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Azure Developer CLI environment '$EnvironmentName' does not exist. Run .\scripts\setup.ps1 first."
}
$values = azd env get-values -o json | ConvertFrom-Json
foreach ($required in @('FOUNDRY_ACCOUNT_ID', 'AZURE_AI_PROJECT_ENDPOINT')) {
    if (-not $values.$required) {
        throw "Missing azd environment value '$required'. Run .\scripts\setup.ps1 first."
    }
}

if (-not $ApiKey) {
    $ApiKey = Read-Host 'Web IQ API key' -AsSecureString
}
if ($ApiKey.Length -eq 0) {
    throw 'A non-empty Web IQ API key is required.'
}

$projectName = $values.AZURE_AI_PROJECT_ENDPOINT.TrimEnd('/').Split('/')[-1]
$connectionId = "$($values.FOUNDRY_ACCOUNT_ID)/projects/$projectName/connections/$connectionName"
$armToken = az account get-access-token --resource https://management.azure.com/ `
    --query accessToken -o tsv
if ($LASTEXITCODE -ne 0 -or -not $armToken) {
    throw 'Azure CLI could not acquire an ARM access token.'
}

$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($ApiKey)
try {
    $plainTextKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $body = @{
        properties = @{
            authType = 'CustomKeys'
            category = 'RemoteTool'
            isSharedToAll = $true
            target = $mcpEndpoint
            credentials = @{
                keys = @{
                    'x-apikey' = $plainTextKey
                }
            }
            metadata = @{
                ApiType = 'Azure'
            }
        }
    } | ConvertTo-Json -Depth 8 -Compress

    $connection = Invoke-RestMethod `
        -Uri "https://management.azure.com${connectionId}?api-version=2026-05-01" `
        -Method Put `
        -Headers @{ Authorization = "Bearer $armToken" } `
        -ContentType 'application/json' `
        -Body $body `
        -TimeoutSec 120
}
finally {
    $plainTextKey = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
}

if (
    $connection.properties.authType -ne 'CustomKeys' -or
    $connection.properties.category -ne 'RemoteTool' -or
    $connection.properties.target -ne $mcpEndpoint
) {
    throw "Foundry connection '$connectionName' was created with an unexpected contract."
}

Write-Host "Configured secure Foundry connection '$connectionName' for Web IQ." -ForegroundColor Green
Write-Host 'The API key was not written to the repository, azd environment, or console.'
