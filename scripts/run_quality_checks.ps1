param(
    [string]$PythonPath = ".\.venv\Scripts\python.exe",
    [switch]$IncludeDynamicSecurity
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Không tìm thấy Python tại: $PythonPath"
}

& $PythonPath -m compileall -q app tests
if ($LASTEXITCODE -ne 0) {
    throw "Python compile check failed."
}

Get-ChildItem -LiteralPath "app\web\static\js" -Filter "*.js" |
    ForEach-Object {
        node --check $_.FullName
        if ($LASTEXITCODE -ne 0) {
            throw "JavaScript syntax check failed: $($_.FullName)"
        }
    }

& $PythonPath -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) {
    throw "Acceptance tests failed."
}

& $PythonPath "scripts\security_static_checks.py"
if ($LASTEXITCODE -ne 0) {
    throw "Static security checks failed."
}

& $PythonPath "scripts\generate_supply_chain_artifacts.py" --verify
if ($LASTEXITCODE -ne 0) {
    throw "Supply-chain artifact verification failed."
}

# B105 also flags UI labels and non-secret JWT identifiers; B310 is reviewed at
# each urlopen call with explicit HTTP(S) validation or a fixed HTTPS endpoint.
& $PythonPath -m bandit -q -r app scripts -x tests,.venv,release -s B105
if ($LASTEXITCODE -ne 0) {
    throw "Bandit SAST failed."
}

$auditCache = Join-Path (Get-Location) ".pip-audit-cache"
New-Item -ItemType Directory -Path $auditCache -Force | Out-Null
try {
    & $PythonPath -m pip_audit -r requirements.lock --disable-pip --cache-dir $auditCache
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency vulnerability scan failed."
    }
} finally {
    if (Test-Path -LiteralPath $auditCache) {
        Remove-Item -LiteralPath $auditCache -Recurse -Force
    }
}

if ($IncludeDynamicSecurity) {
    & ".\scripts\run_dynamic_security_checks.ps1" -PythonPath $PythonPath
    if ($LASTEXITCODE -ne 0) {
        throw "Dynamic security checks failed."
    }
}

Write-Host "Touch VN quality gate: PASS" -ForegroundColor Green
