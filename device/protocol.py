from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


PROTOCOL_VERSION = "pocket-vibe/0.1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def envelope(
    msg_type: str,
    payload: dict[str, Any] | None = None,
    *,
    msg_id: str | None = None,
    task_id: str | None = None,
    seq: int | None = None,
    ack_of: str | None = None,
) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "type": msg_type,
        "msg_id": msg_id or new_id("msg"),
        "task_id": task_id,
        "seq": seq,
        "ack_of": ack_of,
        "ts": now_iso(),
        "payload": payload or {},
    }


def ack(message: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return envelope(
        "ack",
        payload or {},
        task_id=message.get("task_id"),
        ack_of=message.get("msg_id"),
    )

