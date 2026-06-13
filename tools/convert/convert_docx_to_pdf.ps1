param(
    [string]$SourceDirectory = '',
    [string]$Filter = '*.docx'
)

if (-not $SourceDirectory) {
    $SourceDirectory = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) "Documentation\Quality Documents\00 Technical Standards"
}

if (-not (Test-Path $SourceDirectory)) {
    Write-Host "Source directory not found: $SourceDirectory"
    exit 0
}

try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
} catch {
    Write-Error "Microsoft Word application not found or not registered. DOCX to PDF conversion skipped." -ErrorAction Stop
}

if ($word) {
    $docs = Get-ChildItem -Path $SourceDirectory -Filter $Filter
    foreach ($doc in $docs) {
        $pdfPath = [System.IO.Path]::ChangeExtension($doc.FullName, ".pdf")
        Write-Host "Converting " $doc.Name
        $document = $word.Documents.Open($doc.FullName)
        $document.SaveAs([ref] $pdfPath, [ref] 17)
        $document.Close()
    }
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    Write-Host "Conversion completed."
} else {
    Write-Host "DOCX to PDF conversion aborted due to missing Word application."
}
