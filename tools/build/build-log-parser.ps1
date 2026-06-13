<#
    Parse Unreal Engine build/cook logs and extract warnings/errors into a ranked JSON report.
    Quickly identify the real issues without wading through thousands of lines.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\build\build-log-parser.ps1 -LogFile C:\Logs\build.log
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\build\build-log-parser.ps1 -LogFile C:\Logs\cook.log -OutputPath report.json
#>
param(
    [string]$LogFile = '',
    [string]$OutputPath = '',
    [int]$TopIssues = 50
)

if (-not $LogFile -or -not (Test-Path -LiteralPath $LogFile)) {
    Write-Host "Usage: -LogFile <path to build or cook log>"
    exit 1
}

if (-not $OutputPath) {
    $OutputPath = [System.IO.Path]::ChangeExtension($LogFile, '.issues.json')
}

$ErrorActionPreference = 'Stop'
$content = Get-Content -LiteralPath $LogFile -Raw

# Extract warnings and errors with line context
$patterns = @(
    @{ name = 'Error'; pattern = '^\s*(error|ERROR)[:\s](.+?)$'; severity = 3 }
    @{ name = 'Warning'; pattern = '^\s*(warning|WARNING)[:\s](.+?)$'; severity = 2 }
    @{ name = 'Fatal'; pattern = '^\s*(fatal|FATAL)[:\s](.+?)$'; severity = 4 }
    @{ name = 'Assertion'; pattern = '^\s*Assertion failed[:\s](.+?)$'; severity = 3 }
)

$issues = @()
$lines = $content -split "`n"

for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]

    foreach ($p in $patterns) {
        if ($line -match $p.pattern) {
            $msg = if ($matches.Count -gt 2) { $matches[2] } else { $matches[1] }

            $issues += [ordered]@{
                severity = $p.name
                severity_rank = $p.severity
                message = $msg.Trim()
                line_number = $i + 1
                context = $line.Trim()
            }
            break
        }
    }
}

# Deduplicate by message and rank by frequency
$grouped = $issues | Group-Object -Property message |
    ForEach-Object {
        [ordered]@{
            message = $_.Name
            count = $_.Count
            severity = $_.Group[0].severity
            severity_rank = $_.Group[0].severity_rank
            line_numbers = @($_.Group | ForEach-Object { $_.line_number }) | Select-Object -First 5
        }
    } |
    Sort-Object -Property @{Expression = "severity_rank"; Descending = $true}, @{Expression = "count"; Descending = $true} |
    Select-Object -First $TopIssues

$result = [ordered]@{
    generated = (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK')
    log_file = (Resolve-Path -LiteralPath $LogFile).Path
    total_issues_found = $issues.Count
    unique_issues = @($grouped).Count
    top_issues = @($grouped)
}

$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
Write-Host "Parsed $($issues.Count) issues ($(@($grouped).Count) unique) from log. Wrote: $OutputPath"
