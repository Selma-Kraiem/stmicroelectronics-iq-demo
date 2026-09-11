[CmdletBinding()]
param(
    [string]$EnvironmentName = 'st-iq-demo-v2',
    [switch]$Live,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot

if (-not $env:STIQ_V2_API_KEY) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    $env:STIQ_V2_API_KEY = [Convert]::ToBase64String($bytes)
}
if ($Live) {
    azd env select $EnvironmentName --no-prompt | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Azure Developer CLI environment '$EnvironmentName' does not exist."
    }
    $values = azd env get-values -o json | ConvertFrom-Json
    if (-not $values.FOUNDRY_V2_COMMANDER_ENDPOINT) {
        throw 'The live V2 Commander endpoint is not configured.'
    }
    $env:FOUNDRY_V2_COMMANDER_ENDPOINT = $values.FOUNDRY_V2_COMMANDER_ENDPOINT
}
else {
    Remove-Item Env:FOUNDRY_V2_COMMANDER_ENDPOINT -ErrorAction SilentlyContinue
}

Write-Host "Starting V2 Chat at http://127.0.0.1:$Port/v2/chat"
Write-Host "Starting V2 Tasks at http://127.0.0.1:$Port/v2/tasks"
& '.\.venv\Scripts\python.exe' -m uvicorn v2.main:app --host 127.0.0.1 --port $Port
