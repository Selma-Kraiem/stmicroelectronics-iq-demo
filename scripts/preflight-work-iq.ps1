[CmdletBinding()]
param(
    [string]$TenantId = '11111111-1111-1111-1111-111111111111',
    [string]$TestUserPrincipalName = 'presenter@contoso.onmicrosoft.com',
    [string]$ClientApplicationId = '9dd27cf1-0c61-4bf8-b004-cad6321dedd9'
)

$ErrorActionPreference = 'Stop'
$script:Failures = 0

function Write-Check {
    param(
        [ValidateSet('PASS', 'WARN', 'FAIL')]
        [string]$Status,
        [string]$Name,
        [string]$Detail
    )

    $color = switch ($Status) {
        'PASS' { 'Green' }
        'WARN' { 'Yellow' }
        'FAIL' { 'Red' }
    }
    Write-Host "[$Status] $Name - $Detail" -ForegroundColor $color
    if ($Status -eq 'FAIL') {
        $script:Failures++
    }
}

function Invoke-GraphGet {
    param(
        [string]$Path,
        [string]$Token
    )

    $secureToken = ConvertTo-SecureString $Token -AsPlainText -Force
    Invoke-RestMethod -Method Get -Uri "https://graph.microsoft.com/v1.0/$Path" `
        -Authentication Bearer -Token $secureToken
}

Write-Host 'Work IQ / Agent 365 Teams MCP preflight' -ForegroundColor Cyan
Write-Host 'This command is read-only and does not retrieve Teams content.'

[string]$graphToken = (
    az account get-access-token --resource https://graph.microsoft.com --tenant $TenantId `
        --query accessToken -o tsv --only-show-errors | Select-Object -Last 1
)
if (-not $graphToken) {
    throw "Could not acquire a Microsoft Graph token for tenant $TenantId."
}

$me = Invoke-GraphGet -Path 'me?$select=id,userPrincipalName' -Token $graphToken
if ($me.userPrincipalName -ieq $TestUserPrincipalName) {
    Write-Check PASS 'Delegated test user' $me.userPrincipalName
}
else {
    Write-Check WARN 'Delegated test user' `
        "Azure CLI is signed in as $($me.userPrincipalName); live Teams calls must use $TestUserPrincipalName"
}

$encodedUser = [System.Uri]::EscapeDataString($TestUserPrincipalName)
$licenseDetails = @(
    (
        Invoke-GraphGet `
            -Path "users/$encodedUser/licenseDetails?`$select=skuPartNumber,servicePlans" `
            -Token $graphToken
    ).value
)
$servicePlans = @($licenseDetails.servicePlans)

if ($licenseDetails.skuPartNumber -match 'E5|E7') {
    Write-Check PASS 'Microsoft 365 base license' `
        ($licenseDetails.skuPartNumber -join ', ')
}
else {
    Write-Check FAIL 'Microsoft 365 base license' "$TestUserPrincipalName has no E5 or E7 license"
}

$teamsPlan = $servicePlans | Where-Object {
    $_.servicePlanName -eq 'TEAMS1' -and $_.provisioningStatus -eq 'Success'
} | Select-Object -First 1
if ($teamsPlan) {
    Write-Check PASS 'Teams service plan' 'TEAMS1 is active'
}
else {
    Write-Check FAIL 'Teams service plan' 'TEAMS1 is not active'
}

$copilotPlan = $servicePlans | Where-Object {
    $_.servicePlanName -eq 'M365_COPILOT_BUSINESS_CHAT' -and
        $_.provisioningStatus -eq 'Success'
} | Select-Object -First 1
if ($copilotPlan) {
    Write-Check PASS 'Microsoft 365 Copilot' 'M365_COPILOT_BUSINESS_CHAT is active'
}
else {
    Write-Check WARN 'Microsoft 365 Copilot' `
        'no M365 Copilot plan is assigned; verify Copilot Credits/standard-harness billing for this preview path'
}

$requiredServicePrincipals = @(
    @{
        Name = 'Work IQ API'
        AppId = 'fdcc1f02-fc51-4226-8753-f668596af7f7'
        Required = $true
    },
    @{
        Name = 'Agent 365 Tools'
        AppId = 'ea9ffc3e-8a23-4a7d-836d-234d7c7565c1'
        Required = $false
    },
    @{
        Name = 'Teams MCP'
        AppId = 'ce5029ee-c1d3-45c0-bdcc-efb5a4245687'
        Required = $false
    }
)

foreach ($required in $requiredServicePrincipals) {
    $filter = [System.Uri]::EscapeDataString("appId eq '$($required.AppId)'")
    $servicePrincipal = @(
        (
            Invoke-GraphGet `
                -Path "servicePrincipals?`$filter=$filter&`$select=id,displayName" `
                -Token $graphToken
        ).value
    ) | Select-Object -First 1
    if ($servicePrincipal) {
        Write-Check PASS "$($required.Name) service principal" `
            "$($servicePrincipal.displayName) / $($servicePrincipal.id)"
    }
    else {
        $status = if ($required.Required) { 'FAIL' } else { 'WARN' }
        Write-Check $status "$($required.Name) service principal" `
            "$($required.AppId) is missing; only the specialized Agent 365 path needs it"
    }
}

$clientFilter = [System.Uri]::EscapeDataString("appId eq '$ClientApplicationId'")
$clientServicePrincipal = @(
    (
        Invoke-GraphGet `
            -Path "servicePrincipals?`$filter=$clientFilter&`$select=id,displayName" `
            -Token $graphToken
    ).value
) | Select-Object -First 1
if (-not $clientServicePrincipal) {
    Write-Check FAIL 'Work IQ delegated OAuth client' `
        "service principal for $ClientApplicationId is missing"
}
else {
    $grantFilter = [System.Uri]::EscapeDataString(
        "clientId eq '$($clientServicePrincipal.id)'"
    )
    $grants = @(
        (
            Invoke-GraphGet `
                -Path "oauth2PermissionGrants?`$filter=$grantFilter&`$select=consentType,scope" `
                -Token $graphToken
        ).value
    )
    $workIqGrant = $grants | Where-Object {
        $_.consentType -eq 'AllPrincipals' -and
        $_.scope.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries) -contains 'WorkIQAgent.Ask'
    } | Select-Object -First 1
    if ($workIqGrant) {
        Write-Check PASS 'Work IQ delegated OAuth client' `
            "$($clientServicePrincipal.displayName) has tenant-wide WorkIQAgent.Ask consent"
    }
    else {
        Write-Check FAIL 'Work IQ delegated OAuth client' `
            'tenant-wide WorkIQAgent.Ask admin consent is missing'
    }
}

$roles = @(
    (
        Invoke-GraphGet `
            -Path 'directoryRoles?$expand=members($select=userPrincipalName,displayName)&$select=displayName' `
            -Token $graphToken
    ).value
)
$applicationAdmins = @(
    $roles | Where-Object {
        $_.displayName -in @(
            'Global Administrator',
            'Privileged Role Administrator',
            'Cloud Application Administrator',
            'Application Administrator'
        )
    } | ForEach-Object { $_.members } | ForEach-Object {
        if ($_.userPrincipalName) { $_.userPrincipalName } else { $_.displayName }
    } | Select-Object -Unique
)
if ($applicationAdmins.Count -gt 0) {
    Write-Check PASS 'Tenant application administrator' ($applicationAdmins -join ', ')
}
else {
    Write-Check FAIL 'Tenant application administrator' `
        'no active role holder can provision the required service principals'
}

Write-Check WARN 'Work IQ MCP policy' `
    'confirm Teams/Work IQ MCP is allowed under Microsoft 365 admin center > Agents > Tools'
Write-Check WARN 'Copilot Credits billing' `
    'assign the demo user to an active Work IQ API spending policy under Copilot > Cost Management'

if ($script:Failures -gt 0) {
    Write-Host "`nWork IQ preflight failed with $script:Failures blocking issue(s)." -ForegroundColor Red
    Write-Host 'Resolve the failed generic Work IQ checks before attempting delegated tool calls.'
    exit 1
}

Write-Host "`nGeneric Work IQ identity preflight passed. WARN items affect only optional policy or Agent 365 paths." `
    -ForegroundColor Green
exit 0
