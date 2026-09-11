[CmdletBinding()]
param(
    [string]$EnvironmentName = 'st-iq-demo-v2',
    [int]$DelaySeconds = 10
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot
. "$PSScriptRoot\common.ps1"

azd env select $EnvironmentName --no-prompt | Out-Null
Assert-NativeSuccess "Selecting V2 environment '$EnvironmentName'"
$values = azd env get-values -o json | ConvertFrom-Json
foreach ($required in @(
    'AZURE_AI_PROJECT_ENDPOINT',
    'FOUNDRY_V2_COMMANDER_ENDPOINT',
    'V2_MARKET_AGENT_VERSION',
    'V2_QUALITY_AGENT_VERSION',
    'V2_COMMANDER_AGENT_VERSION'
)) {
    if (-not $values.$required) {
        throw "Missing azd value '$required'. Run .\scripts\v2\deploy-agents.ps1 first."
    }
}

$token = Get-AzureAccessToken 'https://ai.azure.com'
$projectEndpoint = $values.AZURE_AI_PROJECT_ENDPOINT.TrimEnd('/')

function Invoke-EvaluationCase {
    param(
        [Parameter(Mandatory)][string]$AgentName,
        [Parameter(Mandatory)][string]$Query,
        [Parameter(Mandatory)][hashtable]$Checks,
        [hashtable]$Reject = @{}
    )
    $endpoint = "$projectEndpoint/agents/$AgentName/endpoint/protocols/openai/responses?api-version=v1"
    $response = Invoke-AzureJson -Method Post -Uri $endpoint -Token $token `
        -Body @{ input = $Query }
    $message = @($response.output | Where-Object type -eq 'message')[-1]
    $text = [string]$message.content[0].text
    $results = [ordered]@{
        completed = $response.status -eq 'completed' -and -not [string]::IsNullOrWhiteSpace($text)
    }
    foreach ($check in $Checks.GetEnumerator()) {
        $results[$check.Key] = $text -match $check.Value
    }
    foreach ($check in $Reject.GetEnumerator()) {
        $results["reject_$($check.Key)"] = $text -notmatch $check.Value
    }
    $passed = @($results.Values | Where-Object { -not $_ }).Count -eq 0
    return [ordered]@{
        agent = $AgentName
        response_id = $response.id
        checks = $results
        passed = $passed
        response_excerpt = $text.Substring(0, [Math]::Min(800, $text.Length))
    }
}

$cases = @()
$cases += Invoke-EvaluationCase -AgentName 'st-iq-market-v2' -Query @'
Retrieve current public automotive silicon-carbide market and logistics context. Use only
sanitized public queries, identify the source as Web Knowledge Source (Web IQ fallback),
and return the required JSON contract with citations.
'@ -Checks @{
    source_label = 'Web Knowledge Source \(Web IQ fallback\)'
    citations = '"citations"\s*:'
}
Start-Sleep -Seconds $DelaySeconds
$cases += Invoke-EvaluationCase -AgentName 'st-iq-quality-v2' -Query @'
For synthetic lot CAT-26-0813-A, retrieve the containment procedure, manufacturing
telemetry anomalies, affected fictional orders, and inventory coverage. Use both structured
APIs where relevant and return the required JSON contract.
'@ -Checks @{
    synthetic_label = '(?i)synthetic'
    telemetry_value = '"value"\s*:\s*9\.59'
    telemetry_anomaly = '"anomaly_count"\s*:\s*1'
    exposure_units = '"affected_units"\s*:\s*300'
    reallocation = '"available_reallocation"\s*:\s*490'
    procedure = '(?i)QMS-017|SCM-042'
    citations = '"citations"\s*:'
} -Reject @{
    failed_tool = '"status"\s*:\s*"failed"'
}
Start-Sleep -Seconds $DelaySeconds
$cases += Invoke-EvaluationCase -AgentName 'st-iq-commander-v2' -Query @'
MODE=TASK
run_id=evaluation-v2
incident_id=INC-SIC-0813
correlation_id=evaluation-v2
OBJECTIVE=Assess current public SiC signals and synthetic operational exposure for lot CAT-26-0813-A. Separate facts, hypotheses, and missing information. Return citations and block Teams sending.
'@ -Checks @{
    completed = '(?s)^\s*\{.{0,320}"status"\s*:\s*"completed"'
    complete = '(?s)^\s*\{.{0,420}"complete"\s*:\s*true'
    market_branch = '"agent"\s*:\s*"market"'
    quality_branch = '"agent"\s*:\s*"quality"'
    telemetry_value = '9\.59'
    exposure_units = '"affected_units"\s*:\s*300'
    procedure = '(?i)QMS-017|SCM-042'
    citations = '"citations"\s*:'
    teams_blocked = '"send_allowed"\s*:\s*false'
    identifiers = '"incident_id"\s*:\s*"INC-SIC-0813"'
}

$passed = @($cases | Where-Object passed).Count
$storageNetwork = az storage account show --subscription $values.AZURE_SUBSCRIPTION_ID `
    --resource-group $values.AZURE_RESOURCE_GROUP --name 'stiqdemodata' `
    --query publicNetworkAccess -o tsv
Assert-NativeSuccess 'Inspecting evaluation storage policy'
$cloudBatch = if ($storageNetwork -eq 'Disabled') {
    [ordered]@{
        status = 'blocked'
        reason = (
            'MCAPSGovDeployPolicies/StorageAccount_PublicNetwork_Modify forces public network ' +
            'access off and no approved Foundry managed private evaluation path is configured.'
        )
        required_admin_action = (
            'Grant a scoped policy exemption for stiqdemodata or provision the approved ' +
            'Foundry managed-network/private-endpoint evaluation pattern.'
        )
    }
}
else {
    [ordered]@{
        status = 'ready-for-managed-batch'
        reason = 'Storage network policy no longer blocks Foundry batch evaluation.'
        required_admin_action = 'Run the evaluation suites declared in agent-metadata.yaml.'
    }
}

$result = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    project = 'st-iq-demo-v2'
    versions = [ordered]@{
        market = $values.V2_MARKET_AGENT_VERSION
        quality = $values.V2_QUALITY_AGENT_VERSION
        commander = $values.V2_COMMANDER_AGENT_VERSION
    }
    live_contract_evaluation = [ordered]@{
        passed = $passed
        total = $cases.Count
        cases = $cases
    }
    managed_batch_evaluation = $cloudBatch
}
$resultsDirectory = '.\v2\agents\.foundry\results'
New-Item -ItemType Directory -Path $resultsDirectory -Force | Out-Null
$resultPath = Join-Path $resultsDirectory "v2-live-eval-$(Get-Date -Format yyyyMMddHHmmss).json"
$result | ConvertTo-Json -Depth 16 | Set-Content $resultPath -Encoding utf8

Write-Host "`nV2 live contract evaluation: $passed/$($cases.Count) passed." `
    -ForegroundColor $(if ($passed -eq $cases.Count) { 'Green' } else { 'Red' })
Write-Host "Managed batch evaluation: $($cloudBatch.status)"
Write-Host "Result: $resultPath"
if ($passed -ne $cases.Count) {
    throw "$($cases.Count - $passed) V2 evaluation case(s) failed."
}
