[CmdletBinding()]
param(
    [string]$EnvironmentName = 'st-iq-demo',
    [string]$AppName = 'st-iq-operations',
    [switch]$EnableDelegatedFabricIq,
    [switch]$EnableDelegatedTeamsSend,
    [switch]$SkipBuild,
    [string]$Image
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

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
        [Parameter(Mandatory)][ValidateSet('Get', 'Post')][string]$Method,
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][string]$Token,
        [object]$Body
    )
    $parameters = @{
        Method = $Method
        Uri = $Uri
        Headers = @{
            Authorization = 'Bear' + 'er ' + $Token
            'Content-Type' = 'application/json'
        }
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

function New-WebImage {
    param(
        [Parameter(Mandatory)][string]$RegistryId,
        [Parameter(Mandatory)][string]$Repository,
        [Parameter(Mandatory)][string]$Tag
    )
    $apiVersion = '2019-06-01-preview'
    $armToken = Get-AzureAccessToken 'https://management.azure.com'
    $upload = Invoke-AzureJson -Method Post `
        -Uri "https://management.azure.com${RegistryId}/listBuildSourceUploadUrl?api-version=$apiVersion" `
        -Token $armToken

    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) "st-iq-web-$([guid]::NewGuid())"
    $sourceRoot = Join-Path $tempRoot 'source'
    $archive = Join-Path $tempRoot 'source.tar.gz'
    try {
        New-Item -ItemType Directory -Path $sourceRoot -Force | Out-Null
        Copy-Item '.\pyproject.toml' $sourceRoot
        Copy-Item '.\app' $sourceRoot -Recurse
        $dataTarget = Join-Path $sourceRoot 'data'
        New-Item -ItemType Directory -Path $dataTarget -Force | Out-Null
        Copy-Item '.\data\v1' $dataTarget -Recurse

        & tar -czf $archive -C $sourceRoot .
        Assert-NativeSuccess 'Web source archive creation'
        Invoke-WebRequest -Method Put -Uri $upload.uploadUrl -InFile $archive `
            -Headers @{ 'x-ms-blob-type' = 'BlockBlob' } | Out-Null

        $request = @{
            type = 'DockerBuildRequest'
            dockerFilePath = 'app/Dockerfile.web'
            imageNames = @("${Repository}:$Tag")
            isPushEnabled = $true
            noCache = $false
            sourceLocation = $upload.relativePath
            platform = @{
                os = 'Linux'
                architecture = 'amd64'
            }
            credentials = @{
                sourceRegistry = @{
                    identity = '[caller]'
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
            throw 'ACR accepted the web build but returned no run ID.'
        }

        $runUri = "https://management.azure.com${RegistryId}/runs/${runId}?api-version=$apiVersion"
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            $runResponse = Invoke-AzureJson -Method Get -Uri $runUri -Token $armToken
            $status = if ($runResponse.properties) { $runResponse.properties } else { $runResponse }
            Write-Host "ACR web run ${runId}: $($status.status)"
            if ($status.status -eq 'Succeeded') {
                $output = @($status.outputImages)[0]
                if (-not $output.digest) {
                    throw "ACR web run ${runId} returned no image digest."
                }
                return "$($output.registry)/$($output.repository)@$($output.digest)"
            }
            if ($status.status -in @('Failed', 'Canceled', 'Error', 'Timeout')) {
                throw "ACR web run ${runId} ended in $($status.status): $($status.runErrorMessage)"
            }
            Start-Sleep -Seconds 10
            if (($attempt + 1) % 30 -eq 0) {
                $armToken = Get-AzureAccessToken 'https://management.azure.com'
            }
        }
        throw "Timed out waiting for ACR web run ${runId}."
    }
    finally {
        if (Test-Path $tempRoot) {
            Remove-Item $tempRoot -Recurse -Force
        }
    }
}

azd env select $EnvironmentName --no-prompt | Out-Null
Assert-NativeSuccess "Selecting azd environment '$EnvironmentName'"
$values = azd env get-values -o json | ConvertFrom-Json
foreach ($required in @(
    'AZURE_SUBSCRIPTION_ID',
    'AZURE_TENANT_ID',
    'AZURE_RESOURCE_GROUP',
    'AZURE_LOCATION',
    'AZURE_AI_PROJECT_ENDPOINT',
    'AZURE_CONTAINER_REGISTRY_NAME',
    'FOUNDRY_ACCOUNT_NAME',
    'FOUNDRY_PROJECT_NAME',
    'LOG_ANALYTICS_NAME',
    'CONTAINER_APPS_ENVIRONMENT_NAME'
)) {
    if (-not $values.$required) {
        throw "Missing azd value '$required'. Run setup.ps1 and deploy-agent.ps1 first."
    }
}

foreach ($provider in @('Microsoft.App', 'Microsoft.ManagedIdentity')) {
    $state = az provider show --subscription $values.AZURE_SUBSCRIPTION_ID `
        --namespace $provider --query registrationState -o tsv
    Assert-NativeSuccess "Inspecting provider $provider"
    if ($state -ne 'Registered') {
        az provider register --subscription $values.AZURE_SUBSCRIPTION_ID `
            --namespace $provider --wait --only-show-errors
        Assert-NativeSuccess "Registering provider $provider"
    }
}

$registryId = "/subscriptions/$($values.AZURE_SUBSCRIPTION_ID)/resourceGroups/$($values.AZURE_RESOURCE_GROUP)/providers/Microsoft.ContainerRegistry/registries/$($values.AZURE_CONTAINER_REGISTRY_NAME)"
if (-not $SkipBuild) {
    $tag = Get-Date -Format 'yyyyMMddHHmmss'
    Write-Host "Building immutable web image apps/st-iq-operations:$tag..." -ForegroundColor Cyan
    $Image = New-WebImage -RegistryId $registryId -Repository 'apps/st-iq-operations' -Tag $tag
}
elseif (-not $Image) {
    $Image = $values.WEB_APP_IMAGE
}
if (-not $Image -or $Image -notmatch '@sha256:[0-9a-f]{64}$') {
    throw 'Web deployment requires an immutable ACR image digest.'
}

$deploymentName = "st-iq-web-{0}" -f (Get-Date -Format 'yyyyMMddHHmmss')
$sharePointMode = if ($values.SHAREPOINT_KNOWLEDGE_MODE) {
    $values.SHAREPOINT_KNOWLEDGE_MODE
}
else {
    'blocked'
}
$sharePointReason = if ($values.SHAREPOINT_KNOWLEDGE_REASON) {
    $values.SHAREPOINT_KNOWLEDGE_REASON
}
else {
    'No approved SharePoint document library has been synchronized.'
}
$workIqBlockerReason = if ($values.WORK_IQ_BLOCKER_REASON) {
    $values.WORK_IQ_BLOCKER_REASON
}
else {
    'Work IQ delegated OAuth is not configured for this deployment.'
}
$evaluationSummaryFile = if ($EnvironmentName -eq 'st-iq-demo') {
    'evaluation-summary.json'
}
else {
    "evaluation-summary.$EnvironmentName.json"
}
if (-not (Test-Path ".\app\$evaluationSummaryFile")) {
    $evaluationSummaryFile = 'evaluation-summary.json'
}
$fabricToolArgumentsBase64 = if ($values.FABRIC_IQ_TOOL_ARGUMENTS_JSON) {
    [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes([string]$values.FABRIC_IQ_TOOL_ARGUMENTS_JSON)
    )
}
else {
    ''
}
$fabricAccessToken = ''
if ($EnableDelegatedFabricIq) {
    $account = az account show | ConvertFrom-Json
    Assert-NativeSuccess 'Inspecting the delegated Fabric presenter'
    if (
        $account.tenantId -ne $values.AZURE_TENANT_ID -or
        -not $values.WORK_IQ_EXPECTED_USER_UPN -or
        $account.user.name -ne $values.WORK_IQ_EXPECTED_USER_UPN
    ) {
        throw (
            'Delegated Fabric IQ deployment requires Azure CLI signed in as ' +
            "$($values.WORK_IQ_EXPECTED_USER_UPN) in the configured tenant."
        )
    }
    $fabricAccessToken = Get-AzureAccessToken 'https://api.fabric.microsoft.com'
}
$teamsAccessToken = ''
$teamsAccessTokenExpiresAt = ''
$teamsApprovalCode = ''
if ($EnableDelegatedTeamsSend) {
    $requiredTeamsValues = @(
        'WORK_IQ_TEAMS_TOOLBOX_ENDPOINT',
        'WORK_IQ_TEAMS_SEND_TOOL',
        'STIQ_TEAMS_RECIPIENT_UPN'
    )
    $missingTeamsValues = @(
        $requiredTeamsValues |
            Where-Object { -not $values.PSObject.Properties[$_].Value }
    )
    if ($missingTeamsValues) {
        throw (
            'Delegated Teams delivery is missing azd values: ' +
            ($missingTeamsValues -join ', ') +
            '. Run .\scripts\setup-work-iq-foundry.ps1 first.'
        )
    }
    $account = az account show | ConvertFrom-Json
    Assert-NativeSuccess 'Inspecting the delegated Teams presenter'
    if (
        $account.tenantId -ne $values.AZURE_TENANT_ID -or
        -not $values.WORK_IQ_EXPECTED_USER_UPN -or
        $account.user.name -ne $values.WORK_IQ_EXPECTED_USER_UPN
    ) {
        throw (
            'Delegated Teams deployment requires Azure CLI signed in as ' +
            "$($values.WORK_IQ_EXPECTED_USER_UPN) in the configured tenant."
        )
    }
    $teamsAccessToken = Get-AzureAccessToken 'https://ai.azure.com'
    $tokenParts = $teamsAccessToken.Split('.')
    if ($tokenParts.Count -ne 3) {
        throw 'The delegated Teams access token is not a JWT and its expiry cannot be verified.'
    }
    $payloadSegment = $tokenParts[1].Replace('-', '+').Replace('_', '/')
    $payloadSegment += '=' * ((4 - $payloadSegment.Length % 4) % 4)
    $tokenPayload = [Text.Encoding]::UTF8.GetString(
        [Convert]::FromBase64String($payloadSegment)
    ) | ConvertFrom-Json
    if (-not $tokenPayload.exp) {
        throw 'The delegated Teams access token has no expiry claim.'
    }
    $teamsAccessTokenExpiresAt = [string]$tokenPayload.exp
    $teamsProbe = Invoke-RestMethod -Method Post `
        -Uri $values.WORK_IQ_TEAMS_TOOLBOX_ENDPOINT `
        -Headers @{
            Authorization = 'Bear' + 'er ' + $teamsAccessToken
            Accept = 'application/json, text/event-stream'
            'Foundry-Features' = 'Toolboxes=V1Preview'
        } `
        -ContentType 'application/json' `
        -Body (@{
            jsonrpc = '2.0'
            id = 'teams-deployment-contract'
            method = 'tools/list'
            params = @{}
        } | ConvertTo-Json -Compress)
    if ($teamsProbe.error) {
        throw "Work IQ Teams toolbox probe failed: $($teamsProbe.error.message)"
    }
    $advertisedTeamsTools = @($teamsProbe.result.tools | ForEach-Object name)
    if ($advertisedTeamsTools -notcontains $values.WORK_IQ_TEAMS_SEND_TOOL) {
        throw (
            "Work IQ Teams toolbox does not advertise '$($values.WORK_IQ_TEAMS_SEND_TOOL)'."
        )
    }
    $teamsApprovalCode = [Convert]::ToHexString(
        [Security.Cryptography.RandomNumberGenerator]::GetBytes(12)
    )
}
$internalApiKey = [Convert]::ToBase64String(
    [Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
)
Write-Host "Deploying public Container App $AppName..." -ForegroundColor Cyan
$secretParameters = Join-Path ([IO.Path]::GetTempPath()) "st-iq-web-secrets-$([guid]::NewGuid()).json"
try {
    $secretDocument = @{
        '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
        contentVersion = '1.0.0.0'
        parameters = @{
            internalApiKey = @{ value = $internalApiKey }
            fabricIqAccessToken = @{ value = $fabricAccessToken }
            workIqAccessToken = @{ value = $teamsAccessToken }
            teamsApprovalCode = @{ value = $teamsApprovalCode }
        }
    } | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($secretParameters, $secretDocument)
    $outputs = az deployment group create --subscription $values.AZURE_SUBSCRIPTION_ID `
        --resource-group $values.AZURE_RESOURCE_GROUP --name $deploymentName `
        --template-file '.\infra\web.bicep' --parameters "@$secretParameters" `
        --parameters "location=$($values.AZURE_LOCATION)" "appName=$AppName" `
        "deploymentNonce=$deploymentName" `
        "containerImage=$Image" "foundryAgentEndpoint=$($values.HOSTED_AGENT_ENDPOINT)" `
        "foundryProjectEndpoint=$($values.AZURE_AI_PROJECT_ENDPOINT)" `
        "foundryAccountName=$($values.FOUNDRY_ACCOUNT_NAME)" `
        "foundryProjectName=$($values.FOUNDRY_PROJECT_NAME)" `
        "registryName=$($values.AZURE_CONTAINER_REGISTRY_NAME)" `
        "logAnalyticsName=$($values.LOG_ANALYTICS_NAME)" `
        "environmentName=$($values.CONTAINER_APPS_ENVIRONMENT_NAME)" `
        "sharePointKnowledgeMode=$sharePointMode" `
        "sharePointKnowledgeReason=$sharePointReason" `
        "workIqBlockerReason=$workIqBlockerReason" `
        "fabricIqMcpEndpoint=$($values.FABRIC_IQ_MCP_ENDPOINT)" `
        "fabricIqToolName=$($values.FABRIC_IQ_TOOL_NAME)" `
        "fabricIqToolArgumentsBase64=$fabricToolArgumentsBase64" `
        "workIqOneDriveToolboxEndpoint=$($values.WORK_IQ_ONEDRIVE_TOOLBOX_ENDPOINT)" `
        "workIqTeamsToolboxEndpoint=$($values.WORK_IQ_TEAMS_TOOLBOX_ENDPOINT)" `
        "workIqTeamsSendTool=$($values.WORK_IQ_TEAMS_SEND_TOOL)" `
        "teamsRecipientUpn=$($values.STIQ_TEAMS_RECIPIENT_UPN)" `
        "workIqAccessTokenExpiresAt=$teamsAccessTokenExpiresAt" `
        "evaluationSummaryFile=$evaluationSummaryFile" `
        --query properties.outputs -o json | ConvertFrom-Json
    Assert-NativeSuccess 'Deploying the web Container App'
}
finally {
    if (Test-Path $secretParameters) {
        Remove-Item $secretParameters -Force
    }
    $secretDocument = $null
}

$url = $outputs.WEB_APP_URL.value
if (-not $url) {
    throw 'Container App deployment returned no public URL.'
}
azd env set WEB_APP_URL $url | Out-Null
azd env set WEB_APP_IMAGE $Image | Out-Null
azd env set V1_INTERNAL_CONNECTION_ID $outputs.V1_INTERNAL_CONNECTION_ID.value | Out-Null

$fabricConfigured = (
    $values.FABRIC_WORKSPACE_ID -and
    $values.FABRIC_IQ_MCP_ENDPOINT -and
    $values.FABRIC_IQ_TOOL_NAME -and
    $values.FABRIC_IQ_TOOL_ARGUMENTS_JSON
)
if ($fabricConfigured) {
    $webPrincipal = $outputs.WEB_APP_IDENTITY_PRINCIPAL_ID.value
    if (-not $webPrincipal) {
        throw 'Container App deployment returned no managed identity principal ID.'
    }
    $fabricToken = Get-AzureAccessToken 'https://api.fabric.microsoft.com'
    $fabricRoleUri = (
        "https://api.fabric.microsoft.com/v1/workspaces/" +
        "$($values.FABRIC_WORKSPACE_ID)/roleAssignments"
    )
    $fabricRoles = Invoke-AzureJson -Method Get -Uri $fabricRoleUri -Token $fabricToken
    $existingFabricRole = @(
        $fabricRoles.value |
            Where-Object {
                $_.principal.id -eq $webPrincipal -and
                $_.role -in @('Contributor', 'Member', 'Admin')
            }
    )[0]
    if (-not $existingFabricRole) {
        Invoke-AzureJson -Method Post -Uri $fabricRoleUri -Token $fabricToken -Body @{
            principal = @{
                id = $webPrincipal
                type = 'ServicePrincipal'
            }
            role = 'Contributor'
        } | Out-Null
    }
}

Write-Host "Waiting for $url/health..." -ForegroundColor Cyan
$health = $null
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    try {
        $health = Invoke-RestMethod "$url/health" -TimeoutSec 10
        if ($health.status -eq 'ok') {
            break
        }
    }
    catch {
        Start-Sleep -Seconds 5
    }
}
if (-not $health -or $health.status -ne 'ok' -or $health.mode -ne 'live-configured') {
    throw 'The public Container App did not become healthy in live-configured mode.'
}

$foundry = $null
if ($values.HOSTED_AGENT_ENDPOINT) {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $status = Invoke-RestMethod "$url/api/preflight" -TimeoutSec 30
        $foundry = @($status.adapters | Where-Object name -eq 'Adaptive Foundry workflow')[0]
        if ($foundry.mode -eq 'live') {
            break
        }
        Start-Sleep -Seconds 2
    }
    if ($foundry.mode -ne 'live') {
        throw "Public app is healthy but Foundry mode is '$($foundry.mode)'."
    }
}
else {
    Write-Warning (
        'HOSTED_AGENT_ENDPOINT is not set. This bootstrap deployment creates the protected ' +
        'internal APIs; run deploy-agent.ps1 and then deploy-web.ps1 again.'
    )
}
$internalHeaders = @{
    'X-STIQ-API-Key' = $internalApiKey
    'X-Correlation-ID' = 'deploy-web-contract'
}
function Invoke-InternalContract {
    param([Parameter(Mandatory)][string]$Uri)
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            return Invoke-RestMethod $Uri -Headers $internalHeaders -TimeoutSec 120
        }
        catch {
            if ($attempt -eq 29) {
                throw
            }
            Start-Sleep -Seconds 5
        }
    }
}
$fabricContract = Invoke-InternalContract "$url/internal/fabric/lots/SiC-AUTO-2451"
if (-not $fabricContract.synthetic -or -not $fabricContract.ontology_path) {
    throw 'The authenticated Fabric IQ internal tool contract did not validate.'
}
$exposureContract = Invoke-InternalContract `
    "$url/internal/onedrive/lots/SiC-AUTO-2451/exposure"
if (
    $exposureContract.units_in_field -ne 22500 -or
    $exposureContract.blockable_stock -ne 13200 -or
    $exposureContract.containment_perimeter_pct -ne 65.9
) {
    throw 'The authenticated OneDrive workbook analysis contract did not validate.'
}
$internalApiKey = $null

Write-Host "`nPublic ST IQ Operations Assistant deployed successfully." -ForegroundColor Green
Write-Host "URL: $url/tasks"
Write-Host "Chat: $url/chat"
Write-Host "History: $url/history"
Write-Host "Evaluation: $url/evaluation"
$fabricState = if ($fabricContract.live_error) {
    "fallback ($($fabricContract.live_error))"
}
else {
    "live ($($fabricContract.source))"
}
$oneDriveState = if ($exposureContract.live_error) {
    "fallback ($($exposureContract.live_error))"
}
else {
    "live ($($exposureContract.source))"
}
Write-Host "Fabric IQ contract: authenticated, $fabricState"
Write-Host "OneDrive contract: authenticated, $oneDriveState"
Write-Host "Image: $Image"
if ($EnableDelegatedTeamsSend) {
    Write-Host (
        'Presenter Teams approval code (valid for this deployment only): ' +
        $teamsApprovalCode
    ) -ForegroundColor Yellow
}
