# Clean untracked build and cache folders in the project and plugins
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean-untracked.ps1 -DryRun
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\clean-untracked.ps1

[CmdletBinding()]
param(
    [string]$Root = '',
    [switch]$IncludePlugins = $true,
    [switch]$IncludeEngine = $false,
    [switch]$ForceTracked = $false,
    [switch]$DryRun = $false,
    [switch]$IgnoreLastRun = $false
)

function Write-Log {
    param([string]$Message)
    if (-not $script:logMessages) { $script:logMessages = [System.Collections.Generic.List[string]]::new() }
    $time = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$time] $Message"
    $script:logMessages.Add($line)
    Write-Verbose $line
}

try {
    if ([string]::IsNullOrWhiteSpace($Root)) {
        $ScriptPath = $MyInvocation.MyCommand.Path
        $ScriptDir = Split-Path -Parent $ScriptPath
        $RepoRoot = Resolve-Path -Path (Join-Path $ScriptDir '..\..') -ErrorAction Stop
        $RepoRoot = $RepoRoot.Path
    } else {
        $RepoRoot = Resolve-Path -Path $Root -ErrorAction Stop
        $RepoRoot = $RepoRoot.Path
    }
} catch {
    Write-Error "Failed to resolve repository root: $_"
    exit 2
}


# Use a single JSON summary file in tools/outputs instead of a separate CleanupLogs folder
$outputsDir = Join-Path $RepoRoot 'tools\outputs'
if (-not (Test-Path -LiteralPath $outputsDir)) { New-Item -ItemType Directory -Path $outputsDir -Force | Out-Null }

# If an old CleanupLogs folder exists, try to merge its summary then remove the folder
$oldLogDir = Join-Path $RepoRoot 'tools\CleanupLogs'
if (Test-Path -LiteralPath $oldLogDir) {
    $oldSummary = Join-Path $oldLogDir 'cleanup-summary.json'
    if (Test-Path -LiteralPath $oldSummary) {
        try {
            $existingOutputsSummary = Join-Path $outputsDir 'cleanup-summary.json'
            $oldText = Get-Content -LiteralPath $oldSummary -Raw -ErrorAction SilentlyContinue
            $old = @()
            if ($oldText -and $oldText.Trim()) {
                try { $old = $oldText | ConvertFrom-Json -ErrorAction Stop } catch { $old = @() }
            }
            $outList = @()
            if (Test-Path -LiteralPath $existingOutputsSummary) {
                $existingText = Get-Content -LiteralPath $existingOutputsSummary -Raw -ErrorAction SilentlyContinue
                try { $outList = $existingText | ConvertFrom-Json -ErrorAction Stop } catch { $outList = @() }
            }
            if ($old -isnot [System.Array]) { $old = @($old) }
            if ($outList -isnot [System.Array]) { $outList = @($outList) }
            $combined = $outList + $old
            $combined | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $existingOutputsSummary -Encoding UTF8
        } catch {}
    }
    try { Remove-Item -LiteralPath $oldLogDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
}

$LastRunFile = Join-Path $outputsDir '.last_cleanup'
$Today = (Get-Date).ToString('yyyy-MM-dd')

if (-not $DryRun -and -not $IgnoreLastRun) {
    if (Test-Path -LiteralPath $LastRunFile) {
        $LastRun = Get-Content -LiteralPath $LastRunFile -ErrorAction SilentlyContinue
        if ($LastRun -and $LastRun[0] -eq $Today) {
            Write-Host "Cleanup already ran today ($Today). Skipping."
            exit 0
        }
    }
    Set-Content -LiteralPath $LastRunFile -Value $Today
}

# initialize in-memory messages list
$script:logMessages = [System.Collections.Generic.List[string]]::new()

Write-Log "Cleanup started"
Write-Log "Repository root: $RepoRoot"
Write-Log "Options: IncludePlugins=$IncludePlugins IncludeEngine=$IncludeEngine ForceTracked=$ForceTracked DryRun=$DryRun"

$targets = @('Binaries','Intermediate','DerivedDataCache')

$script:removed = @()
$script:skipped = @()
$script:errors = @()
$script:PluginInstalledCache = @{}

function Is-InstalledPluginDir {
    param([string]$PluginDir)

    if ($script:PluginInstalledCache.ContainsKey($PluginDir)) {
        return $script:PluginInstalledCache[$PluginDir]
    }

    $isInstalled = $false

    try {
        $descriptor = Get-ChildItem -Path $PluginDir -Filter '*.uplugin' -File -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($descriptor) {
            $pluginJson = Get-Content -LiteralPath $descriptor.FullName -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
            $isInstalled = $pluginJson.Installed -eq $true
        }
    } catch {
        $isInstalled = $false
    }

    $script:PluginInstalledCache[$PluginDir] = $isInstalled
    return $isInstalled
}

function Has-TrackedFiles {
    param([string]$RepoRoot, [string]$AbsolutePath)
    try {
        $git = Get-Command git -ErrorAction SilentlyContinue
        if (-not $git) { return $null }
        $repo = (Resolve-Path $RepoRoot -ErrorAction Stop).Path
        $abs = (Resolve-Path $AbsolutePath -ErrorAction Stop).Path
        if (-not $abs.StartsWith($repo, [System.StringComparison]::OrdinalIgnoreCase)) { return $null }
        $rel = $abs.Substring($repo.Length).TrimStart('\','/') -replace '\\','/'
        $out = & git -C $repo ls-files -- "$rel" 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return -not [string]::IsNullOrWhiteSpace($out)
    } catch {
        return $null
    }
}

function Remove-PathSafely {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return }

    $tracked = Has-TrackedFiles -RepoRoot $RepoRoot -AbsolutePath $Path
    if ($tracked -eq $true -and -not $ForceTracked) {
        Write-Log "SKIP tracked files present: $Path"
        $script:skipped += $Path
        return
    }

    if ($DryRun) {
        Write-Log "DRYRUN would remove: $Path"
        $script:skipped += $Path
        return
    }

    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        Write-Log "REMOVED: $Path"
        $script:removed += $Path
    } catch {
        Write-Log "ERROR removing $Path : $_"
        $script:errors += @{ Path = $Path; Error = $_ }
    }
}

# remove at repo root
foreach ($t in $targets) {
    $p = Join-Path $RepoRoot $t
    if (Test-Path $p) { Remove-PathSafely -Path $p }
}

if ($IncludePlugins) {
    $pluginsRoot = Join-Path $RepoRoot 'Plugins'
    if (Test-Path $pluginsRoot) {
        $pluginFolders = Get-ChildItem -Path $pluginsRoot -Directory -ErrorAction SilentlyContinue
        foreach ($pf in $pluginFolders) {
            $pluginInstalled = Is-InstalledPluginDir -PluginDir $pf.FullName
            foreach ($t in $targets) {
                $p = Join-Path $pf.FullName $t
                if (-not (Test-Path $p)) { continue }
                if ($t -eq 'Binaries' -and $pluginInstalled) {
                    Write-Log "SKIP installed plugin binaries: $p"
                    $script:skipped += $p
                    continue
                }
                Remove-PathSafely -Path $p
            }
            # one level deeper
            $sub = Get-ChildItem -Path $pf.FullName -Directory -ErrorAction SilentlyContinue
            foreach ($s in $sub) {
                $subPluginInstalled = Is-InstalledPluginDir -PluginDir $s.FullName
                foreach ($t in $targets) {
                    $p2 = Join-Path $s.FullName $t
                    if (-not (Test-Path $p2)) { continue }
                    if ($t -eq 'Binaries' -and $subPluginInstalled) {
                        Write-Log "SKIP installed plugin binaries: $p2"
                        $script:skipped += $p2
                        continue
                    }
                    Remove-PathSafely -Path $p2
                }
            }
        }
    } else {
        Write-Log "No Plugins folder found at $pluginsRoot"
    }
}

if ($IncludeEngine) {
    Write-Log "IncludeEngine specified - checking engine paths"
    $possibleEngines = @(
        'C:\Program Files\Epic Games\UE_5.7',
        'C:\Program Files (x86)\Epic Games\UE_5.7',
        'D:\Epic Games\UE_5.7',
        'E:\Epic Games\UE_5.7'
    )

    $engineFound = $false
    foreach ($possibleEngine in $possibleEngines) {
        if (Test-Path $possibleEngine) {
            Write-Log "Found engine at: $possibleEngine"
            foreach ($t in $targets) {
                $p = Join-Path $possibleEngine $t
                if (Test-Path $p) { Remove-PathSafely -Path $p }
            }
            $engineFound = $true
            break
        }
    }

    if (-not $engineFound) {
        Write-Log "Engine root not found at any of: $($possibleEngines -join ', ')"
    }
}

Write-Log "Summary: Removed=$($script:removed.Count) Skipped=$($script:skipped.Count) Errors=$($script:errors.Count)"
if ($script:errors.Count -gt 0) {
    Write-Log "Errors detail:"
    foreach ($e in $script:errors) { Write-Log ("{0} : {1}" -f $e.Path, $e.Error) }
}

Write-Log "Cleanup finished"

$summaryEntry = [ordered]@{
    runAt = (Get-Date).ToString('o')
    repository = $RepoRoot
    options = [ordered]@{
        IncludePlugins = [bool]$IncludePlugins
        IncludeEngine  = [bool]$IncludeEngine
        ForceTracked   = [bool]$ForceTracked
        DryRun         = [bool]$DryRun
        IgnoreLastRun  = [bool]$IgnoreLastRun
    }
    targets = $targets
    removed = $script:removed
    removedCount = $script:removed.Count
    skipped = $script:skipped
    skippedCount = $script:skipped.Count
    errors = @()
    errorsCount = 0
    messages = @()
    messagesCount = 0
    lastRunFile = $LastRunFile
}

# Normalize errors into JSON-friendly objects (strings)
$errList = @()
foreach ($e in $script:errors) {
    if ($e -is [System.Management.Automation.PSCustomObject] -or $e -is [hashtable]) {
        $path = if ($e.Path) { $e.Path } else { $null }
        $errText = if ($e.Error) { ($e.Error | Out-String).Trim() } else { ($e | Out-String).Trim() }
        $errList += [ordered]@{ Path = $path; Error = $errText }
    } else {
        $errList += [ordered]@{ Error = ($e | Out-String).Trim() }
    }
}
$summaryEntry.errors = $errList
$summaryEntry.errorsCount = $errList.Count

# Attach collected messages
$msgs = @()
if ($script:logMessages) { $msgs = $script:logMessages }
$summaryEntry.messages = $msgs
$summaryEntry.messagesCount = $msgs.Count

# Write the single canonical summary into tools/outputs/cleanup-summary.json
try {
    $outputsSummary = Join-Path $outputsDir 'cleanup-summary.json'
    $outList = @()
    if (Test-Path -LiteralPath $outputsSummary) {
        $existingText = Get-Content -LiteralPath $outputsSummary -Raw -ErrorAction SilentlyContinue
        if ($existingText -and $existingText.Trim()) {
            try {
                $existing = $existingText | ConvertFrom-Json -ErrorAction Stop
                if ($existing -is [System.Array]) { $outList = $existing } else { $outList = @($existing) }
            } catch {
                $outList = @()
            }
        }
    }

    $outList += $summaryEntry
    $outList | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $outputsSummary -Encoding UTF8
    Write-Log "Appended run summary to $outputsSummary"
} catch {
    Write-Log "Failed to append run summary to outputs: $_"
}

if ($script:errors.Count -gt 0) { exit 3 } else { exit 0 }
