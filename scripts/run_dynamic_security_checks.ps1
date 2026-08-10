param(
    [string]$PythonPath = ".\.venv\Scripts\python.exe",
    [int]$WebPort = 5015,
    [int]$ApiPort = 8015
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Không tìm thấy Python tại: $PythonPath"
}

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dataDir = Join-Path $root "data"
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
$webOut = Join-Path $dataDir "security-web.out.log"
$webErr = Join-Path $dataDir "security-web.err.log"
$apiOut = Join-Path $dataDir "security-api.out.log"
$apiErr = Join-Path $dataDir "security-api.err.log"

$previousEnvironment = @{
    APP_ENV = $env:APP_ENV
    APP_DEBUG = $env:APP_DEBUG
    APP_PORT = $env:APP_PORT
    APP_API_PORT = $env:APP_API_PORT
}

$webProcess = $null
$apiProcess = $null

function Wait-HttpReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$Attempts = 40
    )

    for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 250
        }
    }
    throw "Dịch vụ không sẵn sàng tại $Url"
}

try {
    $env:APP_ENV = "development"
    $env:APP_DEBUG = "false"
    $env:APP_PORT = [string]$WebPort
    $env:APP_API_PORT = [string]$ApiPort

    $webProcess = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList "run_web.py" `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $webOut `
        -RedirectStandardError $webErr `
        -PassThru

    $apiProcess = Start-Process `
        -FilePath $PythonPath `
        -ArgumentList "run_api.py" `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $apiOut `
        -RedirectStandardError $apiErr `
        -PassThru

    $webUrl = "http://127.0.0.1:$WebPort"
    $apiUrl = "http://127.0.0.1:$ApiPort"
    Wait-HttpReady -Url "$webUrl/healthz"
    Wait-HttpReady -Url "$apiUrl/api/health"

    & $PythonPath "scripts\security_dast.py" --web-url $webUrl --api-url $apiUrl
    if ($LASTEXITCODE -ne 0) {
        throw "DAST security smoke failed."
    }

    & $PythonPath "scripts\stress_smoke.py" --web-url $webUrl --api-url $apiUrl
    if ($LASTEXITCODE -ne 0) {
        throw "Stress smoke failed."
    }
} finally {
    foreach ($process in @($webProcess, $apiProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force
            $process.WaitForExit()
        }
    }
    foreach ($key in $previousEnvironment.Keys) {
        $value = $previousEnvironment[$key]
        if ($null -eq $value) {
            Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
        } else {
            Set-Item -Path "Env:$key" -Value $value
        }
    }
}

Write-Host "Dynamic security checks: PASS" -ForegroundColor Green
