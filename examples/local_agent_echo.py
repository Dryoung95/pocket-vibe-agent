from __future__ import annotations

import json
import platform
import socket
import sys
from datetime import datetime, timezone


def main() -> None:
    task = json.loads(sys.stdin.read() or "{}")
    objective = task.get("objective", "")
    decision = task.get("decision", {})
    response = {
        "ok": True,
        "adapter": "examples/local_agent_echo.py",
        "message": "This is a stand-in for your real local agent. Replace the command in configs/local_agent.example.json.",
        "objective": objective,
        "thinking_level": decision.get("thinking_level"),
        "target_capability": decision.get("target_capability"),
        "machine": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
        },
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

