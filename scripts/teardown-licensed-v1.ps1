[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Confirmation
)

$ErrorActionPreference = 'Stop'

& "$PSScriptRoot\teardown.ps1" `
    -SubscriptionId '00000000-0000-0000-0000-000000000000' `
    -ResourceGroup 'rg-st-iq-demo' `
    -Prefix 'stiqdemo' `
    -Confirmation $Confirmation
