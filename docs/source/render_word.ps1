$ErrorActionPreference = 'Stop'
$metaDocPath = 'C:\Users\user\Documents\ChatGPT\META\META_4_0_Подробный_отчёт.docx'
$metaPdfPath = 'C:\Users\user\Documents\ChatGPT\META\report_work\report_preview.pdf'
$metaWord = $null
$metaDocument = $null
try {
    $metaWord = New-Object -ComObject Word.Application
    $metaWord.Visible = $false
    $metaWord.DisplayAlerts = 0
    $metaDocument = $metaWord.Documents.Open($metaDocPath, $false, $true, $false)
    $metaDocument.Repaginate()
    $metaDocument.ExportAsFixedFormat($metaPdfPath, 17)
    Write-Output ('Pages: ' + $metaDocument.ComputeStatistics(2))
    Write-Output $metaPdfPath
} finally {
    if ($null -ne $metaDocument) { $metaDocument.Close(0) }
    if ($null -ne $metaWord) { $metaWord.Quit(0) }
}
