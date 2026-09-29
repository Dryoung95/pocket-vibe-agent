@echo off
setlocal
set "ROOT=%~dp0.."
cd /d "%ROOT%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-control-panel.ps1"
endlocal
