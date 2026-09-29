from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pocket Vibe adapter for Claude Code CLI")
    parser.add_argument("--mode", choices=["exec", "continue", "resume"], default=os.getenv("POCKET_VIBE_CLAUDE_MODE", "exec"))
    parser.add_argument("--session-id", default=os.getenv("POCKET_VIBE_CLAUDE_SESSION_ID", ""))
    parser.add_argument("--cwd", default=os.getenv("POCKET_VIBE_CLAUDE_CWD", ""))
    parser.add_argument("--model", default=os.getenv("POCKET_VIBE_CLAUDE_MODEL", ""))
    parser.add_argument("--effort", default=os.getenv("POCKET_VIBE_CLAUDE_EFFORT", ""))
    parser.add_argument("--agent", default=os.getenv("POCKET_VIBE_CLAUDE_AGENT", ""))
    parser.add_argument("--output-format", choices=["text", "json", "stream-json"], default=os.getenv("POCKET_VIBE_CLAUDE_OUTPUT_FORMAT", "json"))
    parser.add_argument("--permission-mode", default=os.getenv("POCKET_VIBE_CLAUDE_PERMISSION_MODE", "default"))
    parser.add_argument("--allowed-tool", action="append", default=[])
    parser.add_argument("--disallowed-tool", action="append", default=[])
    parser.add_argument("--max-budget-usd", default=os.getenv("POCKET_VIBE_CLAUDE_MAX_BUDGET_USD", ""))
    parser.add_argument("--system-prompt-file", default=os.getenv("POCKET_VIBE_CLAUDE_SYSTEM_PROMPT_FILE", ""))
    parser.add_argument("--bare", action="store_true", default=os.getenv("POCKET_VIBE_CLAUDE_BARE", "").lower() == "true")
    parser.add_argument("--dry-run", action="store_true", default=os.getenv("POCKET_VIBE_CLAUDE_DRY_RUN", "false").lower() == "true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_stdin = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    task = json.loads(raw_stdin or "{}")
    prompt = build_prompt(task)
    command, effective_cwd = build_claude_command(args, task)

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "adapter": "examples/claude_code_adapter.py",
            "dry_run": True,
            "message": "Claude Code adapter is wired, but dry-run is enabled. Remove --dry-run in config to execute.",
            "would_run": command,
            "prompt_preview": prompt[:1200],
        }, ensure_ascii=False, indent=2))
        return

    launch_command = platform_command(command)
    proc = subprocess.run(
        launch_command,
        input=prompt,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=effective_cwd or None,
        timeout=None,
    )
    parsed_stdout = parse_stdout(proc.stdout, args.output_format)

    print(json.dumps({
        "ok": proc.returncode == 0,
        "adapter": "examples/claude_code_adapter.py",
        "dry_run": False,
        "mode": args.mode,
        "exit_code": proc.returncode,
        "command": command,
        "session_id": extract_session_id(parsed_stdout),
        "stdout": trim(proc.stdout, 24000),
        "stderr": trim(proc.stderr, 10000),
        "json": parsed_stdout,
    }, ensure_ascii=False, indent=2))
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def platform_command(command: list[str]) -> list[str]:
    """Resolve npm command shims without enabling a general-purpose shell."""
    if os.name != "nt" or not command:
        return command
    executable = shutil.which(command[0]) or command[0]
    if Path(executable).suffix.lower() in {".cmd", ".bat"}:
        command_line = subprocess.list2cmdline([executable, *command[1:]])
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command_line]
    return [executable, *command[1:]]


def build_claude_command(args: argparse.Namespace, task: dict[str, Any]) -> tuple[list[str], str]:
    options = task.get("turn_options", {}) if isinstance(task.get("turn_options", {}), dict) else {}
    mode = str(options.get("mode") or task.get("mode") or args.mode)
    session_id = str(options.get("session_id") or task.get("session_id") or args.session_id).strip()
    cwd = str(options.get("cwd") or task.get("cwd") or args.cwd).strip()
    output_format = str(options.get("output_format") or args.output_format)
    model = str(options.get("model") or task.get("model") or args.model).strip()
    effort = normalize_effort(str(options.get("reasoning_effort") or options.get("effort") or task.get("reasoning_effort") or args.effort))
    if session_id and mode == "exec":
        mode = "resume"

    command = ["claude", "--print", "--output-format", output_format]

    if mode == "continue":
        command.append("--continue")
    elif mode == "resume":
        if not session_id:
            raise SystemExit("resume mode requires --session-id or task.session_id")
        command.extend(["--resume", session_id])

    if model:
        command.extend(["--model", model])
    if effort:
        command.extend(["--effort", effort])
    if args.agent:
        command.extend(["--agent", args.agent])
    if args.permission_mode:
        command.extend(["--permission-mode", args.permission_mode])
    if args.max_budget_usd:
        command.extend(["--max-budget-usd", args.max_budget_usd])
    if args.system_prompt_file:
        command.extend(["--system-prompt-file", args.system_prompt_file])
    if args.bare:
        command.append("--bare")

    for tool in args.allowed_tool:
        command.extend(["--allowedTools", tool])
    for tool in args.disallowed_tool:
        command.extend(["--disallowedTools", tool])

    return command, cwd


def normalize_effort(value: str) -> str:
    value = (value or "").strip().lower()
    if value in {"auto", "default", "none"}:
        return ""
    if value == "ultra":
        return "max"
    allowed = {"low", "medium", "high", "xhigh", "max"}
    return value if value in allowed else ""


def build_prompt(task: dict[str, Any]) -> str:
    objective = task.get("objective", "")
    decision = task.get("decision", {})
    bridge = task.get("bridge", {})
    return f"""You are being invoked by Pocket Vibe Agent Bridge.

User objective:
{objective}

Routing decision:
{json.dumps(decision, ensure_ascii=False, indent=2)}

Bridge context:
{json.dumps(bridge, ensure_ascii=False, indent=2)}

Constraints:
- Be concise in your final response.
- If you need permissions, credentials, or an interactive approval, stop and say exactly what is needed.
- Do not assume this invocation is the same as an active GUI chat unless --continue or --resume was explicitly configured.
- Return the most useful result for a remote Linux controller user.
"""


def parse_stdout(stdout: str, output_format: str) -> Any:
    text = stdout.strip()
    if not text:
        return None
    if output_format == "json":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    if output_format == "stream-json":
        events: list[Any] = []
        for line in text.splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"type": "raw", "text": line})
        return {"events": events}
    return None


def extract_session_id(parsed_stdout: Any) -> str:
    if isinstance(parsed_stdout, dict):
        if isinstance(parsed_stdout.get("session_id"), str):
            return parsed_stdout["session_id"]
        events = parsed_stdout.get("events")
        if isinstance(events, list):
            for event in reversed(events):
                if isinstance(event, dict) and isinstance(event.get("session_id"), str):
                    return event["session_id"]
    return ""


def trim(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n... trimmed {len(value) - limit} chars ..."


if __name__ == "__main__":
    main()



