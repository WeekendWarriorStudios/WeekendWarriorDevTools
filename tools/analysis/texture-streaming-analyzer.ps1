<#
    Analyze texture streaming pool configuration and actual usage.
    Flags oversubscription situations to prevent streaming pool exhaustion crashes.

    Parses texture stats from console output or log files.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\analysis\texture-streaming-analyzer.ps1
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\analysis\texture-streaming-analyzer.ps1 -StatsCsvFile textures.csv
#>
param(
    [string]$ProjectRoot = '',
    [string]$StatsCsvFile = '',
    [string]$OutputPath = ''
)

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
    $testUproject = Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.uproject' -File -ErrorAction SilentlyContinue
    if (-not $testUproject) {
        $ProjectRoot = Split-Path -Parent $ProjectRoot
    }
}

if (-not $OutputPath) {
    $outDir = Join-Path $PSScriptRoot 'outputs'
    if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
    $OutputPath = Join-Path $outDir 'texture-streaming-analysis.json'
}

$ErrorActionPreference = 'Stop'

# Default pool sizes (from DefaultEngine.ini)
$poolConfig = [ordered]@{
    streaming_pool_size_mb = 1000
    max_texture_size = 4096
    platform = 'Win64'
}

# Try to read from DefaultEngine.ini if it exists
$engineIni = Join-Path $ProjectRoot 'Config\DefaultEngine.ini'
if (Test-Path -LiteralPath $engineIni) {
    $iniContent = Get-Content -LiteralPath $engineIni -Raw

    if ($iniContent -match 'PoolSize=(\d+)') {
        $poolConfig.streaming_pool_size_mb = [int]$matches[1] / (1024 * 1024)
    }
    if ($iniContent -match 'MaxTextureMIPCount=(\d+)') {
        $poolConfig.max_texture_size = [math]::Pow(2, [int]$matches[1])
    }
}

$textureStats = @()

if ($StatsCsvFile -and (Test-Path -LiteralPath $StatsCsvFile)) {
    $lines = Get-Content -LiteralPath $StatsCsvFile
    foreach ($line in $lines | Select-Object -Skip 1) {
        $parts = $line -split ','
        if ($parts.Count -ge 3) {
            $textureStats += [ordered]@{
                name = $parts[0].Trim()
                size_mb = [double]$parts[1].Trim()
                mip_levels = [int]$parts[2].Trim()
            }
        }
    }
} else {
    # Generate synthetic data for demonstration
    $textureStats = @(
        [ordered]@{ name = "T_Environment_DetailMap"; size_mb = 128.5; mip_levels = 11 }
        [ordered]@{ name = "T_Character_Diffuse"; size_mb = 256.0; mip_levels = 9 }
        [ordered]@{ name = "T_SkySphere"; size_mb = 512.0; mip_levels = 10 }
    )
}

$totalUsed = ($textureStats | Measure-Object -Property size_mb -Sum).Sum
$poolSizeMB = $poolConfig.streaming_pool_size_mb
$utilizationPercent = [math]::Round(($totalUsed / $poolSizeMB) * 100, 2)

$largeTextures = $textureStats | Where-Object { $_.size_mb -gt 256 }
$warningThreshold = $poolSizeMB * 0.85

$warnings = @()
if ($utilizationPercent -gt 85) {
    $warnings += [ordered]@{
        severity = 'High'
        message = "Streaming pool is $utilizationPercent% full. Risk of exhaustion during level streaming."
    }
}

if (@($largeTextures).Count -gt 3) {
    $warnings += [ordered]@{
        severity = 'Medium'
        message = "$(@($largeTextures).Count) textures exceed 256MB. Consider streaming mips or resolution reduction."
    }
}

$result = [ordered]@{
    generated = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    project = $ProjectRoot
    pool_config = $poolConfig
    utilization = [ordered]@{
        used_mb = [math]::Round($totalUsed, 2)
        pool_size_mb = $poolSizeMB
        percent_used = $utilizationPercent
        available_mb = [math]::Round($poolSizeMB - $totalUsed, 2)
    }
    texture_count = @($textureStats).Count
    large_textures = @($largeTextures) | Sort-Object -Property size_mb -Descending | Select-Object -First 5
    warnings = @($warnings)
}

$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Texture Streaming Analysis:"
Write-Host "  Pool: $($poolConfig.streaming_pool_size_mb) MB"
Write-Host "  Used: $([math]::Round($totalUsed, 1)) MB ($utilizationPercent%)"
Write-Host "  Available: $([math]::Round($poolSizeMB - $totalUsed, 1)) MB"
Write-Host "  Warnings: $(@($warnings).Count)"
Write-Host "  Written to: $OutputPath"
