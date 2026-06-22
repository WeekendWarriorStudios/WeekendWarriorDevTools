param(
    [string]$HtmlDirectory = 'A:\Projects\ColossusRising\Documentation\colossus-rising-design-documentation',
    [switch]$Force = $false
)

if (-not $HtmlDirectory) {
    $HtmlDirectory = Join-Path (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))) "Documentation"
}

if (-not (Test-Path $HtmlDirectory)) {
    Write-Host "HTML directory not found: $HtmlDirectory" -ForegroundColor Red
    exit 1
}

$markdownDir = Join-Path $HtmlDirectory "markdown"
New-Item -ItemType Directory -Force -Path $markdownDir | Out-Null

$nodeCheck = & node --version 2>$null
if (-not $nodeCheck) {
    Write-Host "Node.js not found. Please install Node.js from https://nodejs.org/" -ForegroundColor Red
    exit 1
}

$converterScript = Join-Path $PSScriptRoot "lib\html-to-markdown.js"

if (-not (Test-Path $converterScript)) {
    Write-Host "Converter script not found: $converterScript" -ForegroundColor Red
    exit 1
}

Write-Host "Checking for required packages..." -ForegroundColor Cyan
& npm list turndown 2>$null | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing required packages (turndown, turndown-plugin-gfm)..." -ForegroundColor Yellow
    $npmDir = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
    Push-Location $npmDir

    & npm install --save-dev turndown turndown-plugin-gfm 2>&1

    Pop-Location

    if ($LASTEXITCODE -ne 0 -and -not $Force) {
        Write-Host "Failed to install packages. Run with -Force to continue anyway." -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "Converting HTML files..." -ForegroundColor Cyan
Write-Host "Input:  $HtmlDirectory" -ForegroundColor Cyan
Write-Host "Output: $markdownDir" -ForegroundColor Cyan
Write-Host ""

& node $converterScript $HtmlDirectory $markdownDir
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "[OK] Conversion complete!" -ForegroundColor Green
    Write-Host "Markdown files saved to: $markdownDir" -ForegroundColor Green
    exit 0
} else {
    Write-Host "[ERROR] Conversion failed" -ForegroundColor Red
    exit 1
}
