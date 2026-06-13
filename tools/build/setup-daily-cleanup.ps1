# Register a daily scheduled task to run clean-untracked.ps1
# Run this script as Administrator: powershell -NoProfile -ExecutionPolicy Bypass -File tools\setup-daily-cleanup.ps1

param(
    [string]$Time = "02:00",  # Run at 2 AM by default
    [string]$ScriptPath = (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'clean-untracked.ps1')
)

# Verify running as admin
$isAdmin = ([System.Security.Principal.WindowsIdentity]::GetCurrent().Groups -contains 'S-1-5-32-544')
if (-not $isAdmin) {
    Write-Error "This script must run as Administrator. Please run PowerShell as Admin and try again."
    exit 1
}

# Verify script exists
if (-not (Test-Path $ScriptPath)) {
    Write-Error "clean-untracked.ps1 not found at: $ScriptPath"
    exit 1
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$projectName = Split-Path -Leaf $repoRoot
$TaskName = "$projectName-DailyCleanup"
$TaskDescription = "Daily cleanup of untracked Binaries, Intermediate, and DerivedDataCache folders"

# Create action: run PowerShell with the script
$Action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

# Create trigger: daily at specified time
$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At $Time

# Create settings: run with high priority, allow on-demand runs
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunWithoutNetwork `
    -MultipleInstances IgnoreNew

# Register or update the task
try {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "Updating existing task: $TaskName"
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description $TaskDescription `
        -Action $Action `
        -Trigger $Trigger `
        -Settings $Settings `
        -RunLevel Highest | Out-Null

    Write-Host "✓ Task registered successfully!"
    Write-Host "  Name: $TaskName"
    Write-Host "  Runs daily at: $Time"
    Write-Host "  Script: $ScriptPath"
    Write-Host ""
    Write-Host "To view or modify: Open Task Scheduler and search for '$TaskName'"
    Write-Host "To run now: schtasks /run /tn $TaskName"
    Write-Host "To disable: Disable-ScheduledTask -TaskName '$TaskName'"

} catch {
    Write-Error "Failed to register task: $_"
    exit 1
}
