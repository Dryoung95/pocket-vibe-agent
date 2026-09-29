# Pocket Vibe Agent Demo Architecture

## 1. 产品雏形

目标设备是一台便携 Linux 小电脑，承担“入口 + 决策 + 调度”的角色。用户在小屏幕或浏览器 GUI 输入任务，Linux 端本地 Qwen3-4B-Instruct-2507 负责判断任务复杂度、选择思考等级、选择目标 desktop agent，然后通过稳定长连接把任务发送到 Windows/Mac 上的 agent bridge。

## 2. 模块边界

### Linux Device Hub

- 运行像素风 GUI。
- 管理 desktop agent 注册、在线状态、能力声明。
- 调用 Qwen / fallback router 产出结构化决策。
- 将任务封装成协议消息并发送给目标 agent。
- 记录事件日志，用于调试与未来断点恢复。

### Qwen Decision Router

当前 demo 预留四档思考等级：

- `fast`：状态查询、只读检查、简单命令。
- `balanced`：普通 coding 辅助、文件导航、单点修改建议。
- `deep`：多文件调试、测试计划、复杂重构。
- `ultra`：高风险架构变更、长程自主执行，需要更强确认机制。

模型输出建议固定为 JSON schema：

```json
{
  "thinking_level": "balanced",
  "target_capability": "agent.echo",
  "agent_role": "desktop-generalist",
  "summary": "why this route was selected",
  "plan": ["step 1", "step 2"]
}
```

### Desktop Agent Bridge

- Windows/Mac 侧主动连接 Linux Device Hub。
- 上报 `platform`、`hostname`、`capabilities`。
- 收到任务后立即 ACK，执行完成再返回 result。
- 断线自动重连，未发送结果写入本地 outbox。
- 默认安全 demo 模式，不执行任意 shell。

## 3. 通信协议

所有消息都采用 JSON envelope：

```json
{
  "v": "pocket-vibe/0.1",
  "type": "task",
  "msg_id": "msg_xxx",
  "task_id": "task_xxx",
  "seq": 1,
  "ack_of": null,
  "ts": "2026-07-23T00:00:00Z",
  "payload": {}
}
```

关键类型：

- `hello`：agent 注册。
- `heartbeat` / `pong`：链路保活。
- `task`：Hub 下发任务。
- `ack`：agent 已收到任务。
- `result`：agent 执行完成。
- `snapshot`：GUI 初始化状态。

## 4. 稳定性设计

### 当前 demo 已实现

- WebSocket 长连接。
- App-level heartbeat。
- Agent 指数退避重连。
- 每条任务有 `task_id` 和 `msg_id`。
- 任务先 ACK 后 RESULT。
- 事件写入 `runtime/events.jsonl`。
- Agent 结果发送失败时写入 `runtime/desktop_outbox.jsonl`，下次连接后 flush。

### 量产前建议补齐

- 用 SQLite 持久化任务状态和 ACK 游标。
- 给每个 agent 分配长期 identity key，而不是 demo token。
- 增加 mTLS / WireGuard / Tailscale。
- 对高风险能力增加用户确认和权限分级。
- 增加 replay protection：session nonce + monotonic seq。
- 增加 backpressure：限制队列长度、并发任务数、单任务超时。

## 5. 真实控制接入点

不要让便携端直接发 shell 字符串到桌面执行。建议桌面端暴露受控 action API：

- `repo.open(path)`
- `repo.search(query)`
- `file.patch(diff)`
- `test.run(target)`
- `browser.open(url)`
- `agent.chat(prompt, mode)`

每个 action 都声明风险级别、是否需要桌面端确认、是否允许后台执行。

