$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
$port = if ($env:POCKET_VIBE_LOCAL_PANEL_PORT) { $env:POCKET_VIBE_LOCAL_PANEL_PORT } else { "8790" }
Start-Process "http://127.0.0.1:$port"
& ".venv\Scripts\python.exe" device\local_control_panel.py
