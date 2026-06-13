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
    [string]$EnginePath  = '',
    [string]$UEVersion   = '5.7',
    [switch]$SkipRegen,
    [switch]$DryRun
)

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
}

# Auto-detect .uproject
$uprojectFiles = Get-ChildItem -LiteralPath $ProjectRoot -Filter '*.uproject' -File -ErrorAction SilentlyContinue
if (-not $uprojectFiles) { Write-Error "No .uproject file found in: $ProjectRoot"; exit 1 }
$uprojectPath = $uprojectFiles[0].FullName

# Auto-detect UBT if not specified
if (-not $EnginePath) {
    $candidates = @(
        "C:\Program Files\Epic Games\UE_$UEVersion\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.exe",
        "C:\Program Files (x86)\Epic Games\UE_$UEVersion\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.exe",
        "D:\Epic Games\UE_$UEVersion\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.exe",
        "E:\Epic Games\UE_$UEVersion\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $EnginePath = $c; break }
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

if (-not $EnginePath -or -not (Test-Path $EnginePath)) {
    Write-Host "UnrealBuildTool not found. Skipping project file regeneration." -ForegroundColor Yellow
    Write-Host "Specify -EnginePath or -UEVersion to enable regeneration."
    exit 0
}

Write-Host "Regenerating Visual Studio project files..." -ForegroundColor Cyan
if ($DryRun) {
    Write-Host "  [DRY RUN] Would run: $EnginePath -projectfiles -project=`"$uprojectPath`" -game -rocket -progress" -ForegroundColor Yellow
} else {
    Start-Process -FilePath $EnginePath `
        -ArgumentList "-projectfiles", "-project=`"$uprojectPath`"", "-game", "-rocket", "-progress" `
        -Wait -NoNewWindow
    Write-Host "Done!" -ForegroundColor Green
}

