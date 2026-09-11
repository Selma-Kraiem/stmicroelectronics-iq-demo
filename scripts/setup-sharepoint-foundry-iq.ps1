[CmdletBinding()]
param(
    [string]$EnvironmentName = 'st-iq-public-demo',
    [string]$RemoteSourceName = 'st-iq-sharepoint-remote',
    [string]$ValidationKnowledgeBaseName = 'st-iq-sharepoint-validation-base',
    [string]$FilterExpression = $env:STIQ_SHAREPOINT_FILTER_EXPRESSION,
    [string]$ProbeQuery = 'What immediate containment steps apply to an automotive SiC excursion?',
    [switch]$PromoteToActiveKnowledgeBase
)

$ErrorActionPreference = 'Stop'

function Get-AzdValues {
    $raw = azd env get-values --environment $EnvironmentName
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read azd environment '$EnvironmentName'."
    }
    $values = @{}
    foreach ($line in $raw) {
        if ($line -match '^([^=]+)="(.*)"$') {
            $values[$matches[1]] = $matches[2]
        }
    }
    return $values
}

function Invoke-SearchJson {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('GET', 'PUT', 'POST')][string]$Method,
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$SearchToken,
        [object]$Body,
        [string]$QuerySourceAuthorization
    )
    $headers = @{ Authorization = "Bearer $SearchToken" }
    if ($QuerySourceAuthorization) {
        $headers['x-ms-query-source-authorization'] = $QuerySourceAuthorization
    }
    $request = @{
        Method      = $Method
        Uri         = $Uri
        Headers     = $headers
        ContentType = 'application/json'
    }
    if ($null -ne $Body) {
        $request.Body = $Body | ConvertTo-Json -Depth 20
    }
    return Invoke-RestMethod @request
}

function New-KnowledgeBaseBody {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][object]$Template,
        [Parameter(Mandatory = $true)][object[]]$KnowledgeSources
    )
    $body = [ordered]@{
        name             = $Name
        description      = $Template.description
        knowledgeSources = $KnowledgeSources
        models           = @($Template.models)
    }
    foreach ($property in @(
        'retrievalInstructions',
        'answerInstructions',
        'outputMode',
        'retrievalReasoningEffort'
    )) {
        if ($null -ne $Template.$property) {
            $body[$property] = $Template.$property
        }
    }
    return $body
}

if (-not $FilterExpression) {
    throw @'
STIQ_SHAREPOINT_FILTER_EXPRESSION is required. Use a narrow KQL filter, for example:
Path:"https://contoso.sharepoint.com/sites/<site>/Shared Documents/Quality Ops"
AND (FileExtension:"docx" OR FileExtension:"pdf")
'@
}
if ($FilterExpression -notmatch '(?i)(Path|SiteID):') {
    throw 'The SharePoint filter must constrain Path or SiteID; broad tenant search is refused.'
}

azd env select $EnvironmentName | Out-Null
$values = Get-AzdValues
foreach ($required in @('AZURE_SEARCH_ENDPOINT', 'KNOWLEDGE_BASE_NAME')) {
    if (-not $values[$required]) {
        throw "Missing required azd value '$required'."
    }
}

$apiVersion = '2026-05-01-preview'
$searchEndpoint = $values.AZURE_SEARCH_ENDPOINT.TrimEnd('/')
$searchToken = az account get-access-token `
    --resource https://search.azure.com `
    --query accessToken `
    --output tsv
if ($LASTEXITCODE -ne 0 -or -not $searchToken) {
    throw 'Unable to acquire an Azure AI Search token.'
}
$querySourceToken = az account get-access-token `
    --scope https://search.azure.com/.default `
    --query accessToken `
    --output tsv
if ($LASTEXITCODE -ne 0 -or -not $querySourceToken) {
    throw 'Unable to acquire the delegated Search-scoped user token required by SharePoint.'
}

$sourceBody = [ordered]@{
    name                       = $RemoteSourceName
    kind                       = 'remoteSharePoint'
    description                = (
        'Permission-trimmed SharePoint procedures for the fictional ST SiC incident demo. ' +
        'Queried live through the Copilot Retrieval API under the signed-in user.'
    )
    encryptionKey              = $null
    remoteSharePointParameters = @{
        filterExpression = $FilterExpression
        resourceMetadata = @('Author', 'Title')
        containerTypeId  = $null
    }
}
$null = Invoke-SearchJson `
    -Method PUT `
    -Uri "$searchEndpoint/knowledgesources/$RemoteSourceName`?api-version=$apiVersion" `
    -SearchToken $searchToken `
    -Body $sourceBody

$activeKnowledgeBaseUri = (
    "$searchEndpoint/knowledgebases/$($values.KNOWLEDGE_BASE_NAME)" +
    "?api-version=$apiVersion"
)
$activeKnowledgeBase = Invoke-SearchJson `
    -Method GET `
    -Uri $activeKnowledgeBaseUri `
    -SearchToken $searchToken
$validationBody = New-KnowledgeBaseBody `
    -Name $ValidationKnowledgeBaseName `
    -Template $activeKnowledgeBase `
    -KnowledgeSources @(@{ name = $RemoteSourceName })
$null = Invoke-SearchJson `
    -Method PUT `
    -Uri (
        "$searchEndpoint/knowledgebases/$ValidationKnowledgeBaseName" +
        "?api-version=$apiVersion"
    ) `
    -SearchToken $searchToken `
    -Body $validationBody

$probeBody = @{
    messages = @(
        @{
            role    = 'user'
            content = @(@{ type = 'text'; text = $ProbeQuery })
        }
    )
    knowledgeSourceParams = @(
        @{
            knowledgeSourceName = $RemoteSourceName
            kind                = 'remoteSharePoint'
        }
    )
}
try {
    $probe = Invoke-SearchJson `
        -Method POST `
        -Uri (
            "$searchEndpoint/knowledgebases/$ValidationKnowledgeBaseName/retrieve" +
            "?api-version=$apiVersion"
        ) `
        -SearchToken $searchToken `
        -QuerySourceAuthorization $querySourceToken `
        -Body $probeBody
} catch {
    azd env set SHAREPOINT_KNOWLEDGE_MODE 'blocked' | Out-Null
    azd env set SHAREPOINT_KNOWLEDGE_REASON (
        'Native remote SharePoint source exists, but delegated retrieval failed. ' +
        'Verify same-tenant Microsoft 365 Copilot licensing, the KQL path filter, and ' +
        'x-ms-query-source-authorization support. ' + $_.Exception.Message
    ) | Out-Null
    throw
}

$referenceCount = @($probe.references | Where-Object { $_ }).Count
if ($referenceCount -lt 1) {
    azd env set SHAREPOINT_KNOWLEDGE_MODE 'blocked' | Out-Null
    azd env set SHAREPOINT_KNOWLEDGE_REASON (
        'Native delegated SharePoint retrieval returned no references. Upload a supported ' +
        'DOCX, PDF, PPTX, ASPX, or OneNote file under the configured KQL path and retry.'
    ) | Out-Null
    throw 'The remote SharePoint probe returned no references.'
}

if ($PromoteToActiveKnowledgeBase) {
    $sources = @($activeKnowledgeBase.knowledgeSources)
    if ($sources.name -notcontains $RemoteSourceName) {
        $sources += @{ name = $RemoteSourceName }
    }
    $activeBody = New-KnowledgeBaseBody `
        -Name $values.KNOWLEDGE_BASE_NAME `
        -Template $activeKnowledgeBase `
        -KnowledgeSources $sources
    $null = Invoke-SearchJson `
        -Method PUT `
        -Uri $activeKnowledgeBaseUri `
        -SearchToken $searchToken `
        -Body $activeBody
    azd env set SHAREPOINT_KNOWLEDGE_MODE 'live' | Out-Null
    azd env set SHAREPOINT_KNOWLEDGE_REASON (
        'Native remote SharePoint retrieval passed and the source was added to the active ' +
        'Foundry IQ knowledge base. Runtime callers must forward the delegated user token.'
    ) | Out-Null
} else {
    azd env set SHAREPOINT_KNOWLEDGE_MODE 'blocked' | Out-Null
    azd env set SHAREPOINT_KNOWLEDGE_REASON (
        'Native remote SharePoint retrieval passed in its validation knowledge base. It was ' +
        'not added to the Hosted Agent knowledge base because that MCP path does not yet ' +
        'forward x-ms-query-source-authorization.'
    ) | Out-Null
}
azd env set SHAREPOINT_REMOTE_SOURCE_NAME $RemoteSourceName | Out-Null
azd env set SHAREPOINT_VALIDATION_KB_NAME $ValidationKnowledgeBaseName | Out-Null

Write-Host "Remote SharePoint source: $RemoteSourceName"
Write-Host "Delegated validation references: $referenceCount"
if ($PromoteToActiveKnowledgeBase) {
    Write-Warning (
        'The active knowledge base now requires an end-user token for permission-trimmed ' +
        'SharePoint retrieval. Verify every Hosted Agent caller before presenting it as live.'
    )
} else {
    Write-Warning (
        'Validation passed, but the source remains isolated from the active Hosted Agent ' +
        'knowledge base until delegated token forwarding is available.'
    )
}
