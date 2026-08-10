param(
    [Parameter(Mandatory = $true)]
    [string]$SourcePath,
    [Parameter(Mandatory = $true)]
    [string]$OutputDocxPath,
    [Parameter(Mandatory = $true)]
    [string]$OutputPdfPath
)

$ErrorActionPreference = "Stop"

function Replace-AllText {
    param(
        [object]$Document,
        [string]$FindText,
        [string]$ReplaceText
    )

    $range = $Document.Content.Duplicate
    $find = $range.Find
    $find.ClearFormatting()
    $find.Replacement.ClearFormatting()
    $null = $find.Execute(
        $FindText,
        $false,
        $false,
        $false,
        $false,
        $false,
        $true,
        1,
        $false,
        $ReplaceText,
        2
    )
}

function Set-ParagraphTextByPrefix {
    param(
        [object]$Document,
        [string]$Prefix,
        [string]$Replacement
    )

    foreach ($paragraph in $Document.Paragraphs) {
        $text = $paragraph.Range.Text.Trim([char]13, [char]7, " ", "`t")
        if ($text.StartsWith($Prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $paragraph.Range.Text = "$Replacement`r"
            return $true
        }
    }
    return $false
}

$source = (Resolve-Path -LiteralPath $SourcePath).Path
$outputDocx = [System.IO.Path]::GetFullPath($OutputDocxPath)
$outputPdf = [System.IO.Path]::GetFullPath($OutputPdfPath)
Copy-Item -LiteralPath $source -Destination $outputDocx -Force

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0

try {
    $document = $word.Documents.Open($outputDocx)
    try {
        # Replace the imported two-column header with a stable native Word table.
        $headerEnd = $document.Paragraphs.Item(4).Range.End
        $document.Range(0, $headerEnd).Delete()
        $headerTable = $document.Tables.Add($document.Range(0, 0), 1, 2)
        $headerTable.Borders.Enable = 0
        $headerTable.AllowAutoFit = $true
        $headerTable.Rows.AllowBreakAcrossPages = 0
        $headerTable.Cell(1, 1).Range.Text = "ĐẠI HỌC QUỐC GIA TP. HỒ CHÍ MINH`rTRƯỜNG ĐẠI HỌC CÔNG NGHỆ THÔNG TIN"
        $headerTable.Cell(1, 2).Range.Text = "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM`rĐộc lập - Tự do - Hạnh phúc"
        $headerTable.Range.Font.Name = "Times New Roman"
        $headerTable.Range.Font.Size = 12
        $headerTable.Range.Font.Bold = 1
        $headerTable.Range.ParagraphFormat.Alignment = 1
        $headerTable.Range.Cells.VerticalAlignment = 0
        $headerTable.Range.ParagraphFormat.SpaceAfter = 0
        $headerTable.Range.ParagraphFormat.LineSpacingRule = 0

        # Remove HTML-generated section breaks so content flows naturally.
        $sectionBreakFinder = $document.Content.Duplicate.Find
        $sectionBreakFinder.ClearFormatting()
        $sectionBreakFinder.Replacement.ClearFormatting()
        $null = $sectionBreakFinder.Execute("^b", $false, $false, $false, $false, $false, $true, 1, $false, "", 2)

        Replace-AllText -Document $document -FindText "Thạc Sĩ Đỗ Minh Tiến" -ReplaceText "ThS. Đỗ Minh Tiến"
        Replace-AllText -Document $document -FindText "TP. HCM, ngày ..... tháng ..... năm 2026" -ReplaceText "TP. HCM, ngày 14 tháng 07 năm 2026"

        $scopeText = "Dữ liệu hiện có 63 điểm đến, bao phủ 63 tỉnh, thành phố và được phân bổ theo ba miền Bắc, Trung, Nam; quản trị viên có thể cập nhật nội dung, trạng thái và hình ảnh của từng địa điểm."
        $null = Set-ParagraphTextByPrefix -Document $document -Prefix "Dữ liệu điểm đến đại diện cho ba miền" -Replacement $scopeText

        $submissionNote = "Ghi chú: tiến độ có thể được cập nhật theo lịch hướng dẫn và kế hoạch chính thức của Khoa."
        $null = Set-ParagraphTextByPrefix -Document $document -Prefix "Lưu ý khi nộp:" -Replacement $submissionNote

        # Locate the implementation plan by its five-column header and update status cells.
        foreach ($table in $document.Tables) {
            if ($table.Columns.Count -ne 5 -or $table.Rows.Count -lt 8) {
                continue
            }
            $firstCell = $table.Cell(1, 1).Range.Text.Trim([char]13, [char]7, " ")
            $secondCell = $table.Cell(1, 2).Range.Text.Trim([char]13, [char]7, " ")
            if ($firstCell -eq "STT" -and $secondCell -eq "Công việc") {
                $table.Cell(2, 5).Range.Text = "Đang thực hiện"
                $table.Cell(3, 5).Range.Text = "Dự kiến"
            }
        }

        foreach ($section in $document.Sections) {
            $section.PageSetup.PaperSize = 7
            $section.PageSetup.TopMargin = $word.CentimetersToPoints(2)
            $section.PageSetup.BottomMargin = $word.CentimetersToPoints(2)
            $section.PageSetup.LeftMargin = $word.CentimetersToPoints(2.8)
            $section.PageSetup.RightMargin = $word.CentimetersToPoints(1.8)
            $section.PageSetup.HeaderDistance = $word.CentimetersToPoints(1)
            $section.PageSetup.FooterDistance = $word.CentimetersToPoints(1)
            try { $section.Borders.Enable = 0 } catch {}
        }

        foreach ($table in $document.Tables) {
            try { $table.Rows.AllowBreakAcrossPages = 0 } catch {}
        }

        $document.Fields.Update() | Out-Null
        $document.Repaginate()
        $document.Save()
        $document.ExportAsFixedFormat($outputPdf, 17)

        Write-Output "PAGES=$($document.ComputeStatistics(2))"
        Write-Output "SECTIONS=$($document.Sections.Count)"
        Write-Output "TABLES=$($document.Tables.Count)"
    } finally {
        $document.Close(0)
    }
} finally {
    $word.Quit()
}
