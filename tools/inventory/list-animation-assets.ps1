param(
    [string]$ProjectRoot = '',
    [string]$OutputPath = '',
    [string[]]$PluginNames = @()
)

$ErrorActionPreference = 'Stop'

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
}

if (-not $OutputPath) {
    $outDir = Join-Path $PSScriptRoot 'outputs'
    if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
    $OutputPath = Join-Path $outDir 'animation-assets.json'
}

$gameFeatureRoot = Join-Path $ProjectRoot 'Plugins\Game Features'

# auto-detect Game Feature plugins if none specified
if ($PluginNames.Count -eq 0) {
    if (Test-Path -LiteralPath $gameFeatureRoot) {
        $PluginNames = Get-ChildItem -LiteralPath $gameFeatureRoot -Directory | ForEach-Object { $_.Name }
    }
    if ($PluginNames.Count -eq 0) {
        Write-Host "No Game Feature plugins found in: $gameFeatureRoot"
        exit 0
    }
}

$result = [ordered]@{
    generated = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    plugins   = [ordered]@{}
}

$totalAnimations = 0
$totalPoseSearch = 0

foreach ($pluginName in $PluginNames) {
    $contentRoot    = Join-Path $gameFeatureRoot "$pluginName\Content"
    $animPath       = Join-Path $contentRoot 'Animations'
    $poseSearchPath = Join-Path $contentRoot 'PoseSearch'

    $animations = [ordered]@{}
    $schemas    = [System.Collections.Generic.List[string]]::new()
    $databases  = [System.Collections.Generic.List[string]]::new()
    $psOther    = [System.Collections.Generic.List[string]]::new()

    # --- Animations ---
    if (Test-Path $animPath) {
        $animFiles = Get-ChildItem -LiteralPath $animPath -Recurse -Filter '*.uasset' -File |
                     Sort-Object DirectoryName, Name

        foreach ($file in $animFiles) {
            $relative  = $file.DirectoryName.Substring($animPath.Length).TrimStart('\', '/')
            $category  = if ($relative) { $relative.Split('\')[0] } else { '_root' }
            $assetName = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)

            if (-not $animations.Contains($category)) {
                $animations[$category] = [System.Collections.Generic.List[string]]::new()
            }
            $animations[$category].Add($assetName)
            $totalAnimations++
        }
    }

    # --- Pose Search ---
    if (Test-Path $poseSearchPath) {
        $psFiles = Get-ChildItem -LiteralPath $poseSearchPath -Recurse -Filter '*.uasset' -File |
                   Sort-Object Name

        foreach ($file in $psFiles) {
            $assetName = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
            if ($assetName -like 'PSS_*') {
                $schemas.Add($assetName)
            } elseif ($assetName -like 'PSD_*') {
                $databases.Add($assetName)
            } else {
                $psOther.Add($assetName)
            }
            $totalPoseSearch++
        }
    }

    $poseSearch = [ordered]@{
        schemas   = $schemas
        databases = $databases
    }
    if ($psOther.Count -gt 0) { $poseSearch['other'] = $psOther }

    $result.plugins[$pluginName] = [ordered]@{
        animations = $animations
        poseSearch = $poseSearch
    }
}

$result['totalAnimations'] = $totalAnimations
$result['totalPoseSearch']  = $totalPoseSearch
$result['totalAssets']      = $totalAnimations + $totalPoseSearch

$json = $result | ConvertTo-Json -Depth 8
Set-Content -LiteralPath $OutputPath -Value $json -Encoding UTF8

Write-Host "Wrote $totalAnimations animations + $totalPoseSearch pose search assets ($($result.totalAssets) total) to: $OutputPath"

