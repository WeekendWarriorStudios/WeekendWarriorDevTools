param(
    [string]$ProjectRoot = '',
    [string]$OutputPath  = ''
)

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

$ErrorActionPreference = 'Stop'

if (-not $OutputPath) {
    $outDir = Join-Path $PSScriptRoot 'outputs'
    if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
    $OutputPath = Join-Path $outDir 'asset-prefix-breakdown.json'
}

$contentRoot = Join-Path $ProjectRoot 'Content'
if (-not (Test-Path $contentRoot)) { Write-Host "Content folder not found: $contentRoot"; exit 1 }

$excludeDirs = @('__ExternalActors__','__ExternalObjects__')

$prefixMap = @{
    'SM_'  = 'StaticMesh'
    'SK_'  = 'SkeletalMesh'
    'T_'   = 'Texture'
    'BP_'  = 'Blueprint'
    'PSS_' = 'PoseSearchSchema'
    'PSD_' = 'PoseSearchDatabase'
    'M_'   = 'Material'
    'MAT_' = 'Material'
    'FX_'  = 'VFX'
    'ANIM_'= 'Animation'
    'SFX_' = 'Sound'
    'UI_'  = 'UI'
}

$categoryAssets = [ordered]@{}
$needsCleanup = [System.Collections.Generic.List[string]]::new()
$total = 0

$uassets = Get-ChildItem -LiteralPath $contentRoot -Recurse -Filter '*.uasset' -File -ErrorAction SilentlyContinue | Sort-Object FullName

foreach ($file in $uassets) {
    # Skip OFPA / world partition noise directories
    $skip = $false
    foreach ($d in $excludeDirs) {
        if ($file.FullName -match "\\$d\\") { $skip = $true; break }
    }
    if ($skip) { continue }

    $assetName = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
    $matched = $false
    foreach ($prefix in $prefixMap.Keys) {
        if ($assetName.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            $category = $prefixMap[$prefix]
            if (-not $categoryAssets.Contains($category)) { $categoryAssets[$category] = [System.Collections.Generic.List[string]]::new() }
            $categoryAssets[$category].Add($assetName)
            $matched = $true
            break
        }
    }
    if (-not $matched) {
        $category = 'Unknown'
        if (-not $categoryAssets.Contains($category)) { $categoryAssets[$category] = [System.Collections.Generic.List[string]]::new() }
        $categoryAssets[$category].Add($assetName)
        $relative = $file.FullName.Substring($ProjectRoot.Length + 1).Replace('\','/')
        $needsCleanup.Add($relative)
    }
    $total++
}

$result = [ordered]@{
    generated    = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    project      = $ProjectRoot
    totalAssets  = $total
    categories   = $categoryAssets
    needsCleanup = $needsCleanup
}

$json = $result | ConvertTo-Json -Depth 10
Set-Content -LiteralPath $OutputPath -Value $json -Encoding UTF8

Write-Host "Wrote $total assets to $OutputPath ($($needsCleanup.Count) need cleanup)"
