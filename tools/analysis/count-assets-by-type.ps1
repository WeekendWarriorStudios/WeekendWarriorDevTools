<#
    Count all Content/ assets grouped by file extension and top-level folder.
    Gives a quick structural overview of the project's asset composition.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\count-assets-by-type.ps1
#>
param(
    [string]$ProjectRoot = '',
    [string]$OutputPath  = ''
)

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
    # Fallback for submodule nesting: if no .uproject found, try one level up
    $testUproject = Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.uproject' -File -ErrorAction SilentlyContinue
    if (-not $testUproject) {
        $ProjectRoot = Split-Path -Parent $ProjectRoot
    }
}

if (-not $OutputPath) {
    $outDir = Join-Path $PSScriptRoot 'outputs'
    if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
    $OutputPath = Join-Path $outDir 'asset-type-counts.json'
}

$contentRoot = Join-Path $ProjectRoot 'Content'
if (-not (Test-Path $contentRoot)) { Write-Host "Content folder not found: $contentRoot"; exit 1 }

$excludeDirs = @('__ExternalActors__', '__ExternalObjects__')

$allFiles = Get-ChildItem -LiteralPath $contentRoot -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
    $skip = $false
    foreach ($d in $excludeDirs) { if ($_.FullName -match "\\$d\\") { $skip = $true; break } }
    -not $skip
}

$byExtension = [ordered]@{}
$byFolder    = [ordered]@{}
$totalSize   = 0

foreach ($f in $allFiles) {
    $ext = $f.Extension.ToLower()
    if (-not $ext) { $ext = '(none)' }

    if (-not $byExtension.Contains($ext)) { $byExtension[$ext] = [ordered]@{ count = 0; sizeMB = 0.0 } }
    $byExtension[$ext].count++
    $byExtension[$ext].sizeMB += $f.Length / 1MB

    $rel     = $f.FullName.Substring($contentRoot.Length + 1)
    $topDir  = ($rel -split '[\\/]')[0]
    if (-not $byFolder.Contains($topDir)) { $byFolder[$topDir] = 0 }
    $byFolder[$topDir]++

    $totalSize += $f.Length
}

# round sizeMB values
foreach ($ext in $byExtension.Keys) {
    $byExtension[$ext].sizeMB = [math]::Round($byExtension[$ext].sizeMB, 2)
}

$result = [ordered]@{
    generated    = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    project      = $ProjectRoot
    totalFiles   = @($allFiles).Count
    totalSizeMB  = [math]::Round($totalSize / 1MB, 2)
    byExtension  = $byExtension
    byFolder     = $byFolder
}

$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Counted $(@($allFiles).Count) files ($([math]::Round($totalSize/1MB,1)) MB). Wrote: $OutputPath"


