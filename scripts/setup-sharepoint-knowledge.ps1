[CmdletBinding()]
param(
    [string]$EnvironmentName = 'st-iq-public-demo'
)

$ErrorActionPreference = 'Stop'

throw (
    'This legacy delegated-copy ingestion path is disabled because copying SharePoint content ' +
    'into a shared search index does not preserve document ACLs. Use the permission-trimmed ' +
    "remote SharePoint source instead: .\scripts\setup-sharepoint-foundry-iq.ps1 " +
    "-EnvironmentName $EnvironmentName"
)
