<#
    Launch the Weekend Warrior Dev Tools UI: starts the local server (server.py) and opens it
    in your default browser. Stop it with Ctrl+C in this window.

    Usage:
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\ui\Launch-DevToolsUI.ps1
      powershell -NoProfile -ExecutionPolicy Bypass -File tools\ui\Launch-DevToolsUI.ps1 -Port 9000
#>
param(
    [int]$Port = 8756,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$ScriptDir = $PSScriptRoot

$python = Get-Command py -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $python) {
    Write-Error "No Python interpreter found on PATH (tried 'py' and 'python'). Install Python 3.9+ to run the Dev Tools UI server."
    exit 1
}

$serverArgs = @((Join-Path $ScriptDir 'server.py'), '--port', $Port)
if ($NoBrowser) { $serverArgs += '--no-browser' }

& $python.Source @serverArgs
