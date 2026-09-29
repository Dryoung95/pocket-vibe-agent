from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pocket Vibe adapter for Codex CLI")
    parser.add_argument("--mode", choices=["exec", "resume"], default=os.getenv("POCKET_VIBE_CODEX_MODE", "exec"))
    parser.add_argument("--session-id", default=os.getenv("POCKET_VIBE_CODEX_SESSION_ID", ""))
    parser.add_argument("--last", action="store_true", default=os.getenv("POCKET_VIBE_CODEX_LAST", "").lower() == "true")
    parser.add_argument("--cwd", default=os.getenv("POCKET_VIBE_CODEX_CWD", ""))
    parser.add_argument("--model", default=os.getenv("POCKET_VIBE_CODEX_MODEL", ""))
    parser.add_argument("--reasoning-effort", default=os.getenv("POCKET_VIBE_CODEX_REASONING_EFFORT", ""))
    parser.add_argument("--sandbox", default=os.getenv("POCKET_VIBE_CODEX_SANDBOX", "read-only"))
    parser.add_argument("--approval", default=os.getenv("POCKET_VIBE_CODEX_APPROVAL", "never"))
    parser.add_argument("--json-events", action="store_true", default=os.getenv("POCKET_VIBE_CODEX_JSON_EVENTS", "true").lower() != "false")
    parser.add_argument("--skip-git-repo-check", action="store_true", default=os.getenv("POCKET_VIBE_CODEX_SKIP_GIT_REPO_CHECK", "true").lower() != "false")
    parser.add_argument("--dry-run", action="store_true", default=os.getenv("POCKET_VIBE_CODEX_DRY_RUN", "false").lower() == "true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raw_stdin = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    task = json.loads(raw_stdin or "{}")
    prompt = build_prompt(task)
    command, output_file, effective_cwd = build_codex_command(args, task)

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "adapter": "examples/codex_cli_adapter.py",
            "dry_run": True,
            "message": "Codex CLI adapter is wired, but dry-run is enabled. Set dry_run false in configs/codex_cli.example.json to execute.",
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
    last_message = ""
    if output_file.exists():
        last_message = output_file.read_text(encoding="utf-8", errors="replace")

    print(json.dumps({
        "ok": proc.returncode == 0,
        "adapter": "examples/codex_cli_adapter.py",
        "dry_run": False,
        "mode": args.mode,
        "exit_code": proc.returncode,
        "command": command,
        "last_message": trim(last_message, 20000),
        "stdout": trim(proc.stdout, 20000),
        "stderr": trim(proc.stderr, 8000),
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


def build_codex_command(args: argparse.Namespace, task: dict[str, Any]) -> tuple[list[str], Path, str]:
    output_file = Path(tempfile.gettempdir()) / f"pocket-vibe-codex-last-{os.getpid()}.md"
    options = task.get("turn_options", {}) if isinstance(task.get("turn_options", {}), dict) else {}
    mode = str(options.get("mode") or task.get("mode") or args.mode)
    session_id = str(options.get("session_id") or task.get("session_id") or args.session_id).strip()
    cwd = str(options.get("cwd") or task.get("cwd") or args.cwd).strip()
    model = str(options.get("model") or task.get("model") or args.model).strip()
    reasoning_effort = normalize_reasoning_effort(
        str(options.get("reasoning_effort") or options.get("effort") or task.get("reasoning_effort") or args.reasoning_effort)
    )
    if session_id and mode == "exec":
        mode = "resume"

    if mode == "resume":
        command = ["codex", "exec", "resume"]
        if args.json_events:
            command.append("--json")
        if args.last:
            command.append("--last")
        elif session_id:
            command.append(session_id)
        else:
            raise SystemExit("resume mode requires --session-id, task.session_id, or --last")
        if model:
            command.extend(["--model", model])
        if reasoning_effort:
            command.extend(["-c", f"model_reasoning_effort='{reasoning_effort}'"])
        if args.skip_git_repo_check:
            command.append("--skip-git-repo-check")
        command.extend(["--output-last-message", str(output_file), "-"])
        return command, output_file, cwd

    command = ["codex", "exec"]
    if cwd:
        command.extend(["--cd", cwd])
    if model:
        command.extend(["--model", model])
    if reasoning_effort:
        command.extend(["-c", f"model_reasoning_effort='{reasoning_effort}'"])
    if args.sandbox:
        command.extend(["--sandbox", args.sandbox])
    if args.skip_git_repo_check:
        command.append("--skip-git-repo-check")
    if args.json_events:
        command.append("--json")
    command.extend(["--output-last-message", str(output_file), "-"])
    return command, output_file, cwd


def normalize_reasoning_effort(value: str) -> str:
    value = (value or "").strip().lower()
    if value in {"auto", "default", "none"}:
        return ""
    allowed = {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
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
- If the task requires edits, make the smallest safe change and report files changed.
- If permissions, credentials, or user approval are needed, stop and say exactly what is needed.
- Do not assume this invocation is the same as an active GUI chat unless a resume session id was explicitly configured.
"""


def trim(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n... trimmed {len(value) - limit} chars ..."


if __name__ == "__main__":
    main()




