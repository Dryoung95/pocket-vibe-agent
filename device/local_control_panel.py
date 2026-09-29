from __future__ import annotations

import json
import os
import platform
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
CONFIG_DIR = ROOT / "configs"
RUNTIME_DIR = ROOT / "runtime"
PAIRING_FILE = RUNTIME_DIR / "local_pairing.json"
IMPORT_DIR = RUNTIME_DIR / "imported_agents"
BUNDLE_FILE = RUNTIME_DIR / "linux_import_bundle.json"
START_SCRIPT = RUNTIME_DIR / "start-imported-bridges.ps1"


app = FastAPI(title="Pocket Vibe Local Control Panel", version="0.1")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "local-panel.html")


@app.get("/local-panel.js")
async def local_panel_js() -> FileResponse:
    return FileResponse(WEB_DIR / "local-panel.js")


@app.get("/styles.css")
async def styles() -> FileResponse:
    return FileResponse(WEB_DIR / "styles.css")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "role": "local-control-panel",
        "time": now_iso(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
    }


@app.get("/api/local/scan")
async def api_local_scan() -> dict[str, Any]:
    pairing = load_pairing(redact=True)
    return {
        "ok": True,
        "time": now_iso(),
        "local": local_identity(),
        "pairing": pairing,
        "detected_processes": scan_agent_processes(),
        "bridge_templates": list_bridge_templates(),
        "last_bundle": load_last_bundle_summary(),
    }


@app.post("/api/pair")
async def api_pair(payload: dict[str, Any]) -> dict[str, Any]:
    linux_hub_url = str(payload.get("linux_hub_url", "")).strip()
    desktop_token = str(payload.get("desktop_token", "")).strip()
    tool_token = str(payload.get("tool_token", "")).strip()
    label = str(payload.get("label", "")).strip() or "Linux Hub"

    if not linux_hub_url:
        raise HTTPException(status_code=400, detail="linux_hub_url is required")
    if not desktop_token:
        raise HTTPException(status_code=400, detail="desktop_token is required")

    profile = {
        "label": label,
        "linux_hub_url": normalize_http_url(linux_hub_url),
        "desktop_ws_url": normalize_desktop_ws_url(linux_hub_url),
        "desktop_token": desktop_token,
        "tool_token": tool_token,
        "created_at": now_iso(),
        "hostname": socket.gethostname(),
    }
    RUNTIME_DIR.mkdir(exist_ok=True)
    PAIRING_FILE.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "pairing": redact_pairing(profile), "status": test_pairing(profile)}


@app.get("/api/pair/status")
async def api_pair_status() -> dict[str, Any]:
    profile = load_pairing(redact=False)
    if not profile:
        return {"ok": False, "paired": False, "message": "No pairing profile saved yet."}
    return {"ok": True, "paired": True, "pairing": redact_pairing(profile), "status": test_pairing(profile)}


@app.post("/api/import")
async def api_import(payload: dict[str, Any]) -> dict[str, Any]:
    profile = load_pairing(redact=False)
    if not profile:
        raise HTTPException(status_code=400, detail="Pair with a Linux Hub before importing agents.")

    selected = payload.get("selected", [])
    if not isinstance(selected, list) or not selected:
        raise HTTPException(status_code=400, detail="selected must contain at least one process or template")

    launch = bool(payload.get("launch", False))
    agents = build_import_agents(selected)
    if not agents:
        raise HTTPException(status_code=400, detail="No importable Codex or Claude agents were selected.")

    bundle = write_import_bundle(profile, agents)
    launched = launch_imported_agents(profile, agents) if launch else []
    return {
        "ok": True,
        "bundle": bundle,
        "launched": launched,
        "pairing": redact_pairing(profile),
    }


def local_identity() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "root": str(ROOT),
    }


def scan_agent_processes() -> list[dict[str, Any]]:
    if platform.system().lower().startswith("win"):
        return scan_windows_processes()
    return scan_posix_processes()


def scan_windows_processes() -> list[dict[str, Any]]:
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process |
  Where-Object {
    ($_.Name -match 'codex|claude|node|python|pwsh|powershell|cmd') -and
    ($_.CommandLine -match 'codex|claude')
  } |
  Select-Object ProcessId,Name,ExecutablePath,CommandLine |
  ConvertTo-Json -Depth 3
"""
    powershell = "powershell.exe"
    try:
        proc = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
    except Exception as exc:
        return [{
            "provider": "unknown",
            "pid": "",
            "name": "process scan failed",
            "command_line": str(exc),
            "importable": False,
        }]
    if proc.returncode != 0:
        return [{
            "provider": "unknown",
            "pid": "",
            "name": "process scan failed",
            "command_line": proc.stderr.strip(),
            "importable": False,
        }]
    raw = proc.stdout.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    rows = data if isinstance(data, list) else [data]
    return normalize_process_rows(rows)


def scan_posix_processes() -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid=,comm=,args="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=6,
        )
    except Exception as exc:
        return [{
            "provider": "unknown",
            "pid": "",
            "name": "process scan failed",
            "command_line": str(exc),
            "importable": False,
        }]
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        if not re.search(r"\b(codex|claude)\b", line, re.IGNORECASE):
            continue
        parts = line.strip().split(maxsplit=2)
        if len(parts) < 3:
            continue
        rows.append({"ProcessId": parts[0], "Name": parts[1], "CommandLine": parts[2]})
    return normalize_process_rows(rows)


def normalize_process_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        cmd = str(row.get("CommandLine") or "")
        name = str(row.get("Name") or row.get("ExecutablePath") or "process")
        if is_scanner_noise(name, cmd) or not is_agent_command_candidate(name, cmd):
            continue
        provider = detect_provider(name, cmd)
        if provider not in {"codex", "claude"}:
            continue
        pid = str(row.get("ProcessId") or row.get("pid") or "")
        key = f"{provider}:{pid}:{cmd[:80]}"
        if key in seen:
            continue
        seen.add(key)
        session_id = extract_session_id(provider, cmd)
        cwd = extract_cwd(cmd)
        normalized.append({
            "id": f"process:{provider}:{pid or len(normalized)}",
            "kind": "process",
            "provider": provider,
            "pid": pid,
            "name": name,
            "display_name": f"{provider.title()} process {pid}".strip(),
            "command_line": trim(cmd, 900),
            "session_id": session_id,
            "cwd": cwd,
            "importable": True,
            "note": "session id detected; bridge will resume this session" if session_id else "no session id detected; bridge will create a new headless turn",
        })
    normalized.sort(key=lambda item: (item["provider"], item["pid"]))
    return normalized


def is_scanner_noise(name: str, command_line: str) -> bool:
    text = f"{name} {command_line}".lower()
    noise_markers = [
        "get-ciminstance win32_process",
        "convertto-json",
        "local_control_panel.py",
        "desktop_control_panel.py",
        "api/local/scan",
    ]
    return any(marker in text for marker in noise_markers)


def is_agent_command_candidate(name: str, command_line: str) -> bool:
    text = f"{name} {command_line}".lower()
    base_name = Path(name).name.lower()
    if base_name.startswith(("codex", "claude")):
        return True
    patterns = [
        r"(^|[\\/\s\"'])(codex|claude)(\.cmd|\.exe)?($|[\\/\s\"'])",
        r"@anthropic-ai[\\/]claude-code",
        r"claude-code",
        r"@openai[\\/]codex",
        r"codex-cli",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def list_bridge_templates() -> list[dict[str, Any]]:
    templates: list[dict[str, Any]] = []
    for filename in [
        "codex_cli.example.json",
        "codex_current_thread.example.json",
        "claude_code.example.json",
        "claude_current_session.example.json",
    ]:
        path = CONFIG_DIR / filename
        if not path.exists():
            continue
        try:
            config = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            templates.append({
                "id": f"template:{filename}",
                "kind": "template",
                "provider": "unknown",
                "display_name": filename,
                "config_path": str(path),
                "importable": False,
                "error": str(exc),
            })
            continue
        command = [str(part) for part in config.get("command", [])] if isinstance(config.get("command", []), list) else []
        provider = detect_provider(filename, " ".join(command))
        templates.append({
            "id": f"template:{filename}",
            "kind": "template",
            "provider": provider,
            "display_name": str(config.get("display_name") or filename),
            "config_path": rel(path),
            "capabilities": config.get("capabilities", []),
            "dry_run": "--dry-run" in command,
            "session_template": "current" in filename,
            "suggested_agent_id": suggested_agent_id(provider, filename),
            "importable": provider in {"codex", "claude"},
            "note": "template uses dry-run until you remove --dry-run" if "--dry-run" in command else "template can execute real agent commands",
        })
    return templates


def build_import_agents(selected: list[Any]) -> list[dict[str, Any]]:
    available: dict[str, dict[str, Any]] = {}
    for item in scan_agent_processes():
        available[item["id"]] = item
    for item in list_bridge_templates():
        available[item["id"]] = item

    agents: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for raw in selected:
        selection = raw if isinstance(raw, dict) else {"id": str(raw)}
        item_id = str(selection.get("id", "")).strip()
        item = available.get(item_id)
        if not item or not item.get("importable"):
            continue

        provider = str(selection.get("provider") or item.get("provider") or "").lower()
        session_id = str(selection.get("session_id") or item.get("session_id") or "").strip()
        cwd = str(selection.get("cwd") or item.get("cwd") or "").strip()
        agent_id = str(selection.get("agent_id") or "").strip()
        if not agent_id:
            agent_id = make_agent_id(provider, session_id, item)
        agent_id = unique_agent_id(agent_id, used_ids)

        config_path = str(item.get("config_path") or "")
        generated = False
        if item.get("kind") == "process" or session_id or cwd:
            config_path = str(write_generated_config(provider, agent_id, session_id=session_id, cwd=cwd))
            generated = True
        elif config_path:
            config_path = str((ROOT / config_path).resolve()) if not Path(config_path).is_absolute() else config_path

        agents.append({
            "agent_id": agent_id,
            "provider": provider,
            "source": item,
            "local_agent_config": config_path,
            "generated_config": generated,
            "session_id": session_id,
            "cwd": cwd,
            "command": bridge_command(agent_id, config_path, "<PAIRING_DESKTOP_WS_URL>", "<PAIRING_DESKTOP_TOKEN>"),
        })
    return agents


def write_generated_config(provider: str, agent_id: str, session_id: str = "", cwd: str = "") -> Path:
    template_name = "codex_cli.example.json" if provider == "codex" else "claude_code.example.json"
    template_path = CONFIG_DIR / template_name
    config = json.loads(template_path.read_text(encoding="utf-8-sig"))
    command = [str(part) for part in config.get("command", [])]

    if provider == "codex":
        command = remove_option(command, "--mode", takes_value=True)
        command = remove_option(command, "--session-id", takes_value=True)
        if session_id:
            command.extend(["--mode", "resume", "--session-id", session_id])
        if cwd:
            command = remove_option(command, "--cwd", takes_value=True)
            command.extend(["--cwd", cwd])
        config["display_name"] = f"Codex Imported {agent_id}"
        config["capabilities"] = unique(["local.agent", "codex.exec", "repo.read", "repo.write", "test.run", "git.status"])
    else:
        command = remove_option(command, "--mode", takes_value=True)
        command = remove_option(command, "--session-id", takes_value=True)
        if session_id:
            command.extend(["--mode", "resume", "--session-id", session_id])
        if cwd:
            command = remove_option(command, "--cwd", takes_value=True)
            command.extend(["--cwd", cwd])
        config["display_name"] = f"Claude Imported {agent_id}"
        config["capabilities"] = unique(["local.agent", "claude.exec", "repo.read", "repo.write", "test.run", "git.status"])

    config["command"] = command
    config["working_dir"] = "."
    config["generated_by"] = "device/local_control_panel.py"
    config["generated_at"] = now_iso()
    IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = IMPORT_DIR / f"{safe_filename(agent_id)}.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_import_bundle(profile: dict[str, Any], agents: list[dict[str, Any]]) -> dict[str, Any]:
    RUNTIME_DIR.mkdir(exist_ok=True)
    bundle = {
        "created_at": now_iso(),
        "local": local_identity(),
        "pairing": redact_pairing(profile),
        "agents": agents,
        "start_script": str(START_SCRIPT),
        "note": "Run the generated PowerShell script on this computer after the Linux Hub is online and paired.",
    }
    BUNDLE_FILE.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    START_SCRIPT.write_text(make_start_script(profile, agents), encoding="utf-8")
    return {
        "path": str(BUNDLE_FILE),
        "start_script": str(START_SCRIPT),
        "agents": [{k: v for k, v in agent.items() if k != "source"} for agent in agents],
    }


def make_start_script(profile: dict[str, Any], agents: list[dict[str, Any]]) -> str:
    lines = [
        '$ErrorActionPreference = "Stop"',
        f'$root = "{str(ROOT).replace(chr(92), chr(92) + chr(92))}"',
        'Set-Location $root',
        'if (-not (Test-Path ".venv")) { python -m venv .venv }',
        '& ".venv\\Scripts\\python.exe" -m pip install -r requirements.txt',
    ]
    for agent in agents:
        command = bridge_command(agent["agent_id"], agent["local_agent_config"], profile["desktop_ws_url"], profile["desktop_token"])
        quoted = " ".join(ps_quote(part) for part in command)
        lines.append(f"Start-Process -FilePath {ps_quote(command[0])} -ArgumentList @({', '.join(ps_quote(p) for p in command[1:])}) -WorkingDirectory $root")
        lines.append(f"# {quoted}")
    lines.append("")
    return "\n".join(lines)


def launch_imported_agents(profile: dict[str, Any], agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    launched: list[dict[str, Any]] = []
    log_dir = IMPORT_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    for agent in agents:
        command = bridge_command(agent["agent_id"], agent["local_agent_config"], profile["desktop_ws_url"], profile["desktop_token"])
        stdout_path = log_dir / f"{safe_filename(agent['agent_id'])}.out.log"
        stderr_path = log_dir / f"{safe_filename(agent['agent_id'])}.err.log"
        stdout = stdout_path.open("ab")
        stderr = stderr_path.open("ab")
        try:
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            proc = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            launched.append({
                "agent_id": agent["agent_id"],
                "pid": proc.pid,
                "stdout": str(stdout_path),
                "stderr": str(stderr_path),
            })
        except Exception as exc:
            launched.append({"agent_id": agent["agent_id"], "error": str(exc)})
    return launched


def bridge_command(agent_id: str, config_path: str, desktop_ws_url: str, desktop_token: str) -> list[str]:
    python_exe = str(ROOT / ".venv" / "Scripts" / "python.exe")
    if not Path(python_exe).exists():
        python_exe = sys.executable or "python"
    return [
        python_exe,
        str(ROOT / "device" / "desktop_agent.py"),
        "--hub",
        desktop_ws_url,
        "--token",
        desktop_token,
        "--agent-id",
        agent_id,
        "--local-agent-config",
        config_path,
    ]


def test_pairing(profile: dict[str, Any]) -> dict[str, Any]:
    http_url = str(profile.get("linux_hub_url", "")).rstrip("/")
    if not http_url:
        return {"reachable": False, "message": "No Linux Hub URL configured."}
    result: dict[str, Any] = {"reachable": False, "hub": http_url}
    try:
        health = http_get_json(f"{http_url}/health", token="")
        result.update({"reachable": True, "health": health})
    except Exception as exc:
        result["health_error"] = str(exc)
    tool_token = str(profile.get("tool_token", "")).strip()
    if tool_token:
        try:
            agents = http_get_json(f"{http_url}/v1/agents", token=tool_token)
            result["tool_token_ok"] = True
            result["remote_agents"] = agents.get("agents", [])
        except Exception as exc:
            result["tool_token_ok"] = False
            result["tool_error"] = str(exc)
    else:
        result["tool_token_ok"] = None
    return result


def http_get_json(url: str, token: str = "") -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=6) as response:
        return json.loads(response.read().decode("utf-8"))


def load_pairing(redact: bool) -> dict[str, Any]:
    if not PAIRING_FILE.exists():
        return {}
    try:
        data = json.loads(PAIRING_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return redact_pairing(data) if redact else data


def redact_pairing(profile: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(profile)
    for key in ["desktop_token", "tool_token"]:
        if key in redacted:
            redacted[key] = redact_secret(str(redacted.get(key) or ""))
    return redacted


def load_last_bundle_summary() -> dict[str, Any]:
    if not BUNDLE_FILE.exists():
        return {}
    try:
        bundle = json.loads(BUNDLE_FILE.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return {
        "path": str(BUNDLE_FILE),
        "start_script": str(START_SCRIPT) if START_SCRIPT.exists() else "",
        "created_at": bundle.get("created_at", ""),
        "agent_count": len(bundle.get("agents", [])) if isinstance(bundle.get("agents"), list) else 0,
    }


def normalize_http_url(value: str) -> str:
    value = value.strip()
    if value.startswith("ws://"):
        value = "http://" + value.removeprefix("ws://")
    elif value.startswith("wss://"):
        value = "https://" + value.removeprefix("wss://")
    elif not re.match(r"^[a-z]+://", value, re.IGNORECASE):
        value = f"http://{value}"
    parsed = urlparse(value)
    host = parsed.netloc or parsed.path
    scheme = parsed.scheme or "http"
    if host.endswith("/ws/desktop"):
        host = host[: -len("/ws/desktop")]
    return f"{scheme}://{host}".rstrip("/")


def normalize_desktop_ws_url(value: str) -> str:
    http_url = normalize_http_url(value)
    if http_url.startswith("https://"):
        base = "wss://" + http_url.removeprefix("https://")
    else:
        base = "ws://" + http_url.removeprefix("http://")
    return base.rstrip("/") + "/ws/desktop"


def detect_provider(name: str, command_line: str) -> str:
    text = f"{name} {command_line}".lower()
    if "claude" in text:
        return "claude"
    if "codex" in text:
        return "codex"
    return "unknown"


def extract_session_id(provider: str, command_line: str) -> str:
    if provider == "claude":
        match = re.search(r"--resume(?:=|\s+)([^\s\"']+)", command_line)
        if match:
            return match.group(1)
    if provider == "codex":
        match = re.search(r"\bresume\b(?:\s+--json)?(?:\s+--last)?\s+([A-Za-z0-9_.:-]{6,})", command_line)
        if match and not match.group(1).startswith("-"):
            return match.group(1)
    return ""


def extract_cwd(command_line: str) -> str:
    for flag in ["--cwd", "--cd"]:
        match = re.search(rf"{re.escape(flag)}(?:=|\s+)(\"[^\"]+\"|'[^']+'|[^\s]+)", command_line)
        if match:
            return match.group(1).strip("\"'")
    return ""


def suggested_agent_id(provider: str, filename: str) -> str:
    if provider == "codex":
        return "codex-current" if "current" in filename else "codex-worker"
    if provider == "claude":
        return "claude-current" if "current" in filename else "claude-worker"
    return "agent-worker"


def make_agent_id(provider: str, session_id: str, item: dict[str, Any]) -> str:
    if item.get("kind") == "template":
        return str(item.get("suggested_agent_id") or suggested_agent_id(provider, ""))
    suffix = session_id[-6:] if session_id else str(item.get("pid") or "worker")
    return safe_agent_id(f"{provider}-{suffix}")


def unique_agent_id(agent_id: str, used_ids: set[str]) -> str:
    base = safe_agent_id(agent_id)
    candidate = base
    index = 2
    while candidate in used_ids:
        candidate = f"{base}-{index}"
        index += 1
    used_ids.add(candidate)
    return candidate


def safe_agent_id(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip().lower()).strip("-")
    return value or "agent-worker"


def safe_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value.strip()) or "agent"


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())


def remove_option(command: list[str], option: str, takes_value: bool = False) -> list[str]:
    result: list[str] = []
    skip_next = False
    for index, part in enumerate(command):
        if skip_next:
            skip_next = False
            continue
        if part == option:
            if takes_value and index + 1 < len(command):
                skip_next = True
            continue
        if takes_value and part.startswith(option + "="):
            continue
        result.append(part)
    return result


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def redact_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:3] + "…" + value[-3:]


def trim(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"... trimmed {len(value) - limit} chars"


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def main() -> None:
    host = os.getenv("POCKET_VIBE_LOCAL_PANEL_HOST", "127.0.0.1")
    port = int(os.getenv("POCKET_VIBE_LOCAL_PANEL_PORT", "8790"))
    print(f"Pocket Vibe Local Control Panel running at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
