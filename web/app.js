const $ = (id) => document.getElementById(id);

const hubLed = $("hubLed");
const hubState = $("hubState");
const hubMeta = $("hubMeta");
const agentList = $("agentList");
const log = $("log");
const qwenModel = $("qwenModel");
const qwenMode = $("qwenMode");
const activeTask = $("activeTask");
const latestResult = $("latestResult");
const sendBtn = $("sendBtn");
const refreshBtn = $("refreshBtn");
const objective = $("objective");
const provider = $("provider");
const mode = $("mode");
const routerLevel = $("routerLevel");
const agentEffort = $("agentEffort");
const modelInput = $("modelInput");
const cliMirror = $("cliMirror");
const targetAgent = $("targetAgent");
const sessionId = $("sessionId");
const cwdInput = $("cwdInput");

let ws;
let reconnectTimer;
let lastSnapshot = { agents: [], tasks: [], events: [] };

const demoAgents = [
  { agent_id: "codex-worker", display_name: "Codex Worker", platform: "等待 Windows Bridge", capabilities: ["codex.exec", "local.agent"], status: "offline" },
  { agent_id: "claude-worker", display_name: "Claude Code Worker", platform: "等待 Windows Bridge", capabilities: ["claude.exec", "local.agent"], status: "offline" },
  { agent_id: "local-worker", display_name: "Local Echo Worker", platform: "等待本地适配器", capabilities: ["agent.echo"], status: "offline" },
];

function connect() {
  updateCliMirror();
  if (location.protocol === "file:") {
    hubLed.classList.remove("off");
    hubState.textContent = "STATIC PREVIEW";
    hubMeta.textContent = "请打开 http://开发板IP:8787";
    renderAgents(demoAgents, true);
    addLog("preview", "静态预览模式。启动 device_hub.py 后用浏览器打开 Hub 地址。");
    return;
  }

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/gui`);

  ws.onopen = () => {
    hubLed.classList.remove("off");
    hubState.textContent = "CONNECTED";
    hubMeta.textContent = "Linux Hub 在线";
    addLog("hub.connected", "GUI WebSocket 已建立");
  };

  ws.onclose = () => {
    hubLed.classList.add("off");
    hubState.textContent = "DISCONNECTED";
    hubMeta.textContent = "正在重连...";
    addLog("hub.closed", "GUI 通道断开，准备重连");
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connect, 1200);
  };

  ws.onerror = () => {
    hubLed.classList.add("off");
    hubState.textContent = "ERROR";
  };

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    handleMessage(msg);
  };
}

function handleMessage(msg) {
  const payload = msg.payload || {};
  switch (msg.type) {
    case "snapshot":
      lastSnapshot = payload;
      renderSnapshot(payload);
      addLog("snapshot", `${(payload.agents || []).length} 个 Agent，${(payload.tasks || []).length} 个任务`);
      break;
    case "agent_connected":
    case "agent_updated":
    case "agent_disconnected":
      send({ type: "refresh", payload: {} });
      addLog(msg.type, JSON.stringify(payload, null, 2));
      break;
    case "task_created":
    case "task_sent":
    case "task_acked":
    case "task_waiting":
      addLog(msg.type, JSON.stringify(payload, null, 2));
      setActiveTask(payload.task_id || payload.task?.task_id || "");
      send({ type: "refresh", payload: {} });
      break;
    case "task_result":
      addLog(msg.type, JSON.stringify(payload, null, 2));
      renderLatestResult(payload);
      send({ type: "refresh", payload: {} });
      break;
    case "error":
      addLog("error", payload.message || "未知错误");
      latestResult.textContent = payload.message || "未知错误";
      break;
    default:
      addLog(msg.type, JSON.stringify(payload, null, 2));
  }
}

function renderSnapshot(snapshot) {
  lastSnapshot = snapshot;
  qwenModel.textContent = snapshot.qwen?.model || "Qwen/Qwen3-4B-Instruct-2507";
  qwenMode.textContent = snapshot.qwen?.mode || "heuristic-fallback";
  renderAgents(snapshot.agents || []);
  renderTaskSummary(snapshot.tasks || []);
}

function renderTaskSummary(tasks) {
  const current = [...tasks].reverse().find((task) => ["queued", "waiting_for_agent", "sent", "acked", "running"].includes(task.status));
  setActiveTask(current?.task_id || "无");
  const done = [...tasks].reverse().find((task) => task.status === "done" && task.result);
  if (done && latestResult.textContent === "等待任务结果...") {
    latestResult.textContent = JSON.stringify(done.result, null, 2);
  }
}

function setActiveTask(taskId) {
  activeTask.textContent = taskId || "无";
}

function renderAgents(agents, preview = false) {
  const shownAgents = agents.length ? agents : demoAgents;
  agentList.className = "agent-list";
  agentList.innerHTML = shownAgents.map((agent, index) => agentCard(agent, preview || !agents.length, index)).join("");

  document.querySelectorAll("[data-agent-name]").forEach((input) => {
    input.addEventListener("change", () => {
      const agentId = input.getAttribute("data-agent-name");
      const displayName = input.value.trim();
      if (!agentId || !displayName || input.disabled) return;
      send({ type: "rename_agent", payload: { agent_id: agentId, display_name: displayName } });
      addLog("agent.rename", `${agentId} -> ${displayName}`);
    });
  });

  document.querySelectorAll("[data-use-agent]").forEach((button) => {
    button.addEventListener("click", () => {
      const agentId = button.getAttribute("data-use-agent");
      if (!agentId || button.disabled) return;
      targetAgent.value = agentId;
      inferProviderFromAgent(agentId);
      updateCliMirror();
      renderAgents(lastSnapshot.agents || []);
      addLog("agent.target", `目标 Agent 设置为 ${agentId}`);
    });
  });
}

function agentCard(agent, ghost, index) {
  const status = ghost ? "offline" : agent.status || inferStatus(agent.agent_id);
  const capabilities = (agent.capabilities || []).join(" / ") || "无能力声明";
  const name = agent.display_name || localName(agent.agent_id);
  const selected = targetAgent.value.trim() === agent.agent_id;
  const providerName = detectProvider(agent);
  return `
    <div class="agent-card status-${escapeAttr(status)} provider-${escapeAttr(providerName)} persona-${index % 4} ${selected ? "selected-agent" : ""}">
      <div class="agent-avatar-wrap">
        ${pixelSprite(index, status)}
      </div>
      <div class="agent-info">
        <input class="agent-name" data-agent-name="${escapeAttr(agent.agent_id)}" value="${escapeAttr(name)}" ${ghost ? "disabled" : ""} />
        <div class="agent-status">
          <span class="status-dot"></span>
          <b>${escapeHtml(statusLabel(status))}</b>
          <em>${escapeHtml(providerName.toUpperCase())}</em>
        </div>
        <small>${escapeHtml(agent.platform || "unknown platform")}</small>
        <small>${escapeHtml(capabilities)}</small>
        ${agent.active_task_id ? `<code>${escapeHtml(agent.active_task_id)}</code>` : ""}
        <button class="mini-btn" data-use-agent="${escapeAttr(agent.agent_id)}" ${ghost ? "disabled" : ""}>使用这个 Agent</button>
      </div>
    </div>
  `;
}

function detectProvider(agent) {
  const caps = agent.capabilities || [];
  if (caps.some((cap) => String(cap).startsWith("codex."))) return "codex";
  if (caps.some((cap) => String(cap).startsWith("claude."))) return "claude";
  return "local";
}

function inferProviderFromAgent(agentId) {
  const agent = (lastSnapshot.agents || []).find((item) => item.agent_id === agentId);
  if (!agent) return;
  const nextProvider = detectProvider(agent);
  provider.value = nextProvider === "local" ? "" : nextProvider;
}

function pixelSprite(seed, status) {
  const palettes = [
    ["transparent", "#1a1230", "#ffcf9f", "#54e8ff", "#72ff8f", "#050714"],
    ["transparent", "#2b180d", "#ffc38f", "#ff4fb8", "#ffe066", "#050714"],
    ["transparent", "#101a35", "#d9a26f", "#72ff8f", "#54e8ff", "#050714"],
    ["transparent", "#291a42", "#f2b594", "#ff9f43", "#ff4fb8", "#050714"],
  ];
  const p = palettes[seed % palettes.length];
  const matrix = [
    "00111100",
    "01222210",
    "01233210",
    "00133100",
    "00333300",
    "03433430",
    "00400400",
    "05500550",
  ];
  const cells = matrix.join("").split("").map((n) => {
    const color = status === "offline" && n !== "0" ? "#5d627f" : p[Number(n)];
    return `<span style="background:${color}"></span>`;
  }).join("");
  return `<div class="pixie pixie-${escapeAttr(status)}">${cells}</div>`;
}

function inferStatus(agentId) {
  const active = (lastSnapshot.tasks || []).find((task) =>
    task.target_agent === agentId && ["sent", "acked", "running"].includes(task.status)
  );
  return active ? "working" : "idle";
}

function statusLabel(status) {
  if (status === "working") return "工作中";
  if (status === "offline") return "离线";
  return "空闲";
}

function localName(agentId) {
  const names = ["Patch Goblin", "Test Mage", "Repo Scout", "Browser Sprite", "Shell Knight", "Review Owl"];
  const score = Array.from(agentId || "agent").reduce((sum, ch) => sum + ch.charCodeAt(0), 0);
  return names[score % names.length];
}

function addLog(type, message) {
  const row = document.createElement("div");
  row.className = "log-entry";
  row.innerHTML = `<b>${escapeHtml(type)}</b> ${escapeHtml(new Date().toLocaleTimeString())}\n${escapeHtml(message)}`;
  log.prepend(row);
}

function renderLatestResult(payload) {
  latestResult.textContent = JSON.stringify(payload.result || payload, null, 2);
  setActiveTask("");
}

function send(message) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    addLog("send.failed", "Hub WebSocket 未连接");
    return false;
  }
  ws.send(JSON.stringify(message));
  return true;
}

function buildTurnOptions() {
  const options = {};
  if (mode.value) options.mode = mode.value;
  if (sessionId.value.trim()) options.session_id = sessionId.value.trim();
  if (cwdInput.value.trim()) options.cwd = cwdInput.value.trim();
  if (modelInput.value.trim()) options.model = modelInput.value.trim();
  if (agentEffort.value) options.reasoning_effort = agentEffort.value;
  return options;
}

function updateCliMirror() {
  const text = (objective.value || "...").replaceAll('"', "\\\"").slice(0, 100);
  const parts = ["pva turn send"];
  parts.push(`--level ${routerLevel.value}`);
  parts.push(provider.value ? `--provider ${provider.value}` : "--provider auto");
  parts.push(targetAgent.value.trim() ? `--agent ${targetAgent.value.trim()}` : "--agent auto");
  if (mode.value) parts.push(`--mode ${mode.value}`);
  if (modelInput.value.trim()) parts.push(`--model ${modelInput.value.trim()}`);
  if (agentEffort.value) parts.push(`--effort ${agentEffort.value}`);
  if (sessionId.value.trim()) parts.push(`--session ${sessionId.value.trim()}`);
  parts.push(`--prompt "${text}"`);
  cliMirror.textContent = parts.join(" ");
}

function submitTask() {
  updateCliMirror();
  const prompt = objective.value.trim();
  if (!prompt) {
    addLog("send.blocked", "提示词不能为空");
    return;
  }

  const payload = {
    objective: prompt,
    thinking_level: routerLevel.value,
    target_agent_id: targetAgent.value.trim(),
    provider: provider.value,
    session_id: sessionId.value.trim(),
    cwd: cwdInput.value.trim(),
    turn_options: buildTurnOptions(),
    metadata: {
      source: "linux-hub-web",
      ui_version: "v7",
    },
  };

  latestResult.textContent = "任务已发送，等待 ACK / RESULT...";
  const ok = send({ type: "submit_task", payload });
  if (ok) addLog("task.submit", JSON.stringify(payload, null, 2));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

sendBtn.addEventListener("click", submitTask);
refreshBtn.addEventListener("click", () => {
  send({ type: "refresh", payload: {} });
});

[objective, provider, mode, routerLevel, agentEffort, modelInput, targetAgent, sessionId, cwdInput]
  .forEach((element) => element.addEventListener("input", updateCliMirror));

[provider, mode, routerLevel, agentEffort]
  .forEach((element) => element.addEventListener("change", updateCliMirror));

connect();
