from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import socket
import sys
from pathlib import Path
from typing import Any

import websockets

from protocol import ack, envelope, now_iso


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "runtime"
OUTBOX = RUNTIME_DIR / "desktop_outbox.jsonl"


BASE_CAPABILITIES = ["system.info", "agent.echo", "browser.open"]


class LocalAgentRunner:
    """
    Safe adapter from the desktop bridge to a local agent process.

    The hub never sends shell commands. The local operator pre-configures one
    command locally; tasks are passed to that command as JSON over stdin.
    """

    def __init__(self, config_path: str = "", timeout_seconds: float = 120.0) -> None:
        self.config_path = Path(config_path).resolve() if config_path else None
        self.config: dict[str, Any] = {}
        if self.config_path:
            self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.timeout_seconds = float(self.config.get("timeout_seconds", timeout_seconds))
        self.command = self._load_command()
        self.working_dir = self._load_working_dir()
        self.display_name = str(self.config.get("display_name", "")).strip()
        self.route_by_default = bool(self.config.get("route_by_default", True))

    @property
    def enabled(self) -> bool:
        return bool(self.command)

    @property
    def capabilities(self) -> list[str]:
        configured = self.config.get("capabilities", [])
        caps = ["local.agent", "agent.execute"]
        if isinstance(configured, list):
            caps.extend(str(item) for item in configured)
        return unique(caps)

    async def run(self, msg: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {
                "ok": False,
                "capability": "local.agent",
                "error": "Local agent command is not configured.",
                "hint": "Start desktop_agent.py with --local-agent-config configs/local_agent.example.json",
            }

        payload = msg.get("payload", {})
        task_input = {
            "task_id": msg.get("task_id"),
            "msg_id": msg.get("msg_id"),
            "received_at": now_iso(),
            "objective": payload.get("objective", ""),
            "decision": payload.get("decision", {}),
            "safe_mode": payload.get("safe_mode", True),
            "provider": payload.get("provider", ""),
            "session_id": payload.get("session_id", ""),
            "cwd": payload.get("cwd", ""),
            "turn_options": payload.get("turn_options", {}),
            "metadata": payload.get("metadata", {}),
            "bridge": {
                "platform": platform.platform(),
                "hostname": socket.gethostname(),
                "working_dir": str(self.working_dir) if self.working_dir else None,
            },
        }
        stdin_data = json.dumps(task_input, ensure_ascii=False).encode("utf-8")

        try:
            proc = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=str(self.working_dir) if self.working_dir else None,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            return {
                "ok": False,
                "capability": "local.agent",
                "error": f"Configured local agent command was not found: {exc.filename}",
                "command": self.command,
            }

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(stdin_data), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "ok": False,
                "capability": "local.agent",
                "error": "Local agent timed out.",
                "timeout_seconds": self.timeout_seconds,
                "command": self.command,
            }

        stdout_text = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace")
        parsed_stdout: Any = None
        try:
            parsed_stdout = json.loads(stdout_text) if stdout_text.strip() else None
        except json.JSONDecodeError:
            parsed_stdout = None

        return {
            "ok": proc.returncode == 0,
            "capability": "local.agent",
            "exit_code": proc.returncode,
            "command": self.command,
            "working_dir": str(self.working_dir) if self.working_dir else None,
            "stdout": trim(stdout_text, 20000),
            "stderr": trim(stderr_text, 8000),
            "json": parsed_stdout,
        }

    def _load_command(self) -> list[str]:
        command = self.config.get("command", [])
        if isinstance(command, str):
            raise ValueError("local agent config field 'command' must be a list, not a string")
        if not isinstance(command, list):
            return []
        return [str(item) for item in command if str(item).strip()]

    def _load_working_dir(self) -> Path | None:
        raw = str(self.config.get("working_dir", "")).strip()
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute() and self.config_path:
            path = self.config_path.parent.parent / path
        return path.resolve()


class DesktopBridge:
    def __init__(
        self,
        hub: str,
        token: str,
        agent_id: str | None = None,
        display_name: str | None = None,
        local_agent_config: str = "",
        local_agent_timeout: float = 120.0,
    ) -> None:
        self.hub = hub
        self.token = token
        self.agent_id = agent_id or f"{platform.system().lower()}-{socket.gethostname()}"
        self.local_agent = LocalAgentRunner(local_agent_config, local_agent_timeout)
        self.display_name = (
            display_name
            or os.getenv("POCKET_VIBE_DISPLAY_NAME")
            or self.local_agent.display_name
            or ""
        )
        self.stop_event = asyncio.Event()
        self.task_lock = asyncio.Lock()
        self.pending_tasks: set[asyncio.Task[None]] = set()

    async def run_forever(self) -> None:
        delay = 1.0
        while not self.stop_event.is_set():
            try:
                await self._connect_once()
                delay = 1.0
            except Exception as exc:
                print(f"[{now_iso()}] disconnected: {exc.__class__.__name__}: {exc}")
            print(f"[{now_iso()}] reconnecting in {delay:.1f}s")
            await asyncio.sleep(delay)
            delay = min(delay * 1.8, 30.0)

    async def _connect_once(self) -> None:
        uri = f"{self.hub}?token={self.token}&agent_id={self.agent_id}"
        print(f"[{now_iso()}] connecting {self.hub}?token=<redacted>&agent_id={self.agent_id}")
        async with websockets.connect(uri, ping_interval=10, ping_timeout=10, close_timeout=3) as ws:
            await ws.send(json.dumps(envelope("hello", self._hello_payload()), ensure_ascii=False))
            await self._flush_outbox(ws)
            async for raw in ws:
                msg = json.loads(raw)
                await self._handle_message(ws, msg)

    async def _handle_message(self, ws: Any, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type")
        if msg_type == "heartbeat":
            await ws.send(json.dumps(envelope("pong", {"agent_time": now_iso()}, ack_of=msg.get("msg_id")), ensure_ascii=False))
            return
        if msg_type == "task":
            await ws.send(json.dumps(ack(msg, {"agent_id": self.agent_id}), ensure_ascii=False))
            task = asyncio.create_task(self._execute_and_report(ws, msg))
            self.pending_tasks.add(task)
            task.add_done_callback(self.pending_tasks.discard)
            return
        if msg_type == "ack":
            return
        print(f"[{now_iso()}] hub message: {msg_type} {msg.get('payload')}")

    async def _execute_and_report(self, ws: Any, msg: dict[str, Any]) -> None:
        async with self.task_lock:
            result = await self._execute_task(msg)
            result_msg = envelope("result", result, task_id=msg.get("task_id"))
            await self._send_or_spool(ws, result_msg)

    async def _execute_task(self, msg: dict[str, Any]) -> dict[str, Any]:
        payload = msg.get("payload", {})
        decision = payload.get("decision", {})
        capability = decision.get("target_capability", "agent.echo")
        objective = payload.get("objective", "")

        if capability == "system.info":
            return {
                "ok": True,
                "capability": capability,
                "hostname": socket.gethostname(),
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "local_agent_enabled": self.local_agent.enabled,
                "safe_mode": True,
            }

        if capability == "browser.open":
            return {
                "ok": True,
                "capability": capability,
                "note": "Demo safe-mode: browser launch is simulated. Wire this to a signed local action API later.",
                "objective": objective,
            }

        if self.local_agent.enabled and (
            capability in {"local.agent", "agent.execute"}
            or capability not in BASE_CAPABILITIES
            or self.local_agent.route_by_default
        ):
            return await self.local_agent.run(msg)

        await asyncio.sleep(0.35)
        return {
            "ok": True,
            "capability": "agent.echo",
            "note": "Demo safe-mode execution complete. Configure --local-agent-config to forward tasks to your real local agent.",
            "objective": objective,
            "decision": decision,
        }

    def _hello_payload(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "platform": platform.platform(),
            "hostname": socket.gethostname(),
            "capabilities": self._capabilities(),
            "safe_mode": True,
            "local_agent_enabled": self.local_agent.enabled,
            "started_at": now_iso(),
        }

    def _capabilities(self) -> list[str]:
        caps = list(BASE_CAPABILITIES)
        if self.local_agent.enabled:
            caps.extend(self.local_agent.capabilities)
        return unique(caps)

    async def _send_or_spool(self, ws: Any, msg: dict[str, Any]) -> None:
        try:
            await ws.send(json.dumps(msg, ensure_ascii=False))
        except Exception:
            self._spool(msg)
            raise

    async def _flush_outbox(self, ws: Any) -> None:
        if not OUTBOX.exists():
            return
        lines = OUTBOX.read_text(encoding="utf-8").splitlines()
        if not lines:
            return
        OUTBOX.unlink(missing_ok=True)
        for line in lines:
            try:
                await ws.send(line)
            except Exception:
                self._spool(json.loads(line))
                raise

    def _spool(self, msg: dict[str, Any]) -> None:
        RUNTIME_DIR.mkdir(exist_ok=True)
        with OUTBOX.open("a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")


def unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def trim(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n... trimmed {len(value) - limit} chars ..."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pocket Vibe Desktop Agent Bridge")
    parser.add_argument("--hub", default=os.getenv("POCKET_VIBE_HUB", "ws://127.0.0.1:8787/ws/desktop"))
    parser.add_argument("--token", default=os.getenv("POCKET_VIBE_TOKEN", "dev-token"))
    parser.add_argument("--agent-id", default=os.getenv("POCKET_VIBE_AGENT_ID", ""))
    parser.add_argument("--display-name", default=os.getenv("POCKET_VIBE_DISPLAY_NAME", ""))
    parser.add_argument("--local-agent-config", default=os.getenv("POCKET_VIBE_LOCAL_AGENT_CONFIG", ""))
    parser.add_argument("--local-agent-timeout", type=float, default=float(os.getenv("POCKET_VIBE_LOCAL_AGENT_TIMEOUT", "120")))
    return parser.parse_args()


async def amain() -> None:
    args = parse_args()
    bridge = DesktopBridge(
        args.hub,
        args.token,
        args.agent_id or None,
        args.display_name or None,
        args.local_agent_config,
        args.local_agent_timeout,
    )
    await bridge.run_forever()


if __name__ == "__main__":
    asyncio.run(amain())
