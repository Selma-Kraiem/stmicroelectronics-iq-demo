[CmdletBinding()]
param(
    [string]$EnvironmentName = 'st-iq-demo-v2',
    [switch]$SkipBuild,
    [string]$Image
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repoRoot
. "$PSScriptRoot\common.ps1"

azd env select $EnvironmentName --no-prompt | Out-Null
Assert-NativeSuccess "Selecting V2 environment '$EnvironmentName'"
$values = azd env get-values -o json | ConvertFrom-Json
foreach ($required in @(
    'AZURE_SUBSCRIPTION_ID',
    'AZURE_RESOURCE_GROUP',
    'AZURE_AI_PROJECT_ID',
    'AZURE_AI_PROJECT_ENDPOINT',
    'AZURE_AI_MODEL_DEPLOYMENT_NAME',
    'AZURE_SEARCH_ENDPOINT',
    'AZURE_CONTAINER_REGISTRY_NAME',
    'FOUNDRY_ACCOUNT_ID',
    'V2_APP_URL',
    'V2_OPERATIONAL_CONNECTION_ID'
)) {
    if (-not $values.$required) {
        throw "Missing azd value '$required'. Run .\scripts\v2\setup.ps1 first."
    }
}

$projectEndpoint = $values.AZURE_AI_PROJECT_ENDPOINT.TrimEnd('/')
$searchMcp = "$($values.AZURE_SEARCH_ENDPOINT)/knowledgebases/st-iq-v2-knowledge-base/mcp?api-version=2026-05-01-preview"
$webMcp = "$($values.AZURE_SEARCH_ENDPOINT)/knowledgebases/st-iq-v2-web-base/mcp?api-version=2026-05-01-preview"
$aiToken = Get-AzureAccessToken 'https://ai.azure.com'
$searchId = "/subscriptions/$($values.AZURE_SUBSCRIPTION_ID)/resourceGroups/$($values.AZURE_RESOURCE_GROUP)/providers/Microsoft.Search/searchServices/stiqdemo-search"
$registryId = "/subscriptions/$($values.AZURE_SUBSCRIPTION_ID)/resourceGroups/$($values.AZURE_RESOURCE_GROUP)/providers/Microsoft.ContainerRegistry/registries/$($values.AZURE_CONTAINER_REGISTRY_NAME)"

function New-OperationalSpec {
    param(
        [Parameter(Mandatory)][string]$Title,
        [Parameter(Mandatory)][string]$ServerUrl,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$OperationId,
        [Parameter(Mandatory)][string]$Summary
    )
    return @{
        openapi = '3.0.1'
        info = @{
            title = $Title
            version = '2.0.0'
            description = 'Deterministic synthetic demo data only.'
        }
        servers = @(@{ url = $ServerUrl })
        paths = @{
            $Path = @{
                get = @{
                    operationId = $OperationId
                    summary = $Summary
                    parameters = @(
                        @{
                            name = 'lot_id'
                            in = 'path'
                            required = $true
                            schema = @{ type = 'string' }
                        },
                        @{
                            name = 'X-Correlation-ID'
                            in = 'header'
                            required = $false
                            schema = @{ type = 'string' }
                            description = 'Common incident trace identifier.'
                        }
                    )
                    responses = @{
                        '200' = @{
                            description = 'Synthetic evidence with provenance.'
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

Write-Host 'Publishing the Quality operational toolbox with Tool Search...' -ForegroundColor Cyan
$telemetrySpec = New-OperationalSpec `
    -Title 'Manufacturing Telemetry API' `
    -ServerUrl "$($values.V2_APP_URL)/operational/telemetry" `
    -Path '/api/v2/telemetry/lots/{lot_id}' `
    -OperationId 'getLotTelemetry' `
    -Summary 'Retrieve equipment, measurements, thresholds, anomalies, and affected lot evidence.'
$exposureSpec = New-OperationalSpec `
    -Title 'Customer Exposure API' `
    -ServerUrl "$($values.V2_APP_URL)/operational/exposure" `
    -Path '/api/v2/exposure/lots/{lot_id}' `
    -OperationId 'getLotExposure' `
    -Summary 'Retrieve fictional orders, customers, inventory, coverage, and reallocation.'
$connectionAuth = @{
    type = 'project_connection'
    security_scheme = @{
        project_connection_id = $values.V2_OPERATIONAL_CONNECTION_ID
    }
}
$toolbox = Invoke-AzureJson -Method Post `
    -Uri "$projectEndpoint/toolboxes/st-iq-v2-quality-operations/versions?api-version=v1" `
    -Token $aiToken -Body @{
        description = 'Telemetry and customer exposure APIs discovered progressively by Tool Search.'
        tools = @(
            @{ type = 'toolbox_search' },
            @{
                type = 'openapi'
                name = 'manufacturing-telemetry'
                openapi = @{
                    name = 'manufacturing-telemetry'
                    description = 'Synthetic measurements, equipment, anomaly, and lot evidence.'
                    spec = $telemetrySpec
                    auth = $connectionAuth
                }
                tool_configs = @{
                    getLotTelemetry = @{
                        additional_search_text = 'factory manufacturing equipment measurements anomaly temperature leakage threshold lot'
                    }
                }
            },
            @{
                type = 'openapi'
                name = 'customer-exposure'
                openapi = @{
                    name = 'customer-exposure'
                    description = 'Fictional orders, customers, inventory, and reallocation evidence.'
                    spec = $exposureSpec
                    auth = $connectionAuth
                }
                tool_configs = @{
                    getLotExposure = @{
                        additional_search_text = 'customer orders inventory demand allocation commercial impact coverage gap substitute'
                    }
                }
            }
        )
    }
if (-not $toolbox.version) {
    throw 'Foundry did not return a Quality toolbox version.'
}
$qualityToolboxEndpoint = "$projectEndpoint/toolboxes/st-iq-v2-quality-operations/versions/$($toolbox.version)/mcp?api-version=v1"

if (-not $SkipBuild) {
    $tag = Get-Date -Format 'yyyyMMddHHmmss'
    Write-Host 'Building immutable shared V2 Hosted Agent image...' -ForegroundColor Cyan
    $Image = New-V2AcrImage -RegistryId $registryId -Repository 'agents/st-iq-v2' `
        -Tag $tag -Dockerfile 'v2/agents/Dockerfile'
}
elseif (-not $Image) {
    $Image = $values.V2_AGENT_IMAGE
}
if (-not $Image -or $Image -notmatch '@sha256:[0-9a-f]{64}$') {
    throw 'V2 agent deployment requires an immutable ACR image digest.'
}

function New-HostedAgent {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][hashtable]$Environment
    )
    $body = @{
        description = $Description
        definition = @{
            kind = 'hosted'
            image = $Image
            cpu = '1'
            memory = '2Gi'
            container_protocol_versions = @(
                @{ protocol = 'responses'; version = '2.0.0' }
            )
            environment_variables = $Environment
        }
    }
    try {
        $existing = Invoke-AzureJson -Method Get `
            -Uri "$projectEndpoint/agents/${Name}?api-version=v1" -Token $aiToken
        $latest = $existing.versions.latest
        $existingEnvironment = $latest.definition.environment_variables
        $environmentMatches = @($Environment.Keys).Count -eq @(
            $existingEnvironment.PSObject.Properties
        ).Count
        foreach ($key in $Environment.Keys) {
            if ([string]$existingEnvironment.$key -ne [string]$Environment[$key]) {
                $environmentMatches = $false
                break
            }
        }
        if (
            $latest.status -eq 'active' -and
            $latest.definition.image -eq $Image -and
            $environmentMatches
        ) {
            return $latest
        }
    }
    catch {
        $statusCode = $_.Exception.Response.StatusCode.value__
        if ($statusCode -ne 404) {
            throw
        }
    }
    try {
        $created = Invoke-AzureJson -Method Post `
            -Uri "$projectEndpoint/agents/$Name/versions?api-version=v1" `
            -Token $aiToken -Body $body
    }
    catch {
        $errorText = $_ | Out-String
        if ($errorText -notmatch 'Missing required query parameter: api-version') {
            throw
        }
        $agent = Invoke-AzureJson -Method Get `
            -Uri "$projectEndpoint/agents/${Name}?api-version=v1" -Token $aiToken
        $created = $agent.versions.latest
    }
    if (-not $created.version -or -not $created.instance_identity.principal_id) {
        throw "Foundry created '$Name' without a version or dedicated identity."
    }
    return $created
}

function Wait-HostedAgent {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Version
    )
    $uri = "$projectEndpoint/agents/$Name/versions/${Version}?api-version=v1"
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        $current = Invoke-AzureJson -Method Get -Uri $uri -Token $aiToken
        Write-Host "Hosted agent $Name version ${Version}: $($current.status)"
        if ($current.status -eq 'active') {
            return $current
        }
        if ($current.status -in @('failed', 'deleted')) {
            throw "Hosted agent '$Name' ended in '$($current.status)'."
        }
        Start-Sleep -Seconds 15
        if (($attempt + 1) % 20 -eq 0) {
            $script:aiToken = Get-AzureAccessToken 'https://ai.azure.com'
        }
    }
    throw "Timed out waiting for Hosted Agent '$Name'."
}

function Enable-AgentA2A {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][string]$SkillId,
        [Parameter(Mandatory)][string]$SkillName
    )
    Invoke-AzureJson -Method Patch -Uri "$projectEndpoint/agents/${Name}?api-version=v1" `
        -Token $aiToken -Body @{
            agent_card = @{
                description = $Description
                version = '1.0'
                skills = @(
                    @{
                        id = $SkillId
                        name = $SkillName
                        description = $Description
                    }
                )
            }
            agent_endpoint = @{
                protocol_configuration = @{
                    responses = @{}
                    a2a = @{}
                }
            }
        } | Out-Null
    $card = Invoke-AzureJson -Method Get `
        -Uri "$projectEndpoint/agents/$Name/endpoint/protocols/a2a/agentCard/v1.0?api-version=v1" `
        -Token $aiToken
    $a2aV1 = @(
        $card.supportedInterfaces |
            Where-Object {
                $_.protocolBinding -eq 'JSONRPC' -and $_.protocolVersion -eq '1.0'
            }
    )
    if ($a2aV1.Count -eq 0) {
        throw "Agent '$Name' did not publish an A2A v1.0 card."
    }
}

function Grant-AgentRoles {
    param(
        [Parameter(Mandatory)][string]$PrincipalId,
        [switch]$A2AConsumer
    )
    Ensure-Role -SubscriptionId $values.AZURE_SUBSCRIPTION_ID `
        -AssigneeObjectId $PrincipalId -RoleName 'Foundry User' `
        -RoleDefinitionId '53ca6127-db72-4b80-b1b0-d745d6d5456d' `
        -Scope $values.FOUNDRY_ACCOUNT_ID
    Ensure-Role -SubscriptionId $values.AZURE_SUBSCRIPTION_ID `
        -AssigneeObjectId $PrincipalId -RoleName 'Search Index Data Reader' `
        -RoleDefinitionId '1407120a-92aa-4202-b7e9-c0e197c71c8f' `
        -Scope $searchId
    if ($A2AConsumer) {
        Ensure-Role -SubscriptionId $values.AZURE_SUBSCRIPTION_ID `
            -AssigneeObjectId $PrincipalId -RoleName 'Foundry Agent Consumer' `
            -RoleDefinitionId 'eed3b665-ab3a-47b6-8f48-c9382fb1dad6' `
            -Scope $values.AZURE_AI_PROJECT_ID
    }
}

$baseEnvironment = @{
    AZURE_AI_MODEL_DEPLOYMENT_NAME = $values.AZURE_AI_MODEL_DEPLOYMENT_NAME
    ENABLE_INSTRUMENTATION = 'true'
    ENABLE_SENSITIVE_DATA = 'false'
    LOG_LEVEL = 'INFO'
}

Write-Host 'Deploying Market specialist...' -ForegroundColor Cyan
$marketEnvironment = $baseEnvironment.Clone()
$marketEnvironment.STIQ_V2_AGENT_ROLE = 'market'
$marketEnvironment.WEB_KNOWLEDGE_MCP_ENDPOINT = $webMcp
$market = New-HostedAgent -Name 'st-iq-market-v2' `
    -Description 'Public Market specialist using Web Knowledge Source (Web IQ fallback).' `
    -Environment $marketEnvironment
Grant-AgentRoles -PrincipalId $market.instance_identity.principal_id
$market = Wait-HostedAgent -Name 'st-iq-market-v2' -Version $market.version
Enable-AgentA2A -Name 'st-iq-market-v2' `
    -Description 'Current public market, regulatory, weather, logistics, and supply research.' `
    -SkillId 'public-market-research' -SkillName 'Public market research'

Write-Host 'Deploying Quality specialist...' -ForegroundColor Cyan
$qualityEnvironment = $baseEnvironment.Clone()
$qualityEnvironment.STIQ_V2_AGENT_ROLE = 'quality'
$qualityEnvironment.STIQ_FOUNDRY_IQ_MCP_ENDPOINT = $searchMcp
$qualityEnvironment.QUALITY_TOOLBOX_ENDPOINT = $qualityToolboxEndpoint
$quality = New-HostedAgent -Name 'st-iq-quality-v2' `
    -Description 'Quality specialist using Foundry IQ plus telemetry and exposure Tool Search.' `
    -Environment $qualityEnvironment
Grant-AgentRoles -PrincipalId $quality.instance_identity.principal_id
$quality = Wait-HostedAgent -Name 'st-iq-quality-v2' -Version $quality.version
Enable-AgentA2A -Name 'st-iq-quality-v2' `
    -Description 'Foundry IQ, manufacturing telemetry, and fictional customer exposure analysis.' `
    -SkillId 'quality-exposure-analysis' -SkillName 'Quality and customer exposure'

$marketA2A = "$projectEndpoint/agents/st-iq-market-v2/endpoint/protocols/a2a"
$qualityA2A = "$projectEndpoint/agents/st-iq-quality-v2/endpoint/protocols/a2a"

Write-Host 'Deploying Commander...' -ForegroundColor Cyan
$commanderEnvironment = $baseEnvironment.Clone()
$commanderEnvironment.STIQ_V2_AGENT_ROLE = 'commander'
$commanderEnvironment.MARKET_A2A_ENDPOINT = $marketA2A
$commanderEnvironment.QUALITY_A2A_ENDPOINT = $qualityA2A
$commander = New-HostedAgent -Name 'st-iq-commander-v2' `
    -Description 'Single-entry Commander with adaptive A2A routing and concurrent fan-out/fan-in.' `
    -Environment $commanderEnvironment
Grant-AgentRoles -PrincipalId $commander.instance_identity.principal_id -A2AConsumer
$commander = Wait-HostedAgent -Name 'st-iq-commander-v2' -Version $commander.version
Enable-AgentA2A -Name 'st-iq-commander-v2' `
    -Description 'Adaptive incident routing and cited parallel A2A assessment synthesis.' `
    -SkillId 'incident-command' -SkillName 'Incident command'

$commanderEndpoint = "$projectEndpoint/agents/st-iq-commander-v2/endpoint/protocols/openai/responses?api-version=v1"
Write-Host 'Invoking the deployed Commander end to end...' -ForegroundColor Cyan
$response = Invoke-AzureJson -Method Post -Uri $commanderEndpoint -Token $aiToken -Body @{
    input = @'
MODE=TASK
run_id=deploy-v2-smoke
incident_id=INC-SIC-0813
correlation_id=deploy-v2-smoke
OBJECTIVE=Assess current public SiC signals and synthetic operational exposure for lot CAT-26-0813-A. Return a cited incident brief and perform no side effects.
'@
}
if ($response.status -ne 'completed') {
    throw "Commander smoke invocation ended in '$($response.status)'."
}
$message = @($response.output | Where-Object type -eq 'message')[-1]
$text = [string]$message.content[0].text
if ($text -notmatch '"citations"' -or $text -notmatch '"send_allowed"\s*:\s*false') {
    throw 'Commander smoke invocation did not return citations and a blocked Teams contract.'
}

Write-Host 'Pointing the V2 presenter at the live Commander...' -ForegroundColor Cyan
az containerapp update --subscription $values.AZURE_SUBSCRIPTION_ID `
    --resource-group $values.AZURE_RESOURCE_GROUP --name 'st-iq-commander-v2' `
    --set-env-vars "FOUNDRY_V2_COMMANDER_ENDPOINT=$commanderEndpoint" `
    --only-show-errors | Out-Null
Assert-NativeSuccess 'Updating the V2 presenter Commander endpoint'

$envValues = @{
    V2_AGENT_IMAGE = $Image
    V2_QUALITY_TOOLBOX_ENDPOINT = $qualityToolboxEndpoint
    V2_QUALITY_TOOLBOX_VERSION = [string]$toolbox.version
    V2_MARKET_AGENT_VERSION = [string]$market.version
    V2_QUALITY_AGENT_VERSION = [string]$quality.version
    V2_COMMANDER_AGENT_VERSION = [string]$commander.version
    V2_MARKET_A2A_ENDPOINT = $marketA2A
    V2_QUALITY_A2A_ENDPOINT = $qualityA2A
    FOUNDRY_V2_COMMANDER_ENDPOINT = $commanderEndpoint
}
foreach ($item in $envValues.GetEnumerator()) {
    azd env set $item.Key $item.Value | Out-Null
}

$status = $null
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $status = Invoke-RestMethod "$($values.V2_APP_URL)/api/v2/status" -TimeoutSec 30
        $commanderStatus = @($status.adapters | Where-Object name -eq 'Commander / Router V2')[0]
        if ($commanderStatus.mode -eq 'live-hosted-a2a') {
            break
        }
    }
    catch {
        Start-Sleep -Seconds 5
    }
}
if ($commanderStatus.mode -ne 'live-hosted-a2a') {
    throw 'The V2 presenter did not switch to live Hosted A2A mode.'
}

Write-Host "`nThree isolated V2 Hosted Agents are active and verified." -ForegroundColor Green
Write-Host "Commander: $commanderEndpoint"
Write-Host "Market A2A: $marketA2A"
Write-Host "Quality A2A: $qualityA2A"
Write-Host "Presenter Chat: $($values.V2_APP_URL)/v2/chat"
Write-Host "Presenter Tasks: $($values.V2_APP_URL)/v2/tasks"
Write-Host 'Next: .\scripts\v2\evaluate.ps1'
