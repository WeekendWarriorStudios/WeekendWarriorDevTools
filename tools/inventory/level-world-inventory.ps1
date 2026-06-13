param(
    [string]$ProjectRoot = '',
    [string]$OutputPath  = ''
)

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
}

$ErrorActionPreference = 'Stop'

if (-not $OutputPath) {
    $outDir = Join-Path $PSScriptRoot 'outputs'
    if (-not (Test-Path -LiteralPath $outDir)) { New-Item -ItemType Directory -Path $outDir -Force | Out-Null }
    $OutputPath = Join-Path $outDir 'level-inventory.json'
}

$contentRoot = Join-Path $ProjectRoot 'Content'
if (-not (Test-Path $contentRoot)) { Write-Host "Content folder not found: $contentRoot"; exit 1 }

$umaps = Get-ChildItem -LiteralPath $contentRoot -Recurse -Filter '*.umap' -File -ErrorAction SilentlyContinue | Sort-Object FullName

$maps = [System.Collections.Generic.List[object]]::new()
$totalSize = 0

foreach ($m in $umaps) {
    $relative = $m.FullName.Substring($contentRoot.Length + 1).TrimStart('\','/')
    $parts = $relative -split '[\\/]'
    $category = if ($parts.Length -ge 2) { $parts[0] } else { '_root' }
    $sizeMB = [math]::Round(($m.Length / 1MB), 2)
    $isLevelInstance = ($m.FullName -match '\\LevelInstances\\') -or ($m.DirectoryName -match 'LevelInstances$')
    $maps.Add([ordered]@{
        path = $relative.Replace('\\','/')
        category = $category
        sizeMB = $sizeMB
        isLevelInstance = $isLevelInstance
    })
    $totalSize += $m.Length
}

$result = [ordered]@{
    generated = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    project = $ProjectRoot
    totalMaps = $maps.Count
    totalSizeMB = [math]::Round($totalSize / 1MB, 2)
    maps = $maps
}

$json = $result | ConvertTo-Json -Depth 8
Set-Content -LiteralPath $OutputPath -Value $json -Encoding UTF8

Write-Host "Found $($maps.Count) maps, total size $($result.totalSizeMB) MB. Wrote: $OutputPath"

