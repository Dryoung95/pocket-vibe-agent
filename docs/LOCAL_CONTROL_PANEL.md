# Local Control Panel GUI

这个页面运行在当前电脑上，用来扫描本机正在运行的 Codex / Claude Code，并把选中的 agent bridge 导入到待配对的 Linux Hub。

## 启动

PowerShell：

```powershell
cd S:\portable-vibe-agent-demo
.\scripts\start-local-control-panel.ps1
```

然后打开：

```text
http://127.0.0.1:8790
```

## 使用流程

1. 在 Linux 小电脑上先启动 Hub：

```bash
cd /path/to/portable-vibe-agent-demo
export POCKET_VIBE_TOKEN='change-me-desktop-token'
export POCKET_VIBE_TOOL_TOKEN='change-me-tool-token'
export POCKET_VIBE_HOST='0.0.0.0'
export POCKET_VIBE_PORT='8787'
python device/device_hub.py
```

2. 在本机 GUI 的“Linux 配对”区填写：

- Linux Hub URL：例如 `http://192.168.1.20:8787`
- Desktop Token：Linux 上的 `POCKET_VIBE_TOKEN`
- Tool Token：Linux 上的 `POCKET_VIBE_TOOL_TOKEN`，可选但推荐填写，用于验证远端在线 agent

3. 点击“保存 / 测试配对”。

4. 在“本机运行中”或“可导入模板”里勾选 Codex / Claude：

- 运行中进程如果能识别到 session id，会生成 resume 配置。
- 如果没有识别到 session id，会作为新 headless worker 导入。
- 模板项可以直接导入标准 Codex / Claude worker。
- 如需恢复某个会话，在卡片里的 `session id` 输入框手动填入 Codex thread id 或 Claude session id。

5. 点击：

- “生成待配对导入包”：只写入 `runtime/linux_import_bundle.json` 和 `runtime/start-imported-bridges.ps1`
- “生成并启动 Bridge”：写入导入包并立即在本机启动对应 `desktop_agent.py` bridge，主动连到 Linux Hub

## 输出文件

- `runtime/local_pairing.json`：本机保存的 Linux 配对信息，包含 token，请勿外传。
- `runtime/linux_import_bundle.json`：本次导入计划。
- `runtime/start-imported-bridges.ps1`：可重复运行的本机 bridge 启动脚本。
- `runtime/imported_agents/*.json`：由 GUI 生成的 Codex / Claude adapter 配置。

## 安全说明

- 示例配置默认真实执行 Codex / Claude；只验证链路时请在对应 config 中临时加入 `--dry-run`。
- GUI 默认只监听 `127.0.0.1:8790`，不暴露到局域网。
- Linux Hub 侧仍应更换默认 token；跨不可信网络时建议用 WireGuard、Tailscale 或 SSH tunnel。
