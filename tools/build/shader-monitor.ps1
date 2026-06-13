<#
    Monitor shader compilation status during a cook operation.
    Polls the editor or build logs and reports on stalled/failed shaders.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\build\shader-monitor.ps1 -LogFile C:\Logs\cook.log
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\build\shader-monitor.ps1 -LogFile C:\Logs\cook.log -PollInterval 5
#>
param(
    [string]$LogFile = '',
    [int]$PollInterval = 10,  # seconds
    [string]$OutputPath = ''
)

if (-not $LogFile) {
    Write-Host "Usage: -LogFile <path to cook log>"
    Write-Host "Will poll for shader compilation messages every $PollInterval seconds"
    exit 1
}

if (-not $OutputPath) {
    $OutputPath = [System.IO.Path]::ChangeExtension($LogFile, '.shaders.json')
}

$ErrorActionPreference = 'Continue'

$shaderStats = @{
    compiling = @()
    completed = 0
    failed = @()
    stalled = @()
}

Write-Host "Monitoring shader compilation in: $LogFile"
Write-Host "Polling every $PollInterval seconds. Press Ctrl+C to stop."
Write-Host ""

$lastSize = 0
while ($true) {
    if (-not (Test-Path -LiteralPath $LogFile)) {
        Start-Sleep -Seconds $PollInterval
        continue
    }

    $current = Get-Content -LiteralPath $LogFile -Raw -ErrorAction SilentlyContinue
    if ($current.Length -eq $lastSize) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] No new content (stalled?)" -ForegroundColor Yellow
    } else {
        $lastSize = $current.Length
    }

    # Extract shader compilation info
    $compiling = [regex]::Matches($current, 'Compiling shader.*?(?=\n)', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    $failed = [regex]::Matches($current, 'Shader .+? FAILED', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
    $completed = [regex]::Matches($current, 'Shader .+? compiled successfully', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

    if ($compiling.Count -gt 0 -or $failed.Count -gt 0) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Compiling: $($compiling.Count) | Failed: $($failed.Count) | Completed: $($completed.Count)"
    }

    if ($failed.Count -gt 0) {
        Write-Host "  ⚠ Failed shaders detected!" -ForegroundColor Red
        $failed | ForEach-Object { Write-Host "    - $($_.Value)" }
    }

    Start-Sleep -Seconds $PollInterval
}
