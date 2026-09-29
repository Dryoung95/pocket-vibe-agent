# Pocket Vibe Linux 控制端

这是发给 Linux / RK3588 队友的一键包。它的作用是：在 Linux 上启动 Hub，生成配对码；Windows 端配对并导入 Codex / Claude Bridge 后，Linux 端就能通过网页或命令行输入提示词，控制 Windows 本地电脑上的 Agent 工作。

## 1. 解压并启动

运行：

    mkdir pocket-vibe-linux-control
    unzip pocket-vibe-linux-handoff-*.zip -d pocket-vibe-linux-control
    cd pocket-vibe-linux-control
    chmod +x start-linux-control-app.sh send-prompt.sh scripts/start-rk3588-pairing.sh
    ./start-linux-control-app.sh

启动后终端会打印：

    PVA_PAIRING_CODE=...
    Hub URL: http://<linux-ip>:8787

把整行 PVA_PAIRING_CODE=... 发给 Windows 端操作者。这个终端不要关闭，关闭后 Hub 会停止。

## 2. Windows 端配对

Windows 端打开：

    http://127.0.0.1:8790/?v=6#pairing

粘贴 PVA_PAIRING_CODE=...，点击“应用配对码”，再到“本机 Agent”里导入并启动 Codex 或 Claude Bridge。

## 3. Linux 端网页控制

在 Linux / RK3588 浏览器打开：

    http://127.0.0.1:8787/?v=7

如果从同一局域网其他设备访问，把 127.0.0.1 换成脚本打印的 Linux IP。

网页里可以选择 Agent 类型、模型、推理强度、会话模式、会话 ID 和工作目录。

## 4. Linux 端命令行控制

查看是否有 Windows Agent 连入：

    ./send-prompt.sh agent list

发送给 Codex：

    ./send-prompt.sh --provider codex --model gpt-5.6-terra --effort high --prompt "请检查当前项目状态并给出下一步建议" --wait

发送给 Claude Code：

    ./send-prompt.sh --provider claude --model sonnet --effort max --prompt "请总结这个仓库的入口文件和启动命令" --wait

恢复指定会话：

    ./send-prompt.sh --provider codex --mode resume --session-id "<SESSION_ID>" --prompt "继续刚才的任务" --wait

## 5. 常见问题

- 如果 Windows 端检测 Hub 失败，确认两台机器在同一局域网，且 Windows 能访问 http://<linux-ip>:8787/health。
- 如果网页能打开但没有 Agent，说明 Windows 端还没有导入/启动 Bridge，或 token 不一致。
- 新建 Bridge 默认真实执行；如果只想验证链路，Windows 端应在启动前手动开启 dry-run。
- 这个 demo 的 HTTP / WebSocket 没有内置 TLS；跨不可信网络请走 Tailscale、WireGuard 或 SSH tunnel。
