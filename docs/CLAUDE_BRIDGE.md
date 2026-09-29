# Claude Code Bridge

`examples/claude_code_adapter.py` 是 Desktop Agent Bridge 到 Claude Code CLI 的本地适配器。它从 stdin 接收 JSON task，把 objective 包装成 Claude Code prompt，然后调用：

```text
claude --print --output-format json ...
```

## 默认安全行为

`configs/claude_code.example.json` 默认会真实调用 Claude Code；只验证链路时可临时加入 `--dry-run`，仅返回命令和 prompt 预览。

启用真实执行：

1. 确认当前电脑已经登录并能运行 `claude --help`。
2. 如需只验证链路，在 `configs/claude_code.example.json` 的命令末尾临时加入 `--dry-run`。
3. 按需要设置 `--cwd`、`--model`、`--permission-mode`、`--allowedTools`。
4. 重新启动 Claude worker。

## 会话模式

- 新会话：`--mode exec`
- 继续当前目录最近会话：`--mode continue`
- 恢复指定会话：`--mode resume --session-id <CLAUDE_SESSION_ID>`

如果要让 Linux 小软件选择不同 Claude 会话，建议复制配置文件，每个会话启动一个独立 agent id，例如：

```powershell
python device\desktop_agent.py `
  --hub 'ws://192.168.1.20:8787/ws/desktop' `
  --token 'change-me-desktop-token' `
  --agent-id 'claude-current' `
  --local-agent-config 'configs\claude_current_session.example.json'
```

然后 Linux 端使用：

```bash
python tools/pva.py --hub http://127.0.0.1:8787 --token change-me-tool-token \
  task send --agent claude-current --objective '继续刚才的修复任务'
```

## 输出

adapter 会返回：

- `ok`
- `exit_code`
- `command`
- `session_id`（如果 Claude JSON/stream-json 输出中包含）
- `stdout` / `stderr`
- parsed `json`

PowerShell 管道可能带 UTF-8 BOM，adapter 已使用 `utf-8-sig` 读取 stdin。
