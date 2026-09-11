[CmdletBinding()]
param(
    [string]$TenantId = '11111111-1111-1111-1111-111111111111',
    [string]$SubscriptionId = '00000000-0000-0000-0000-000000000000',
    [string]$ResourceGroup = 'rg-st-iq-demo',
    [string]$FoundryAccountName = 'stiqdemo-foundry',
    [string]$FoundryProjectName = 'st-iq-demo',
    [string]$EnvironmentName = 'st-iq-public-demo',
    [string]$ExpectedUserPrincipalName = 'presenter@contoso.onmicrosoft.com',
    [string]$OneDriveConnectionName = 'WorkIqOneDriveConnection',
    [string]$TeamsConnectionName = 'WorkIqTeamsConnection',
    [string]$OneDriveToolboxName = 'st-iq-workiq-onedrive-toolbox',
    [string]$TeamsToolboxName = 'st-iq-workiq-teams-toolbox',
    [string]$TeamsRecipientUpn = 'presenter@contoso.com',
    [switch]$DoNotOpenConsent
)

$ErrorActionPreference = 'Stop'
$oneDriveEndpoint = 'https://agent365.svc.cloud.microsoft/agents/servers/mcp_OneDriveRemoteServer'
$teamsEndpoint = 'https://agent365.svc.cloud.microsoft/agents/servers/mcp_TeamsServer'
$projectEndpoint = "https://$FoundryAccountName.services.ai.azure.com/api/projects/$FoundryProjectName"
$projectId = (
    "/subscriptions/$SubscriptionId/resourceGroups/$ResourceGroup/providers/" +
    "Microsoft.CognitiveServices/accounts/$FoundryAccountName/projects/$FoundryProjectName"
)

function Assert-NativeSuccess {
    param([Parameter(Mandatory)][string]$Operation)
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed."
    }
}

function Get-AccessToken {
    [string]$token = (
        az account get-access-token --resource https://ai.azure.com --tenant $TenantId `
            --query accessToken -o tsv --only-show-errors | Select-Object -Last 1
    )
    Assert-NativeSuccess 'Acquiring a Foundry access token'
    if (-not $token) {
        throw 'Foundry token acquisition returned no token.'
    }
    return $token
}

function Invoke-FoundryJson {
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
            Authorization = ('Bear' + 'er ' + $Token)
            Accept = 'application/json, text/event-stream'
            'Foundry-Features' = 'Toolboxes=V1Preview'
        }
    }
    if ($null -ne $Body) {
        $parameters.ContentType = 'application/json'
        $parameters.Body = $Body | ConvertTo-Json -Depth 20 -Compress
    }
    Invoke-RestMethod @parameters
}

function Get-ProjectConnection {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][object[]]$Connections
    )

    $matches = @($Connections | Where-Object name -eq $Name)
    if ($matches.Count -ne 1) {
        throw "Expected exactly one Foundry connection named '$Name', found $($matches.Count)."
    }
    return $matches[0]
}

function New-ToolboxVersion {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Description,
        [Parameter(Mandatory)][hashtable]$Tool,
        [Parameter(Mandatory)][string]$Token
    )

    $created = Invoke-FoundryJson -Method Post `
        -Uri "$projectEndpoint/toolboxes/$Name/versions?api-version=v1" `
        -Token $Token -Body @{
            description = $Description
            tools = @($Tool)
        }
    if (-not $created.version) {
        throw "Foundry created toolbox '$Name' but returned no version."
    }
    return "$projectEndpoint/toolboxes/$Name/versions/$($created.version)/mcp?api-version=v1"
}

function Test-ToolboxContract {
    param(
        [Parameter(Mandatory)][string]$Endpoint,
        [Parameter(Mandatory)][string]$Token,
        [Parameter(Mandatory)][string[]]$ExpectedToolNames,
        [Parameter(Mandatory)][string]$Purpose
    )

    $response = Invoke-FoundryJson -Method Post -Uri $Endpoint -Token $Token -Body @{
        jsonrpc = '2.0'
        id = "st-iq-$Purpose-tools"
        method = 'tools/list'
        params = @{}
    }
    if ($response.error.code -eq -32006) {
        $consentMatch = [regex]::Match([string]$response.error.message, 'https://[^"\s]+')
        if ($consentMatch.Success -and -not $DoNotOpenConsent) {
            Start-Process $consentMatch.Value
        }
        throw (
            "The $Purpose toolbox requires delegated consent for $ExpectedUserPrincipalName. " +
            'Complete the Foundry consent flow, then rerun this script.'
        )
    }
    if ($response.error) {
        throw "$Purpose toolbox enumeration failed: $($response.error.message)"
    }
    $actual = @($response.result.tools | ForEach-Object name | Sort-Object)
    $difference = @(Compare-Object @($ExpectedToolNames | Sort-Object) $actual)
    if ($difference.Count -gt 0) {
        throw "$Purpose toolbox has an unexpected tool contract: $($actual -join ', ')"
    }
}

$account = az account show | ConvertFrom-Json
Assert-NativeSuccess 'Inspecting the active Azure account'
if ($account.tenantId -ne $TenantId -or $account.id -ne $SubscriptionId) {
    throw "Azure CLI must target tenant $TenantId and subscription $SubscriptionId."
}
if ($account.user.name -ne $ExpectedUserPrincipalName) {
    throw "Azure CLI must be signed in as $ExpectedUserPrincipalName, not $($account.user.name)."
}

$connections = az rest --method get `
    --url "https://management.azure.com${projectId}/connections?api-version=2026-05-01" `
    -o json --only-show-errors | ConvertFrom-Json
Assert-NativeSuccess 'Enumerating Foundry project connections'
$oneDriveConnection = Get-ProjectConnection -Name $OneDriveConnectionName -Connections $connections.value
$teamsConnection = Get-ProjectConnection -Name $TeamsConnectionName -Connections $connections.value

if (
    $oneDriveConnection.properties.authType -ne 'UserEntraToken' -or
    $oneDriveConnection.properties.category -ne 'RemoteTool' -or
    $oneDriveConnection.properties.target -ne $oneDriveEndpoint -or
    $oneDriveConnection.properties.isSharedToAll -ne $false
) {
    throw "Connection '$OneDriveConnectionName' is not the expected private OneDrive MCP tool."
}
if (
    $teamsConnection.properties.authType -ne 'UserEntraToken' -or
    $teamsConnection.properties.category -ne 'RemoteTool' -or
    $teamsConnection.properties.target -ne $teamsEndpoint -or
    $teamsConnection.properties.isSharedToAll -ne $false
) {
    throw "Connection '$TeamsConnectionName' is not the expected private Teams MCP tool."
}

$aiToken = Get-AccessToken
$oneDriveTools = @(
    'getOnedrive',
    'getFolderChildrenInMyOnedrive',
    'getFileOrFolderMetadataInMyOnedrive'
)
$oneDriveToolboxEndpoint = New-ToolboxVersion -Name $OneDriveToolboxName `
    -Description (
        'Private read-only OneDrive access for deterministic analysis of the synthetic ' +
        'ST-IQ-Demo shipment workbook; no write, move, share, rename, or delete tools.'
    ) `
    -Token $aiToken -Tool @{
        type = 'mcp'
        server_label = $OneDriveConnectionName
        server_url = $oneDriveEndpoint
        require_approval = 'never'
        allowed_tools = $oneDriveTools
        project_connection_id = "$projectId/connections/$OneDriveConnectionName"
    }
$teamsToolboxEndpoint = New-ToolboxVersion -Name $TeamsToolboxName `
    -Description 'Approval-gated direct Teams delivery through the user-tested Teams MCP tool' `
    -Token $aiToken -Tool @{
        type = 'mcp'
        server_label = $TeamsConnectionName
        server_url = $teamsEndpoint
        require_approval = 'never'
        allowed_tools = @('SendMessageToUser')
        project_connection_id = "$projectId/connections/$TeamsConnectionName"
    }

azd env select $EnvironmentName --no-prompt | Out-Null
Assert-NativeSuccess "Selecting azd environment '$EnvironmentName'"
foreach ($value in @{
    WORK_IQ_ONEDRIVE_CONNECTION_NAME = $OneDriveConnectionName
    WORK_IQ_TEAMS_CONNECTION_NAME = $TeamsConnectionName
    WORK_IQ_ONEDRIVE_TOOLBOX_ENDPOINT = $oneDriveToolboxEndpoint
    WORK_IQ_TEAMS_TOOLBOX_ENDPOINT = $teamsToolboxEndpoint
    WORK_IQ_TEAMS_SEND_TOOL = "${TeamsConnectionName}___SendMessageToUser"
    WORK_IQ_EXPECTED_USER_UPN = $ExpectedUserPrincipalName
    STIQ_TEAMS_RECIPIENT_UPN = $TeamsRecipientUpn
}.GetEnumerator()) {
    azd env set $value.Key $value.Value | Out-Null
    Assert-NativeSuccess "Persisting $($value.Key)"
}

Test-ToolboxContract -Endpoint $teamsToolboxEndpoint -Token $aiToken `
    -ExpectedToolNames @("${TeamsConnectionName}___SendMessageToUser") `
    -Purpose 'teams'
Test-ToolboxContract -Endpoint $oneDriveToolboxEndpoint -Token $aiToken `
    -ExpectedToolNames @($oneDriveTools | ForEach-Object { "${OneDriveConnectionName}___$_" }) `
    -Purpose 'onedrive'

Write-Host 'User-tested Work IQ and Teams connections are ready for V1.' -ForegroundColor Green
Write-Host "OneDrive toolbox: $oneDriveToolboxEndpoint"
Write-Host "Teams toolbox: $teamsToolboxEndpoint"
Write-Host "Direct Teams recipient: $TeamsRecipientUpn"
Write-Host 'No Microsoft 365 content was fetched and no Teams message was sent.'
