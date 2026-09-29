# Local Agent Gateway Design

## 1. 目标

在 Windows / macOS 本机运行一个 **Local Agent Gateway**，让 Linux 小设备上的 Pocket GUI 可以通过 Wi‑Fi 控制这台电脑上的 Codex 与 Claude Code。

目标体验：

```text
Linux Pocket GUI
  -> 选择本机 Agent: Codex / Claude Code
  -> 选择会话: 新建 / 继续最近 / 指定 session
  -> 输入提示词
  -> 本机 Gateway 调用对应 CLI
  -> 任务状态、日志、结果回流到 Pocket GUI
```

## 2. 关键判断

Codex / Claude Code 里通常没有一个可以直接公开给外部产品的“Agent ID”。它们更常见的是：

- CLI 进程
- session / thread / conversation id
- 当前工作目录
- 当前 project / repo
- model / permission mode
- 输出流

因此 Pocket 产品里的 **Agent ID 应该由我们自己的 Gateway 分配**，例如：

```text
codex-worker
claude-reviewer
claude-planner
codex-readonly
```

这些 Agent ID 是 Pocket 的通讯录地址。背后可以绑定一个 Codex 或 Claude Code 的运行配置。

## 3. 总体架构

```text
+--------------------------+
| Linux Pocket Device      |
| Pixel GUI + Qwen Router  |
| Pocket Hub               |
+------------+-------------+
             |
             | WebSocket / HTTP over Wi-Fi
             |
+------------v-------------+
| Local Agent Gateway      |
| runs on Windows / macOS  |
+------------+-------------+
             |
             | adapter interface
             |
   +---------+----------+
   |                    |
+--v---------+    +-----v------+
| Codex CLI  |    | Claude Code|
| codex exec |    | claude -p  |
| resume     |    | resume     |
+------------+    +------------+
```

## 4. 组件设计

### 4.1 Pocket Hub

运行在 Linux 小设备上。

职责：

- 保存在线 Agent Card。
- 给 GUI 提供 agent list / task timeline。
- 接收用户任务。
- 按 Agent ID 或 Qwen 自动路由任务。
- 通过 WebSocket 把任务发给 Local Agent Gateway。
- 接收 ACK / progress / result。

### 4.2 Local Agent Gateway

运行在当前电脑上。

职责：

- 主动连接 Linux Pocket Hub。
- 注册一个或多个本机 Agent ID。
- 探测 Codex / Claude Code 是否可用。
- 列出可恢复的 session / conversation。
- 接收 Pocket 任务。
- 调用 Codex / Claude Code adapter。
- 把 stdout / stderr / JSONL events / final result 回传给 Pocket。

### 4.3 Adapter

每个本机 agent 一个 adapter。

建议内置：

```text
adapters/codex_adapter.py
adapters/claude_code_adapter.py
```

它们统一接收：

```json
{
  "task_id": "task_xxx",
  "agent_id": "codex-worker",
  "objective": "修复测试失败",
  "mode": "new | resume | continue",
  "session_id": "optional",
  "cwd": "S:/project",
  "permission": "read-only | workspace-write",
  "output_format": "jsonl"
}
```

统一输出：

```json
{
  "ok": true,
  "task_id": "task_xxx",
  "agent_id": "codex-worker",
  "session_id": "abc123",
  "status": "done",
  "stdout": "...",
  "stderr": "...",
  "final_message": "...",
  "events": []
}
```

## 5. Codex 接入设计

### 5.1 新任务模式

推荐 MVP 使用：

```powershell
codex exec --cd S:/project --sandbox read-only --json -
```

Pocket 发来的 prompt 通过 stdin 输入。

优点：

- 每个任务独立。
- 不污染当前聊天。
- 易于审计。
- 失败隔离好。

### 5.2 Resume 模式

用于继续已有 Codex session：

```powershell
codex exec resume <session_id> --json -
```

或继续最近 session：

```powershell
codex exec resume --last --json -
```

但不建议默认用 `--last`，因为它可能误恢复到用户正在手动操作的会话。

### 5.3 Pocket Agent Card

```json
{
  "agent_id": "codex-worker",
  "display_name": "Codex Worker",
  "kind": "codex",
  "entrypoint": "codex exec",
  "capabilities": [
    "codex.exec",
    "codex.resume",
    "repo.read",
    "repo.write",
    "test.run"
  ],
  "default_cwd": "S:/project",
  "default_sandbox": "read-only",
  "status": "idle"
}
```

## 6. Claude Code 接入设计

### 6.1 新任务模式

```powershell
claude -p "prompt" --output-format stream-json
```

或者 stdin：

```powershell
type prompt.txt | claude -p --output-format json
```

### 6.2 Continue 模式

继续当前目录最近会话：

```powershell
claude -c -p "继续刚才的任务" --output-format json
```

### 6.3 Resume 指定 session

```powershell
claude -r "<session-id>" "继续这个任务"
```

或：

```powershell
claude --resume <session-id> "继续这个任务"
```

### 6.4 Pocket Agent Card

```json
{
  "agent_id": "claude-reviewer",
  "display_name": "Claude Reviewer",
  "kind": "claude-code",
  "entrypoint": "claude -p",
  "capabilities": [
    "claude.print",
    "claude.resume",
    "repo.read",
    "review",
    "test.plan"
  ],
  "default_cwd": "S:/project",
  "status": "idle"
}
```

## 7. 会话选择 UI

Linux Pocket GUI 上增加一个 **Session Picker**：

```text
Agent: Codex Worker

Mode:
[ New task ]
[ Continue latest in cwd ]
[ Resume selected session ]

Sessions:
- codex session abc123   S:/project   10 min ago
- codex session def456   S:/other     yesterday
```

Claude Code 类似：

```text
Agent: Claude Reviewer

Mode:
[ New print task ]
[ Continue latest ]
[ Resume session id ]

Session ID:
[________________]
```

## 8. 网络连接

MVP：

```text
Gateway -> Pocket Hub
WebSocket outbound
ws://pocket.local:8787/ws/desktop
```

为什么用 Gateway 主动连 Hub：

- Windows/macOS 不需要开入站端口。
- 避免防火墙/NAT 问题。
- Linux 小设备只维护一个 Hub。
- 断线可自动重连。

生产版：

```text
wss://pocket.local:8787
Agent token
Pairing code
Optional Tailscale / WireGuard / mTLS
```

## 9. 安全模型

不要让 Linux 设备发送任意 shell 命令。

正确链路：

```text
Pocket prompt
  -> structured task JSON
  -> Gateway
  -> fixed adapter command
  -> Codex / Claude Code
```

不要做：

```text
Pocket prompt -> powershell/cmd/bash arbitrary command
```

权限建议：

| 权限 | 行为 |
|---|---|
| read-only | 只读 repo、总结、分析 |
| workspace-write | 可以改当前项目文件 |
| shell-limited | 只能跑 allowlist 命令 |
| shell-full | 高风险，需要二次确认 |
| deploy | 禁止默认开启 |

## 10. MVP 实现路径

### Phase 1: 单 Agent 打通

- 固定 `agent_id=codex-worker`
- Gateway 调用 `codex exec --dry-run`
- Pocket GUI 能看到 Codex Worker 小人上线
- 输入 prompt 后返回 dry-run 命令

### Phase 2: 真实 Codex 执行

- 移除 dry-run
- 默认 read-only
- 支持 `--cwd`
- 回传 JSONL / final message

### Phase 3: Claude Code Adapter

- 支持 `claude -p --output-format json`
- 支持 `claude -c`
- 支持 `claude -r <session-id>`

### Phase 4: Session Picker

- Gateway 扫描 Codex / Claude session metadata
- GUI 展示可恢复会话
- 用户显式选择 session 后 resume

### Phase 5: Pairing + 权限

- Linux 显示 pair code
- Gateway 输入 pair code
- Hub 签发 scoped token
- Agent Card 显示能力与权限

## 11. 最小 API

Gateway 暴露给 Pocket Hub 的协议仍走 WebSocket。Pocket Hub 对 GUI/CLI 暴露：

```http
GET /api/agents
GET /api/agents/{agent_id}
POST /api/tasks
GET /api/tasks/{task_id}
```

Task payload：

```json
{
  "target_agent_id": "codex-worker",
  "objective": "修复当前项目测试失败",
  "thinking_level": "deep",
  "mode": "new",
  "session_id": null,
  "cwd": "S:/project"
}
```

## 12. 关键产品原则

1. Agent ID 是 Pocket 的地址，不是 Codex/Claude 原生 ID。
2. Codex/Claude session ID 是 Agent 背后的会话指针。
3. 默认新建任务，不默认接管当前正在交互的聊天。
4. Resume 必须用户显式选择 session。
5. GUI 负责可视化，CLI/API 负责自动化。
6. 所有危险能力都需要权限层。

