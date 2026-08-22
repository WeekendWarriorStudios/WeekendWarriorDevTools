param(
    [string]$ProjectRoot = '',
    [string]$OutputPath = '',
    [string[]]$PluginNames = @()
)

$ErrorActionPreference = 'Stop'

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
    # Fallback for submodule nesting: if no .uproject found, try one level up
    $testUproject = Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.uproject' -File -ErrorAction SilentlyContinue
    if (-not $testUproject) {
        $ProjectRoot = Split-Path -Parent $ProjectRoot
    }
}

# Always write inventory output under the project documentation reports folder.
$outDir = Join-Path $ProjectRoot 'Documentation/analysis-reports'
if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
$OutputPath = Join-Path $outDir 'animation-assets.json'

$contentRoots = [System.Collections.Generic.List[object]]::new()
$contentRoots.Add([PSCustomObject]@{ Name = '_project'; Path = Join-Path $ProjectRoot 'Content' })

$pluginFiles = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'Plugins') -Recurse -Filter '*.uplugin' -File -ErrorAction SilentlyContinue
foreach ($pluginFile in $pluginFiles) {
    $pluginContent = Join-Path $pluginFile.DirectoryName 'Content'
    if (Test-Path -LiteralPath $pluginContent) {
        $contentRoots.Add([PSCustomObject]@{ Name = $pluginFile.BaseName; Path = $pluginContent })
    }
}

if ($PluginNames.Count -gt 0) {
    $contentRoots = [System.Collections.Generic.List[object]]@(
        $contentRoots | Where-Object { $_.Name -eq '_project' -or $_.Name -in $PluginNames }
    )
}

$contentRoots = [System.Collections.Generic.List[object]]@(
    $contentRoots | Group-Object Path | ForEach-Object { $_.Group[0] }
)

$result = [ordered]@{
    generated = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    plugins   = [ordered]@{}
}

$totalAnimations = 0
$totalPoseSearch = 0
$seenAssets = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

foreach ($contentRootInfo in $contentRoots) {
    $pluginName = $contentRootInfo.Name
    $contentRoot = $contentRootInfo.Path

    $animations = [ordered]@{}
    $schemas    = [System.Collections.Generic.List[string]]::new()
    $databases  = [System.Collections.Generic.List[string]]::new()
    $psOther    = [System.Collections.Generic.List[string]]::new()

    if (-not (Test-Path -LiteralPath $contentRoot)) { continue }

    foreach ($file in (Get-ChildItem -LiteralPath $contentRoot -Recurse -Filter '*.uasset' -File | Sort-Object FullName)) {
        $relative = $file.FullName.Substring($contentRoot.Length).TrimStart('\', '/')
        $parts = $relative -split '[\\/]'
        $assetName = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
        $isPoseSearch = $parts -contains 'PoseSearch' -or $assetName -like 'PSS_*' -or $assetName -like 'PSD_*'
        $isAnimation = $parts -contains 'Animation' -or $parts -contains 'Animations' -or
                       $assetName -match '^(AS|AM|ABP|AO|BS|PSS|PSD|PA)_'

        if (-not $isAnimation -and -not $isPoseSearch) { continue }
        if (-not $seenAssets.Add($file.FullName)) { continue }

        if ($isPoseSearch) {
            if ($assetName -like 'PSS_*') {
                $schemas.Add($assetName)
            } elseif ($assetName -like 'PSD_*') {
                $databases.Add($assetName)
            } else {
                $psOther.Add($assetName)
            }
            $totalPoseSearch++
            continue
        }

        $category = if ($parts.Count -gt 1) { $parts[0] } else { '_root' }
        if (-not $animations.Contains($category)) {
            $animations[$category] = [System.Collections.Generic.List[string]]::new()
        }
        $animations[$category].Add($assetName)
        $totalAnimations++
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


