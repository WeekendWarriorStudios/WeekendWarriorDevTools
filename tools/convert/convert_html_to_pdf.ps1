param(
    [string]$HtmlDirectory = 'A:\Projects\ColossusRising\Documentation\colossus-rising-design-documentation',
    [string]$EdgePath = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
)

if (-not $HtmlDirectory) {
    $HtmlDirectory = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) "Documentation"
}

if (-not (Test-Path $HtmlDirectory)) {
    Write-Host "HTML directory not found: $HtmlDirectory"
    exit 0
}

$htmlDir = $HtmlDirectory
$pdfDir = Join-Path $htmlDir "pdfs"
New-Item -ItemType Directory -Force -Path $pdfDir | Out-Null

if (-not (Test-Path $EdgePath)) {
    Write-Host "Microsoft Edge not found at: $EdgePath"
    exit 1
}

$htmlFiles = Get-ChildItem -Path $htmlDir -Filter "*.html" -Recurse

foreach ($file in $htmlFiles) {
    $pdfPath = Join-Path $pdfDir ($file.BaseName + ".pdf")
    Write-Host "Converting " $file.Name " to PDF..."
    $htmlPath = $file.FullName
    Start-Process -FilePath $edgePath -ArgumentList "--headless --disable-gpu --run-all-compositor-stages-before-draw --print-to-pdf=`"$pdfPath`" `"$htmlPath`"" -Wait -NoNewWindow
    Start-Sleep -Seconds 1
}
Write-Host "Done!"

