# RK3588 Pairing

这条流程用于“开发板在另一台机器上”的场景：RK3588 端运行 Hub，并生成一段可转发的配对码；Windows 端粘贴配对码后自动填入 Hub 地址、Desktop Bridge Token 和 Tool Token。

## 1. RK3588 端

把项目目录放到 RK3588 开发板上，然后运行：

```bash
cd /path/to/portable-vibe-agent-demo
chmod +x scripts/start-rk3588-pairing.sh
./scripts/start-rk3588-pairing.sh
```

脚本会做这些事：

- 创建或复用 `.venv`
- 安装 `requirements.txt`
- 在 `runtime/rk3588_pairing.env` 里生成并保存随机 token
- 自动检测开发板局域网 IP
- 打印 `PVA_PAIRING_CODE=...`
- 如果系统有图形界面，会打开 `runtime/rk3588_pairing.html`
- 启动 `device/device_hub.py`

保持这个终端不要关闭。终端关闭后，开发板 Hub 也会停止。

## 2. Windows 端

启动本机控制台：

```powershell
cd S:\portable-vibe-agent-demo
.\scripts\start-control-panel.cmd
```

浏览器打开：

```text
http://127.0.0.1:8790/#pairing
```

把 RK3588 端显示的整行 `PVA_PAIRING_CODE=...` 粘贴到“开发板配对码”，点击“应用配对码”。页面会自动填入：

- Linux Hub 地址
- Desktop Bridge Token
- Tool Token

随后点击“检测 Hub”。通过后，到“本机 Agent”重新扫描，再到“导入”启动 Codex 或 Claude Bridge。

## 3. 常见问题

- 如果 Windows 检测 Hub 失败，先确认 Windows 和 RK3588 在同一个局域网，并且能访问脚本打印的 `Hub URL`。
- 如果开发板 IP 检测不准，可以手动指定：

```bash
POCKET_VIBE_PAIRING_IP=192.168.1.20 ./scripts/start-rk3588-pairing.sh
```

- 如果需要固定 token，可以先设置环境变量再运行：

```bash
export POCKET_VIBE_TOKEN='your-desktop-bridge-token'
export POCKET_VIBE_TOOL_TOKEN='your-tool-token'
./scripts/start-rk3588-pairing.sh
```

- 这个 demo 的 HTTP/WS 没有内置 TLS。跨不可信网络时，请使用 WireGuard、Tailscale 或 SSH tunnel。
