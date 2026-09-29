# Remote Linux Control Quickstart

这个 demo 已经可以让 Linux 小软件通过 Wi-Fi 控制当前电脑上的 Codex CLI 和 Claude Code。架构是：Linux 端运行 Device Hub；Windows/Mac 端运行 Desktop Agent Bridge，主动连回 Linux Hub；Linux 端通过 HTTP API/CLI 发任务。

## 1. Linux 小电脑：启动 Hub

RK3588 / Linux 开发板推荐直接使用一键配对脚本：

```bash
cd /path/to/portable-vibe-agent-demo
chmod +x scripts/start-rk3588-pairing.sh
./scripts/start-rk3588-pairing.sh
```

脚本会生成 `PVA_PAIRING_CODE=...`。把这行发给 Windows 端，在控制台 `http://127.0.0.1:8790/#pairing` 粘贴并点击“应用配对码”即可。更详细的步骤见 `docs/RK3588_PAIRING.md`。

手动启动方式如下：

```bash
cd /path/to/portable-vibe-agent-demo
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
export POCKET_VIBE_TOKEN='change-me-desktop-token'
export POCKET_VIBE_TOOL_TOKEN='change-me-tool-token'
export POCKET_VIBE_HOST='0.0.0.0'
export POCKET_VIBE_PORT='8787'
python device/device_hub.py
```

记下 Linux 的局域网 IP，例如 `192.168.1.20`。

## 2. 当前电脑：启动 Codex worker

PowerShell：

```powershell
cd S:\portable-vibe-agent-demo
$env:POCKET_VIBE_TOKEN='change-me-desktop-token'
python device\desktop_agent.py `
  --hub 'ws://192.168.1.20:8787/ws/desktop' `
  --token $env:POCKET_VIBE_TOKEN `
  --agent-id 'codex-worker' `
  --local-agent-config 'configs\codex_cli.example.json'
```

默认配置会真实执行。只验证链路时，可在 `configs/codex_cli.example.json` 中临时加入 `--dry-run`；需要写文件时，再按安全边界把 `--sandbox` 从 `read-only` 改成 `workspace-write`。

## 3. 当前电脑：启动 Claude Code worker

PowerShell：

```powershell
cd S:\portable-vibe-agent-demo
$env:POCKET_VIBE_TOKEN='change-me-desktop-token'
python device\desktop_agent.py `
  --hub 'ws://192.168.1.20:8787/ws/desktop' `
  --token $env:POCKET_VIBE_TOKEN `
  --agent-id 'claude-worker' `
  --local-agent-config 'configs\claude_code.example.json'
```

默认配置会真实执行 Claude Code。只验证链路时可临时加入 `--dry-run`；如需非交互权限策略，可按安全边界调整 `--permission-mode` 和 `--allowedTools`。

## 4. Linux 小电脑：查看在线 agent

```bash
python tools/pva.py \
  --hub 'http://192.168.1.20:8787' \
  --token 'change-me-tool-token' \
  agent list
```

如果 Hub 就运行在 Linux 本机，也可以用：

```bash
python tools/pva.py --hub 'http://127.0.0.1:8787' --token 'change-me-tool-token' agent list
```

## 5. Linux 小电脑：发送提示词

发给 Codex：

```bash
python tools/pva.py --hub 'http://127.0.0.1:8787' --token 'change-me-tool-token' \
  task send --agent codex-worker --objective '请检查当前项目结构并给出下一步修改建议'
```

发给 Claude Code：

```bash
python tools/pva.py --hub 'http://127.0.0.1:8787' --token 'change-me-tool-token' \
  task send --agent claude-worker --objective '请总结这个仓库的入口文件和启动命令'
```

结果会显示在 Hub GUI、`runtime/events.jsonl`，以及 CLI 返回的 task 状态中。

## 6. 选择“对话进程”

推荐方式不是抓 GUI 窗口，而是把每个可恢复会话注册成一个独立 agent id：

- Codex 新任务：`configs/codex_cli.example.json` + `agent-id codex-worker`
- Codex 指定 session：复制 `configs/codex_current_thread.example.json`，替换 session id，然后用 `agent-id codex-current`
- Claude 新任务：`configs/claude_code.example.json` + `agent-id claude-worker`
- Claude 指定 session：复制 `configs/claude_current_session.example.json`，替换 session id，然后用 `agent-id claude-current`

Linux 端选择目标时只需要传 `--agent codex-current` 或 `--agent claude-current`。

## 7. 安全默认值

- 默认 token 是开发值，真实 Wi-Fi 使用必须改掉 `POCKET_VIBE_TOKEN` 和 `POCKET_VIBE_TOOL_TOKEN`。
- 默认 adapter 会真实驱动 Codex/Claude；dry-run 需要显式开启。
- 不建议默认开启 Claude `bypassPermissions` 或 Codex `danger-full-access`。
- 跨不可信网络时，用 WireGuard/Tailscale/SSH tunnel；这个 demo 的 HTTP/WS 未内置 TLS。

## 8. 直接 HTTP API

Linux 小软件不想调用 `tools/pva.py` 时，可以直接走 HTTP：

```bash
curl -H 'Authorization: Bearer change-me-tool-token' \
  http://127.0.0.1:8787/v1/agents

curl -H 'Authorization: Bearer change-me-tool-token' \
  'http://127.0.0.1:8787/v1/sessions?provider=claude'

curl -X POST http://127.0.0.1:8787/v1/turns \
  -H 'Authorization: Bearer change-me-tool-token' \
  -H 'Content-Type: application/json' \
  -d '{"provider":"claude","prompt":"继续解释当前项目","session_id":"CLAUDE_SESSION_ID_IF_NEEDED"}'
```

`session_id` 有两种用法：

- 如果等于在线 agent id，例如 `claude-worker`，Hub 会直接投给这个 worker。
- 如果是 Codex/Claude 原生 session id，Hub 会透传给 adapter；adapter 会自动改成 `codex exec resume <id>` 或 `claude --print --resume <id>`。
