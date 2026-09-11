[CmdletBinding()]
param(
    [string]$AccessToken = $env:WORK_IQ_ACCESS_TOKEN,
    [string]$Endpoint = 'https://workiq.svc.cloud.microsoft/a2a/'
)

$ErrorActionPreference = 'Stop'
if (-not $AccessToken) {
    throw @'
Work IQ live setup requires WORK_IQ_ACCESS_TOKEN in the current process. A Global
Administrator must provision the Work IQ service principal, grant delegated
WorkIQAgent.Ask to a single-tenant app, grant tenant-wide admin consent, and
enable Copilot Credits. Complete real-user OAuth, then set the short-lived
delegated token in the process environment. The token is never written to azd,
disk, or git.
'@
}

$headers = @{
    Authorization = "Bearer $AccessToken"
    'A2A-Version' = '1.0'
    'Content-Type' = 'application/json'
}
$body = @{
    jsonrpc = '2.0'
    id = 'st-iq-work-iq-readiness'
    method = 'SendMessage'
    params = @{
        message = @{
            messageId = 'st-iq-work-iq-readiness-message'
            role = 'ROLE_USER'
            parts = @(
                @{
                    text = 'Return a readiness response without retrieving or echoing tenant content.'
                }
            )
        }
    }
} | ConvertTo-Json -Depth 10 -Compress

$response = Invoke-RestMethod -Method Post -Uri $Endpoint -Headers $headers -Body $body
if (-not $response.result) {
    throw 'Work IQ A2A accepted the request but returned no result.'
}

$env:WORK_IQ_A2A_ENDPOINT = $Endpoint
$env:WORK_IQ_ACCESS_TOKEN = $AccessToken
Write-Host 'Work IQ delegated A2A is verified for this process. Start the UI with .\scripts\run-local.ps1 -Live from the same shell.' -ForegroundColor Green
