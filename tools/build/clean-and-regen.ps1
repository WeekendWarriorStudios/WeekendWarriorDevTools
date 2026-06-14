<#
    Deep-clean all Unreal Engine build artifacts and regenerate Visual Studio project files.
    Use this when you have corrupt caches, stale VS solutions, or want a clean slate before a build.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean-and-regen.ps1
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean-and-regen.ps1 -SkipRegen
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean-and-regen.ps1 -DryRun
#>
param(
    [string]$ProjectRoot = '',
    [string]$EnginePath  = 'A:\GE\UE_5.7',
    [string]$UEVersion   = '5.7',
    [switch]$SkipRegen,
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

# Resolve the UnrealBuildTool executable.
# $EnginePath is an engine *root* (e.g. A:\GE\UE_5.7); UBT lives under it.
# If no engine root was given, probe the common install locations.
$ubtRelative = 'Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.exe'
$UbtPath = ''
if ($EnginePath) {
    if ($EnginePath -like '*UnrealBuildTool.exe') {
        # Caller passed the exe directly.
        $UbtPath = $EnginePath
    } else {
        $UbtPath = Join-Path $EnginePath $ubtRelative
    }
} else {
    $engineRoots = @(
        "C:\Program Files\Epic Games\UE_$UEVersion",
        "C:\Program Files (x86)\Epic Games\UE_$UEVersion",
        "D:\Epic Games\UE_$UEVersion",
        "E:\Epic Games\UE_$UEVersion"
    )
    foreach ($r in $engineRoots) {
        $candidate = Join-Path $r $ubtRelative
        if (Test-Path $candidate) { $UbtPath = $candidate; break }
    }
}

$targetDirs = @('Binaries', 'Intermediate', 'DerivedDataCache', 'Saved', '.vs')

Write-Host "Project: $uprojectPath"
Write-Host "Cleaning build artifacts..." -ForegroundColor Cyan

foreach ($dir in $targetDirs) {
    $full = Join-Path $ProjectRoot $dir
    if (Test-Path $full) {
        if ($DryRun) {
            Write-Host "  [DRY RUN] Would remove: $full" -ForegroundColor Yellow
        } else {
            Remove-Item -Path $full -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host "  Removed: $dir" -ForegroundColor Yellow
        }
    }
}

# Clean plugin build artifacts too
$pluginsRoot = Join-Path $ProjectRoot 'Plugins'
if (Test-Path $pluginsRoot) {
    Get-ChildItem -Path $pluginsRoot -Recurse -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in $targetDirs } |
        ForEach-Object {
            if ($DryRun) {
                Write-Host "  [DRY RUN] Would remove plugin dir: $($_.FullName)" -ForegroundColor Yellow
            } else {
                Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
                Write-Host "  Removed plugin dir: $($_.FullName)" -ForegroundColor Yellow
            }
        }
}

if ($SkipRegen) {
    Write-Host "Skipping project file regeneration (-SkipRegen specified)." -ForegroundColor Gray
    exit 0
}

if (-not $UbtPath -or -not (Test-Path $UbtPath)) {
    Write-Host "UnrealBuildTool not found (looked for: $UbtPath). Skipping project file regeneration." -ForegroundColor Yellow
    Write-Host "Specify -EnginePath (engine root) or -UEVersion to enable regeneration."
    exit 0
}

Write-Host "Regenerating Visual Studio project files..." -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "  [DRY RUN] Would run: $UbtPath -projectfiles -project=`"$uprojectPath`" -game -rocket -progress" -ForegroundColor Yellow
} else {
    & $UbtPath -projectfiles -project="$uprojectPath" -game -rocket -progress
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Project file regeneration failed (exit code $LASTEXITCODE)."
        exit $LASTEXITCODE
    }
    Write-Host "Done!" -ForegroundColor Green
}


