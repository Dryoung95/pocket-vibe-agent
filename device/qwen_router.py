from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal

import httpx


ThinkingLevel = Literal["fast", "balanced", "deep", "ultra"]


@dataclass
class Decision:
    thinking_level: ThinkingLevel
    target_capability: str
    agent_role: str
    summary: str
    plan: list[str]
    model_used: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "thinking_level": self.thinking_level,
            "target_capability": self.target_capability,
            "agent_role": self.agent_role,
            "summary": self.summary,
            "plan": self.plan,
            "model_used": self.model_used,
        }


class QwenDecisionRouter:
    """
    Decision layer for the Linux-side hub.

    It tries an OpenAI-compatible Qwen endpoint first. If the local model is not
    available, it falls back to a deterministic heuristic so the demo still works.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("QWEN_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("QWEN_API_KEY", "local-not-needed")
        self.model = os.getenv("QWEN_MODEL", "Qwen/Qwen3-4B-Instruct-2507")
        self.timeout = float(os.getenv("QWEN_TIMEOUT_SECONDS", "8"))

    async def decide(
        self,
        objective: str,
        requested_level: str = "auto",
        agents: list[dict[str, Any]] | None = None,
    ) -> Decision:
        if self.base_url:
            try:
                return await self._decide_with_qwen(objective, requested_level, agents or [])
            except Exception as exc:
                fallback = self._decide_heuristic(objective, requested_level, agents or [])
                fallback.summary = (
                    f"{fallback.summary} / Qwen endpoint unavailable, "
                    f"heuristic fallback: {exc.__class__.__name__}"
                )
                return fallback
        return self._decide_heuristic(objective, requested_level, agents or [])

    async def _decide_with_qwen(
        self,
        objective: str,
        requested_level: str,
        agents: list[dict[str, Any]],
    ) -> Decision:
        system_prompt = (
            "You are the local decision model on a portable Linux coding device. "
            "Route user intent to desktop agents. Return strict JSON only with keys: "
            "thinking_level, target_capability, agent_role, summary, plan. "
            "thinking_level must be one of fast, balanced, deep, ultra."
        )
        user_prompt = {
            "objective": objective,
            "requested_level": requested_level,
            "available_agents": agents,
            "routing_policy": {
                "fast": "small read-only tasks, quick commands, status checks",
                "balanced": "normal coding assistance and file navigation",
                "deep": "multi-file changes, debugging, test planning",
                "ultra": "risky architecture changes, long autonomous planning",
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
        data = json.loads(raw)
        return Decision(
            thinking_level=_coerce_level(data.get("thinking_level", requested_level)),
            target_capability=str(data.get("target_capability", "agent.echo")),
            agent_role=str(data.get("agent_role", "desktop-generalist")),
            summary=str(data.get("summary", "Qwen routed this task.")),
            plan=[str(item) for item in data.get("plan", [])][:6]
            or ["Acknowledge task", "Execute safely", "Return result"],
            model_used=self.model,
        )

    def _decide_heuristic(
        self,
        objective: str,
        requested_level: str,
        agents: list[dict[str, Any]],
    ) -> Decision:
        lower = objective.lower()
        local_agent_available = any("local.agent" in agent.get("capabilities", []) for agent in agents)
        level = _coerce_level(requested_level)

        if requested_level == "auto":
            if any(word in lower for word in [
                "architecture", "debug", "refactor", "multi-file",
                "架构", "重构", "调试", "修复", "多文件", "排查",
            ]):
                level = "deep"
            elif any(word in lower for word in [
                "status", "system", "whoami", "info",
                "状态", "系统", "信息", "检查", "连通", "通信",
            ]):
                level = "fast"
            else:
                level = "balanced"

        local_agent_intent = any(
            word in lower
            for word in [
                "local agent",
                "desktop agent",
                "codex",
                "claude",
                "cursor",
                "cline",
                "本地agent",
                "本地 agent",
                "本机agent",
                "本机 agent",
                "电脑上的agent",
                "命令我的电脑",
                "命令本机",
                "调用本地",
                "调用电脑",
                "发送提示词",
                "执行任务",
            ]
        )

        if any(word in lower for word in ["status", "system", "info", "whoami", "状态", "系统", "信息"]) and not local_agent_intent:
            capability = "system.info"
            plan = ["Check desktop bridge identity", "Collect safe system metadata", "Return concise status"]
        elif any(word in lower for word in ["open", "url", "browser", "打开", "浏览器", "网页"]):
            capability = "browser.open"
            plan = ["Validate requested URL", "Ask desktop bridge to open browser", "Return launch status"]
        elif local_agent_intent or local_agent_available:
            capability = "local.agent"
            plan = [
                "Package objective as JSON",
                "Forward to the configured local desktop agent adapter",
                "Return stdout, stderr, exit code, and parsed JSON if available",
            ]
        else:
            capability = "agent.echo"
            plan = ["Summarize objective", "Select available desktop bridge", "Return simulated execution result"]

        agent_hint = "desktop-generalist"
        if agents:
            agent_hint = str(agents[0].get("agent_id", "desktop-generalist"))

        return Decision(
            thinking_level=level,
            target_capability=capability,
            agent_role=agent_hint,
            summary=f"Routed by local heuristic as {level}/{capability}.",
            plan=plan,
            model_used="heuristic-fallback",
        )


def _coerce_level(value: str) -> ThinkingLevel:
    value = (value or "balanced").lower()
    if value in {"fast", "balanced", "deep", "ultra"}:
        return value  # type: ignore[return-value]
    return "balanced"
