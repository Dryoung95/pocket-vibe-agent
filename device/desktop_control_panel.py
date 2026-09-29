from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from protocol import new_id, now_iso


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web_control_panel"
RUNTIME_DIR = ROOT / "runtime"
PANEL_CONFIG_DIR = RUNTIME_DIR / "control_panel_configs"
PANEL_LOG_DIR = RUNTIME_DIR / "control_panel_logs"
PANEL_STATE = RUNTIME_DIR / "control_panel_state.json"
PANEL_KEY = os.getenv("POCKET_VIBE_PANEL_KEY", "").strip()


TOKEN_RE = re.compile(r"(?i)(token|api[_-]?key|authorization|bearer)([=\s:]+)([^\s\"']+)")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


@dataclass
class ManagedBridge:
    bridge_id: str
    provider: str
    agent_id: str
    hub: str
    config_path: str
    log_path: str
    started_at: str
    process: subprocess.Popen[str]
    mode: str = "exec"
    session_id: str = ""
    dry_run: bool = False
    cwd: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "bridge_id": self.bridge_id,
            "provider": self.provider,
            "agent_id": self.agent_id,
            "hub": self.hub,
            "config_path": self.config_path,
            "log_path": self.log_path,
            "started_at": self.started_at,
            "pid": self.process.pid,
            "running": self.process.poll() is None,
            "exit_code": self.process.poll(),
            "mode": self.mode,
            "session_id": self.session_id,
            "dry_run": self.dry_run,
            "cwd": self.cwd,
        }


managed_bridges: dict[str, ManagedBridge] = {}

app = FastAPI(title="Pocket Vibe Desktop Control Panel", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(null|https?://(127\.0\.0\.1|localhost)(:\d+)?)$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="control-panel-static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/app.js")
async def app_js() -> FileResponse:
    return FileResponse(WEB_DIR / "app.js")


@app.get("/styles.css")
async def styles() -> FileResponse:
    return FileResponse(WEB_DIR / "styles.css")


@app.get("/site.webmanifest")
async def site_manifest() -> FileResponse:
    return FileResponse(WEB_DIR / "site.webmanifest")


@app.get("/service-worker.js")
async def service_worker() -> FileResponse:
    return FileResponse(WEB_DIR / "service-worker.js")


@app.get("/icon.svg")
async def icon_svg() -> FileResponse:
    return FileResponse(WEB_DIR / "icon.svg")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "pocket-vibe-control-site", "time": now_iso()}


@app.get("/api/site/info")
async def api_site_info(request: Request) -> dict[str, Any]:
    host = socket.gethostname()
    local_port = request.url.port or int(os.getenv("POCKET_VIBE_PANEL_PORT", "8790"))
    return {
        "ok": True,
        "time": now_iso(),
        "panel_key_required": bool(PANEL_KEY),
        "host": {
            "hostname": host,
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        },
        "site": {
            "origin": str(request.base_url).rstrip("/"),
            "lan_urls": local_site_urls(local_port),
        },
    }


@app.get("/api/scan")
async def api_scan(request: Request) -> dict[str, Any]:
    require_panel_key(request)
    return scan_local_agents()


@app.get("/api/bridges")
async def api_bridges(request: Request) -> dict[str, Any]:
    require_panel_key(request)
    cleanup_finished()
    return {"ok": True, "bridges": [bridge.snapshot() for bridge in managed_bridges.values()]}


@app.post("/api/hub/check")
async def api_hub_check(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    require_panel_key(request)
    hub = str(payload.get("hub", "")).strip()
    tool_token = str(payload.get("tool_token", "")).strip()
    if not hub:
        raise HTTPException(status_code=400, detail="hub is required")
    http_base = normalize_http_hub(hub)
    return check_hub(http_base, tool_token)


@app.post("/api/bridges/start")
async def api_start_bridge(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    require_panel_key(request)
    provider = str(payload.get("provider", "")).strip().lower()
    if provider not in {"codex", "claude"}:
        raise HTTPException(status_code=400, detail="provider must be codex or claude")

    hub = str(payload.get("hub", "")).strip()
    token = str(payload.get("desktop_token", "") or payload.get("token", "")).strip()
    if not hub:
        raise HTTPException(status_code=400, detail="hub is required")
    if not token:
        raise HTTPException(status_code=400, detail="desktop_token is required")
    if is_default_token(token) and not is_loopback_hub(hub):
        raise HTTPException(
            status_code=400,
            detail="Refusing to connect to a non-local Hub with the default dev token. Set a strong POCKET_VIBE_TOKEN first.",
        )

    mode = str(payload.get("mode", "exec")).strip().lower() or "exec"
    session_id = str(payload.get("session_id", "")).strip()
    cwd = str(payload.get("cwd", "")).strip()
    dry_run = bool(payload.get("dry_run", False))
    agent_id = str(payload.get("agent_id", "")).strip() or default_agent_id(provider, mode, session_id)
    hub_ws = normalize_ws_hub(hub)

    config_path = write_adapter_config(
        provider=provider,
        agent_id=agent_id,
        mode=mode,
        session_id=session_id,
        cwd=cwd,
        dry_run=dry_run,
        payload=payload,
    )
    bridge_id = new_id("bridge")
    log_path = PANEL_LOG_DIR / f"{bridge_id}.log"
    PANEL_LOG_DIR.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["POCKET_VIBE_TOKEN"] = token
    env["PYTHONIOENCODING"] = "utf-8"
    command = [
        sys.executable,
        str(ROOT / "device" / "desktop_agent.py"),
        "--hub",
        hub_ws,
        "--agent-id",
        agent_id,
        "--local-agent-config",
        str(config_path),
    ]
    log_file = log_path.open("a", encoding="utf-8")
    log_file.write(f"[{now_iso()}] starting {redact(' '.join(command))}\n")
    log_file.flush()

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creationflags,
    )
    bridge = ManagedBridge(
        bridge_id=bridge_id,
        provider=provider,
        agent_id=agent_id,
        hub=hub_ws,
        config_path=str(config_path),
        log_path=str(log_path),
        started_at=now_iso(),
        process=proc,
        mode=mode,
        session_id=session_id,
        dry_run=dry_run,
        cwd=cwd,
    )
    managed_bridges[bridge_id] = bridge
    save_panel_state()
    return {"ok": True, "bridge": bridge.snapshot()}


@app.post("/api/bridges/{bridge_id}/stop")
async def api_stop_bridge(bridge_id: str, request: Request) -> dict[str, Any]:
    require_panel_key(request)
    return stop_and_remove_bridge(bridge_id)


@app.delete("/api/bridges/{bridge_id}")
async def api_delete_bridge(bridge_id: str, request: Request) -> dict[str, Any]:
    require_panel_key(request)
    return stop_and_remove_bridge(bridge_id)


def stop_and_remove_bridge(bridge_id: str) -> dict[str, Any]:
    bridge = managed_bridges.get(bridge_id)
    if not bridge:
        raise HTTPException(status_code=404, detail=f"bridge is not managed by this panel: {bridge_id}")
    if bridge.process.poll() is None:
        terminate_process(bridge.process)
    snapshot = bridge.snapshot()
    managed_bridges.pop(bridge_id, None)
    save_panel_state()
    return {"ok": True, "bridge": snapshot}


@app.get("/api/bridges/{bridge_id}/log")
async def api_bridge_log(bridge_id: str, request: Request) -> dict[str, Any]:
    require_panel_key(request)
    bridge = managed_bridges.get(bridge_id)
    if not bridge:
        raise HTTPException(status_code=404, detail=f"bridge is not managed by this panel: {bridge_id}")
    path = Path(bridge.log_path)
    text = ""
    if path.exists():
        text = path.read_text(encoding="utf-8", errors="replace")[-12000:]
    return {"ok": True, "bridge_id": bridge_id, "log": redact(text)}


def scan_local_agents() -> dict[str, Any]:
    return {
        "ok": True,
        "time": now_iso(),
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
        },
        "tools": {
            "codex": inspect_cli("codex"),
            "claude": inspect_cli("claude"),
        },
        "processes": scan_processes(),
        "sessions": {
            "codex": discover_sessions("codex"),
            "claude": discover_sessions("claude"),
        },
        "managed_bridges": [bridge.snapshot() for bridge in managed_bridges.values()],
        "saved_pairings": load_saved_pairings(),
    }


def require_panel_key(request: Request) -> None:
    if not PANEL_KEY:
        return
    provided = (
        request.headers.get("x-panel-key")
        or bearer_token(request.headers.get("authorization", ""))
        or request.query_params.get("panel_key")
        or ""
    )
    if not secrets.compare_digest(str(provided), PANEL_KEY):
        raise HTTPException(status_code=401, detail="Panel key is required. Paste POCKET_VIBE_PANEL_KEY in the website header.")


def bearer_token(value: str) -> str:
    parts = value.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def local_site_urls(port: int) -> list[str]:
    hosts = ["127.0.0.1"]
    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM):
            ip = item[4][0]
            if ip and not ip.startswith("127.") and ip not in hosts:
                hosts.append(ip)
    except OSError:
        pass
    return [f"http://{host}:{port}" for host in hosts]


def inspect_cli(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    result = {"name": name, "available": bool(path), "path": path or "", "version": "", "help_ok": False}
    if not path:
        return result
    version = run_short([name, "--version"], timeout=8)
    if version["ok"]:
        result["version"] = first_line(version["stdout"] or version["stderr"])
    help_result = run_short([name, "--help"], timeout=8)
    result["help_ok"] = help_result["ok"]
    if not result["version"]:
        result["version"] = first_line(help_result["stdout"] or help_result["stderr"])
    return result


def run_short(command: list[str], timeout: float = 5) -> dict[str, Any]:
    try:
        if os.name == "nt":
            # npm-installed Codex / Claude shims are usually .cmd/.ps1 files.
            # Running through the Windows shell avoids WinError 5/2 from direct exec.
            proc = subprocess.run(
                subprocess.list2cmdline(command),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                shell=True,
            )
        else:
            proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": trim(proc.stdout, 4000),
            "stderr": trim(proc.stderr, 4000),
        }
    except Exception as exc:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": f"{exc.__class__.__name__}: {exc}"}


def scan_processes() -> list[dict[str, Any]]:
    if os.name == "nt":
        script = (
            "$items = Get-CimInstance Win32_Process | "
            "Where-Object { ($_.Name -match 'codex|claude|node|python') -or ($_.CommandLine -match 'codex|claude') } | "
            "Select-Object ProcessId,Name,CommandLine; "
            "$items | ConvertTo-Json -Depth 3"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return []
        rows = data if isinstance(data, list) else [data]
        return [process_row(str(row.get("ProcessId", "")), str(row.get("Name", "")), str(row.get("CommandLine", ""))) for row in rows]

    proc = subprocess.run(
        ["ps", "-eo", "pid=,comm=,args="],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    rows = []
    for line in proc.stdout.splitlines():
        if "codex" not in line.lower() and "claude" not in line.lower():
            continue
        parts = line.strip().split(None, 2)
        if len(parts) >= 2:
            rows.append(process_row(parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return rows


def process_row(pid: str, name: str, command_line: str) -> dict[str, Any]:
    lower = f"{name} {command_line}".lower()
    provider = "unknown"
    if "codex" in lower:
        provider = "codex"
    if "claude" in lower:
        provider = "claude"
    return {
        "pid": pid,
        "name": name,
        "provider": provider,
        "command_line": trim(redact(command_line), 500),
    }


def discover_sessions(provider: str, limit: int = 60) -> list[dict[str, Any]]:
    roots = session_roots(provider)
    thread_index = load_codex_thread_index() if provider == "codex" else {}
    sessions: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".jsonl", ".json"}:
                continue
            session_id = infer_session_id(path)
            if not session_id:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            summary = extract_session_summary(provider, path, session_id, thread_index)
            sessions.append({
                "provider": provider,
                "session_id": session_id,
                "path": str(path),
                "modified_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
                "size": stat.st_size,
                **summary,
            })
    sessions.sort(key=lambda item: item["modified_at"], reverse=True)
    return sessions[:limit]


def session_roots(provider: str) -> list[Path]:
    home = Path.home()
    roots: list[Path] = []
    if provider == "claude":
        roots.extend([home / ".claude" / "projects", ROOT.parent / ".claude"])
    elif provider == "codex":
        roots.extend([home / ".codex" / "sessions", home / ".codex" / "tasks", ROOT.parent / ".codex"])
    seen: set[str] = set()
    result: list[Path] = []
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key not in seen:
            seen.add(key)
            result.append(root)
    return result


def infer_session_id(path: Path) -> str:
    match = UUID_RE.search(path.stem)
    if match:
        return match.group(0)
    if UUID_RE.search(path.name):
        return UUID_RE.search(path.name).group(0)  # type: ignore[union-attr]
    if len(path.stem) >= 8:
        return path.stem
    return ""


def load_codex_thread_index() -> dict[str, dict[str, str]]:
    """Best-effort local Codex task labels from app state.

    The session jsonl files are the source of truth for resuming, but the
    desktop app stores friendlier generated descriptions and prompt history in
    .codex-global-state.json.  This index lets the control panel show readable
    labels instead of forcing users to distinguish UUIDs.
    """
    state_path = Path.home() / ".codex" / ".codex-global-state.json"
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    state = raw.get("electron-persisted-atom-state", {})
    if not isinstance(state, dict):
        return {}

    descriptions = state.get("thread-descriptions-v1", {})
    if not isinstance(descriptions, dict):
        descriptions = {}

    prompt_history = state.get("prompt-history", {})
    if not isinstance(prompt_history, dict):
        prompt_history = {}

    client_ids: dict[str, str] = {}
    prefix = "thread-client-id-v1:local%3A"
    for key, value in state.items():
        if isinstance(key, str) and key.startswith(prefix) and isinstance(value, str):
            client_ids[key[len(prefix):]] = value

    ids = set(descriptions.keys()) | set(prompt_history.keys()) | set(client_ids.keys())
    index: dict[str, dict[str, str]] = {}
    for session_id in ids:
        if not isinstance(session_id, str) or not UUID_RE.fullmatch(session_id):
            continue

        history = prompt_history.get(session_id)
        if not isinstance(history, list):
            history = prompt_history.get(client_ids.get(session_id, ""))
        if not isinstance(history, list):
            history = []

        prompts = [clean_session_text(item) for item in history if isinstance(item, str)]
        prompts = [item for item in prompts if item]
        description = clean_session_text(descriptions.get(session_id, ""))
        first_prompt = prompts[0] if prompts else ""
        last_prompt = prompts[-1] if prompts else ""
        title = description or first_prompt
        if not title and last_prompt:
            title = last_prompt

        index[session_id] = {
            "title": trim(title, 90),
            "first_prompt": trim(first_prompt, 220),
            "last_prompt": trim(last_prompt, 220),
        }
    return index


def extract_session_summary(
    provider: str,
    path: Path,
    session_id: str,
    thread_index: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    summary = {
        "title": "",
        "cwd": "",
        "source": "",
        "model": "",
        "preview": "",
        "first_user_message": "",
        "last_user_message": "",
    }

    if provider == "codex" and thread_index:
        indexed = thread_index.get(session_id, {})
        summary["title"] = indexed.get("title", "")
        summary["first_user_message"] = indexed.get("first_prompt", "")
        summary["last_user_message"] = indexed.get("last_prompt", "")

    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                if line_number > 240:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                payload = entry.get("payload", {})
                if not isinstance(payload, dict):
                    continue

                if entry.get("type") == "session_meta":
                    summary["cwd"] = summary["cwd"] or clean_session_text(payload.get("cwd", ""))
                    summary["source"] = summary["source"] or clean_session_text(payload.get("source", "") or payload.get("originator", ""))
                    summary["model"] = summary["model"] or clean_session_text(payload.get("model", "") or payload.get("model_provider", ""))

                text = extract_message_text(payload)
                if text:
                    if not summary["first_user_message"]:
                        summary["first_user_message"] = trim(text, 220)
                    summary["last_user_message"] = trim(text, 220)
    except OSError:
        pass

    if not summary["title"]:
        summary["title"] = summary["first_user_message"] or f"{provider.title()} {session_id[:8]}"
    summary["preview"] = summary["last_user_message"] or summary["first_user_message"]
    summary["display_name"] = trim(summary["title"], 90)
    return {key: value for key, value in summary.items() if value}


def extract_message_text(payload: dict[str, Any]) -> str:
    role = payload.get("role")
    item_type = payload.get("type")
    if role not in {"user", "human"} and item_type not in {"user_message", "human_message"}:
        # Codex stores user messages as response_item payloads with
        # role=user/type=message.  Do not accept every type=message payload:
        # developer/assistant messages use the same shape and would otherwise
        # overwrite the readable session preview.
        return ""

    parts: list[str] = []
    content = payload.get("content")
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text_value = item.get("text") or item.get("input_text") or item.get("content")
                if isinstance(text_value, str):
                    parts.append(text_value)

    message = payload.get("message")
    if isinstance(message, str):
        parts.append(message)
    if isinstance(message, dict):
        nested = extract_message_text(message)
        if nested:
            parts.append(nested)

    text = clean_session_text("\n".join(parts))
    if is_internal_session_text(text):
        return ""
    return text


def is_internal_session_text(text: str) -> bool:
    lower = text.strip().lower()
    return lower.startswith((
        "<environment_context>",
        "<permissions instructions>",
        "<app-context>",
        "<plugins_instructions>",
        "<skills_instructions>",
        "<multi_agent_mode>",
        "message type: new_task",
        "message type: message",
        "message type: final_answer",
    ))


def clean_session_text(value: Any) -> str:
    text_value = str(value or "")
    text_value = re.sub(r"\s+", " ", text_value).strip()
    return redact(text_value)


def trim(value: Any, limit: int) -> str:
    text_value = clean_session_text(value)
    if len(text_value) <= limit:
        return text_value
    return text_value[: max(0, limit - 1)].rstrip() + "…"


def write_adapter_config(
    *,
    provider: str,
    agent_id: str,
    mode: str,
    session_id: str,
    cwd: str,
    dry_run: bool,
    payload: dict[str, Any],
) -> Path:
    PANEL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    safe_agent = re.sub(r"[^A-Za-z0-9_.-]+", "-", agent_id).strip("-") or new_id("agent")
    path = PANEL_CONFIG_DIR / f"{safe_agent}.json"
    command = build_adapter_command(provider, mode, session_id, cwd, dry_run, payload)
    config = {
        "display_name": payload.get("display_name") or f"{provider.title()} Worker",
        "command": command,
        "working_dir": str(ROOT),
        "timeout_seconds": int(payload.get("timeout_seconds") or 600),
        "route_by_default": True,
        "capabilities": capabilities_for(provider, mode),
    }
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_adapter_command(provider: str, mode: str, session_id: str, cwd: str, dry_run: bool, payload: dict[str, Any]) -> list[str]:
    if provider == "codex":
        actual_mode = "resume" if session_id else "exec"
        command = [sys.executable, str(ROOT / "examples" / "codex_cli_adapter.py"), "--mode", actual_mode]
        if session_id:
            command.extend(["--session-id", session_id])
        if cwd:
            command.extend(["--cwd", cwd])
        command.extend(["--sandbox", str(payload.get("sandbox") or "read-only")])
        command.extend(["--approval", str(payload.get("approval") or "never")])
        if dry_run:
            command.append("--dry-run")
        return command

    actual_mode = mode if mode in {"exec", "continue", "resume"} else "exec"
    if session_id:
        actual_mode = "resume"
    command = [sys.executable, str(ROOT / "examples" / "claude_code_adapter.py"), "--mode", actual_mode]
    if session_id:
        command.extend(["--session-id", session_id])
    if cwd:
        command.extend(["--cwd", cwd])
    command.extend(["--output-format", str(payload.get("output_format") or "json")])
    command.extend(["--permission-mode", str(payload.get("permission_mode") or "default")])
    if dry_run:
        command.append("--dry-run")
    return command


def capabilities_for(provider: str, mode: str) -> list[str]:
    base = ["local.agent", "repo.read", "repo.write", "test.run", "git.status"]
    if provider == "codex":
        return base + ["codex.exec", "codex.resume" if mode == "resume" else "codex.new-session"]
    return base + ["claude.exec", "claude.resume" if mode == "resume" else "claude.new-session"]


def default_agent_id(provider: str, mode: str, session_id: str) -> str:
    if session_id:
        return f"{provider}-{session_id[:8]}"
    return f"{provider}-worker"


def normalize_ws_hub(hub: str) -> str:
    hub = hub.strip().rstrip("/")
    if hub.startswith("ws://") or hub.startswith("wss://"):
        return hub if hub.endswith("/ws/desktop") else f"{hub}/ws/desktop"
    if hub.startswith("https://"):
        return "wss://" + hub.removeprefix("https://").rstrip("/") + "/ws/desktop"
    if hub.startswith("http://"):
        return "ws://" + hub.removeprefix("http://").rstrip("/") + "/ws/desktop"
    return f"ws://{hub}/ws/desktop"


def normalize_http_hub(hub: str) -> str:
    hub = hub.strip().rstrip("/")
    if hub.startswith("ws://"):
        return "http://" + hub.removeprefix("ws://").removesuffix("/ws/desktop")
    if hub.startswith("wss://"):
        return "https://" + hub.removeprefix("wss://").removesuffix("/ws/desktop")
    if hub.startswith("http://") or hub.startswith("https://"):
        return hub
    return f"http://{hub}"


def is_default_token(token: str) -> bool:
    return token.strip() in {"dev-token", "dev-tool-token", "changeme", "password"}


def is_loopback_hub(hub: str) -> bool:
    http_base = normalize_http_hub(hub)
    parsed = urllib.parse.urlparse(http_base)
    hostname = (parsed.hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1"}


def check_hub(http_base: str, tool_token: str = "") -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    if tool_token:
        headers["Authorization"] = f"Bearer {tool_token}"
    result: dict[str, Any] = {"ok": False, "hub": http_base, "health": None, "agents": None}
    try:
        result["health"] = http_json(http_base + "/health", headers={})
        result["ok"] = True
    except Exception as exc:
        result["error"] = f"{exc.__class__.__name__}: {exc}"
        return result
    if tool_token:
        try:
            result["agents"] = http_json(http_base + "/v1/agents", headers=headers)
        except Exception as exc:
            result["agents_error"] = f"{exc.__class__.__name__}: {exc}"
    return result


def http_json(url: str, headers: dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def terminate_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[arg-type]
            time.sleep(0.8)
            if proc.poll() is None:
                proc.terminate()
        else:
            proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


def cleanup_finished() -> None:
    for bridge_id, bridge in list(managed_bridges.items()):
        if bridge.process.poll() is not None:
            # Keep finished bridges visible until the user refreshes once after completion.
            continue


def save_panel_state() -> None:
    RUNTIME_DIR.mkdir(exist_ok=True)
    state = {
        "saved_at": now_iso(),
        "managed_bridges": [bridge.snapshot() for bridge in managed_bridges.values()],
    }
    PANEL_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_saved_pairings() -> list[dict[str, Any]]:
    if not PANEL_STATE.exists():
        return []
    try:
        data = json.loads(PANEL_STATE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    pairings = []
    for bridge in data.get("managed_bridges", []):
        pairings.append({
            "provider": bridge.get("provider", ""),
            "agent_id": bridge.get("agent_id", ""),
            "hub": bridge.get("hub", ""),
            "last_started_at": bridge.get("started_at", ""),
        })
    return pairings


def redact(value: str) -> str:
    return TOKEN_RE.sub(r"\1\2<redacted>", value)


def trim(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n... trimmed {len(value) - limit} chars ..."


def first_line(value: str) -> str:
    for line in value.splitlines():
        if line.strip():
            return line.strip()
    return ""


def main() -> None:
    global PANEL_KEY
    host = os.getenv("POCKET_VIBE_PANEL_HOST", "127.0.0.1")
    port = int(os.getenv("POCKET_VIBE_PANEL_PORT", "8790"))
    if host not in {"127.0.0.1", "localhost", "::1"} and not PANEL_KEY:
        PANEL_KEY = secrets.token_urlsafe(24)
    RUNTIME_DIR.mkdir(exist_ok=True)
    print("Pocket Vibe Control Site")
    for url in local_site_urls(port):
        if host in {"127.0.0.1", "localhost", "::1"} and not url.startswith("http://127.0.0.1"):
            continue
        print(f"  {url}")
    if PANEL_KEY:
        print(f"Panel key: {PANEL_KEY}")
        print("Open the site and paste this key into the top-right Panel Key field.")
    else:
        print("Panel key: disabled for loopback-only development.")
    print("Set POCKET_VIBE_PANEL_HOST=0.0.0.0 to expose the website on your Wi-Fi/LAN.")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
