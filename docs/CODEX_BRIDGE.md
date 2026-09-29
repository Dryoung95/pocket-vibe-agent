# Codex Bridge

可以接 Codex，但建议分成两种模式。

## 推荐模式：启动新的 Codex CLI 任务

这是最稳定的方式。Pocket GUI 发任务，Desktop Bridge 调用：

```text
codex exec ...
```

启动：

```powershell
cd S:\portable-vibe-agent-demo
python device\desktop_agent.py `
  --hub ws://127.0.0.1:8787/ws/desktop `
  --token dev-token `
  --agent-id codex-worker `
  --local-agent-config configs\codex_cli.example.json
```

默认配置会真实执行 Codex。只验证链路时，在 `configs/codex_cli.example.json` 的命令末尾临时加入 `--dry-run`。

## 可选模式：resume 某个 Codex session

Codex CLI 支持：

```text
codex exec resume [SESSION_ID] -
```

因此可以把 Pocket GUI 任务投递到某个已有 Codex session。配置文件模板：

```text
configs/codex_current_thread.example.json
```

把 `REPLACE_WITH_CODEX_SESSION_OR_THREAD_ID` 换成目标 session/thread id；只验证链路时再临时加入 `--dry-run`。

## 关于“当前这个对话框”

技术上有三条路径：

1. `codex exec`：启动新的非交互 Codex 任务。推荐。
2. `codex exec resume SESSION_ID`：继续某个已存在 session。可用，但只建议目标 session 空闲时使用。
3. Codex App thread API / app-server / remote-control：更接近“控制当前对话框”，但属于更深的 app 集成层，当前 demo 不直接依赖它。

不建议让当前正在工作的这个聊天框自己通过 GUI 再给自己发消息。这会形成递归控制：当前 agent 既是操作者、又是被操作对象，状态和权限边界会混乱。

## 当前桥接安全默认值

- `--dry-run`：可选，只显示将要运行的命令。
- `--sandbox read-only`：默认只读。
- `--approval never`：非交互模式不等待人工确认。
- `--skip-git-repo-check`：允许 demo 目录这种非 git 场景跑通。

要让 Codex 真正改项目，需要你显式改配置，例如：

```json
{
  "command": [
    "python",
    "examples/codex_cli_adapter.py",
    "--mode",
    "exec",
    "--cwd",
    "S:/your-project",
    "--sandbox",
    "workspace-write",
    "--approval",
    "never"
  ]
}
```
