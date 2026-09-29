from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from protocol import envelope, new_id, now_iso
from qwen_router import QwenDecisionRouter


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
RUNTIME_DIR = ROOT / "runtime"
EVENT_LOG = RUNTIME_DIR / "events.jsonl"
DEV_TOKEN = os.getenv("POCKET_VIBE_TOKEN", "dev-token")
TOOL_TOKEN = os.getenv("POCKET_VIBE_TOOL_TOKEN", "dev-tool-token")


@asynccontextmanager
async def lifespan(_: FastAPI):
    RUNTIME_DIR.mkdir(exist_ok=True)
    yield


app = FastAPI(title="Pocket Vibe Device Hub", version="0.1", lifespan=lifespan)
router = QwenDecisionRouter()


@dataclass
class DesktopAgent:
    agent_id: str
    websocket: WebSocket
    display_name: str = ""
    platform: str = "unknown"
    capabilities: list[str] = field(default_factory=list)
    connected_at: str = field(default_factory=now_iso)
    last_seen: str = field(default_factory=now_iso)
    status: str = "idle"
    active_task_id: str | None = None
    seq: int = 0

    async def send(self, msg_type: str, payload: dict[str, Any], task_id: str | None = None) -> dict[str, Any]:
        self.seq += 1
        msg = envelope(msg_type, payload, task_id=task_id, seq=self.seq)
        await self.websocket.send_json(msg)
        await append_event("hub.send", {"agent_id": self.agent_id, "message": msg})
        return msg

    def snapshot(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "display_name": self.display_name or self.agent_id,
            "platform": self.platform,
            "capabilities": self.capabilities,
            "status": self.status,
            "active_task_id": self.active_task_id,
            "connected_at": self.connected_at,
            "last_seen": self.last_seen,
        }


agents: dict[str, DesktopAgent] = {}
gui_clients: set[WebSocket] = set()
recent_events: list[dict[str, Any]] = []
tasks: dict[str, dict[str, Any]] = {}


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/styles.css")
async def styles() -> FileResponse:
    return FileResponse(WEB_DIR / "styles.css")


@app.get("/app.js")
async def app_js() -> FileResponse:
    return FileResponse(WEB_DIR / "app.js")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "time": now_iso(),
        "agents": [agent.snapshot() for agent in agents.values()],
        "qwen_mode": "openai-compatible" if router.base_url else "heuristic-fallback",
    }


@app.get("/api/agents")
async def api_agents(request: Request) -> dict[str, Any]:
    require_tool_token(request)
    return {
        "ok": True,
        "time": now_iso(),
        "count": len(agents),
        "agents": [agent.snapshot() for agent in agents.values()],
    }


@app.get("/api/agents/{agent_id}")
async def api_agent(agent_id: str, request: Request) -> dict[str, Any]:
    require_tool_token(request)
    agent = agents.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent is not online: {agent_id}")
    return {"ok": True, "agent": agent.snapshot()}


@app.post("/api/tasks")
async def api_create_task(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    require_tool_token(request)
    objective = str(payload.get("objective", "")).strip()
    requested_level = str(payload.get("thinking_level", "auto")).strip() or "auto"
    requested_agent_id = str(payload.get("target_agent_id") or payload.get("agent_id") or "").strip()
    if not objective:
        raise HTTPException(status_code=400, detail="objective is required")
    task = await create_and_route_task(
        objective,
        requested_level,
        requested_agent_id,
        source="api",
    )
    return {"ok": True, "task": task}


@app.get("/v1/agents")
async def v1_agents(request: Request) -> dict[str, Any]:
    require_tool_token(request)
    return {
        "ok": True,
        "time": now_iso(),
        "count": len(agents),
        "agents": [agent.snapshot() for agent in agents.values()],
    }


@app.get("/v1/sessions")
async def v1_sessions(request: Request, provider: str = "") -> dict[str, Any]:
    require_tool_token(request)
    provider = provider.strip().lower()
    sessions = []
    for agent in agents.values():
        if provider and not agent_matches_provider(agent, provider):
            continue
        sessions.append({
            "session_id": agent.agent_id,
            "provider": detect_provider(agent),
            "display_name": agent.display_name or agent.agent_id,
            "status": agent.status,
            "capabilities": agent.capabilities,
            "agent": agent.snapshot(),
            "note": "For provider-native resume, start a bridge with a config that pins the Codex/Claude session id, or pass session_id to /v1/turns.",
        })
    return {"ok": True, "time": now_iso(), "count": len(sessions), "sessions": sessions}


@app.post("/v1/turns")
async def v1_create_turn(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    require_tool_token(request)
    objective = str(payload.get("prompt") or payload.get("objective") or "").strip()
    if not objective:
        raise HTTPException(status_code=400, detail="prompt or objective is required")

    provider = str(payload.get("provider", "")).strip().lower()
    session_id = str(payload.get("session_id", "")).strip()
    requested_agent_id = str(payload.get("target_agent_id") or payload.get("agent_id") or "").strip()
    if not requested_agent_id and session_id in agents:
        requested_agent_id = session_id
    if not requested_agent_id and provider:
        match = resolve_agent_by_provider(provider)
        if match:
            requested_agent_id = match.agent_id

    extra_payload = {
        "provider": provider,
        "session_id": session_id,
        "cwd": str(payload.get("cwd", "")).strip(),
        "turn_options": payload.get("turn_options", {}) if isinstance(payload.get("turn_options", {}), dict) else {},
        "metadata": payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {},
    }
    task = await create_and_route_task(
        objective,
        str(payload.get("thinking_level", "auto")).strip() or "auto",
        requested_agent_id,
        source="v1",
        extra_payload=extra_payload,
    )
    return {"ok": True, "turn_id": task["task_id"], "task": task}


@app.get("/v1/turns/{turn_id}")
async def v1_get_turn(turn_id: str, request: Request) -> dict[str, Any]:
    require_tool_token(request)
    task = tasks.get(turn_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Turn is not found: {turn_id}")
    return {"ok": True, "turn_id": turn_id, "task": task}


@app.websocket("/ws/gui")
async def ws_gui(websocket: WebSocket) -> None:
    await websocket.accept()
    gui_clients.add(websocket)
    await websocket.send_json(envelope("snapshot", await snapshot()))
    try:
        while True:
            msg = await websocket.receive_json()
            await handle_gui_message(websocket, msg)
    except WebSocketDisconnect:
        gui_clients.discard(websocket)


@app.websocket("/ws/desktop")
async def ws_desktop(websocket: WebSocket, token: str = "", agent_id: str = "") -> None:
    if token != DEV_TOKEN:
        await websocket.close(code=4401, reason="bad token")
        return
    await websocket.accept()
    assigned_id = agent_id or new_id("desktop")
    if assigned_id in agents:
        await append_event("agent.duplicate_rejected", {"agent_id": assigned_id})
        await websocket.close(code=4409, reason="agent id already connected")
        return
    desktop = DesktopAgent(agent_id=assigned_id, websocket=websocket, display_name=default_agent_name(assigned_id))
    agents[assigned_id] = desktop
    await append_event("agent.connected", {"agent_id": assigned_id})
    await broadcast("agent_connected", desktop.snapshot())

    heartbeat = asyncio.create_task(heartbeat_loop(desktop))
    try:
        while True:
            msg = await websocket.receive_json()
            desktop.last_seen = now_iso()
            await handle_desktop_message(desktop, msg)
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat.cancel()
        agents.pop(assigned_id, None)
        await append_event("agent.disconnected", {"agent_id": assigned_id})
        await broadcast("agent_disconnected", {"agent_id": assigned_id})


async def heartbeat_loop(agent: DesktopAgent) -> None:
    while True:
        await asyncio.sleep(8)
        try:
            await agent.send("heartbeat", {"server_time": now_iso()})
        except Exception:
            return


async def handle_gui_message(websocket: WebSocket, msg: dict[str, Any]) -> None:
    msg_type = msg.get("type")
    payload = msg.get("payload", {})
    if msg_type == "submit_task":
        objective = str(payload.get("objective", "")).strip()
        requested_level = str(payload.get("thinking_level", "auto"))
        requested_agent_id = str(payload.get("target_agent_id", "")).strip()
        if not objective:
            await websocket.send_json(envelope("error", {"message": "Objective is empty"}))
            return

        turn_options = payload.get("turn_options", {})
        if not isinstance(turn_options, dict):
            turn_options = {}
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        extra_payload = {
            "provider": str(payload.get("provider", "")).strip().lower(),
            "session_id": str(payload.get("session_id", "")).strip(),
            "cwd": str(payload.get("cwd", "")).strip(),
            "turn_options": turn_options,
            "metadata": metadata,
        }

        await create_and_route_task(
            objective,
            requested_level,
            requested_agent_id,
            source="gui",
            extra_payload=extra_payload,
        )

    elif msg_type == "refresh":
        await websocket.send_json(envelope("snapshot", await snapshot()))
    elif msg_type == "rename_agent":
        agent_id = str(payload.get("agent_id", "")).strip()
        display_name = str(payload.get("display_name", "")).strip()[:32]
        if agent_id in agents and display_name:
            agents[agent_id].display_name = display_name
            await append_event("agent.renamed", {"agent_id": agent_id, "display_name": display_name})
            await broadcast("agent_updated", agents[agent_id].snapshot())


async def handle_desktop_message(agent: DesktopAgent, msg: dict[str, Any]) -> None:
    msg_type = msg.get("type")
    payload = msg.get("payload", {})
    if msg_type == "hello":
        agent.platform = str(payload.get("platform", "unknown"))
        agent.display_name = str(payload.get("display_name") or agent.display_name or default_agent_name(agent.agent_id))
        agent.capabilities = [str(item) for item in payload.get("capabilities", [])]
        await append_event("agent.hello", {"agent_id": agent.agent_id, "payload": payload})
        await broadcast("agent_updated", agent.snapshot())
        await dispatch_waiting_tasks(agent)
    elif msg_type == "ack":
        task_id = msg.get("task_id")
        if task_id and task_id in tasks:
            tasks[task_id]["status"] = "acked"
            tasks[task_id]["ack_at"] = now_iso()
        await append_event("agent.ack", {"agent_id": agent.agent_id, "message": msg})
        await broadcast("task_acked", {"agent_id": agent.agent_id, "task_id": task_id, "ack_of": msg.get("ack_of")})
    elif msg_type == "result":
        task_id = msg.get("task_id")
        if task_id and task_id in tasks:
            succeeded = payload.get("ok") is not False
            tasks[task_id]["status"] = "done" if succeeded else "failed"
            tasks[task_id]["result"] = payload
            if not succeeded:
                tasks[task_id]["error"] = payload.get("error") or payload.get("stderr") or "Agent execution failed"
            tasks[task_id]["done_at"] = now_iso()
            target_agent_id = tasks[task_id].get("target_agent")
            if target_agent_id in agents:
                agents[target_agent_id].status = "idle"
                agents[target_agent_id].active_task_id = None
        await append_event("agent.result", {"agent_id": agent.agent_id, "message": msg})
        await broadcast("task_result", {"agent_id": agent.agent_id, "task_id": task_id, "result": payload})
    elif msg_type == "pong":
        await append_event("agent.pong", {"agent_id": agent.agent_id})
    else:
        await append_event("agent.message", {"agent_id": agent.agent_id, "message": msg})
        await broadcast("agent_message", {"agent_id": agent.agent_id, "message": msg})


def detect_provider(agent: DesktopAgent) -> str:
    caps = set(agent.capabilities)
    if any(cap.startswith("codex.") for cap in caps):
        return "codex"
    if any(cap.startswith("claude.") for cap in caps):
        return "claude"
    return "local"


def agent_matches_provider(agent: DesktopAgent, provider: str) -> bool:
    if not provider:
        return True
    return detect_provider(agent) == provider


def resolve_agent_by_provider(provider: str) -> DesktopAgent | None:
    provider = provider.strip().lower()
    for agent in agents.values():
        if agent_matches_provider(agent, provider):
            return agent
    return None


def resolve_agent(decision: dict[str, Any], requested_agent_id: str = "") -> DesktopAgent | None:
    if requested_agent_id:
        return agents.get(requested_agent_id)

    target_capability = decision.get("target_capability")
    for agent in agents.values():
        if target_capability in agent.capabilities:
            return agent
    return next(iter(agents.values()), None)


async def create_and_route_task(
    objective: str,
    requested_level: str = "auto",
    requested_agent_id: str = "",
    source: str = "unknown",
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision = await router.decide(objective, requested_level, [a.snapshot() for a in agents.values()])
    task_id = new_id("task")
    task: dict[str, Any] = {
        "task_id": task_id,
        "objective": objective,
        "decision": decision.as_dict(),
        "status": "queued",
        "source": source,
        "created_at": now_iso(),
    }
    if requested_agent_id:
        task["requested_agent_id"] = requested_agent_id
    if extra_payload:
        for key, value in extra_payload.items():
            if value not in (None, "", {}):
                task[key] = value
    tasks[task_id] = task
    await append_event("task.created", task)
    await broadcast("task_created", task)

    target = resolve_agent(decision.as_dict(), requested_agent_id) if agents else None
    if target is None:
        task["status"] = "waiting_for_agent"
        await broadcast("task_waiting", task)
        return task

    await send_task_to_agent(task, target)
    return task


async def send_task_to_agent(task: dict[str, Any], agent: DesktopAgent, resumed_from_waiting_queue: bool = False) -> None:
    task["status"] = "sent"
    task["target_agent"] = agent.agent_id
    agent.status = "working"
    agent.active_task_id = task["task_id"]
    payload = {
        "objective": task["objective"],
        "decision": task.get("decision", {}),
        "safe_mode": True,
    }
    for key in ("provider", "session_id", "cwd", "turn_options", "metadata"):
        if key in task:
            payload[key] = task[key]
    if resumed_from_waiting_queue:
        payload["resumed_from_waiting_queue"] = True
    sent = await agent.send("task", payload, task_id=task["task_id"])
    task["last_message_id"] = sent["msg_id"]
    await broadcast("task_sent", task)


async def dispatch_waiting_tasks(agent: DesktopAgent) -> None:
    for task in list(tasks.values()):
        if task.get("status") != "waiting_for_agent":
            continue
        decision = task.get("decision", {})
        requested_agent_id = str(task.get("requested_agent_id", "")).strip()
        if requested_agent_id and agent.agent_id != requested_agent_id:
            continue
        capability = decision.get("target_capability")
        if not requested_agent_id and capability and agent.capabilities and capability not in agent.capabilities:
            continue
        await send_task_to_agent(task, agent, resumed_from_waiting_queue=True)


def default_agent_name(agent_id: str) -> str:
    names = ["Patch Goblin", "Test Mage", "Repo Scout", "Browser Sprite", "Shell Knight", "Review Owl"]
    return names[sum(ord(ch) for ch in agent_id) % len(names)]


async def snapshot() -> dict[str, Any]:
    return {
        "time": now_iso(),
        "agents": [agent.snapshot() for agent in agents.values()],
        "tasks": list(tasks.values())[-20:],
        "events": recent_events[-40:],
        "qwen": {
            "model": router.model,
            "mode": "openai-compatible" if router.base_url else "heuristic-fallback",
            "base_url": router.base_url or None,
        },
    }


async def broadcast(event_type: str, payload: dict[str, Any]) -> None:
    msg = envelope(event_type, payload)
    stale: list[WebSocket] = []
    for client in list(gui_clients):
        try:
            await client.send_json(msg)
        except Exception:
            stale.append(client)
    for client in stale:
        gui_clients.discard(client)


async def append_event(event_type: str, payload: dict[str, Any]) -> None:
    event = {"time": now_iso(), "event": event_type, "payload": payload}
    recent_events.append(event)
    if len(recent_events) > 200:
        del recent_events[:100]
    RUNTIME_DIR.mkdir(exist_ok=True)
    with EVENT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def require_tool_token(request: Request) -> None:
    if not TOOL_TOKEN:
        return
    auth = request.headers.get("authorization", "")
    bearer = auth.removeprefix("Bearer ").strip() if auth.lower().startswith("bearer ") else ""
    token = request.headers.get("x-pocket-token", "") or bearer
    if token != TOOL_TOKEN:
        raise HTTPException(status_code=401, detail="missing or invalid pocket tool token")


def main() -> None:
    host = os.getenv("POCKET_VIBE_HOST", "0.0.0.0")
    port = int(os.getenv("POCKET_VIBE_PORT", "8787"))
    print(f"Pocket Vibe Device Hub running at http://127.0.0.1:{port}")
    print(f"Desktop agent token: {DEV_TOKEN}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
