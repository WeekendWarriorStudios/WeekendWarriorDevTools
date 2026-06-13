<#
    Find large assets in the project's Content folder.
    Outputs a ranked list of assets exceeding the size threshold.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\find-large-assets.ps1
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\find-large-assets.ps1 -ThresholdMB 50 -Top 25
#>
param(
    [string]$ProjectRoot = '',
    [string]$OutputPath  = '',
    [double]$ThresholdMB = 10,
    [int]$Top            = 50,
    [string[]]$Extensions = @('.uasset', '.umap')
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
    $OutputPath = Join-Path $outDir 'large-assets.json'
}

$contentRoot = Join-Path $ProjectRoot 'Content'
if (-not (Test-Path $contentRoot)) { Write-Host "Content folder not found: $contentRoot"; exit 1 }

$thresholdBytes = $ThresholdMB * 1MB
$extSet = [System.Collections.Generic.HashSet[string]]::new($Extensions, [System.StringComparer]::OrdinalIgnoreCase)

$allFiles = Get-ChildItem -LiteralPath $contentRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $extSet.Contains($_.Extension) } |
    Where-Object { $_.Length -ge $thresholdBytes } |
    Sort-Object Length -Descending |
    Select-Object -First $Top

$assets = $allFiles | ForEach-Object {
    [ordered]@{
        path      = $_.FullName.Substring($contentRoot.Length + 1).Replace('\', '/')
        sizeMB    = [math]::Round($_.Length / 1MB, 2)
        extension = $_.Extension
        modified  = $_.LastWriteTime.ToString('yyyy-MM-ddTHH:mm:ss')
    }
}

$result = [ordered]@{
    generated    = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    project      = $ProjectRoot
    thresholdMB  = $ThresholdMB
    found        = @($assets).Count
    assets       = @($assets)
}

$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Found $(@($assets).Count) assets >= ${ThresholdMB}MB. Wrote: $OutputPath"


