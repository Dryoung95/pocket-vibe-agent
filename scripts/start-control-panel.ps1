$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$port = if ($env:POCKET_VIBE_PANEL_PORT) { $env:POCKET_VIBE_PANEL_PORT } else { "8790" }
$url = "http://127.0.0.1:$port/#agents"
$infoUrl = "http://127.0.0.1:$port/api/site/info"
try {
    $response = Invoke-WebRequest -Uri $infoUrl -UseBasicParsing -TimeoutSec 2
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
        Write-Host "Pocket Vibe control panel backend is already running."
        Write-Host "Opening existing control panel:"
        Write-Host "  $url"
        Start-Process $url
        exit 0
    }
} catch {
    # Backend is not reachable; continue with normal startup.
}
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
Write-Host "Pocket Vibe control panel backend is starting..."
Write-Host "Open this URL in Chrome/Edge if it does not open automatically:"
Write-Host "  $url"
Start-Process $url
& ".venv\Scripts\python.exe" device\desktop_control_panel.py
