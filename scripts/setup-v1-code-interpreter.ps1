[CmdletBinding()]
param(
    [string]$EnvironmentName = 'st-iq-public-demo',
    [switch]$EnableToolbox
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

azd env select $EnvironmentName --no-prompt | Out-Null
$values = azd env get-values -o json | ConvertFrom-Json
$account = az account show -o json | ConvertFrom-Json

if ($account.id -ne $values.AZURE_SUBSCRIPTION_ID) {
    throw "Expected subscription $($values.AZURE_SUBSCRIPTION_ID), got $($account.id)."
}
if (
    $values.WORK_IQ_EXPECTED_USER_UPN -and
    $account.user.name -ine $values.WORK_IQ_EXPECTED_USER_UPN
) {
    throw "Expected $($values.WORK_IQ_EXPECTED_USER_UPN), got $($account.user.name)."
}

$endpoint = $values.AZURE_AI_PROJECT_ENDPOINT
if (-not $endpoint) {
    $endpoint = $values.FOUNDRY_PROJECT_ENDPOINT
}
if (-not $endpoint) {
    throw 'The selected azd environment has no Foundry project endpoint.'
}

$env:AZURE_AI_PROJECT_ENDPOINT = $endpoint
$result = uv run --with 'azure-ai-projects==2.3.0' --with 'azure-identity>=1.17,<2' `
    python scripts\setup-v1-code-interpreter.py | Select-Object -Last 1 | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $result.endpoint) {
    throw 'Code Interpreter workbook upload or toolbox creation failed.'
}

azd env set FAB_CODE_INTERPRETER_FILE_IDS ($result.file_ids -join ',') | Out-Null
if ($EnableToolbox) {
    azd env set CODE_INTERPRETER_TOOLBOX_ENDPOINT $result.endpoint | Out-Null
}

Write-Host "Workbook: $($result.file_name)" -ForegroundColor Green
Write-Host "SHA-256: $($result.sha256)"
Write-Host "Toolbox: $($result.toolbox) version $($result.version)"
Write-Host "Endpoint: $($result.endpoint)"
if (-not $EnableToolbox) {
    Write-Warning (
        'The toolbox was not enabled for deployment. First validate file ownership by invoking ' +
        'it from the Hosted Agent, then rerun with -EnableToolbox.'
    )
}
