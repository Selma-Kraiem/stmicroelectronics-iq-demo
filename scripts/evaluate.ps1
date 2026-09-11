[CmdletBinding()]
param(
    [string]$EnvironmentName = 'st-iq-demo',
    [string]$AgentService = 'st-iq-incident-agent',
    [int]$MaxCases = 5,
    [int]$DelaySeconds = 45,
    [switch]$CloudOnly
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
azd env select $EnvironmentName --no-prompt | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Azure Developer CLI environment '$EnvironmentName' does not exist."
}
$values = azd env get-values -o json | ConvertFrom-Json

function Assert-NativeSuccess {
    param([string]$Operation)
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed."
    }
}

function Get-AzureAccessToken {
    param([Parameter(Mandatory)][string]$Resource)
    $token = az account get-access-token --resource $Resource --tenant $values.AZURE_TENANT_ID `
        --query accessToken -o tsv
    Assert-NativeSuccess "Azure token acquisition for $Resource"
    if (-not $token) {
        throw "Azure token acquisition for $Resource returned no token."
    }
    return $token
}

function Invoke-AgentResponse {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][hashtable]$Headers,
        [Parameter(Mandatory)][string]$Body
    )
    $maxAttempts = 5
    for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
        try {
            $response = Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers `
                -Body $Body -TimeoutSec 900
            $message = @($response.output | Where-Object type -eq 'message')[-1]
            $text = if ($message -and $message.content) {
                [string]$message.content[0].text
            }
            if ($response.status -eq 'completed' -and -not [string]::IsNullOrWhiteSpace($text)) {
                return $response
            }
            if ($attempt -eq $maxAttempts) {
                throw "Agent returned status '$($response.status)' without final output text."
            }
            Write-Warning "Agent invocation attempt $attempt returned no final message; retrying."
            Start-Sleep -Seconds (15 * $attempt)
        }
        catch {
            $statusCode = $_.Exception.Response.StatusCode.value__
            $isTransportFailure = -not $statusCode
            $isTransientStatus = $statusCode -in @(408, 429, 500, 502, 503, 504)
            if (
                $attempt -eq $maxAttempts -or
                (-not $isTransportFailure -and -not $isTransientStatus)
            ) {
                throw
            }
            Write-Warning "Agent invocation attempt $attempt failed transiently; retrying."
            Start-Sleep -Seconds (15 * $attempt)
        }
    }
}

foreach ($required in @(
    'AZURE_AI_PROJECT_ENDPOINT',
    'AZURE_SUBSCRIPTION_ID',
    'AZURE_TENANT_ID',
    'AZURE_RESOURCE_GROUP',
    'AZURE_STORAGE_ACCOUNT_NAME',
    'APPLICATIONINSIGHTS_NAME'
)) {
    if (-not $values.$required) {
        throw "Missing azd environment value '$required'. Run .\scripts\setup.ps1 first."
    }
}

$storageName = $values.AZURE_STORAGE_ACCOUNT_NAME
$publicNetwork = az storage account show --subscription $values.AZURE_SUBSCRIPTION_ID `
    --resource-group $values.AZURE_RESOURCE_GROUP --name $storageName `
    --query publicNetworkAccess -o tsv
Assert-NativeSuccess 'Evaluation storage policy inspection'

if ($publicNetwork -eq 'Disabled') {
    $policyMessage = @"
Foundry cloud batch evaluation is blocked before sampling. The subscription policy
MCAPSGovDeployPolicies / StorageAccount_PublicNetwork_Modify forces publicNetworkAccess=Disabled
on $storageName, while this project has no approved private endpoint path for the Foundry
evaluation service. An administrator must grant a scoped policy exemption for this demo
storage account or provision the approved Foundry managed-network/private-endpoint pattern.
"@
    Write-Warning $policyMessage
    if ($CloudOnly) {
        throw 'Cloud-only evaluation requested, but the required evaluation storage path is blocked.'
    }
    $cloudEvaluationBlocked = $true
    $cloudEvaluationBlocker = 'Storage account public network access is disabled.'
}
else {
    if ($CloudOnly) {
        throw @"
Cloud-only evaluation requires the Foundry evaluation MCP workflow. This script validates the
live hosted-agent contract; run the evaluation suite in the selected .foundry metadata file.
"@
    }
    $cloudEvaluationBlocked = $false
    $cloudEvaluationBlocker = $null
}

$datasetPath = '.\.foundry\datasets\st-iq-incident-agent-eval-seed-v1.jsonl'
$allCases = @(Get-Content $datasetPath | Where-Object { $_.Trim() } | ForEach-Object {
    $_ | ConvertFrom-Json
})
if ($allCases.Count -lt 15) {
    throw "The seed evaluation dataset must contain at least 15 cases; found $($allCases.Count)."
}
$cases = @($allCases | Select-Object -First $MaxCases)
if (-not $cases) {
    throw 'No evaluation cases were selected.'
}

$projectEndpoint = $values.AZURE_AI_PROJECT_ENDPOINT.TrimEnd('/')
$invokeEndpoint = "$projectEndpoint/agents/$AgentService/endpoint/protocols/openai/responses?api-version=v1"
$token = Get-AzureAccessToken 'https://ai.azure.com'
$headers = @{
    Authorization = "Bearer $token"
    'Content-Type' = 'application/json'
}
$results = @()

for ($index = 0; $index -lt $cases.Count; $index++) {
    $case = $cases[$index]
    Write-Host "Evaluating case $($index + 1)/$($cases.Count): $($case.context)" -ForegroundColor Cyan
    if (-not $case.expected_route) {
        throw "Evaluation case $($index + 1) has no expected_route."
    }
    $body = @{
        input = "$($case.query)`nReturn one JSON object."
    } | ConvertTo-Json -Compress
    $response = Invoke-AgentResponse -Uri $invokeEndpoint -Headers $headers -Body $body
    $message = @($response.output | Where-Object type -eq 'message')[-1]
    $text = [string]$message.content[0].text
    $toolCalls = @($response.output | Where-Object type -eq 'function_call')
    $webCalls = @($toolCalls | Where-Object name -like '*web*')
    $jsonText = $text.Trim() -replace '^```(?:json)?\s*', '' -replace '\s*```$', ''
    $jsonStart = $jsonText.IndexOf('{')
    $jsonEnd = $jsonText.LastIndexOf('}')
    $compiled = $null
    if ($jsonStart -ge 0 -and $jsonEnd -gt $jsonStart) {
        try {
            $compiled = $jsonText.Substring(
                $jsonStart,
                $jsonEnd - $jsonStart + 1
            ) | ConvertFrom-Json -Depth 40
        }
        catch {
            $compiled = $null
        }
    }

    $route = [string]$compiled.route
    $payload = if ($route -and $compiled.result) { $compiled.result } else { $compiled }
    $activatedAgents = @($compiled.activated_agents | Where-Object { $_ })
    $expectedAgents = switch ([string]$case.expected_route) {
        'radar_only' { @('Radar') }
        'fab_only' { @('Fab Intelligence') }
        'full_assessment' { @('Radar', 'Fab Intelligence', 'Chief/Compiler') }
        default { throw "Unsupported expected_route '$($case.expected_route)'." }
    }
    $isFullAssessment = $route -eq 'full_assessment' -or -not $route
    $citations = if ($route) { @($compiled.sources | Where-Object { $_ }) } else {
        @($payload.citations | Where-Object { $_ })
    }
    $checks = [ordered]@{
        task_completion = $response.status -eq 'completed' -and -not [string]::IsNullOrWhiteSpace($text)
        strict_json = $null -ne $compiled
        route_match = $route -eq [string]$case.expected_route
        activated_agents_match = (
            ($activatedAgents | Sort-Object) -join '|'
        ) -eq (($expectedAgents | Sort-Object) -join '|')
        orchestration_call = $toolCalls.Count -eq 1 -and `
            $toolCalls[0].name -eq 'dispatch_request'
        parallel_workers = if ($isFullAssessment) {
            $null -ne $payload.agent_outputs.radar -and `
                $null -ne $payload.agent_outputs.fab_intelligence
        } else {
            $activatedAgents.Count -eq 1
        }
        chief_synthesis = if ($isFullAssessment) {
            $payload.evidence_trace.completed -gt 0 -and `
                $payload.evidence_trace.completed -eq $payload.evidence_trace.total
        } else {
            $activatedAgents -notcontains 'Chief/Compiler'
        }
        citation_presence = if ($case.context -eq 'safety_boundary') {
            $true
        } else {
            $citations.Count -gt 0
        }
        side_effect_safety = if ($isFullAssessment) {
            $payload.teams_update.delivery -eq 'dry-run'
        } else {
            $text -notmatch '(?i)"delivery"\s*:\s*"(sent|live)"'
        }
    }
    if ($case.expected_behavior -match '(?i)synthetic') {
        $checks.synthetic_label = $text -match '(?i)synthetic'
    }
    if ($case.expected_behavior -match '(?i)fallback') {
        $checks.fallback_provenance = $text -match '(?i)fallback'
    }
    if ($case.expected_behavior -match '(?i)sanitiz|confidential|tenant-private') {
        $unsafeWebArgument = $false
        foreach ($call in $webCalls) {
            if ($call.arguments -match '(?i)confidential|customer|yield|SC-24-0917|Orion Mobility|tenant|lot') {
                $unsafeWebArgument = $true
            }
        }
        $checks.web_query_privacy = -not $unsafeWebArgument
    }
    $passed = @($checks.Values | Where-Object { -not $_ }).Count -eq 0
    $results += [ordered]@{
        case             = $index + 1
        context          = $case.context
        query            = $case.query
        responseId       = $response.id
        status           = $response.status
        toolCalls        = @($toolCalls | ForEach-Object { $_.name } | Where-Object { $_ })
        checks           = $checks
        passed           = $passed
        responseExcerpt  = $text.Substring(0, [Math]::Min(500, $text.Length))
    }
    if ($index -lt $cases.Count - 1 -and $DelaySeconds -gt 0) {
        Start-Sleep -Seconds $DelaySeconds
    }
}

$passedCount = @($results | Where-Object passed).Count
$telemetryQuery = "dependencies | where timestamp > ago(24h) | where tostring(customDimensions['gen_ai.agent.version']) == '$($values.FOUNDRY_AGENT_VERSION)' | where name startswith 'tools/call ' | summarize calls=count() by name"
$expectedTelemetry = @(
    'tools/call tool_search',
    'tools/call foundry-iq___knowledge_base_retrieve',
    'tools/call fabric-iq-ontology___searchFabricOntology',
    'tools/call work-iq-onedrive-workbook___analyzeOneDriveWorkbook'
)
$observedTelemetry = @()
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $telemetryJson = az monitor app-insights query `
        --app $values.APPLICATIONINSIGHTS_RESOURCE_ID `
        --analytics-query $telemetryQuery `
        --output json
    Assert-NativeSuccess 'Querying Tool Search telemetry'
    $telemetry = $telemetryJson | ConvertFrom-Json -Depth 20
    $observedTelemetry = @(
        $telemetry.tables[0].rows | ForEach-Object { [string]$_[0] }
    ) | Sort-Object -Unique
    if (@($expectedTelemetry | Where-Object { $_ -notin $observedTelemetry }).Count -eq 0) {
        break
    }
    Start-Sleep -Seconds 10
}
$missingTelemetry = @($expectedTelemetry | Where-Object { $_ -notin $observedTelemetry })
if ($missingTelemetry.Count -gt 0) {
    throw "Missing live Tool Search telemetry: $($missingTelemetry -join ', ')"
}
$resultDocument = [ordered]@{
    mode                   = 'live-hosted-contract'
    cloudEvaluationBlocked = $cloudEvaluationBlocked
    blocker                = $cloudEvaluationBlocker
    agent                  = $AgentService
    agentVersion           = $values.FOUNDRY_AGENT_VERSION
    dataset                = 'st-iq-incident-agent-eval-seed-v1'
    datasetCases           = $allCases.Count
    executedCases          = $cases.Count
    passed                 = $passedCount
    failed                 = $cases.Count - $passedCount
    toolSearchTelemetry    = $observedTelemetry
    generatedAt            = (Get-Date).ToUniversalTime().ToString('o')
    results                = $results
}

$resultsDirectory = '.\.foundry\results'
New-Item -ItemType Directory -Path $resultsDirectory -Force | Out-Null
$resultPrefix = "$EnvironmentName-live-smoke"
$resultPath = Join-Path $resultsDirectory "$resultPrefix-$(Get-Date -Format yyyyMMddHHmmss).json"
$resultDocument | ConvertTo-Json -Depth 16 | Set-Content $resultPath -Encoding utf8

$candidateFiles = @(Get-ChildItem $resultsDirectory -Filter "$resultPrefix-*.json" |
    Sort-Object LastWriteTime)
$candidateResults = @()
foreach ($file in $candidateFiles) {
    $candidate = Get-Content $file.FullName -Raw | ConvertFrom-Json
    if ($candidate.executedCases -gt 0 -and $candidate.agentVersion) {
        $strategy = if ([int]$candidate.agentVersion -ge 15) {
            'adaptive Radar/Fab routing + Chief/Compiler synthesis'
        }
        else {
            'parallel Radar/Fab + Chief/Compiler'
        }
        $candidateResults += [pscustomobject][ordered]@{
            name         = "workflow_v$($candidate.agentVersion)"
            agent_version = [string]$candidate.agentVersion
            strategy     = $strategy
            score        = [Math]::Round(
                [double]$candidate.passed / [double]$candidate.executedCases,
                3
            )
            passed       = [int]$candidate.passed
            failed       = [int]$candidate.failed
            best         = $false
            evidence     = ".foundry/results/$($file.Name)"
        }
    }
}
$latestByVersion = @($candidateResults | Group-Object -Property agent_version | ForEach-Object {
    $_.Group[-1]
})
$bestScore = ($latestByVersion | Measure-Object score -Maximum).Maximum
foreach ($candidate in $latestByVersion) {
    $candidate.best = $candidate.score -eq $bestScore -and `
        $candidate.agent_version -eq [string]$values.FOUNDRY_AGENT_VERSION
}
$summary = [ordered]@{
    status = if ($cloudEvaluationBlocked) {
        'verified-with-platform-blocker'
    }
    else {
        'verified'
    }
    generated_at = (Get-Date).ToUniversalTime().ToString('o')
    dataset = [ordered]@{
        name = 'st-iq-incident-agent-eval-seed-v1'
        total_cases = $allCases.Count
        executed_cases = $cases.Count
    }
    candidates = $latestByVersion
    optimizer = [ordered]@{
        state = if ($cloudEvaluationBlocked) { 'blocked' } else { 'not-run' }
        label = 'Foundry Agent Optimizer'
        reason = if ($cloudEvaluationBlocked) {
            'Cloud batch evaluation is blocked by the storage network policy.'
        }
        else {
            'Foundry evaluation MCP tools are unavailable in this CLI runtime; the live hosted ' +
            'contract suite was executed and persisted instead.'
        }
        action = if ($cloudEvaluationBlocked) {
            'Provision an approved private evaluation path or a scoped storage-policy exemption.'
        }
        else {
            'Run the smoke-core suite from the selected metadata sidecar when the Foundry ' +
            'evaluation MCP tools are available.'
        }
    }
    portal = [ordered]@{
        project = 'st-iq-demo'
        agent = $AgentService
        application_insights = $values.APPLICATIONINSIGHTS_NAME
    }
}
$summaryFile = if ($EnvironmentName -eq 'st-iq-demo') {
    '.\app\evaluation-summary.json'
}
else {
    ".\app\evaluation-summary.$EnvironmentName.json"
}
$summary | ConvertTo-Json -Depth 12 | Set-Content $summaryFile -Encoding utf8

Write-Host "`nLive hosted-agent contract evaluation: $passedCount/$($cases.Count) passed." `
    -ForegroundColor $(if ($passedCount -eq $cases.Count) { 'Green' } else { 'Red' })
Write-Host "Result: $resultPath"
if ($passedCount -ne $cases.Count) {
    throw "$($cases.Count - $passedCount) live evaluation case(s) failed."
}
