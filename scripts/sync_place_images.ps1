param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$sampleDataPath = Join-Path $projectRoot "app\shared\sample_data.py"
$assetDirectory = Join-Path $projectRoot "app\web\static\img\places"
$attributionPath = Join-Path $assetDirectory "attribution.json"
$userAgent = "TouchVN-StudentProject/1.0 (educational local demo; contact: admin@localhost)"

$searchOverrides = @{
    "ha-noi-old-quarter" = "Khu phố cổ Hà Nội"
    "cat-ba" = "Quần đảo Cát Bà"
    "bac-ninh-dong-ho" = "Tranh Đông Hồ"
    "con-son-kiep-bac" = "Khu di tích Côn Sơn Kiếp Bạc"
    "tran-temple-nam-dinh" = "Đền Trần Nam Định"
    "con-den" = "Cồn Đen Thái Bình"
    "atks-dinh-hoa" = "ATK Định Hóa"
    "tay-yen-tu" = "Tây Yên Tử Bắc Giang"
    "dien-bien-phu" = "Chiến dịch Điện Biên Phủ di tích"
    "sam-son" = "Bãi biển Sầm Sơn"
    "cua-lo" = "Bãi biển Cửa Lò"
    "thien-cam" = "Bãi biển Thiên Cầm"
    "vinh-moc" = "Địa đạo Vịnh Mốc"
    "ky-co" = "Kỳ Co Eo Gió"
    "ghenh-da-dia" = "Gành Đá Đĩa"
    "ninh-chu" = "Bãi biển Ninh Chữ"
    "bien-ho-che" = "Biển Hồ Chè Gia Lai"
    "buon-don" = "Buôn Đôn Đắk Lắk"
    "bu-gia-map" = "Vườn quốc gia Bù Gia Mập"
    "ba-den" = "Núi Bà Đen"
    "dai-nam" = "Khu du lịch Đại Nam"
    "buulong" = "Khu du lịch Bửu Long"
    "tan-lap" = "Làng nổi Tân Lập Long An"
    "con-phung" = "Cồn Phụng Bến Tre"
    "an-binh" = "Cù lao An Bình Vĩnh Long"
    "tram-chim" = "Vườn quốc gia Tràm Chim"
    "tra-su" = "Rừng tràm Trà Sư"
    "lung-ngoc-hoang" = "Khu bảo tồn Lung Ngọc Hoàng"
    "nga-nam" = "Chợ nổi Ngã Năm"
    "bac-lieu-wind-farm" = "Điện gió Bạc Liêu"
    "dat-mui" = "Mũi Cà Mau"
}

function ConvertTo-QueryString {
    param([hashtable]$Parameters)

    return ($Parameters.GetEnumerator() | ForEach-Object {
        $key = [uri]::EscapeDataString([string]$_.Key)
        $value = [uri]::EscapeDataString([string]$_.Value)
        "$key=$value"
    }) -join "&"
}

function Invoke-WikimediaApi {
    param(
        [string]$BaseUrl,
        [hashtable]$Parameters
    )

    $uri = "${BaseUrl}?$(ConvertTo-QueryString -Parameters $Parameters)"
    return Invoke-JsonWithRetry -Uri $uri
}

function Get-HttpStatusCode {
    param([System.Management.Automation.ErrorRecord]$ErrorRecord)

    if ($ErrorRecord.Exception.Response -and $ErrorRecord.Exception.Response.StatusCode) {
        return [int]$ErrorRecord.Exception.Response.StatusCode
    }
    return $null
}

function Invoke-JsonWithRetry {
    param(
        [string]$Uri,
        [switch]$AllowNotFound
    )

    $waitSeconds = @(3, 8, 20, 45)
    for ($attempt = 0; $attempt -le $waitSeconds.Count; $attempt++) {
        try {
            $response = Invoke-RestMethod -Uri $Uri -Headers @{
                "User-Agent" = $userAgent
                "Api-User-Agent" = $userAgent
            } -TimeoutSec 45
            Start-Sleep -Milliseconds 700
            return $response
        } catch {
            $statusCode = Get-HttpStatusCode -ErrorRecord $_
            if ($AllowNotFound -and $statusCode -eq 404) {
                return $null
            }
            $retryable = $statusCode -eq 429 -or $statusCode -ge 500 -or -not $statusCode
            if (-not $retryable -or $attempt -ge $waitSeconds.Count) {
                throw
            }
            Start-Sleep -Seconds $waitSeconds[$attempt]
        }
    }
}

function Save-ImageWithRetry {
    param(
        [string]$Uri,
        [string]$Destination
    )

    $waitSeconds = @(3, 8, 20, 45)
    for ($attempt = 0; $attempt -le $waitSeconds.Count; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Uri -Headers @{ "User-Agent" = $userAgent } -OutFile $Destination -TimeoutSec 75
            Start-Sleep -Milliseconds 700
            return
        } catch {
            $statusCode = Get-HttpStatusCode -ErrorRecord $_
            $retryable = $statusCode -eq 429 -or $statusCode -ge 500 -or -not $statusCode
            if (-not $retryable -or $attempt -ge $waitSeconds.Count) {
                throw
            }
            Start-Sleep -Seconds $waitSeconds[$attempt]
        }
    }
}

function Get-PlaceInventory {
    $source = Get-Content $sampleDataPath -Raw -Encoding UTF8
    $items = [System.Collections.Generic.List[object]]::new()

    $corePattern = '(?s)Place\(\s*id="([^"]+)"\s*,\s*name="([^"]+)"\s*,\s*region="[^"]+"\s*,\s*province="([^"]+)"'
    foreach ($match in [regex]::Matches($source, $corePattern)) {
        $items.Add([pscustomobject]@{
            place_id = $match.Groups[1].Value
            name = $match.Groups[2].Value
            province = $match.Groups[3].Value
        })
    }

    $extendedPattern = '(?s)_province_place\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"[^"]+"\s*,\s*"([^"]+)"'
    foreach ($match in [regex]::Matches($source, $extendedPattern)) {
        $items.Add([pscustomobject]@{
            place_id = $match.Groups[1].Value
            name = $match.Groups[2].Value
            province = $match.Groups[3].Value
        })
    }

    return $items | Sort-Object place_id -Unique
}

function Get-ExistingAsset {
    param([string]$PlaceId)

    foreach ($extension in @("jpg", "jpeg", "png", "svg")) {
        $candidate = Join-Path $assetDirectory "$PlaceId.$extension"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

function Get-WikipediaCandidate {
    param(
        [string]$SearchTerm,
        [string]$Province
    )

    $summaryTitle = [uri]::EscapeDataString(($SearchTerm -replace ' ', '_'))
    $summary = Invoke-JsonWithRetry -Uri "https://vi.wikipedia.org/api/rest_v1/page/summary/$summaryTitle" -AllowNotFound
    if ($summary -and $summary.thumbnail.source) {
        $thumbnailUrl = $summary.thumbnail.source -replace '/\d+px-', '/1280px-'
        return [pscustomobject]@{
            title = $summary.title
            file_title = $null
            fallback_url = $thumbnailUrl
            source_page = $summary.content_urls.desktop.page
        }
    }

    $queries = @(
        "intitle:`"$SearchTerm`"",
        "`"$SearchTerm`" `"$Province`""
    )

    foreach ($query in $queries) {
        $response = Invoke-WikimediaApi -BaseUrl "https://vi.wikipedia.org/w/api.php" -Parameters @{
            action = "query"
            format = "json"
            formatversion = "2"
            generator = "search"
            gsrsearch = $query
            gsrlimit = "6"
            prop = "pageimages"
            piprop = "thumbnail|name"
            pithumbsize = "1280"
            pilicense = "free"
            redirects = "1"
        }

        $candidate = @($response.query.pages) |
            Where-Object { $_.pageimage -and $_.thumbnail.source } |
            Sort-Object index |
            Select-Object -First 1
        if ($candidate) {
            return [pscustomobject]@{
                title = $candidate.title
                file_title = "File:$($candidate.pageimage)"
                fallback_url = $candidate.thumbnail.source
                source_page = "https://vi.wikipedia.org/wiki/$([uri]::EscapeDataString(($candidate.title -replace ' ', '_')))"
            }
        }
    }

    return $null
}

function Get-CommonsFileInfo {
    param([string]$FileTitle)

    $response = Invoke-WikimediaApi -BaseUrl "https://commons.wikimedia.org/w/api.php" -Parameters @{
        action = "query"
        format = "json"
        formatversion = "2"
        titles = $FileTitle
        prop = "imageinfo"
        iiprop = "url|mime|extmetadata"
        iiurlwidth = "1280"
    }
    $page = @($response.query.pages) | Where-Object { -not $_.missing -and $_.imageinfo } | Select-Object -First 1
    if (-not $page) {
        return $null
    }
    $info = @($page.imageinfo) | Select-Object -First 1
    return [pscustomobject]@{
        title = $page.title
        url = if ($info.thumburl) { $info.thumburl } else { $info.url }
        description_url = $info.descriptionurl
        mime = $info.mime
        metadata = $info.extmetadata
    }
}

function Search-CommonsCandidate {
    param(
        [string]$SearchTerm,
        [string]$Province
    )

    $response = Invoke-WikimediaApi -BaseUrl "https://commons.wikimedia.org/w/api.php" -Parameters @{
        action = "query"
        format = "json"
        formatversion = "2"
        generator = "search"
        gsrnamespace = "6"
        gsrsearch = "$SearchTerm $Province"
        gsrlimit = "12"
        prop = "imageinfo"
        iiprop = "url|mime|extmetadata"
        iiurlwidth = "1280"
    }

    $excludedTitlePattern = '(?i)\b(map|locator|logo|flag|seal|icon|diagram|route|banner)\b|bản đồ|quốc kỳ|huy hiệu'
    foreach ($page in @($response.query.pages) | Sort-Object index) {
        $info = @($page.imageinfo) | Select-Object -First 1
        if (-not $info -or $page.title -match $excludedTitlePattern) {
            continue
        }
        if ($info.mime -notmatch '^image/(jpeg|png)$') {
            continue
        }
        return [pscustomobject]@{
            title = $page.title
            url = if ($info.thumburl) { $info.thumburl } else { $info.url }
            description_url = $info.descriptionurl
            mime = $info.mime
            metadata = $info.extmetadata
        }
    }
    return $null
}

function Get-MetadataValue {
    param(
        [object]$Metadata,
        [string]$Name
    )

    if (-not $Metadata) {
        return $null
    }
    $property = $Metadata.PSObject.Properties[$Name]
    if (-not $property -or -not $property.Value) {
        return $null
    }
    return $property.Value.value
}

function Get-ImageExtension {
    param(
        [string]$Mime,
        [string]$Url
    )

    if ($Mime -eq "image/png" -or $Url -match '(?i)\.png(?:/|\?|$)') {
        return "png"
    }
    return "jpg"
}

function Test-DownloadedImage {
    param(
        [string]$Path,
        [string]$Extension
    )

    $file = Get-Item -LiteralPath $Path
    if ($file.Length -lt 10000) {
        return $false
    }
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($Extension -eq "png") {
        return $bytes.Length -gt 8 -and $bytes[0] -eq 0x89 -and $bytes[1] -eq 0x50 -and $bytes[2] -eq 0x4E -and $bytes[3] -eq 0x47
    }
    return $bytes.Length -gt 3 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xD8
}

New-Item -ItemType Directory -Path $assetDirectory -Force | Out-Null
$inventory = @(Get-PlaceInventory)
$attributions = [System.Collections.Generic.List[object]]::new()
$previousAttributions = @{}
if (Test-Path -LiteralPath $attributionPath -PathType Leaf) {
    try {
        $previousManifest = Get-Content -LiteralPath $attributionPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($entry in @($previousManifest.places)) {
            if ($entry.place_id) {
                $previousAttributions[$entry.place_id] = $entry
            }
        }
    } catch {
        Write-Warning "Không thể đọc attribution.json cũ; manifest sẽ được tạo lại."
    }
}
$downloaded = 0
$skipped = 0
$failed = [System.Collections.Generic.List[object]]::new()

foreach ($place in $inventory) {
    $existingAsset = Get-ExistingAsset -PlaceId $place.place_id
    if ($existingAsset -and -not $Force) {
        if ($previousAttributions.ContainsKey($place.place_id)) {
            $attributions.Add($previousAttributions[$place.place_id])
        }
        $skipped++
        continue
    }

    $searchTerm = if ($searchOverrides.ContainsKey($place.place_id)) {
        $searchOverrides[$place.place_id]
    } else {
        $place.name
    }

    Write-Host "[$($downloaded + $failed.Count + 1)/$($inventory.Count - $skipped)] $($place.name)" -ForegroundColor Cyan
    try {
        $wikipedia = Get-WikipediaCandidate -SearchTerm $searchTerm -Province $place.province
        $commons = $null
        if ($wikipedia -and $wikipedia.file_title) {
            $commons = Get-CommonsFileInfo -FileTitle $wikipedia.file_title
        }
        if (-not $commons -and -not $wikipedia) {
            $commons = Search-CommonsCandidate -SearchTerm $searchTerm -Province $place.province
        }
        if (-not $commons -and -not $wikipedia) {
            throw "Không tìm thấy ảnh tự do phù hợp."
        }

        $imageUrl = if ($commons) { $commons.url } else { $wikipedia.fallback_url }
        $mime = if ($commons) { $commons.mime } else { "image/jpeg" }
        $extension = Get-ImageExtension -Mime $mime -Url $imageUrl
        $targetPath = Join-Path $assetDirectory "$($place.place_id).$extension"
        $temporaryPath = "$targetPath.download"

        Save-ImageWithRetry -Uri $imageUrl -Destination $temporaryPath
        if (-not (Test-DownloadedImage -Path $temporaryPath -Extension $extension)) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
            throw "Tệp tải về không phải ảnh hợp lệ hoặc có kích thước quá nhỏ."
        }

        if ($Force) {
            foreach ($oldExtension in @("jpg", "jpeg", "png", "svg")) {
                $oldPath = Join-Path $assetDirectory "$($place.place_id).$oldExtension"
                if ((Test-Path -LiteralPath $oldPath) -and $oldPath -ne $targetPath) {
                    Remove-Item -LiteralPath $oldPath -Force
                }
            }
        }
        Move-Item -LiteralPath $temporaryPath -Destination $targetPath -Force

        $metadata = if ($commons) { $commons.metadata } else { $null }
        $attributions.Add([ordered]@{
            place_id = $place.place_id
            place_name = $place.name
            province = $place.province
            asset = "img/places/$($place.place_id).$extension"
            source_title = if ($commons) { $commons.title } else { $wikipedia.title }
            source_page = if ($commons) { $commons.description_url } else { $wikipedia.source_page }
            image_url = $imageUrl
            author = Get-MetadataValue -Metadata $metadata -Name "Artist"
            license = Get-MetadataValue -Metadata $metadata -Name "LicenseShortName"
            license_url = Get-MetadataValue -Metadata $metadata -Name "LicenseUrl"
        })
        $downloaded++
    } catch {
        $failed.Add([ordered]@{
            place_id = $place.place_id
            place_name = $place.name
            error = $_.Exception.Message
        })
        Write-Warning "$($place.name): $($_.Exception.Message)"
    }

    Start-Sleep -Milliseconds 120
}

$manifest = [ordered]@{
    generated_at = (Get-Date).ToUniversalTime().ToString("o")
    source_policy = "Images are downloaded from freely licensed Wikipedia/Wikimedia Commons results. See each source page for full attribution and license terms."
    downloaded_count = $downloaded
    attributed_image_count = $attributions.Count
    skipped_existing_count = $skipped
    failed_count = $failed.Count
    places = $attributions
    failures = $failed
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $attributionPath -Encoding UTF8

Write-Host "Downloaded: $downloaded | Existing: $skipped | Failed: $($failed.Count)" -ForegroundColor Green
if ($failed.Count -gt 0) {
    $failed | Format-Table -AutoSize
    exit 2
}
