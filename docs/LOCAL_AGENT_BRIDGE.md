# Local Agent Bridge

这个 demo 现在可以把便携 Linux Hub 发来的任务转交给本机正在运行/可调用的 agent。

核心原则：

- Hub 不发送 shell 命令。
- 远端任务只作为 JSON 输入。
- 本机用户预先配置一个固定 command。
- `desktop_agent.py` 只执行这个本机配置里的 command，并把 stdout/stderr/exit_code 回传 GUI。

## 1. 先跑示例适配器

终端 A 启动 Hub：

```powershell
cd S:\portable-vibe-agent-demo
python device\device_hub.py
```

终端 B 启动本机 Desktop Bridge，并启用 local agent adapter：

```powershell
cd S:\portable-vibe-agent-demo
python device\desktop_agent.py `
  --hub ws://127.0.0.1:8787/ws/desktop `
  --token dev-token `
  --agent-id local-windows `
  --local-agent-config configs\local_agent.example.json
```

或者直接运行：

```powershell
.\scripts\start-local-agent-bridge.ps1
```

打开：

```text
http://127.0.0.1:8787
```

此时小人会以 `Byte Clerk` 上线，并声明 `local.agent / repo.read / repo.write / test.run / git.status` 等能力。GUI 发普通任务时，Bridge 会调用：

```powershell
python examples\local_agent_echo.py
```

并通过 stdin 传入任务 JSON。

## 2. 接入你自己的本地 agent

把 `configs/local_agent.example.json` 复制成自己的配置，例如：

```powershell
Copy-Item configs\local_agent.example.json configs\my_agent.local.json
```

然后把 `command` 换成你的本地 agent 适配器：

```json
{
  "display_name": "Codex Worker",
  "command": [
    "python",
    "adapters/my_codex_adapter.py"
  ],
  "working_dir": "S:/your-project",
  "route_by_default": true,
  "capabilities": [
    "local.agent",
    "repo.read",
    "repo.write",
    "test.run"
  ]
}
```

推荐你写一个很薄的 adapter 脚本，由它去调用真正的 Codex / Claude Code / Cursor / Cline / 其他本机 agent。这样可以在 adapter 里控制：

- 允许访问的工作目录。
- 是否允许改文件。
- 是否允许跑 shell。
- 超时。
- 日志脱敏。
- 危险动作是否需要人工确认。

## 3. Adapter 输入格式

Bridge 会把类似下面的 JSON 通过 stdin 传给你的本机 adapter：

```json
{
  "task_id": "task_xxx",
  "msg_id": "msg_xxx",
  "received_at": "2026-07-23T00:00:00Z",
  "objective": "修复当前项目的测试失败",
  "decision": {
    "thinking_level": "deep",
    "target_capability": "local.agent",
    "summary": "..."
  },
  "safe_mode": true,
  "bridge": {
    "platform": "Windows-11",
    "hostname": "MY-PC",
    "working_dir": "S:/your-project"
  }
}
```

Adapter 可以输出普通文本，也可以输出 JSON。Bridge 会尝试解析 stdout JSON，并把原始 stdout/stderr 一起回传 GUI。

## 4. 安全边界

不要把 GUI 文本直接拼成 shell 命令。

推荐链路：

```text
GUI objective -> Hub/Qwen decision -> desktop_agent.py -> fixed local adapter command -> local agent
```

不推荐链路：

```text
GUI objective -> powershell/cmd/bash arbitrary execution
```

真正要接入生产级本机 agent 时，建议再加：

- allowlist 工作目录。
- command allowlist。
- 文件 diff 审批。
- destructive action 二次确认。
- task_id 幂等缓存。
- stdout/stderr 脱敏。
