<#
    Run a headless Unreal Automation Tool (UAT) build-cook-run cycle.
    Bypasses the editor GUI for faster, memory-efficient local builds and nightlies.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\headless-cook.ps1
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\headless-cook.ps1 -Platform Win64 -Config Shipping -StagingDir D:\Builds\MyGame
#>
param(
    [string]$ProjectRoot  = '',
    [string]$UATPath      = '',
    [string]$UEVersion    = '5.7',
    [string]$Platform     = 'Win64',
    [string]$Config       = 'Development',
    [string]$StagingDir   = '',
    [switch]$SkipBuild,
    [switch]$SkipCook,
    [switch]$SkipPackage,
    [switch]$DryRun
)

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
    # Fallback for submodule nesting: if no .uproject found, try one level up
    $testUproject = Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.uproject' -File -ErrorAction SilentlyContinue
    if (-not $testUproject) {
        $ProjectRoot = Split-Path -Parent $ProjectRoot
    }
}

# Auto-detect .uproject
$uprojectFiles = Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.uproject' -File -ErrorAction SilentlyContinue
if (-not $uprojectFiles) { Write-Error "No .uproject file found in: $ProjectRoot"; exit 1 }
$uprojectPath = $uprojectFiles[0].FullName
$projectName  = [System.IO.Path]::GetFileNameWithoutExtension($uprojectPath)

# Default staging directory
if (-not $StagingDir) {
    $StagingDir = Join-Path $ProjectRoot "Staging\$Platform"
}

# Auto-detect UAT
if (-not $UATPath) {
    $candidates = @(
        "C:\Program Files\Epic Games\UE_$UEVersion\Engine\Build\BatchFiles\RunUAT.bat",
        "C:\Program Files (x86)\Epic Games\UE_$UEVersion\Engine\Build\BatchFiles\RunUAT.bat",
        "D:\Epic Games\UE_$UEVersion\Engine\Build\BatchFiles\RunUAT.bat",
        "E:\Epic Games\UE_$UEVersion\Engine\Build\BatchFiles\RunUAT.bat"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $UATPath = $c; break }
    }
}

if (-not $UATPath -or -not (Test-Path $UATPath)) {
    Write-Error "RunUAT.bat not found. Specify -UATPath or -UEVersion."
    exit 1
}

# Build argument list
$args = @(
    'BuildCookRun',
    "-project=`"$uprojectPath`"",
    "-noP4",
    "-clientconfig=$Config",
    "-serverconfig=$Config",
    "-nocompileeditor",
    "-unattended",
    "-utf8output",
    "-platform=$Platform",
    "-stagingdirectory=`"$StagingDir`"",
    '-cmdline="-messaging"'
)

if (-not $SkipBuild)   { $args += '-build' }
if (-not $SkipCook)    { $args += '-cook' }
if (-not $SkipPackage) { $args += '-stage'; $args += '-package' }

Write-Host "Project : $uprojectPath"
Write-Host "Platform: $Platform  Config: $Config"
Write-Host "Staging : $StagingDir"
Write-Host ""

if ($DryRun) {
    Write-Host "[DRY RUN] Would run:" -ForegroundColor Yellow
    Write-Host "  $UATPath $($args -join ' ')" -ForegroundColor Yellow
    exit 0
}

Write-Host "Starting UAT cook..." -ForegroundColor Cyan
& cmd.exe /c "`"$UATPath`" $($args -join ' ')"

if ($LASTEXITCODE -eq 0) {
    Write-Host "Build completed successfully." -ForegroundColor Green
} else {
    Write-Host "Build failed with exit code $LASTEXITCODE." -ForegroundColor Red
    exit $LASTEXITCODE
}


