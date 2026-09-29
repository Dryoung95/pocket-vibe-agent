# Agent Visualization Strategy

## Goal

把 agent 从“后台黑盒任务”具象成“正在办公的像素小人”。小人不是装饰，而是一个状态机入口：名字、角色、能力、所在机器、当前任务、风险等级和审计日志都挂在这个角色上。

## Current Prototype

当前 demo 已经加入：

- `AGENT CREW`：每个 desktop agent 渲染成一个像素小人卡片。
- 命名：GUI 可直接修改小人名称，Hub 内存态保存 `display_name`。
- 状态：`offline`、`idle`、`working` 三种状态。
- 动画：working 状态头像跳动，状态灯闪烁；offline 灰化。
- CLI Mirror：GUI 输入任务时同步生成等价 CLI 命令。

## Recommended Avatar States

- `offline`：灰色小人，未连接。
- `idle`：待机小人，轻微呼吸动画。
- `thinking`：头顶气泡/齿轮，Qwen 正在路由。
- `planning`：展开蓝图，生成步骤。
- `working`：敲键盘，执行 task。
- `testing`：戴护目镜，跑测试。
- `browsing`：打开浏览器/望远镜。
- `waiting_approval`：举手，等待用户确认危险动作。
- `blocked`：红色路障，任务卡住。
- `done`：举旗/打勾。
- `failed`：冒烟/红叉，可点开日志。

## Market Map

### Coding Agent Workspaces

- Devin：有 Shell、IDE、Browser，可实时跟随和接管 agent 工作；也支持 Web、CLI、API、Slack/Teams 工作流。参考：https://docs.devin.ai/get-started/devin-intro
- OpenAI Codex：定位为 ChatGPT 中的 coding agent command center，支持多 agent/worktree/cloud environment 并行。参考：https://openai.com/codex/
- Google Jules：异步 coding agent，连接 GitHub 后自主修 bug、写文档、加功能。参考：https://jules.google/docs/
- OpenHands Agent Canvas：本地视觉工作区，可并行运行多个 coding agents，连接本地/远程/云 backend，并支持自动化。参考：https://www.openhands.dev/product/canvas

结论：这些产品让 agent 工作过程可见，但大多仍是任务、日志、IDE、diff、PR 视角；“人格化/角色化/像素小人办公现场”很少。

### Workflow Builders

- Dify Workflow Studio：视觉画布连接模型、检索、工具、代码、分支、触发器、人工审核，并支持 trace。参考：https://www.dify.ai/workflows
- Flowise：Visual Builder、Agentflow、Tracing & Analytics、API/CLI/SDK。参考：https://docs.flowiseai.com/
- AutoGen Studio：声明式创建多 agent workflow，提供聊天式运行、inner monologue、成本、turns、tool/code execution，并可从命令行启动 API endpoint。参考：https://autogenhub.github.io/autogen/docs/autogen-studio/usage/
- CrewAI AMP / Crew Studio：部署、监控 crews/agents，查看 execution traces/logs。参考：https://docs.crewai.com/enterprise/introduction

结论：画布适合“设计 agent 系统”，但不适合作为便携设备的一线操作台。我们的重点应是“调度 + 观察 + 接管 + 自动化”。

### Observability Platforms

- LangSmith：agent behavior visibility、trace、debug/eval/monitor。参考：https://www.langchain.com/langsmith-platform
- Langfuse：trace、session、timeline、agent graph、dashboard。参考：https://langfuse.com/docs
- AgentOps / Braintrust / LangGraph Studio：偏工程诊断、评估和执行树分析。

结论：trace 是专业层必需，但不能作为第一界面。我们的界面应先展示“谁在干什么”，再允许点开小人的日志、命令、trace。

### Marvis / AIOps Inspiration

- Juniper Marvis 是网络运维领域的 Virtual Network Assistant，不是 coding agent；但它把 AI 定位成“IT team 的自动化扩展”，并通过自然语言诊断网络问题。参考：https://www.juniper.net/documentation/us/en/software/mist/marvis/mist-aiops/topics/concept/marvis-vna.html
- Marvis Minis 更有启发：它是 digital experience twin，主动模拟客户端验证 DHCP、DNS、ARP、RADIUS、应用可达性，并持续监控。参考：https://www.juniper.net/documentation/us/en/software/mist/mist-aiops/topics/topic-map/marvis-minis-overview.html

结论：Marvis 的强点不是视觉，而是“虚拟成员 + 主动巡检 + 可行动建议”的产品心智。我们的像素小人可以借鉴这个心智：小人不只是任务执行者，也可以是主动巡检员。

## Differentiation

### We Should Not Be

- 另一个 Devin：纯 coding agent workspace。
- 另一个 Dify：低代码 agent workflow canvas。
- 另一个 Langfuse：工程 observability dashboard。

### We Should Be

掌上 Agent Command Deck：

- GUI：小人、状态、任务、风险、进度，降低理解门槛。
- CLI：每个操作都可复制、脚本化、远程调度。
- Hub：便携 Linux 小电脑作为 always-on router。
- Qwen：把自然语言转成结构化任务、思考等级、agent 路由。
- Trace：藏在小人详情页里，作为审计和 debug 层。

## Next UI Iterations

1. Agent Avatar Strip：顶部横排小人，显示在线/工作/卡住。
2. Avatar Detail Drawer：点小人展开当前计划、最近命令、日志、diff、风险。
3. Mission Timeline：`CREATED -> ROUTED -> SENT -> ACKED -> RUNNING -> RESULT`。
4. Slash Command Palette：`/agents`、`/status`、`/run`、`/tail`、`/approve`、`/cancel`。
5. Playbook Save：成功任务保存为 YAML/JSON，可 GUI 一键复跑或 CLI 调度。
6. Approval State：危险命令让小人举手等待确认，展示命令、影响范围和允许策略。

