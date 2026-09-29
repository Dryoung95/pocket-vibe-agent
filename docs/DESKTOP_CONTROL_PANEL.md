# Pocket Vibe Agent Gateway 网站

这个控制台现在是一个本机网站/PWA，不再只是“像软件的 GUI”。它运行在当前电脑上，通过浏览器访问，负责：

- 扫描本机 Codex / Claude Code CLI 是否可用。
- 展示相关运行进程和可恢复 session。
- 配置待配对 Linux Hub。
- 一键启动 Desktop Bridge，把本机 Codex / Claude Code 导入 Linux Hub。
- 管理由网站启动的 Bridge，包括查看日志和停止。

## 启动网站

Windows PowerShell：

```powershell
cd S:\portable-vibe-agent-demo
.\scripts\start-control-panel.ps1
```

浏览器会自动打开：

```text
http://127.0.0.1:8790
```

也可以使用更直观的网站别名：

```powershell
.\scripts\start-agent-gateway-site.ps1
```

## 网站部署方式

默认情况下，网站只绑定本机：

```text
127.0.0.1:8790
```

这意味着其他 Wi-Fi 设备不能直接打开这个网站。真正跨机器的部分是 Desktop Bridge 主动连接 Linux Hub。

如果确实要让局域网设备访问这个网站，请显式设置：

```powershell
$env:POCKET_VIBE_PANEL_HOST = "0.0.0.0"
$env:POCKET_VIBE_PANEL_KEY = "replace-with-a-strong-panel-key"
.\scripts\start-control-panel.ps1
```

然后在网页的 `Panel Key` 输入框填写同一个 key。不要在没有 key 的情况下把网站暴露到局域网。

## Linux Hub 端准备

在 Linux 电脑上启动 Hub：

```bash
cd /path/to/portable-vibe-agent-demo
export POCKET_VIBE_TOKEN='replace-with-a-strong-desktop-bridge-token'
export POCKET_VIBE_TOOL_TOKEN='replace-with-a-strong-tool-token'
export POCKET_VIBE_HOST='0.0.0.0'
export POCKET_VIBE_PORT='8787'
python device/device_hub.py
```

记下 Linux 的局域网地址，例如：

```text
http://192.168.1.20:8787
```

## 网页使用流程

1. 打开本机网站。
2. 在“连接待配对 Linux Hub”里填 Linux Hub 地址。
3. 填 `Desktop Bridge Token`，它必须等于 Linux 端的 `POCKET_VIBE_TOKEN`。
4. 可选填 `Tool Token`，用于检测 Linux Hub 的 `/v1/agents`。
5. 点击“检测 Hub”。
6. 在“本机 Agent 能力 / 进程 / 可恢复会话”里选择 Codex 或 Claude Code。
7. 默认关闭 `dry-run`，点击“导入 / 启动 Bridge”会真实执行；若只验证链路，请先手动开启 `dry-run`。
8. Linux Hub 能看到 worker 后，即可发送提示词；测试结束后按需要保留或删除 Bridge。

## 支持模式

- `exec`：导入为新的 Codex / Claude worker。
- `resume`：把指定 session id 导入为可恢复 worker。
- `continue`：Claude Code 专用，继续当前目录最近会话。

## PWA / 网站能力

网站包含：

- `site.webmanifest`
- `service-worker.js`
- `icon.svg`

在支持的浏览器里可以安装为桌面应用，但本质仍是本机网页 + 本机 FastAPI 后端。

## 安全默认值

- 网站默认只监听 loopback。
- 非本机 Linux Hub 拒绝使用 `dev-token` 等默认 token。
- 新导入默认真实执行；dry-run 需要手动开启。
- Codex 默认 `sandbox=read-only`、`approval=never`。
- Claude 默认 `permission-mode=default`。
- 跨不可信网络请用 WireGuard / Tailscale / SSH tunnel。
