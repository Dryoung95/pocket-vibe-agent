from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


DEFAULT_HUB_URL = "http://127.0.0.1:8787"
DEFAULT_TOOL_TOKEN = "dev-tool-token"


def main() -> int:
    parser = argparse.ArgumentParser(description="Pocket Vibe Agent CLI")
    parser.add_argument("--hub", default=os.getenv("POCKET_VIBE_HUB_URL", DEFAULT_HUB_URL))
    parser.add_argument("--token", default=os.getenv("POCKET_VIBE_TOOL_TOKEN", DEFAULT_TOOL_TOKEN))
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    parser.add_argument("--request-timeout", type=float, default=30.0)

    sub = parser.add_subparsers(dest="resource", required=True)

    sub.add_parser("doctor", help="Diagnose Hub reachability, token, and online agents")

    agent = sub.add_parser("agent", help="Inspect online agents")
    agent_sub = agent.add_subparsers(dest="action", required=True)
    agent_sub.add_parser("list", help="List online agents")
    inspect_cmd = agent_sub.add_parser("inspect", help="Inspect one online agent by id")
    inspect_cmd.add_argument("agent_id")

    turn = sub.add_parser("turn", help="Create and inspect remote agent turns")
    turn_sub = turn.add_subparsers(dest="action", required=True)
    turn_send = turn_sub.add_parser("send", help="Send a prompt to a connected local agent")
    add_turn_send_args(turn_send)
    turn_get = turn_sub.add_parser("get", help="Get one turn by id")
    turn_get.add_argument("turn_id")

    task = sub.add_parser("task", help="Backward-compatible task commands")
    task_sub = task.add_subparsers(dest="action", required=True)
    task_send = task_sub.add_parser("send", help="Alias for turn send")
    add_turn_send_args(task_send)

    args = parser.parse_args()

    if args.resource == "doctor":
        return doctor(args)

    if args.resource == "agent" and args.action == "list":
        data = request(args, "GET", "/v1/agents")
        print_json(data) if args.json else print_agents(data)
        return 0

    if args.resource == "agent" and args.action == "inspect":
        data = request(args, "GET", f"/api/agents/{args.agent_id}")
        print_json(data) if args.json else print_agent(data["agent"])
        return 0

    if args.resource in {"turn", "task"} and args.action == "send":
        return send_turn(args)

    if args.resource == "turn" and args.action == "get":
        data = request(args, "GET", f"/v1/turns/{args.turn_id}")
        print_json(data) if args.json else print_turn(data["task"])
        return 0

    raise SystemExit("unknown command")


def add_turn_send_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent", default="", help="Target Agent ID. Omit for auto-route.")
    parser.add_argument("--provider", default="", choices=["", "auto", "codex", "claude", "local"], help="Agent provider preference")
    parser.add_argument("--level", default="auto", choices=["auto", "fast", "balanced", "deep", "ultra"], help="Hub routing complexity")
    parser.add_argument("--model", default="", help="Model passed through to Codex/Claude adapter")
    parser.add_argument("--effort", "--reasoning-effort", dest="effort", default="", help="Agent reasoning effort, e.g. low/medium/high/xhigh/max/ultra")
    parser.add_argument("--mode", default="", choices=["", "exec", "resume", "continue"], help="Provider session mode")
    parser.add_argument("--session-id", "--session", dest="session_id", default="", help="Codex/Claude native session id")
    parser.add_argument("--cwd", default="", help="Working directory passed to the local adapter")
    parser.add_argument("--wait", action="store_true", help="Poll until the turn finishes")
    parser.add_argument("--timeout", type=float, default=600.0, help="Seconds to wait with --wait")
    parser.add_argument("--poll", type=float, default=1.0, help="Polling interval for --wait")
    parser.add_argument("--prompt", "--objective", dest="prompt", default="", help="Prompt text. If omitted, remaining args are joined.")
    parser.add_argument("words", nargs="*", help="Prompt words")


def send_turn(args: argparse.Namespace) -> int:
    prompt = args.prompt or " ".join(args.words).strip()
    if not prompt:
        raise SystemExit("prompt is required")

    provider = "" if args.provider == "auto" else args.provider
    turn_options: dict[str, Any] = {}
    if args.mode:
        turn_options["mode"] = args.mode
    if args.session_id:
        turn_options["session_id"] = args.session_id
    if args.cwd:
        turn_options["cwd"] = args.cwd
    if args.model:
        turn_options["model"] = args.model
    if args.effort:
        turn_options["reasoning_effort"] = args.effort

    payload = {
        "prompt": prompt,
        "thinking_level": args.level,
        "target_agent_id": args.agent,
        "provider": provider,
        "session_id": args.session_id,
        "cwd": args.cwd,
        "turn_options": turn_options,
        "metadata": {"source": "pva-cli"},
    }
    data = request(args, "POST", "/v1/turns", payload)
    if args.wait:
        data = wait_for_turn(args, data["turn_id"], args.timeout, args.poll)

    if args.json:
        print_json(data)
    else:
        print_turn(data["task"])
    return 0


def wait_for_turn(args: argparse.Namespace, turn_id: str, timeout: float, poll: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        data = request(args, "GET", f"/v1/turns/{turn_id}")
        status = data.get("task", {}).get("status")
        if status in {"done", "failed", "error"}:
            return data
        if time.monotonic() >= deadline:
            print(f"Timed out waiting for turn {turn_id}; last status: {status}", file=sys.stderr)
            return data
        time.sleep(max(0.2, poll))


def request(args: argparse.Namespace, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    hub = args.hub.rstrip("/")
    body = None
    headers = {
        "Accept": "application/json",
        "X-Pocket-Token": args.token,
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{hub}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=args.request_timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code}: {message}", file=sys.stderr)
        raise SystemExit(1)
    except urllib.error.URLError as exc:
        print(f"Could not reach Pocket Hub at {hub}: {exc}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Checklist:", file=sys.stderr)
        print("  1) Start Hub: bash start-linux-control-app.sh", file=sys.stderr)
        print("  2) Open GUI:  http://127.0.0.1:8787/?v=7", file=sys.stderr)
        print("  3) If Hub uses another port, pass --hub http://127.0.0.1:<port>", file=sys.stderr)
        raise SystemExit(1)


def doctor(args: argparse.Namespace) -> int:
    hub = args.hub.rstrip("/")
    print(f"Pocket Hub: {hub}")
    try:
        health = public_get(hub, "/health")
    except urllib.error.URLError as exc:
        print(f"FAIL: Hub is not reachable: {exc}")
        print("Start it with:")
        print("  bash start-linux-control-app.sh")
        return 1
    except Exception as exc:
        print(f"FAIL: Health check failed: {exc}")
        return 1

    print(f"OK: Hub health endpoint is reachable ({health.get('qwen_mode', 'unknown')})")
    print(f"GUI: {hub}/?v=7")

    try:
        agents = request(args, "GET", "/v1/agents")
    except SystemExit:
        print("FAIL: Tool API token is invalid or missing.")
        print("The token is saved in runtime/rk3588_pairing.env as POCKET_VIBE_TOOL_TOKEN.")
        return 1

    count = agents.get("count", 0)
    print(f"OK: Tool token accepted. Online agents: {count}")
    if count == 0:
        print("No agents are online yet. On Windows, apply the pairing code and import/start a Codex or Claude bridge.")
    else:
        print_agents(agents)
    return 0


def public_get(hub: str, path: str) -> dict[str, Any]:
    req = urllib.request.Request(f"{hub}{path}", headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def print_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def print_agents(data: dict[str, Any]) -> None:
    agents = data.get("agents", [])
    if not agents:
        print("No online agents.")
        return
    for agent in agents:
        caps = ", ".join(agent.get("capabilities", []))
        print(f"{agent['agent_id']}\t{agent.get('display_name', '')}\t{agent.get('status', '')}\t{caps}")


def print_agent(agent: dict[str, Any]) -> None:
    print(f"Agent ID:     {agent.get('agent_id')}")
    print(f"Name:         {agent.get('display_name')}")
    print(f"Status:       {agent.get('status')}")
    print(f"Platform:     {agent.get('platform')}")
    print(f"Active task:  {agent.get('active_task_id') or '-'}")
    print(f"Capabilities: {', '.join(agent.get('capabilities', []))}")


def print_turn(task: dict[str, Any]) -> None:
    print(f"Turn ID:      {task.get('task_id')}")
    print(f"Status:       {task.get('status')}")
    print(f"Requested ID: {task.get('requested_agent_id') or '-'}")
    print(f"Target Agent: {task.get('target_agent') or '-'}")
    decision = task.get("decision", {})
    print(f"Decision:     {decision.get('thinking_level')} / {decision.get('target_capability')}")
    if task.get("turn_options"):
        print(f"Options:      {json.dumps(task.get('turn_options'), ensure_ascii=False)}")
    result = task.get("result")
    if result is not None:
        print("")
        print("Result:")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
