param(
    [string]$SourceHtml = (Join-Path $PSScriptRoot 'DeCuongChiTiet_TouchVN.html'),
    [string]$OutputDocx = (Join-Path $PSScriptRoot 'DeCuongChiTiet_TouchVN.docx')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function ConvertTo-Base64Lines {
    param([byte[]]$Bytes)
    $encoded = [Convert]::ToBase64String($Bytes)
    $lines = for ($offset = 0; $offset -lt $encoded.Length; $offset += 76) {
        $length = [Math]::Min(76, $encoded.Length - $offset)
        $encoded.Substring($offset, $length)
    }
    return ($lines -join "`r`n")
}

function Add-ZipTextEntry {
    param(
        [System.IO.Compression.ZipArchive]$Archive,
        [string]$Name,
        [string]$Content
    )
    $entry = $Archive.CreateEntry($Name, [System.IO.Compression.CompressionLevel]::Optimal)
    $stream = $entry.Open()
    try {
        $utf8 = New-Object System.Text.UTF8Encoding($false)
        $bytes = $utf8.GetBytes($Content)
        $stream.Write($bytes, 0, $bytes.Length)
    }
    finally {
        $stream.Dispose()
    }
}

$html = [System.IO.File]::ReadAllText($SourceHtml, [System.Text.Encoding]::UTF8)
$images = @(
    @{ File = 'architecture.png'; Id = 'architecture@touchvn' },
    @{ File = 'use-case.png'; Id = 'use-case@touchvn' },
    @{ File = 'planner-flow.png'; Id = 'planner-flow@touchvn' },
    @{ File = 'data-model.png'; Id = 'data-model@touchvn' }
)

foreach ($image in $images) {
    $relativePath = 'decuong-assets/' + $image.File
    $html = $html.Replace($relativePath, 'cid:' + $image.Id)
}

$boundary = '----=_TouchVN_DeCuong_20260714'
$mhtml = New-Object System.Text.StringBuilder
[void]$mhtml.AppendLine('MIME-Version: 1.0')
[void]$mhtml.AppendLine('Content-Type: multipart/related; type="text/html"; boundary="' + $boundary + '"')
[void]$mhtml.AppendLine('')
[void]$mhtml.AppendLine('--' + $boundary)
[void]$mhtml.AppendLine('Content-Type: text/html; charset="utf-8"')
[void]$mhtml.AppendLine('Content-Transfer-Encoding: base64')
[void]$mhtml.AppendLine('Content-Location: DeCuongChiTiet_TouchVN.html')
[void]$mhtml.AppendLine('')
[void]$mhtml.AppendLine((ConvertTo-Base64Lines -Bytes ([System.Text.Encoding]::UTF8.GetBytes($html))))

foreach ($image in $images) {
    $imagePath = Join-Path (Join-Path $PSScriptRoot 'decuong-assets') $image.File
    [void]$mhtml.AppendLine('--' + $boundary)
    [void]$mhtml.AppendLine('Content-Type: image/png')
    [void]$mhtml.AppendLine('Content-Transfer-Encoding: base64')
    [void]$mhtml.AppendLine('Content-ID: <' + $image.Id + '>')
    [void]$mhtml.AppendLine('Content-Location: ' + $image.File)
    [void]$mhtml.AppendLine('')
    [void]$mhtml.AppendLine((ConvertTo-Base64Lines -Bytes ([System.IO.File]::ReadAllBytes($imagePath))))
}
[void]$mhtml.AppendLine('--' + $boundary + '--')

$contentTypes = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/afchunk.mht" ContentType="message/rfc822"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
'@

$rootRelationships = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
'@

$documentXml = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    <w:altChunk r:id="rIdHtml"/>
    <w:sectPr>
      <w:pgSz w:w="11906" w:h="16838"/>
      <w:pgMar w:top="567" w:right="680" w:bottom="680" w:left="680" w:header="360" w:footer="360" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
'@

$documentRelationships = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdHtml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk" Target="afchunk.mht"/>
</Relationships>
'@

$timestamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
$coreProperties = @"
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Đề cương chi tiết - Touch VN</dc:title>
  <dc:subject>Nền tảng du lịch thông minh Việt Nam</dc:subject>
  <dc:creator>Touch VN Project</dc:creator>
  <cp:keywords>Touch VN; du lịch; AI; FastAPI; Flask; AR; OWASP</cp:keywords>
  <dc:description>Đề cương chi tiết được xây dựng từ mã nguồn và tài liệu dự án Touch VN.</dc:description>
  <dcterms:created xsi:type="dcterms:W3CDTF">$timestamp</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">$timestamp</dcterms:modified>
</cp:coreProperties>
"@

$appProperties = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Microsoft Office Word</Application>
  <AppVersion>16.0000</AppVersion>
  <Company>Touch VN</Company>
</Properties>
'@

if (Test-Path -LiteralPath $OutputDocx) {
    Remove-Item -LiteralPath $OutputDocx -Force
}
$fileStream = [System.IO.File]::Open($OutputDocx, [System.IO.FileMode]::CreateNew)
try {
    $archive = New-Object System.IO.Compression.ZipArchive($fileStream, [System.IO.Compression.ZipArchiveMode]::Create, $false)
    try {
        Add-ZipTextEntry -Archive $archive -Name '[Content_Types].xml' -Content $contentTypes
        Add-ZipTextEntry -Archive $archive -Name '_rels/.rels' -Content $rootRelationships
        Add-ZipTextEntry -Archive $archive -Name 'word/document.xml' -Content $documentXml
        Add-ZipTextEntry -Archive $archive -Name 'word/_rels/document.xml.rels' -Content $documentRelationships
        Add-ZipTextEntry -Archive $archive -Name 'word/afchunk.mht' -Content $mhtml.ToString()
        Add-ZipTextEntry -Archive $archive -Name 'docProps/core.xml' -Content $coreProperties
        Add-ZipTextEntry -Archive $archive -Name 'docProps/app.xml' -Content $appProperties
    }
    finally {
        $archive.Dispose()
    }
}
finally {
    $fileStream.Dispose()
}

Get-Item -LiteralPath $OutputDocx | Select-Object FullName, Length, LastWriteTime
