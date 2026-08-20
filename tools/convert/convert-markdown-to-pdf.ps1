#Requires -Version 5.1
<#
.SYNOPSIS
    Converts markdown documentation to PDF, mirroring the source folder structure.

.DESCRIPTION
    Walks -InputDir for *.md and writes a PDF per file at the same relative path under
    -OutputDir, so the two trees stay parallel.  Defaults line up with the generated-api
    layout the doc generators produce:

        Documentation\generated-api\markdown\   <- convert-cpp-to-markdown.ps1 writes here
        Documentation\generated-api\pdf\        <- this script writes here

    Markdown is rendered by lib\markdown-to-pdf.js (marked, GFM tables) and printed by a
    single headless Edge/Chrome instance via puppeteer-core.  One browser handles the whole
    run - launching one per file costs seconds each, and these doc sets run to thousands of
    files.  Required npm packages are installed on first use unless -SkipInstall is given.

    Conversion is incremental: a PDF at least as new as its .md is left alone.  Use -Force
    to re-render everything.

.PARAMETER InputDir
    Markdown root to scan.  Defaults to <ProjectRoot>\Documentation\generated-api\markdown,
    falling back to <ProjectRoot>\Documentation\generated-api if that folder does not exist yet.

.PARAMETER OutputDir
    PDF root.  Defaults to <ProjectRoot>\Documentation\generated-api\pdf.

.PARAMETER ProjectRoot
    UE project root.  Auto-detected from the script location when omitted.

.PARAMETER BrowserPath
    Chromium-based browser used for printing.  Auto-detected (Edge, then Chrome) when omitted.

.PARAMETER Css
    Extra stylesheet appended after the built-in print CSS, to restyle the output.

.PARAMETER Exclude
    Path globs (relative to -InputDir, forward slashes) to skip, e.g. "content/Graph/**".

.PARAMETER Concurrency
    Pages printed in parallel.  Defaults to 4.

.PARAMETER Max
    Stop after this many files.  Useful for smoke-testing styling before a full run.

.PARAMETER Force
    Re-render every file, ignoring up-to-date PDFs.

.PARAMETER DryRun
    List what would be written without launching a browser.

.PARAMETER SkipInstall
    Do not run npm install, even if the packages appear to be missing.

.EXAMPLE
    .\convert-markdown-to-pdf.ps1
    .\convert-markdown-to-pdf.ps1 -Max 5
    .\convert-markdown-to-pdf.ps1 -InputDir "..\..\..\Documentation\generated-api\markdown\source" -Force
    .\convert-markdown-to-pdf.ps1 -Exclude "content/Graph/**","**/Deprecated/**"
    .\convert-markdown-to-pdf.ps1 -DryRun
#>
param(
    [string]$InputDir = "",
    [string]$OutputDir = "",
    [string]$ProjectRoot = "",
    [string]$BrowserPath = "",
    [string]$Css = "",
    [string[]]$Exclude = @(),
    [int]$Concurrency = 4,
    [int]$Max = 0,
    [switch]$Force,
    [switch]$DryRun,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'

# tools\convert -> tools -> WeekendWarriorDevTools -> <ProjectRoot>
if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
}
if (-not (Test-Path $ProjectRoot)) {
    Write-Host "[ERROR] Project root not found: $ProjectRoot" -ForegroundColor Red
    exit 1
}
$ProjectRoot = (Resolve-Path $ProjectRoot).Path

$generatedApi = Join-Path $ProjectRoot "Documentation\generated-api"

if (-not $InputDir) {
    # Prefer the split layout; tolerate a tree that has not been reorganised yet.
    $markdownRoot = Join-Path $generatedApi "markdown"
    $InputDir = if (Test-Path $markdownRoot) { $markdownRoot } else { $generatedApi }
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $generatedApi "pdf"
}

if (-not (Test-Path $InputDir)) {
    Write-Host "[ERROR] Markdown directory not found: $InputDir" -ForegroundColor Red
    exit 1
}
$InputDir = (Resolve-Path $InputDir).Path

$converterScript = Join-Path $PSScriptRoot "lib\markdown-to-pdf.js"
if (-not (Test-Path $converterScript)) {
    Write-Host "[ERROR] Converter script not found: $converterScript" -ForegroundColor Red
    exit 1
}

# --- Node -------------------------------------------------------------------

$nodeVersion = & node --version 2>$null
if (-not $nodeVersion) {
    Write-Host "[ERROR] Node.js not found. Install from https://nodejs.org/" -ForegroundColor Red
    exit 1
}

# node_modules lives at the project root, matching convert_html_to_markdown.ps1; Node resolves
# it by walking up from lib\, so the converter finds the packages from there.
$npmDir = $ProjectRoot
$requiredPackages = @('marked', 'puppeteer-core')

if (-not $SkipInstall) {
    $missing = @($requiredPackages | Where-Object { -not (Test-Path (Join-Path $npmDir "node_modules\$_")) })
    if ($missing.Count -gt 0) {
        Write-Host "Installing required packages: $($missing -join ', ')" -ForegroundColor Yellow
        Push-Location $npmDir
        try {
            & npm install --save-dev @missing
            $installExit = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        if ($installExit -ne 0) {
            Write-Host "[ERROR] npm install failed. Install manually, or re-run with -SkipInstall." -ForegroundColor Red
            exit 1
        }
    }
}

# --- Browser ----------------------------------------------------------------

if (-not $BrowserPath) {
    $candidates = @(
        "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe",
        "C:\Program Files\Google\Chrome\Application\chrome.exe",
        "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    )
    $BrowserPath = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}
if (-not $BrowserPath -or -not (Test-Path $BrowserPath)) {
    Write-Host "[ERROR] No Chromium-based browser found. Pass -BrowserPath to msedge.exe or chrome.exe." -ForegroundColor Red
    exit 1
}

# --- Run --------------------------------------------------------------------

Write-Host "Markdown in : $InputDir" -ForegroundColor Cyan
Write-Host "PDF out     : $OutputDir" -ForegroundColor Cyan
Write-Host "Browser     : $BrowserPath" -ForegroundColor Cyan
Write-Host ""

$nodeArgs = @($converterScript, $InputDir, $OutputDir, '--browser', $BrowserPath, '--concurrency', $Concurrency)
if ($Css)      { $nodeArgs += @('--css', $Css) }
if ($Exclude)  { $nodeArgs += @('--exclude', ($Exclude -join ',')) }
if ($Max -gt 0){ $nodeArgs += @('--max', $Max) }
if ($Force)    { $nodeArgs += '--force' }
if ($DryRun)   { $nodeArgs += '--dry-run' }

& node @nodeArgs
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    if (-not $DryRun) {
        Write-Host ""
        Write-Host "[OK] PDFs written to: $OutputDir" -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "[ERROR] Conversion reported failures (exit $exitCode)." -ForegroundColor Red
}
exit $exitCode
