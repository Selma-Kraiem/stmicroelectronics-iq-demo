[CmdletBinding()]
param(
    [string]$WorkspaceId = $env:FABRIC_WORKSPACE_ID,
    [string]$OntologyItemId = $env:FABRIC_ONTOLOGY_ITEM_ID,
    [string]$AccessToken = $env:FABRIC_IQ_ACCESS_TOKEN,
    [string]$ToolName = $env:FABRIC_IQ_TOOL_NAME,
    [string]$ToolArgumentsJson = $env:FABRIC_IQ_TOOL_ARGUMENTS_JSON
)

$ErrorActionPreference = 'Stop'
if (
    -not $WorkspaceId -or
    -not $OntologyItemId -or
    -not $AccessToken -or
    -not $ToolName -or
    -not $ToolArgumentsJson
) {
    throw @'
Fabric IQ live setup requires FABRIC_WORKSPACE_ID, FABRIC_ONTOLOGY_ITEM_ID,
FABRIC_IQ_ACCESS_TOKEN, FABRIC_IQ_TOOL_NAME, and
FABRIC_IQ_TOOL_ARGUMENTS_JSON in the current process. A Fabric administrator
must enable the Ontology preview tenant setting and use paid F2+ capacity. The
delegated token needs Item.Execute.All and Item.Read.All. Tokens are never
written to azd, disk, or git.
'@
}

try {
    $arguments = $ToolArgumentsJson | ConvertFrom-Json -AsHashtable
}
catch {
    throw 'FABRIC_IQ_TOOL_ARGUMENTS_JSON must be a valid JSON object.'
}
if ($arguments -isnot [hashtable]) {
    throw 'FABRIC_IQ_TOOL_ARGUMENTS_JSON must be a JSON object.'
}

$endpoint = "https://api.fabric.microsoft.com/v1/mcp/dataPlane/workspaces/$WorkspaceId/items/$OntologyItemId/ontologyEndpoint"
$headers = @{
    Authorization = "Bearer $AccessToken"
    Accept = 'application/json, text/event-stream'
    'Content-Type' = 'application/json'
}
$body = @{
    jsonrpc = '2.0'
    id = 'st-iq-fabric-tools-list'
    method = 'tools/list'
} | ConvertTo-Json -Compress
$response = Invoke-RestMethod -Method Post -Uri $endpoint -Headers $headers -Body $body
$advertised = @($response.result.tools | Where-Object name -eq $ToolName)
if ($advertised.Count -eq 0) {
    throw "Fabric IQ ontology MCP did not advertise configured tool '$ToolName'."
}

$env:FABRIC_IQ_MCP_ENDPOINT = $endpoint
$env:FABRIC_IQ_TOOL_NAME = $ToolName
$env:FABRIC_IQ_TOOL_ARGUMENTS_JSON = $ToolArgumentsJson
$env:FABRIC_IQ_ACCESS_TOKEN = $AccessToken
Write-Host 'Fabric IQ ontology MCP is verified for this process. Start the UI with .\scripts\run-local.ps1 -Live from the same shell.' -ForegroundColor Green
