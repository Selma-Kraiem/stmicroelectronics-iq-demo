[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$values = azd env get-values -o json | ConvertFrom-Json
foreach ($name in @(
    'AZURE_SEARCH_ENDPOINT',
    'AZURE_OPENAI_ENDPOINT',
    'AZURE_AI_MODEL_DEPLOYMENT_NAME',
    'AZURE_TENANT_ID'
)) {
    if (-not $values.$name) {
        throw "Missing azd environment value '$name'. Run .\scripts\setup.ps1 first."
    }
    [Environment]::SetEnvironmentVariable($name, $values.$name, 'Process')
}

foreach ($name in @(
    'AZURE_SEARCH_INDEX_NAME',
    'KNOWLEDGE_SOURCE_NAME',
    'KNOWLEDGE_BASE_NAME',
    'WEB_KNOWLEDGE_SOURCE_NAME',
    'WEB_KNOWLEDGE_BASE_NAME'
)) {
    if ($values.$name) {
        [Environment]::SetEnvironmentVariable($name, $values.$name, 'Process')
    }
}


uv run --with azure-identity --with requests python scripts\seed-search.py
if ($LASTEXITCODE -ne 0) {
    throw 'Search and Foundry IQ data seeding failed.'
}
