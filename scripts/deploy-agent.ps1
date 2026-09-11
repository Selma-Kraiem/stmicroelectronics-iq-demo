[CmdletBinding()]
param(
    [string]$EnvironmentName = 'st-iq-demo',
    [string]$AgentService = 'st-iq-incident-agent',
    [switch]$EnableWorkIq,
    [switch]$EnableFabricIq,
    [switch]$SkipBuild,
    [string]$Image
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
azd env select $EnvironmentName --no-prompt | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Azure Developer CLI environment '$EnvironmentName' does not exist."
}
$values = azd env get-values -o json | ConvertFrom-Json
if ($EnableWorkIq -or $EnableFabricIq) {
    Write-Warning (
        'EnableWorkIq and EnableFabricIq are retained for command compatibility only. ' +
        'Fab Intelligence now discovers both capabilities through INTERNAL_TOOLBOX_ENDPOINT.'
    )
}

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

function Invoke-AzureJson {
    param(
        [Parameter(Mandatory)][ValidateSet('Get', 'Post', 'Put', 'Patch')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token,
        [object]$Body
    )
    $headers = @{
        Authorization = "Bearer $Token"
        'Content-Type' = 'application/json'
    }
    $parameters = @{
        Method  = $Method
        Uri     = $Uri
        Headers = $headers
    }
    if ($null -ne $Body) {
        $parameters.Body = $Body | ConvertTo-Json -Depth 24 -Compress
    }
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        try {
            return Invoke-RestMethod @parameters
        }
        catch {
            $statusCode = $_.Exception.Response.StatusCode.value__
            $isTransient = -not $statusCode -or $statusCode -in @(408, 429, 500, 502, 503, 504)
            if (-not $isTransient -or $attempt -eq 4) {
                throw
            }
            Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
        }
    }
}

function Invoke-ToolboxJson {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token,
        [Parameter(Mandatory)][hashtable]$Body
    )
    Invoke-RestMethod -Method Post -Uri $Uri -Headers @{
        Authorization = 'Bear' + 'er ' + $Token
        Accept = 'application/json, text/event-stream'
        'Foundry-Features' = 'Toolboxes=V1Preview'
    } -ContentType 'application/json' -Body ($Body | ConvertTo-Json -Depth 20 -Compress)
}

function New-InternalToolSpec {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][string]$ServerUrl,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$OperationId,
        [Parameter(Mandatory)][string]$Summary
    )
    return @{
        openapi = '3.0.1'
        info = @{
            title = $Title
            version = '1.0.0'
            description = $Description
        }
        servers = @(@{ url = $ServerUrl })
        paths = @{
            $Path = @{
                get = @{
                    operationId = $OperationId
                    summary = $Summary
                    description = $Description
                    parameters = @(
                        @{
                            name = 'lot_id'
                            in = 'path'
                            required = $true
                            description = 'Synthetic semiconductor lot identifier.'
                            schema = @{ type = 'string' }
                        },
                        @{
                            name = 'X-Correlation-ID'
                            in = 'header'
                            required = $false
                            description = 'Common incident trace identifier.'
                            schema = @{ type = 'string' }
                        }
                    )
                    responses = @{
                        '200' = @{
                            description = 'Validated internal evidence with source provenance.'
                            content = @{
                                'application/json' = @{
                                    schema = @{ type = 'object'; additionalProperties = $true }
                                }
                            }
                        }
                    }
                    security = @(@{ apiKeyAuth = @() })
                }
            }
        }
        components = @{
            securitySchemes = @{
                apiKeyAuth = @{
                    type = 'apiKey'
                    in = 'header'
                    name = 'X-STIQ-API-Key'
                }
            }
        }
    }
}

function New-AcrImage {
    param(
        [Parameter(Mandatory)][string]$RegistryId,
        [Parameter(Mandatory)][string]$RegistryName,
        [Parameter(Mandatory)][string]$Repository,
        [Parameter(Mandatory)][string]$Tag
    )
    $apiVersion = '2019-06-01-preview'
    $armToken = Get-AzureAccessToken 'https://management.azure.com'
    $upload = Invoke-AzureJson -Method Post `
        -Uri "https://management.azure.com${RegistryId}/listBuildSourceUploadUrl?api-version=$apiVersion" `
        -Token $armToken

    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) "st-iq-acr-$([guid]::NewGuid())"
    $sourceRoot = Join-Path $tempRoot 'source'
    $archive = Join-Path $tempRoot 'source.tar.gz'
    try {
        New-Item -ItemType Directory -Path $sourceRoot -Force | Out-Null
        Copy-Item '.\pyproject.toml' $sourceRoot
        Copy-Item '.\app' $sourceRoot -Recurse
        New-Item -ItemType Directory -Path (Join-Path $sourceRoot 'agents') -Force | Out-Null
        Copy-Item '.\agents\__init__.py' (Join-Path $sourceRoot 'agents')
        Copy-Item '.\agents\hosted' (Join-Path $sourceRoot 'agents') -Recurse
        New-Item -ItemType Directory -Path (Join-Path $sourceRoot 'data') -Force | Out-Null
        Copy-Item '.\data\v1' (Join-Path $sourceRoot 'data') -Recurse

        & tar -czf $archive -C $sourceRoot .
        Assert-NativeSuccess 'Hosted-agent source archive creation'
        Invoke-WebRequest -Method Put -Uri $upload.uploadUrl -InFile $archive `
            -Headers @{ 'x-ms-blob-type' = 'BlockBlob' } | Out-Null

        $request = @{
            type           = 'DockerBuildRequest'
            dockerFilePath = 'agents/hosted/Dockerfile'
            imageNames     = @("${Repository}:$Tag")
            isPushEnabled  = $true
            noCache        = $false
            sourceLocation = $upload.relativePath
            platform       = @{
                os           = 'Linux'
                architecture = 'amd64'
            }
            credentials    = @{
                sourceRegistry = @{
                    identity  = '[caller]'
                    loginMode = 'Default'
                }
            }
        }
        $run = Invoke-AzureJson -Method Post `
            -Uri "https://management.azure.com${RegistryId}/scheduleRun?api-version=$apiVersion" `
            -Token $armToken -Body $request
        $runId = if ($run.properties.runId) {
            $run.properties.runId
        }
        elseif ($run.runId) {
            $run.runId
        }
        else {
            $run.name
        }
        if (-not $runId) {
            throw 'ACR accepted the build request but returned no run ID.'
        }

        $runUri = "https://management.azure.com${RegistryId}/runs/${runId}?api-version=$apiVersion"
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            $runResponse = Invoke-AzureJson -Method Get -Uri $runUri -Token $armToken
            $status = if ($runResponse.properties) { $runResponse.properties } else { $runResponse }
            Write-Host "ACR run ${runId}: $($status.status)"
            if ($status.status -eq 'Succeeded') {
                $output = @($status.outputImages)[0]
                if (-not $output.digest) {
                    throw "ACR run ${runId} succeeded but returned no image digest."
                }
                return "$($output.registry)/$($output.repository)@$($output.digest)"
            }
            if ($status.status -in @('Failed', 'Canceled', 'Error', 'Timeout')) {
                throw "ACR run ${runId} ended in $($status.status): $($status.runErrorMessage)"
            }
            Start-Sleep -Seconds 10
            if (($attempt + 1) % 30 -eq 0) {
                $armToken = Get-AzureAccessToken 'https://management.azure.com'
            }
        }
        throw "Timed out waiting for ACR run ${runId}."
    }
    finally {
        if (Test-Path $tempRoot) {
            Remove-Item $tempRoot -Recurse -Force
        }
    }
}

foreach ($required in @(
    'AZURE_SUBSCRIPTION_ID',
    'AZURE_TENANT_ID',
    'AZURE_RESOURCE_GROUP',
    'AZURE_AI_PROJECT_ENDPOINT',
    'AZURE_SEARCH_ENDPOINT',
    'AZURE_SEARCH_NAME',
    'AZURE_CONTAINER_REGISTRY_NAME',
    'AZURE_CONTAINER_REGISTRY_ENDPOINT',
    'AZURE_AI_MODEL_DEPLOYMENT_NAME',
    'FOUNDRY_ACCOUNT_ID',
    'KNOWLEDGE_BASE_NAME',
    'WEB_KNOWLEDGE_BASE_NAME',
    'WEB_APP_URL',
    'V1_INTERNAL_CONNECTION_ID'
)) {
    if (-not $values.$required) {
        throw (
            "Missing azd environment value '$required'. Run .\scripts\setup.ps1, then " +
            ".\scripts\deploy-web.ps1 once to bootstrap the protected internal APIs."
        )
    }
}

$projectEndpoint = $values.AZURE_AI_PROJECT_ENDPOINT.TrimEnd('/')
$projectName = $projectEndpoint.Split('/')[-1]
$projectId = "$($values.FOUNDRY_ACCOUNT_ID)/projects/$projectName"
$kbEndpoint = "$($values.AZURE_SEARCH_ENDPOINT)/knowledgebases/$($values.KNOWLEDGE_BASE_NAME)/mcp?api-version=2026-05-01-preview"
$aiToken = Get-AzureAccessToken 'https://ai.azure.com'
$connections = az rest --method get `
    --url "https://management.azure.com${projectId}/connections?api-version=2026-05-01" `
    -o json 2>$null | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $connections.value) {
    throw 'Could not enumerate Foundry project connections; refusing to select a web source.'
}
$webIqConnection = @($connections.value | Where-Object name -eq 'st-iq-webiq-mcp')[0]
if ($webIqConnection) {
    if (
        $webIqConnection.properties.authType -ne 'CustomKeys' -or
        $webIqConnection.properties.category -ne 'RemoteTool' -or
        $webIqConnection.properties.target -ne 'https://api.microsoft.ai/v3/mcp'
    ) {
        throw "Foundry connection 'st-iq-webiq-mcp' has an unexpected Web IQ contract."
    }
    $marketTool = @{
        type = 'mcp'
        server_label = 'web-iq'
        server_url = 'https://api.microsoft.ai/v3/mcp'
        require_approval = 'never'
        project_connection_id = "$projectId/connections/st-iq-webiq-mcp"
    }
    $marketDescription = (
        'Web IQ public intelligence for current market, regulatory, weather, recall, ' +
        'and semiconductor supply-chain evidence. Never send internal identifiers.'
    )
    $marketSourceLabel = 'Web IQ'
}
else {
    $marketTool = @{
        type = 'mcp'
        server_label = 'st-iq-web-knowledge-source'
        server_url = "$($values.AZURE_SEARCH_ENDPOINT)/knowledgebases/$($values.WEB_KNOWLEDGE_BASE_NAME)/mcp?api-version=2026-05-01-preview"
        require_approval = 'never'
        project_connection_id = "$projectId/connections/st-iq-web-mcp"
    }
    $marketDescription = 'Public-only research through Web Knowledge Source (Web IQ fallback)'
    $marketSourceLabel = 'Web Knowledge Source (Web IQ fallback)'
    Write-Warning (
        "Web IQ connection 'st-iq-webiq-mcp' is absent. Radar remains on the accurately " +
        'labelled Web Knowledge Source fallback until a rotated key is configured.'
    )
}

Write-Host 'Publishing specialist Foundry toolboxes...' -ForegroundColor Cyan
$marketToolbox = Invoke-AzureJson -Method Post `
    -Uri "$projectEndpoint/toolboxes/st-iq-market-toolbox/versions?api-version=v1" `
    -Token $aiToken -Body @{
        description = $marketDescription
        tools = @($marketTool)
    }
if (-not $marketToolbox.version) {
    throw "Foundry created the Radar toolbox but returned no version."
}
$marketToolboxEndpoint = (
    "$projectEndpoint/toolboxes/st-iq-market-toolbox/versions/" +
    "$($marketToolbox.version)/mcp?api-version=v1"
)

$connectionAuth = @{
    type = 'project_connection'
    security_scheme = @{
        project_connection_id = $values.V1_INTERNAL_CONNECTION_ID
    }
}
$fabricSpec = New-InternalToolSpec `
    -Title 'Fabric IQ Semiconductor Ontology' `
    -Description (
        'Queries the live Fabric IQ ontology for synthetic lot genealogy, wafers, testers, ' +
        'recipes, measurements, process limits, incidents, and causal paths.'
    ) `
    -ServerUrl $values.WEB_APP_URL `
    -Path '/internal/fabric/lots/{lot_id}' `
    -OperationId 'searchFabricOntology' `
    -Summary 'Trace a synthetic semiconductor lot through the Fabric IQ ontology.'
$oneDriveSpec = New-InternalToolSpec `
    -Title 'Work IQ OneDrive Shipment Analysis' `
    -Description (
        'Retrieves the exact synthetic shipment workbook from the signed-in user OneDrive and ' +
        'returns deterministic field, inventory, customer, and containment KPIs without ' +
        'placing workbook bytes in model context.'
    ) `
    -ServerUrl $values.WEB_APP_URL `
    -Path '/internal/onedrive/lots/{lot_id}/exposure' `
    -OperationId 'analyzeOneDriveWorkbook' `
    -Summary 'Analyze the delegated synthetic OneDrive workbook for lot exposure.'
$internalToolbox = Invoke-AzureJson -Method Post `
    -Uri "$projectEndpoint/toolboxes/st-iq-internal-intelligence/versions?api-version=v1" `
    -Token $aiToken -Body @{
        description = (
            'Internal read-only intelligence discovered with Tool Search: Foundry IQ documents ' +
            'and SharePoint knowledge, Fabric IQ ontology, and Work IQ OneDrive workbook analysis.'
        )
        tools = @(
            @{ type = 'toolbox_search' },
            @{
                type = 'mcp'
                server_label = 'foundry-iq'
                server_url = $kbEndpoint
                require_approval = 'never'
                project_connection_id = "$projectId/connections/st-iq-kb-mcp"
                tool_configs = @{
                    knowledge_base_retrieve = @{
                        additional_search_text = (
                            'ST product report document SharePoint procedure QMS FMEA ' +
                            'SCM containment process specification excursion history ' +
                            'tester correlation AEC-Q101 quality handbook'
                        )
                    }
                }
            },
            @{
                type = 'openapi'
                name = 'fabric-iq-ontology'
                openapi = @{
                    name = 'fabric-iq-ontology'
                    description = (
                        'Live Fabric IQ ontology evidence for synthetic semiconductor ' +
                        'manufacturing relationships and root-cause analysis.'
                    )
                    spec = $fabricSpec
                    auth = $connectionAuth
                }
                tool_configs = @{
                    searchFabricOntology = @{
                        additional_search_text = (
                            'lot wafer genealogy tester T-07 recipe R-GOX-12 Vth gate oxide ' +
                            'e-test telemetry measurement USL process limit root cause Fabric IQ'
                        )
                    }
                }
            },
            @{
                type = 'openapi'
                name = 'work-iq-onedrive-workbook'
                openapi = @{
                    name = 'work-iq-onedrive-workbook'
                    description = (
                        'Delegated Work IQ OneDrive retrieval plus deterministic Python analysis ' +
                        'of the synthetic SiC shipment workbook.'
                    )
                    spec = $oneDriveSpec
                    auth = $connectionAuth
                }
                tool_configs = @{
                    analyzeOneDriveWorkbook = @{
                        additional_search_text = (
                            'OneDrive xlsx Excel shipment customer units in field inventory ' +
                            'blockable stock allocation containment perimeter exposure Work IQ'
                        )
                    }
                }
            }
        )
    }
if (-not $internalToolbox.version) {
    throw 'Foundry created the Internal Intelligence toolbox but returned no version.'
}
$internalToolboxEndpoint = (
    "$projectEndpoint/toolboxes/st-iq-internal-intelligence/versions/" +
    "$($internalToolbox.version)/mcp?api-version=v1"
)
$listed = Invoke-ToolboxJson -Uri $internalToolboxEndpoint -Token $aiToken -Body @{
    jsonrpc = '2.0'
    id = 'internal-tools-list'
    method = 'tools/list'
    params = @{}
}
$deferToolSearchProbe = $false
if ($listed.error) {
    if ([string]$listed.error.message -match 'AgenticIdentityToken auth type') {
        $deferToolSearchProbe = $true
        Write-Warning (
            'Foundry IQ uses agent identity and cannot resolve during a user-token toolbox ' +
            'probe. Tool Search validation is deferred to the deployed agent runtime.'
        )
    }
    else {
        throw "Internal Tool Search tools/list failed: $($listed.error.message)"
    }
}
else {
    $listedNames = @($listed.result.tools | ForEach-Object name)
    if (
        $listedNames -notcontains 'tool_search' -or
        $listedNames -notcontains 'call_tool' -or
        @($listedNames | Where-Object { $_ -notin @('tool_search', 'call_tool') }).Count -gt 0
    ) {
        throw "Internal Tool Search contract is invalid: $($listedNames -join ', ')"
    }
}
if (-not $deferToolSearchProbe) {
    foreach ($probe in @(
        @{ Query = 'retrieve the QMS containment procedure from Foundry IQ'; Expected = 'knowledge_base_retrieve' },
        @{ Query = 'trace lot wafers tester recipe and Vth root cause in Fabric IQ'; Expected = 'searchFabricOntology' },
        @{ Query = 'calculate shipped customer exposure from the OneDrive XLSX workbook'; Expected = 'analyzeOneDriveWorkbook' }
    )) {
        $searchResult = Invoke-ToolboxJson -Uri $internalToolboxEndpoint -Token $aiToken -Body @{
            jsonrpc = '2.0'
            id = "tool-search-$($probe.Expected)"
            method = 'tools/call'
            params = @{
                name = 'tool_search'
                arguments = @{ query = $probe.Query; limit = 5 }
            }
        }
        $serialized = $searchResult | ConvertTo-Json -Depth 30 -Compress
        if ($searchResult.error -or $serialized -notmatch [regex]::Escape($probe.Expected)) {
            throw "Tool Search did not discover '$($probe.Expected)' for '$($probe.Query)'."
        }
    }
}
azd env set MARKET_TOOLBOX_ENDPOINT $marketToolboxEndpoint | Out-Null
azd env set MARKET_SOURCE_LABEL $marketSourceLabel | Out-Null
azd env set INTERNAL_TOOLBOX_ENDPOINT $internalToolboxEndpoint | Out-Null
azd env set INTERNAL_TOOLBOX_VERSION $internalToolbox.version | Out-Null

if (-not $SkipBuild) {
    $tag = Get-Date -Format 'yyyyMMddHHmmss'
    $registryId = "/subscriptions/$($values.AZURE_SUBSCRIPTION_ID)/resourceGroups/$($values.AZURE_RESOURCE_GROUP)/providers/Microsoft.ContainerRegistry/registries/$($values.AZURE_CONTAINER_REGISTRY_NAME)"
    Write-Host "Building immutable Linux AMD64 image agents/st-iq-incident-agent:$tag..." -ForegroundColor Cyan
    $Image = New-AcrImage -RegistryId $registryId `
        -RegistryName $values.AZURE_CONTAINER_REGISTRY_NAME `
        -Repository 'agents/st-iq-incident-agent' -Tag $tag
}
elseif (-not $Image) {
    $Image = $values.AGENT_IMAGE
}
if (-not $Image -or $Image -notmatch '@sha256:[0-9a-f]{64}$') {
    throw 'Hosted deployment requires an immutable ACR image digest.'
}
azd env set AGENT_IMAGE $Image | Out-Null

Write-Host 'Creating the Responses 2.0.0 hosted-agent version...' -ForegroundColor Cyan
$agentEnvironment = @{
    AZURE_AI_MODEL_DEPLOYMENT_NAME = $values.AZURE_AI_MODEL_DEPLOYMENT_NAME
    MARKET_TOOLBOX_ENDPOINT        = $marketToolboxEndpoint
    INTERNAL_TOOLBOX_ENDPOINT      = $internalToolboxEndpoint
    MARKET_SOURCE_LABEL            = $marketSourceLabel
    ENABLE_INSTRUMENTATION         = 'true'
    ENABLE_SENSITIVE_DATA          = 'false'
    OPTIMIZATION_LOCAL_DIR          = '.agent_configs'
    LOG_LEVEL                      = 'INFO'
    STIQ_V1_DATA_ROOT              = '/app/data/v1'
}
$agentRequest = @{
    description = 'Chief/Compiler with adaptive parallel Radar and Fab Intelligence specialists'
    definition  = @{
        kind                        = 'hosted'
        image                       = $Image
        cpu                         = '1'
        memory                      = '2Gi'
        container_protocol_versions = @(
            @{
                protocol = 'responses'
                version  = '2.0.0'
            }
        )
        environment_variables       = $agentEnvironment
    }
}
$agent = Invoke-AzureJson -Method Post `
    -Uri "$projectEndpoint/agents/$AgentService/versions?api-version=v1" `
    -Token $aiToken -Body $agentRequest
if (-not $agent.version -or -not $agent.instance_identity.principal_id) {
    throw 'Foundry accepted the hosted agent but returned no version or dedicated identity.'
}

$agentPrincipal = $agent.instance_identity.principal_id
$searchId = "/subscriptions/$($values.AZURE_SUBSCRIPTION_ID)/resourceGroups/$($values.AZURE_RESOURCE_GROUP)/providers/Microsoft.Search/searchServices/$($values.AZURE_SEARCH_NAME)"
foreach ($grant in @(
    @{ Role = 'Foundry User'; RoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'; Scope = $values.FOUNDRY_ACCOUNT_ID },
    @{ Role = 'Search Index Data Reader'; RoleId = '1407120a-92aa-4202-b7e9-c0e197c71c8f'; Scope = $searchId }
)) {
    $existing = az role assignment list --scope $grant.Scope `
        --query "[?principalId=='$agentPrincipal' && contains(roleDefinitionId, '$($grant.RoleId)')] | [0].id" -o tsv
    Assert-NativeSuccess "Inspecting $($grant.Role) assignments"
    if (-not $existing) {
        az role assignment create --assignee-object-id $agentPrincipal `
            --assignee-principal-type ServicePrincipal --role $grant.RoleId `
            --scope $grant.Scope --only-show-errors | Out-Null
        Assert-NativeSuccess "Assigning $($grant.Role)"
    }
}
$agentUri = "$projectEndpoint/agents/$AgentService/versions/$($agent.version)?api-version=v1"
for ($attempt = 0; $attempt -lt 120; $attempt++) {
    $agent = Invoke-AzureJson -Method Get -Uri $agentUri -Token $aiToken
    Write-Host "Hosted agent version $($agent.version): $($agent.status)"
    if ($agent.status -eq 'active') {
        break
    }
    if ($agent.status -in @('failed', 'deleted')) {
        throw "Hosted agent deployment ended in $($agent.status)."
    }
    Start-Sleep -Seconds 15
    if (($attempt + 1) % 20 -eq 0) {
        $aiToken = Get-AzureAccessToken 'https://ai.azure.com'
    }
}
if ($agent.status -ne 'active') {
    throw 'Timed out waiting for hosted-agent activation.'
}

$invokeEndpoint = "$projectEndpoint/agents/$AgentService/endpoint/protocols/openai/responses?api-version=v1"
azd env set FOUNDRY_AGENT_VERSION $agent.version | Out-Null
azd env set FOUNDRY_AGENT_ENDPOINT $invokeEndpoint | Out-Null
azd env set HOSTED_AGENT_ENDPOINT $invokeEndpoint | Out-Null

Write-Host 'Invoking the deployed agent through the Responses endpoint...' -ForegroundColor Cyan
$invokeRequest = @{
    input = @'
ROUTE=FULL_ASSESSMENT
Assess synthetic lot SiC-AUTO-2451 for a Vth parametric excursion. Run Radar and Fab
Intelligence in parallel. Fab must use tool_search to discover Foundry IQ, Fabric IQ, and
Work IQ OneDrive workbook analysis before using any explicitly labelled local fallback.
Synthesize the strict cited incident JSON contract and produce a Teams dry-run only.
'@
}
$response = Invoke-AzureJson -Method Post -Uri $invokeEndpoint -Token $aiToken -Body $invokeRequest
if ($response.status -ne 'completed') {
    if (
        $response.error.message -match 'CONSENT_REQUIRED'
    ) {
        $consentUrl = [regex]::Match([string]$response.error.message, 'https://[^"\s]+').Value
        if ($consentUrl) {
            Start-Process $consentUrl
        }
        throw (
            'Hosted Agent version is active, but a toolbox caller context needs consent. ' +
            $(if ($consentUrl) { 'Complete the opened browser flow, then rerun with ' } else {
                'No consent URL was returned; rerun setup and deployment diagnostics. '
            }) +
            '-SkipBuild after completing consent.'
        )
    }
    throw "Hosted invocation did not complete; status: $($response.status)"
}
$message = @($response.output | Where-Object type -eq 'message')[-1]
$outputText = [string]$message.content[0].text
$jsonText = $outputText.Trim()
if ($jsonText.StartsWith('```')) {
    $jsonText = $jsonText -replace '^```(?:json)?\s*', '' -replace '\s*```$', ''
}
$jsonStart = $jsonText.IndexOf('{')
$jsonEnd = $jsonText.LastIndexOf('}')
if ($jsonStart -ge 0 -and $jsonEnd -gt $jsonStart) {
    $jsonText = $jsonText.Substring($jsonStart, $jsonEnd - $jsonStart + 1)
}
try {
    $compiled = $jsonText | ConvertFrom-Json -Depth 40
}
catch {
    throw 'Hosted invocation completed without a valid Chief/Compiler JSON object.'
}
if ($compiled.route -eq 'full_assessment' -and $compiled.result) {
    $compiled = $compiled.result
}
if (
    -not $compiled.agent_outputs.radar -or
    -not $compiled.agent_outputs.fab_intelligence -or
    $compiled.teams_update.delivery -ne 'dry-run' -or
    $compiled.evidence_trace.completed -ne $compiled.evidence_trace.total
) {
    throw 'Hosted invocation JSON did not satisfy the parallel evidence and dry-run contract.'
}
$fabSelectedTools = @(
    $compiled.agent_outputs.fab_intelligence.tool_trace |
        ForEach-Object selected_tool
)
foreach ($expectedDomain in @(
    @('knowledge_base_retrieve', 'work_iq_handbook_fallback'),
    @('searchFabricOntology', 'fabric_iq_trace'),
    @('analyzeOneDriveWorkbook', 'fab_field_exposure')
)) {
    $matchingTools = @(
        $fabSelectedTools |
            Where-Object {
                $selectedTool = [string]$_
                @(
                    $expectedDomain |
                        Where-Object {
                            $selectedTool -eq $_ -or $selectedTool.EndsWith("___$_")
                        }
                ).Count -gt 0
            }
    )
    if ($matchingTools.Count -lt 1) {
        throw (
            'Hosted Fab tool trace did not record one expected live or fallback tool from: ' +
            ($expectedDomain -join ', ')
        )
    }
}

Write-Host "`nHosted agent deployed and invoked successfully." -ForegroundColor Green
Write-Host "Version: $($agent.version)"
Write-Host "Image: $Image"
Write-Host "Identity: $agentPrincipal"
Write-Host "Endpoint: $invokeEndpoint"
Write-Host 'Next: .\scripts\evaluate.ps1'
