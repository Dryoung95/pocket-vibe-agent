const $ = (id) => document.getElementById(id);

const localLed = $("localLed");
const localState = $("localState");
const localMeta = $("localMeta");
const linuxUrl = $("linuxUrl");
const desktopToken = $("desktopToken");
const toolToken = $("toolToken");
const pairBtn = $("pairBtn");
const pairStatusBtn = $("pairStatusBtn");
const pairingStatus = $("pairingStatus");
const processList = $("processList");
const templateList = $("templateList");
const scanBtn = $("scanBtn");
const bundleBtn = $("bundleBtn");
const launchBtn = $("launchBtn");
const selectedSummary = $("selectedSummary");
const importOutput = $("importOutput");
const localLog = $("localLog");

let currentScan = { detected_processes: [], bridge_templates: [] };
let selectedIds = new Set();

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Accept": "application/json",
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  const text = await response.text();
  let data = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!response.ok) {
    throw new Error(data.detail || data.message || `HTTP ${response.status}`);
  }
  return data;
}

async function refreshScan() {
  setStatus("SCANNING", "checking local codex / claude processes", false);
  try {
    const data = await api("/api/local/scan");
    currentScan = data;
    renderPairing(data.pairing || {}, null);
    renderItems(processList, data.detected_processes || [], "process");
    renderItems(templateList, data.bridge_templates || [], "template");
    updateSelectedSummary();
    setStatus("LOCAL READY", `${data.local.hostname} // ${data.local.platform}`, false);
    addLog("scan.ok", `${(data.detected_processes || []).length} process(es), ${(data.bridge_templates || []).length} template(s)`);
  } catch (error) {
    setStatus("SCAN ERROR", error.message, true);
    addLog("scan.error", error.message);
  }
}

function renderPairing(pairing, status) {
  if (pairing.linux_hub_url && !linuxUrl.value) {
    linuxUrl.value = pairing.linux_hub_url;
  }
  const parts = [];
  if (pairing.linux_hub_url) {
    parts.push(`已保存：${pairing.label || "Linux Hub"} @ ${pairing.linux_hub_url}`);
  } else {
    parts.push("尚未保存 Linux 配对信息。");
  }
  if (pairing.desktop_token) parts.push(`desktop token: ${pairing.desktop_token}`);
  if (pairing.tool_token) parts.push(`tool token: ${pairing.tool_token}`);
  if (status) {
    parts.push(status.reachable ? "Hub 可访问" : `Hub 暂不可访问：${status.health_error || "unknown"}`);
    if (status.tool_token_ok === true) parts.push(`Tool token 有效，远端在线 agent：${(status.remote_agents || []).length}`);
    if (status.tool_token_ok === false) parts.push(`Tool token 失败：${status.tool_error || "unknown"}`);
  }
  pairingStatus.textContent = parts.join(" / ");
}

function renderItems(container, items, kind) {
  if (!items.length) {
    container.className = "agent-list empty";
    container.textContent = kind === "process"
      ? "没有扫描到正在运行的 Codex / Claude Code 进程。可以直接导入模板启动新 worker。"
      : "没有找到 bridge 模板。";
    return;
  }
  container.className = "agent-list";
  container.innerHTML = items.map((item, index) => itemCard(item, index)).join("");
  container.querySelectorAll("[data-select-agent]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) selectedIds.add(checkbox.value);
      else selectedIds.delete(checkbox.value);
      updateSelectedSummary();
    });
  });
}

function itemCard(item, index) {
  const provider = item.provider || "unknown";
  const selected = selectedIds.has(item.id);
  const agentId = defaultAgentId(item);
  const session = item.session_id || "";
  const cwd = item.cwd || "";
  const title = item.display_name || item.name || item.id;
  const detail = item.command_line || item.config_path || "";
  const badges = [
    provider.toUpperCase(),
    item.kind === "process" ? `PID ${item.pid || "-"}` : "TEMPLATE",
    item.dry_run ? "DRY-RUN" : "",
    item.session_id ? "RESUME" : "",
  ].filter(Boolean);
  const disabled = item.importable ? "" : "disabled";
  return `
    <div class="agent-card local-agent-card persona-${index % 4} ${selected ? "selected-agent" : ""}">
      <div class="agent-avatar-wrap">${pixelSprite(index, item.importable ? "idle" : "offline")}</div>
      <div class="agent-info">
        <label class="select-line">
          <input type="checkbox" data-select-agent value="${escapeHtml(item.id)}" ${selected ? "checked" : ""} ${disabled} />
          <span>${escapeHtml(title)}</span>
        </label>
        <div class="badge-row">${badges.map((badge) => `<b>${escapeHtml(badge)}</b>`).join("")}</div>
        <small>${escapeHtml(item.note || "")}</small>
        <small>${escapeHtml(detail)}</small>
        <div class="compact-fields">
          <input data-agent-id="${escapeHtml(item.id)}" value="${escapeHtml(agentId)}" placeholder="agent id" />
          <input data-session-id="${escapeHtml(item.id)}" value="${escapeHtml(session)}" placeholder="session id，可选" />
          <input data-cwd="${escapeHtml(item.id)}" value="${escapeHtml(cwd)}" placeholder="cwd，可选" />
        </div>
      </div>
    </div>
  `;
}

function updateSelectedSummary() {
  const items = allItems().filter((item) => selectedIds.has(item.id));
  if (!items.length) {
    selectedSummary.textContent = "请选择上面的 Codex / Claude 项。";
    return;
  }
  selectedSummary.innerHTML = items.map((item) => {
    const provider = (item.provider || "unknown").toUpperCase();
    return `<span class="selection-pill">${escapeHtml(provider)} / ${escapeHtml(item.display_name || item.name || item.id)}</span>`;
  }).join("");
}

function allItems() {
  return [
    ...(currentScan.detected_processes || []),
    ...(currentScan.bridge_templates || []),
  ];
}

function collectSelections() {
  return allItems()
    .filter((item) => selectedIds.has(item.id))
    .map((item) => ({
      id: item.id,
      provider: item.provider,
      agent_id: valueFor(`[data-agent-id="${cssEscape(item.id)}"]`),
      session_id: valueFor(`[data-session-id="${cssEscape(item.id)}"]`),
      cwd: valueFor(`[data-cwd="${cssEscape(item.id)}"]`),
    }));
}

function valueFor(selector) {
  const element = document.querySelector(selector);
  return element ? element.value.trim() : "";
}

async function savePairing() {
  try {
    const data = await api("/api/pair", {
      method: "POST",
      body: JSON.stringify({
        linux_hub_url: linuxUrl.value.trim(),
        desktop_token: desktopToken.value.trim(),
        tool_token: toolToken.value.trim(),
      }),
    });
    renderPairing(data.pairing || {}, data.status || null);
    desktopToken.value = "";
    toolToken.value = "";
    addLog("pair.saved", JSON.stringify(data.status || {}, null, 2));
  } catch (error) {
    addLog("pair.error", error.message);
    pairingStatus.textContent = error.message;
  }
}

async function checkPairStatus() {
  try {
    const data = await api("/api/pair/status");
    renderPairing(data.pairing || {}, data.status || null);
    addLog("pair.status", JSON.stringify(data, null, 2));
  } catch (error) {
    addLog("pair.status.error", error.message);
  }
}

async function importSelected(launch) {
  const selected = collectSelections();
  if (!selected.length) {
    importOutput.textContent = "请先选择至少一个 Codex / Claude 项。";
    return;
  }
  try {
    const data = await api("/api/import", {
      method: "POST",
      body: JSON.stringify({ selected, launch }),
    });
    const lines = [
      `导入包：${data.bundle.path}`,
      `启动脚本：${data.bundle.start_script}`,
      `agents：${data.bundle.agents.map((agent) => agent.agent_id).join(", ")}`,
    ];
    if (launch) {
      lines.push(`已启动：${(data.launched || []).map((item) => item.agent_id + (item.pid ? `#${item.pid}` : "")).join(", ")}`);
    }
    importOutput.textContent = lines.join("\n");
    addLog(launch ? "import.launch" : "import.bundle", JSON.stringify(data, null, 2));
  } catch (error) {
    importOutput.textContent = error.message;
    addLog("import.error", error.message);
  }
}

function defaultAgentId(item) {
  if (item.suggested_agent_id) return item.suggested_agent_id;
  const provider = item.provider || "agent";
  if (item.session_id) return safeId(`${provider}-${item.session_id.slice(-6)}`);
  if (item.pid) return safeId(`${provider}-${item.pid}`);
  return safeId(`${provider}-worker`);
}

function safeId(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9_.-]+/g, "-").replace(/^-+|-+$/g, "") || "agent-worker";
}

function addLog(type, message) {
  const row = document.createElement("div");
  row.className = "log-entry";
  row.innerHTML = `<b>${escapeHtml(type)}</b> ${escapeHtml(new Date().toLocaleTimeString())}\n${escapeHtml(message)}`;
  localLog.prepend(row);
}

function setStatus(state, meta, isError) {
  localState.textContent = state;
  localMeta.textContent = meta;
  localLed.classList.toggle("off", !!isError);
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
  return `<div class="pixie pixie-${escapeHtml(status)}">${cells}</div>`;
}

function cssEscape(value) {
  if (window.CSS && window.CSS.escape) return window.CSS.escape(value);
  return String(value).replace(/["\\]/g, "\\$&");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

pairBtn.addEventListener("click", savePairing);
pairStatusBtn.addEventListener("click", checkPairStatus);
scanBtn.addEventListener("click", refreshScan);
bundleBtn.addEventListener("click", () => importSelected(false));
launchBtn.addEventListener("click", () => importSelected(true));

refreshScan();
