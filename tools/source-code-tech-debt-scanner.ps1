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
    $OutputPath = Join-Path $outDir 'source-tech-debt.json'
}

$sourceRoot = Join-Path $ProjectRoot 'Source'
if (-not (Test-Path $sourceRoot)) { Write-Host "Source folder not found: $sourceRoot"; exit 1 }

$excludeFolders = @('ThirdParty','Plugins','External','Vendor')

$files = Get-ChildItem -LiteralPath $sourceRoot -Recurse -Include '*.cpp','*.h' -File -ErrorAction SilentlyContinue | Where-Object {
    $p = $_.FullName
    foreach ($ex in $excludeFolders) { if ($p -match "\\$ex\\") { return $false } }
    return $true
} | Sort-Object FullName

$totalFiles = $files.Count
$totalLOC = 0

foreach ($file in $files) {
    $lines = (Get-Content -LiteralPath $file.FullName -ErrorAction SilentlyContinue).Count
    $totalLOC += $lines
}

$pattern = '(?i)//\s*(TODO|FIXME|HACK|OPTIMIZE):(.*)'
$matches = @()
if ($files.Count -gt 0) {
    $matches = Select-String -Path ($files | ForEach-Object { $_.FullName }) -Pattern $pattern -AllMatches -ErrorAction SilentlyContinue
}

$issues = [System.Collections.Generic.List[object]]::new()
foreach ($m in $matches) {
    foreach ($match in $m.Matches) {
        $tag = $match.Groups[1].Value.ToUpper()
        $text = $match.Groups[2].Value.Trim()
        $entry = [ordered]@{
            file = $m.Path.Substring($ProjectRoot.Length + 1).Replace('\\','/')
            line = $m.LineNumber
            tag  = $tag
            text = $text
        }
        $issues.Add($entry)
    }
}

$result = [ordered]@{
    generated  = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    project    = $ProjectRoot
    totalFiles = $totalFiles
    totalLOC   = $totalLOC
    issues     = $issues
}

$json = $result | ConvertTo-Json -Depth 8
Set-Content -LiteralPath $OutputPath -Value $json -Encoding UTF8

Write-Host "Scanned $totalFiles files, $totalLOC LOC, found $($issues.Count) items. Wrote: $OutputPath"
