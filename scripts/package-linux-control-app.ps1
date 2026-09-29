param(
  [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
  [string]$OutDir = ''
)

$ErrorActionPreference = 'Stop'

if (-not $OutDir) {
  $OutDir = Join-Path $Root 'runtime\packages'
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$zip = Join-Path $OutDir "pocket-vibe-linux-handoff-$timestamp.zip"
$items = @(
  'device',
  'web',
  'web_control_panel',
  'tools',
  'scripts',
  'configs',
  'examples',
  'docs',
  'requirements.txt',
  'README.md',
  'README_FOR_TEAMMATE.md',
  'LINUX_CODEX_PROMPT.md',
  'start-linux-control-app.sh',
  'send-prompt.sh'
)
$tarArgs = @(
  '-a',
  '-c',
  '-f',
  $zip,
  "--exclude=*/__pycache__",
  "--exclude=*/__pycache__/*",
  "--exclude=*.pyc",
  "--exclude=*.pyo"
) + $items

Push-Location $Root
try {
  & tar.exe @tarArgs
  if ($LASTEXITCODE -ne 0) {
    throw "tar.exe failed with exit code $LASTEXITCODE"
  }
}
finally {
  Pop-Location
}

$entries = @(& tar.exe -tf $zip)
$critical = @(
  'device/device_hub.py',
  'device/desktop_control_panel.py',
  'web_control_panel/index.html',
  'web/index.html',
  'tools/pva.py',
  'README_FOR_TEAMMATE.md',
  'LINUX_CODEX_PROMPT.md',
  'start-linux-control-app.sh',
  'send-prompt.sh'
)
$missing = @($critical | Where-Object { $_ -notin $entries })
if ($missing.Count -gt 0) {
  throw "Package is missing required entries: $($missing -join ', ')"
}

$forbidden = @(
  $entries | Where-Object {
    $_ -match '(^|/)(\.venv|runtime)(/|$)' -or
    $_ -match 'rk3588_pairing\.env|control_panel_state\.json|__pycache__|\.py[co]$'
  }
)
if ($forbidden.Count -gt 0) {
  throw "Package contains forbidden entries: $($forbidden -join ', ')"
}

$file = Get-Item -LiteralPath $zip
$hash = Get-FileHash -LiteralPath $zip -Algorithm SHA256

[pscustomobject]@{
  zip = $zip
  size_bytes = $file.Length
  entry_count = $entries.Count
  sha256 = $hash.Hash
}
