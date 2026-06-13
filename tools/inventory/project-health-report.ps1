<#
    Run all inventory tools and write a combined project-health JSON report.
    Each tool's output JSON is merged under its own key in the final report.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\project-health-report.ps1
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\project-health-report.ps1 -ProjectRoot C:\Projects\MyGame
#>
param(
    [string]$ProjectRoot = '',
    [string]$OutputPath  = ''
)

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
}

if (-not $OutputPath) {
    $outDir = Join-Path $PSScriptRoot 'outputs'
    if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
    $OutputPath = Join-Path $outDir 'project-health-report.json'
}

$tools = [ordered]@{
    plugins        = 'list-installed-plugins.ps1'
    assetPrefixes  = 'asset-prefix-breakdown.ps1'
    levelInventory = 'level-world-inventory.ps1'
    techDebt       = 'source-code-tech-debt-scanner.ps1'
    assetTypes     = 'count-assets-by-type.ps1'
    largeAssets    = 'find-large-assets.ps1'
    animations     = 'list-animation-assets.ps1'
}

$report = [ordered]@{
    generated   = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    project     = $ProjectRoot
    toolResults = [ordered]@{}
}

foreach ($key in $tools.Keys) {
    $scriptPath = Join-Path $PSScriptRoot $tools[$key]
    if (-not (Test-Path -LiteralPath $scriptPath)) {
        Write-Host "  [SKIP] $($tools[$key]) not found"
        $report.toolResults[$key] = $null
        continue
    }

    $tempOut = Join-Path ([System.IO.Path]::GetTempPath()) "$key-$(Get-Date -Format 'yyyyMMddHHmmss').json"
    Write-Host "  [RUN]  $($tools[$key])..."
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $scriptPath `
            -ProjectRoot $ProjectRoot -OutputPath $tempOut -ErrorAction Stop 2>&1 | Out-Null

        if (Test-Path -LiteralPath $tempOut) {
            $json = Get-Content -LiteralPath $tempOut -Raw -ErrorAction SilentlyContinue
            $report.toolResults[$key] = $json | ConvertFrom-Json
            Remove-Item -LiteralPath $tempOut -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Host "  [FAIL] $($tools[$key]): $_"
        $report.toolResults[$key] = [ordered]@{ error = "$_" }
    }
}

$report | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Project health report written to: $OutputPath"

