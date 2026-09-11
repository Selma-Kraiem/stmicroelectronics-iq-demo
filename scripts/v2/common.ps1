$ErrorActionPreference = 'Stop'

function Assert-NativeSuccess {
    param([Parameter(Mandatory)][string]$Operation)
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed."
    }
}

function Get-AzureAccessToken {
    param([Parameter(Mandatory)][string]$Resource)
    $token = az account get-access-token --resource $Resource --query accessToken -o tsv
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
    $parameters = @{
        Method = $Method
        Uri = $Uri
        Headers = @{
            Authorization = "Bearer $Token"
            'Content-Type' = 'application/json'
        }
        TimeoutSec = 180
    }
    if ($null -ne $Body) {
        $parameters.Body = $Body | ConvertTo-Json -Depth 40 -Compress
    }
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        try {
            return Invoke-RestMethod @parameters
        }
        catch {
            $statusCode = $_.Exception.Response.StatusCode.value__
            $isTransient = -not $statusCode -or $statusCode -in @(408, 409, 429, 500, 502, 503, 504)
            if (-not $isTransient -or $attempt -eq 5) {
                throw
            }
            Start-Sleep -Seconds ([Math]::Pow(2, $attempt))
        }
    }
}

function New-V2AcrImage {
    param(
        [Parameter(Mandatory)][string]$RegistryId,
        [Parameter(Mandatory)][string]$Repository,
        [Parameter(Mandatory)][string]$Tag,
        [Parameter(Mandatory)][string]$Dockerfile
    )
    $apiVersion = '2019-06-01-preview'
    $armToken = Get-AzureAccessToken 'https://management.azure.com'
    $upload = Invoke-AzureJson -Method Post `
        -Uri "https://management.azure.com${RegistryId}/listBuildSourceUploadUrl?api-version=$apiVersion" `
        -Token $armToken

    $tempRoot = Join-Path ([IO.Path]::GetTempPath()) "st-iq-v2-acr-$([guid]::NewGuid())"
    $sourceRoot = Join-Path $tempRoot 'source'
    $archive = Join-Path $tempRoot 'source.tar.gz'
    try {
        New-Item -ItemType Directory -Path $sourceRoot -Force | Out-Null
        Copy-Item '.\pyproject.toml' $sourceRoot
        Copy-Item '.\app' $sourceRoot -Recurse
        Copy-Item '.\v2' $sourceRoot -Recurse

        & tar -czf $archive -C $sourceRoot .
        Assert-NativeSuccess 'V2 source archive creation'
        Invoke-WebRequest -Method Put -Uri $upload.uploadUrl -InFile $archive `
            -Headers @{ 'x-ms-blob-type' = 'BlockBlob' } | Out-Null

        $request = @{
            type = 'DockerBuildRequest'
            dockerFilePath = $Dockerfile
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
            throw 'ACR accepted the V2 build but returned no run ID.'
        }

        $runUri = "https://management.azure.com${RegistryId}/runs/${runId}?api-version=$apiVersion"
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            $runResponse = Invoke-AzureJson -Method Get -Uri $runUri -Token $armToken
            $status = if ($runResponse.properties) { $runResponse.properties } else { $runResponse }
            Write-Host "ACR run ${runId}: $($status.status)"
            if ($status.status -eq 'Succeeded') {
                $output = @($status.outputImages)[0]
                if (-not $output.digest) {
                    throw "ACR run ${runId} returned no image digest."
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

function Ensure-Role {
    param(
        [Parameter(Mandatory)][string]$SubscriptionId,
        [Parameter(Mandatory)][string]$AssigneeObjectId,
        [Parameter(Mandatory)][string]$RoleName,
        [Parameter(Mandatory)][string]$RoleDefinitionId,
        [Parameter(Mandatory)][string]$Scope
    )
    $existing = az role assignment list --subscription $SubscriptionId --scope $Scope `
        --query "[?principalId=='$AssigneeObjectId' && contains(roleDefinitionId, '$RoleDefinitionId')] | [0].id" -o tsv
    Assert-NativeSuccess "Inspecting $RoleName assignments"
    if (-not $existing) {
        az role assignment create --subscription $SubscriptionId `
            --assignee-object-id $AssigneeObjectId --assignee-principal-type ServicePrincipal `
            --role $RoleDefinitionId --scope $Scope --only-show-errors | Out-Null
        Assert-NativeSuccess "Assigning $RoleName"
    }
}
