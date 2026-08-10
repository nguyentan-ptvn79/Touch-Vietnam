param(
    [string]$Version = "1.1.0"
)

$ErrorActionPreference = "Stop"

if ($Version -notmatch "^[0-9]+(\.[0-9]+){1,3}(-[A-Za-z0-9.-]+)?$") {
    throw "Phiên bản không hợp lệ. Ví dụ hợp lệ: 1.1.0 hoặc 1.1.0-rc.1"
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$releaseRoot = Join-Path $root "release"
$packageName = "TouchVN_{0}_{1}" -f $Version, $timestamp
$packageDir = Join-Path $releaseRoot $packageName
$zipPath = Join-Path $releaseRoot ($packageName + ".zip")

function Assert-PathInside {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ParentPath,
        [Parameter(Mandatory = $true)]
        [string]$ChildPath
    )

    $resolvedParent = [System.IO.Path]::GetFullPath($ParentPath).TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar
    ) + [System.IO.Path]::DirectorySeparatorChar
    $resolvedChild = [System.IO.Path]::GetFullPath($ChildPath)

    if (-not $resolvedChild.StartsWith($resolvedParent, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Đường dẫn nằm ngoài thư mục phát hành: $resolvedChild"
    }
}

$itemsToCopy = @(
    "app",
    "docs",
    "tests",
    "scripts",
    ".env.example",
    "requirements.txt",
    "requirements.lock",
    "requirements-security.txt",
    "pyproject.toml",
    "sbom.cdx.json",
    "README.md",
    "run_web.py",
    "run_api.py"
)

Assert-PathInside -ParentPath $releaseRoot -ChildPath $packageDir
Assert-PathInside -ParentPath $releaseRoot -ChildPath $zipPath

if (Test-Path $packageDir) {
    Remove-Item -LiteralPath $packageDir -Recurse -Force
}

if (Test-Path $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}

New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
New-Item -ItemType Directory -Path $packageDir -Force | Out-Null

foreach ($relativePath in $itemsToCopy) {
    $sourcePath = Join-Path $root $relativePath
    if (-not (Test-Path $sourcePath)) {
        throw "Thiếu thành phần bắt buộc khi đóng gói: $relativePath"
    }

    $destinationPath = Join-Path $packageDir $relativePath
    $destinationDir = Split-Path -Parent $destinationPath
    if ($destinationDir) {
        New-Item -ItemType Directory -Path $destinationDir -Force | Out-Null
    }

    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Recurse -Force
}

# Loại bỏ hoàn toàn tệp tạm do Python sinh ra khỏi gói phát hành.
$cacheDirectories = Get-ChildItem -LiteralPath $packageDir -Directory -Recurse -Filter "__pycache__"
foreach ($cacheDirectory in $cacheDirectories) {
    Assert-PathInside -ParentPath $packageDir -ChildPath $cacheDirectory.FullName
    Remove-Item -LiteralPath $cacheDirectory.FullName -Recurse -Force
}

$compiledFiles = Get-ChildItem -LiteralPath $packageDir -File -Recurse |
    Where-Object { $_.Extension -in @(".pyc", ".pyo") }
foreach ($compiledFile in $compiledFiles) {
    Assert-PathInside -ParentPath $packageDir -ChildPath $compiledFile.FullName
    Remove-Item -LiteralPath $compiledFile.FullName -Force
}

# Hồ sơ DOCX/PDF/PPTX được bàn giao ở bộ hồ sơ tốt nghiệp, không lặp lại trong
# ZIP mã nguồn. Giữ lại Markdown, HTML và tài nguyên thiết kế phục vụ bảo trì.
$documentArtifacts = Get-ChildItem -LiteralPath (Join-Path $packageDir "docs") -File -Recurse |
    Where-Object { $_.Extension -in @(".docx", ".pdf", ".pptx") }
foreach ($documentArtifact in $documentArtifacts) {
    Assert-PathInside -ParentPath $packageDir -ChildPath $documentArtifact.FullName
    Remove-Item -LiteralPath $documentArtifact.FullName -Force
}

$releaseNotes = @"
Touch! Vietnam - Release package
Version: $Version
Packaged at: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

Run website:
  .venv\Scripts\python.exe run_web.py

Run API:
  .venv\Scripts\python.exe run_api.py

Quality checks:
  .\scripts\run_quality_checks.ps1

Notes:
  - Copy .env.example to .env and replace every deployment secret and URL.
  - The release package contains no database or demo account.
  - Enable SEED_DEMO_USERS only in a local development environment.
  - Install dependencies from requirements.lock with --require-hashes.
"@

Set-Content -LiteralPath (Join-Path $packageDir "RELEASE_NOTES.txt") -Value $releaseNotes -Encoding UTF8

Compress-Archive -Path (Join-Path $packageDir "*") -DestinationPath $zipPath -Force

Write-Output ("PACKAGE_DIR=" + $packageDir)
Write-Output ("PACKAGE_ZIP=" + $zipPath)
