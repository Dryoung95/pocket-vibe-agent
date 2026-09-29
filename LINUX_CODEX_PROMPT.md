# 给 Linux / RK3588 端 Codex 的任务

你现在拿到的是 Pocket Vibe 的完整交接源码。请直接阅读、修改、运行和验证代码，不要只输出设计方案。

## 最终目标

让 Linux 虚拟机或 RK3588 作为远程 Hub。用户在 Linux 网页或终端输入提示词，Hub 将任务发给 Windows 电脑上已经配对的 Codex / Claude Code Bridge，由 Windows 本地 Agent 执行，再把状态和结果返回 Linux。

通信链路：

    Linux Web / CLI
      -> POST /v1/turns
      -> Linux device/device_hub.py
      -> WebSocket /ws/desktop
      -> Windows device/desktop_agent.py
      -> examples/codex_cli_adapter.py 或 examples/claude_code_adapter.py
      -> 执行结果原路返回 Linux

## Windows 本机控制面板

Windows 管理页面是：

    http://127.0.0.1:8790/?v=6#agents

相关源码：

- device/desktop_control_panel.py
- web_control_panel/index.html
- web_control_panel/app.js
- web_control_panel/styles.css
- scripts/start-control-panel.ps1

这个地址只属于 Windows 本机。Linux 不能通过自己的 127.0.0.1 访问 Windows 控制面板。Windows 控制面板负责扫描本机 Codex / Claude 会话、生成 Bridge 配置并启动 desktop_agent.py。随后 Windows Bridge 主动连接 Linux Hub：

    ws://<linux-ip>:8787/ws/desktop

## 已实现部分

- Linux Hub：device/device_hub.py
- Linux 网页控制台：web/index.html、web/app.js、web/styles.css
- Linux CLI：tools/pva.py
- 一键配对：scripts/start-rk3588-pairing.sh
- Linux 启动入口：start-linux-control-app.sh
- Linux 终端入口：send-prompt.sh
- Codex 模型和 reasoning effort 透传
- Claude model 和 effort 透传
- session_id、cwd、mode 透传
- Agent ACK、result、断线重连和等待队列基础逻辑

## 需要完成和验证

1. 修复并验证 Linux 一键启动：

       bash start-linux-control-app.sh

   它必须创建或复用 .venv、安装 requirements.txt、生成随机 token、打印 PVA_PAIRING_CODE、启动 0.0.0.0:8787。

2. 验证 Windows 配对流程：

   - Linux 打印 PVA_PAIRING_CODE。
   - Windows 把配对码粘贴到 http://127.0.0.1:8790/?v=6#pairing。
   - Windows 导入 Codex 或 Claude 会话并启动 Bridge。
   - Linux /v1/agents 可以看到在线 Agent。

3. 完善 Linux 网页：

   - 地址：http://127.0.0.1:8787/?v=7
   - 输入提示词。
   - 选择 auto / codex / claude。
   - 选择模型和推理强度。
   - 支持 exec / resume / continue。
   - 支持 session_id 和 cwd。
   - 显示 queued、waiting_for_agent、sent、acked、done 和最终 result。

4. 完善 Linux CLI：

       ./send-prompt.sh agent list

       ./send-prompt.sh --provider codex --model gpt-5.6-terra --effort high --prompt "检查项目状态" --wait

       ./send-prompt.sh --provider claude --model sonnet --effort max --prompt "总结仓库入口" --wait

5. 保持安全边界：

   - Linux Hub 不接受和执行任意 shell 命令。
   - 真正执行只能发生在 Windows 预配置的 adapter 中。
   - desktop_token 用于 WebSocket Bridge。
   - tool_token 用于 HTTP API。
   - 默认真实执行；Windows 操作者可按需显式启用 dry-run。
   - 不要把 runtime/rk3588_pairing.env 或 token 提交到源码包。

6. 运行验证：

       python3 -m compileall device tools examples
       bash -n start-linux-control-app.sh
       bash -n send-prompt.sh
       bash -n scripts/start-rk3588-pairing.sh
       curl http://127.0.0.1:8787/health

7. 做一次本地 dry-run 回环测试：

   - 启动临时 Hub。
   - 启动临时 Desktop Bridge。
   - POST /v1/turns。
   - 验证 prompt、model、reasoning_effort、session_id 和 cwd 到达 adapter。
   - 验证最终状态为 done。

## 最终输出

完成后请报告：

- 修改文件列表。
- Linux 启动命令。
- Windows 配对步骤。
- 网页和 CLI 使用方式。
- 完整测试结果。
- 尚未解决的限制和安全风险。
