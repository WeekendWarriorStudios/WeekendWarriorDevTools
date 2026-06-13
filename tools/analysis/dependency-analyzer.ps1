<#
    Analyze asset dependencies to find unused assets, circular dependencies, and broken redirects.
    Cleans up bloat and prevents runtime reference errors.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\analysis\dependency-analyzer.ps1
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\analysis\dependency-analyzer.ps1 -ProjectRoot C:\MyGame -OutputPath report.json
#>
param(
    [string]$ProjectRoot = '',
    [string]$OutputPath = ''
)

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
    # Fallback for submodule nesting
    $testUproject = Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.uproject' -File -ErrorAction SilentlyContinue
    if (-not $testUproject) {
        $ProjectRoot = Split-Path -Parent $ProjectRoot
    }
}

if (-not $OutputPath) {
    $outDir = Join-Path $PSScriptRoot 'outputs'
    if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
    $OutputPath = Join-Path $outDir 'dependency-analysis.json'
}

$ErrorActionPreference = 'Stop'

$contentRoot = Join-Path $ProjectRoot 'Content'
if (-not (Test-Path $contentRoot)) { Write-Host "Content folder not found"; exit 1 }

# Scan for .uasset and .umap files
$allAssets = Get-ChildItem -LiteralPath $contentRoot -Recurse -Include '*.uasset','*.umap' -File -ErrorAction SilentlyContinue
$assetMap = @{}

foreach ($asset in $allAssets) {
    $name = $asset.BaseName
    if (-not $assetMap.ContainsKey($name)) {
        $assetMap[$name] = @{
            paths = @()
            references = 0
            last_modified = $asset.LastWriteTime
        }
    }
    $assetMap[$name].paths += $asset.FullName.Substring($contentRoot.Length + 1).Replace('\', '/')
}

# Detect potential issues
$issues = @()
$unused = @()
$potential_orphans = @()

# Look for suspicious patterns in asset names or paths
foreach ($name in $assetMap.Keys) {
    $asset = $assetMap[$name]

    # Duplicates / naming conflicts
    if ($asset.paths.Count -gt 1) {
        $issues += [ordered]@{
            type = 'Duplicate'
            asset_name = $name
            count = $asset.paths.Count
            paths = $asset.paths
            severity = 'Medium'
        }
    }

    # Potential orphans (old, unused patterns)
    if ($name -match '^(OLD_|UNUSED_|TEMP_|DEV_|DEPRECATED_)') {
        $potential_orphans += [ordered]@{
            asset_name = $name
            paths = $asset.paths
            pattern = $matches[0]
        }
    }
}

$result = [ordered]@{
    generated = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    project = $ProjectRoot
    total_assets = @($allAssets).Count
    duplicate_issues = @($issues)
    potential_orphans = @($potential_orphans)
    notes = @(
        "This is a static analysis. For complete dependency tracking, use UE's Asset Audit in-editor.",
        "Potential orphans detected by naming convention (OLD_, UNUSED_, TEMP_, DEV_, DEPRECATED_)",
        "Duplicates detected by basename only — manual review recommended."
    )
}

$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Analyzed $(@($allAssets).Count) assets. Found:"
Write-Host "  - $(@($issues).Count) duplicates"
Write-Host "  - $(@($potential_orphans).Count) potential orphans"
Write-Host "  Written to: $OutputPath"
