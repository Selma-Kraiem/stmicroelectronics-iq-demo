[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Live,
    [switch]$EnableWorkIq,
    [string]$EnvironmentName = 'st-iq-demo'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

if (-not (Test-Path '.venv')) {
    uv sync --all-groups
}

if ($Live) {
    azd env select $EnvironmentName --no-prompt | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Azure Developer CLI environment '$EnvironmentName' does not exist."
    }
    $values = azd env get-values -o json | ConvertFrom-Json
    foreach ($property in $values.PSObject.Properties) {
        [Environment]::SetEnvironmentVariable($property.Name, [string]$property.Value, 'Process')
    }
    if ($values.FABRIC_IQ_MCP_ENDPOINT) {
        $account = az account show | ConvertFrom-Json
        if (
            $LASTEXITCODE -ne 0 -or
            $account.tenantId -ne $values.AZURE_TENANT_ID -or
            -not $values.WORK_IQ_EXPECTED_USER_UPN -or
            $account.user.name -ne $values.WORK_IQ_EXPECTED_USER_UPN
        ) {
            throw (
                'Live Fabric IQ requires Azure CLI signed in as ' +
                "$($values.WORK_IQ_EXPECTED_USER_UPN) in the configured tenant."
            )
        }
        $env:FABRIC_IQ_ACCESS_TOKEN = az account get-access-token `
            --resource https://api.fabric.microsoft.com `
            --tenant $values.AZURE_TENANT_ID --query accessToken -o tsv
        if ($LASTEXITCODE -ne 0 -or -not $env:FABRIC_IQ_ACCESS_TOKEN) {
            throw 'Could not acquire the short-lived delegated Fabric IQ token.'
        }
    }
    $env:FOUNDRY_PROJECT_ENDPOINT = $values.AZURE_AI_PROJECT_ENDPOINT
    if ($EnableWorkIq) {
        if (-not $values.WORK_IQ_HOSTED_AGENT_ENDPOINT) {
            throw (
                'Work IQ live mode requires WORK_IQ_HOSTED_AGENT_ENDPOINT. Run ' +
                '.\scripts\deploy-agent.ps1 -AgentService st-iq-incident-agent-workiq ' +
                '-EnableWorkIq first.'
            )
        }
        $env:FOUNDRY_AGENT_ENDPOINT = $values.WORK_IQ_HOSTED_AGENT_ENDPOINT
    }
    elseif (-not $env:FOUNDRY_AGENT_ENDPOINT) {
        $env:FOUNDRY_AGENT_ENDPOINT = $values.HOSTED_AGENT_ENDPOINT
    }
    if (-not $EnableWorkIq) {
        Remove-Item Env:WORK_IQ_TOOLBOX_ENDPOINT -ErrorAction SilentlyContinue
        Remove-Item Env:WORK_IQ_TEAMS_TOOLBOX_ENDPOINT -ErrorAction SilentlyContinue
        Remove-Item Env:WORK_IQ_TEAMS_SEND_TOOL -ErrorAction SilentlyContinue
        Remove-Item Env:WORK_IQ_A2A_ENDPOINT -ErrorAction SilentlyContinue
        Remove-Item Env:WORK_IQ_ACCESS_TOKEN -ErrorAction SilentlyContinue
    }
    if (-not $env:FOUNDRY_AGENT_ENDPOINT) {
        throw 'Live mode requires FOUNDRY_AGENT_ENDPOINT. Run .\scripts\deploy-agent.ps1 first.'
    }
    $env:STIQ_LIVE_MODE = '1'
}
else {
    $env:STIQ_LIVE_MODE = '0'
}
if (-not $env:STIQ_ALLOW_TEAMS_SEND) {
    $env:STIQ_ALLOW_TEAMS_SEND = '0'
}
uv run uvicorn app.main:app --host 127.0.0.1 --port $Port
