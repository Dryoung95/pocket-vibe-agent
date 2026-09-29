const state = {
  scan: null,
  siteInfo: null,
  deferredInstallPrompt: null,
  sessionFilter: "",
};

const $ = (id) => document.getElementById(id);
const API_BASE = location.protocol === "file:" ? "http://127.0.0.1:8790" : "";
const LOCAL_BACKEND_COMMAND = "cd S:\\portable-vibe-agent-demo; .\\scripts\\start-control-panel.cmd";

const providerLabels = {
  codex: "Codex",
  claude: "Claude Code",
  local: "Local Agent",
  unknown: "Unknown",
};

function panelHeaders() {
  const key = $("panelKeyInput")?.value?.trim();
  return key ? { "X-Panel-Key": key } : {};
}

async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...panelHeaders(),
        ...(options.headers || {}),
      },
      ...options,
    });
  } catch (err) {
    if (location.protocol === "file:") {
      throw new Error(`本机后端未启动或不可访问。请在 PowerShell 运行：${LOCAL_BACKEND_COMMAND}`);
    }
    throw err;
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `${res.status} ${res.statusText}`);
  }
  return data;
}

function saveInputs() {
  const values = {
    hub: $("hubInput").value,
    panelKey: $("panelKeyInput").value,
    desktopToken: $("desktopTokenInput").value,
    toolToken: $("toolTokenInput").value,
    pairingCode: $("pairingCodeInput")?.value || "",
    provider: $("providerInput").value,
    mode: $("modeInput").value,
    agentId: $("agentIdInput").value,
    sessionId: $("sessionIdInput").value,
    cwd: $("cwdInput").value,
    permission: $("permissionInput").value,
    dryRun: $("dryRunInput").checked,
  };
  localStorage.setItem("pva-control-site", JSON.stringify(values));
}

function loadInputs() {
  const defaults = {
    hub: "http://127.0.0.1:8787",
    panelKey: "",
    desktopToken: "",
    toolToken: "",
    pairingCode: "",
    provider: "codex",
    mode: "exec",
    agentId: "",
    sessionId: "",
    cwd: "",
    permission: "",
    dryRun: false,
  };
  let values = defaults;
  try {
    values = { ...defaults, ...JSON.parse(localStorage.getItem("pva-control-site") || "{}") };
  } catch {
    values = defaults;
  }
  for (const [key, elementId] of Object.entries({
    hub: "hubInput",
    panelKey: "panelKeyInput",
    desktopToken: "desktopTokenInput",
    toolToken: "toolTokenInput",
    pairingCode: "pairingCodeInput",
    provider: "providerInput",
    mode: "modeInput",
    agentId: "agentIdInput",
    sessionId: "sessionIdInput",
    cwd: "cwdInput",
    permission: "permissionInput",
  })) {
    $(elementId).value = values[key] || "";
  }
  // Real execution is the default, including for browsers that saved the old default.
  $("dryRunInput").checked = false;
}

async function refreshSiteInfo() {
  try {
    const res = await fetch(`${API_BASE}/api/site/info`);
    const info = await res.json();
    state.siteInfo = info;
    $("siteOrigin").textContent = location.protocol === "file:" ? `${API_BASE} 后端 / file 预览` : (info.site?.origin || location.origin);
    $("hostName").textContent = info.host?.hostname || "unknown";
    if (info.panel_key_required && !$("panelKeyInput").value) {
      showToast("此网站后端已启用 Panel Key，请填写后再扫描。");
    }
  } catch {
    $("siteOrigin").textContent = location.protocol === "file:" ? "file 预览模式：后端未连接" : location.origin;
    if (location.protocol === "file:") {
      $("hostName").textContent = "请启动 127.0.0.1:8790 后端";
    }
  }
}

async function refresh() {
  saveInputs();
  $("scanTime").textContent = "扫描中...";
  try {
    const [scan, bridges] = await Promise.all([
      api("/api/scan"),
      api("/api/bridges"),
    ]);
    state.scan = scan;
    scan.managed_bridges = bridges.bridges || [];
    renderScan(scan);
    showToast("扫描完成");
  } catch (err) {
    $("scanTime").textContent = "扫描失败";
    renderBackendOffline(err);
    showToast(String(err.message || err), true);
  }
}

function renderBackendOffline(err) {
  if (location.protocol !== "file:") return;
  const message = String(err?.message || err || "");
  $("toolStatus").innerHTML = emptyState(`需要先启动本机后端：${LOCAL_BACKEND_COMMAND}`);
  $("processList").innerHTML = emptyState(message || "本机后端未启动，无法扫描系统进程。");
  $("sessionList").innerHTML = emptyState("浏览器 file:// 页面没有权限读取本机进程或会话文件，请通过后端扫描。");
  $("bridgeList").innerHTML = emptyState("后端未连接，暂不能读取已导入 Bridge。");
}

function renderScan(scan) {
  $("scanTime").textContent = formatTime(scan.time) || "刚刚";
  $("hostName").textContent = scan.host?.hostname || "unknown";
  renderTools(scan.tools || {});
  renderProcesses(scan.processes || []);
  renderSessions(scan.sessions || {});
  renderBridges(scan.managed_bridges || []);
}

function renderTools(tools) {
  $("toolStatus").innerHTML = ["codex", "claude"].map((name) => {
    const tool = tools[name] || {};
    const available = Boolean(tool.available);
    return `
      <article class="tool-card" data-provider="${escapeAttr(name)}">
        <div class="tool-icon ${available ? "ready" : ""}" data-provider="${escapeAttr(name)}">${name === "codex" ? "Cx" : "Cl"}</div>
        <div>
          <div class="row">
            <strong>${providerName(name)}</strong>
            <span class="badge ${available ? "ok" : "warn"}">${available ? "可用" : "未找到"}</span>
          </div>
          <p>${escapeHtml(tool.version || "未检测到版本")}</p>
          <code title="${escapeAttr(tool.path || "not on PATH")}">${escapeHtml(tool.path || "not on PATH")}</code>
        </div>
      </article>
    `;
  }).join("");
}

function renderProcesses(processes) {
  const filtered = processes.filter((p) => p.provider === "codex" || p.provider === "claude");
  if (!filtered.length) {
    $("processList").innerHTML = emptyState("没有发现 Codex / Claude 相关运行进程。仍可导入一个新 worker。");
    return;
  }
  $("processList").innerHTML = filtered.map((p) => `
    <button class="item process-item" data-provider="${escapeAttr(p.provider)}">
      <span>
        <strong>${providerName(p.provider)} · PID ${escapeHtml(p.pid)}</strong>
        <small>${escapeHtml(p.name)}</small>
      </span>
      <code title="${escapeAttr(p.command_line || "")}">${escapeHtml(p.command_line || "")}</code>
    </button>
  `).join("");
  document.querySelectorAll(".process-item").forEach((el) => {
    el.addEventListener("click", () => {
      const provider = el.dataset.provider || "codex";
      $("providerInput").value = provider;
      $("modeInput").value = "exec";
      $("sessionIdInput").value = "";
      $("agentIdInput").value = $("agentIdInput").value || `${provider}-worker`;
      saveInputs();
      showToast(`已选择 ${providerName(provider)} 新 worker`);
    });
  });
}

function renderSessions(sessionsByProvider) {
  const rows = [];
  for (const provider of ["codex", "claude"]) {
    for (const session of (sessionsByProvider[provider] || [])) {
      rows.push({ provider, ...session });
    }
  }
  if (!rows.length) {
    $("sessionList").innerHTML = emptyState("未发现可恢复 session 文件。可以手动填写 session id，或直接导入新 worker。");
    return;
  }
  const filter = String(state.sessionFilter || "").trim().toLowerCase();
  const filteredRows = filter
    ? rows.filter((s) => sessionSearchText(s).includes(filter))
    : rows;
  const visibleRows = filteredRows.slice(0, 36);
  $("sessionCount").textContent = filter
    ? "已匹配 " + filteredRows.length + " / " + rows.length + " 个会话"
    : "显示最近 " + visibleRows.length + " / " + rows.length + " 个会话";

  if (!visibleRows.length) {
    $("sessionList").innerHTML = emptyState("没有匹配的会话。可以试试搜索任务标题、第一句话、工作目录或短 ID。");
    return;
  }

  $("sessionList").innerHTML = visibleRows.map((s) => {
    const title = s.display_name || s.title || shortId(s.session_id);
    const preview = s.preview || s.first_user_message || "";
    const cwd = s.cwd || "";
    const meta = [
      s.modified_at || "",
      formatBytes(s.size || 0),
      cwd ? compactPath(cwd) : "",
    ].filter(Boolean).join(" · ");
    const previewHtml = preview ? '<p class="session-preview">' + escapeHtml(preview) + "</p>" : "";
    return [
      '<button class="session-card provider-' + escapeAttr(s.provider) + '" draggable="true" data-provider="' + escapeAttr(s.provider) + '" data-session="' + escapeAttr(s.session_id) + '" data-cwd="' + escapeAttr(cwd) + '" data-title="' + escapeAttr(title) + '">',
      '<span class="session-provider">' + providerName(s.provider) + "</span>",
      '<strong title="' + escapeAttr(title) + '">' + escapeHtml(title) + "</strong>",
      "<small>" + escapeHtml(meta) + "</small>",
      previewHtml,
      '<code title="' + escapeAttr(s.path || s.session_id) + '">' + escapeHtml(shortId(s.session_id)) + "</code>",
      "</button>",
    ].join("");
  }).join("");
  document.querySelectorAll(".session-card").forEach((el) => {
    el.addEventListener("click", () => {
      applySessionSelection(sessionFromCard(el));
      showToast("已填入可恢复 session");
      location.hash = "#import";
    });
    el.addEventListener("dragstart", (event) => {
      const session = sessionFromCard(el);
      event.dataTransfer.effectAllowed = "copy";
      event.dataTransfer.setData("application/json", JSON.stringify(session));
      event.dataTransfer.setData("text/plain", session.session_id);
      el.classList.add("dragging");
      $("importDropZone")?.classList.add("ready");
    });
    el.addEventListener("dragend", () => {
      el.classList.remove("dragging");
      $("importDropZone")?.classList.remove("ready", "active");
    });
  });
}

function sessionFromCard(el) {
  return {
    provider: el.dataset.provider || "codex",
    session_id: el.dataset.session || "",
    cwd: el.dataset.cwd || "",
    title: el.dataset.title || el.querySelector("strong")?.textContent || "",
  };
}

function applySessionSelection(session) {
  const provider = session.provider || "codex";
  const sessionId = session.session_id || session.sessionId || "";
  $("providerInput").value = provider;
  $("modeInput").value = "resume";
  $("sessionIdInput").value = sessionId;
  $("cwdInput").value = session.cwd || "";
  $("agentIdInput").value = makeAgentId(provider, session.title || sessionId);
  saveInputs();
}

function parseDraggedSession(event) {
  const json = event.dataTransfer?.getData("application/json");
  if (json) {
    try {
      const session = JSON.parse(json);
      if (session && (session.session_id || session.sessionId)) return session;
    } catch {
      // Fall through to plain-text session id.
    }
  }
  const sessionId = event.dataTransfer?.getData("text/plain")?.trim();
  if (!sessionId) return null;
  return {
    provider: $("providerInput").value || "codex",
    session_id: sessionId,
    title: sessionId,
    cwd: $("cwdInput").value || "",
  };
}

function canAutoImportBridge() {
  return Boolean($("hubInput").value.trim() && $("desktopTokenInput").value.trim());
}

async function importDroppedSession(session) {
  applySessionSelection(session);
  location.hash = "#import";
  $("startResult").textContent = "已填入会话，准备导入到 Linux Hub。";
  if (!canAutoImportBridge()) {
    $("startResult").textContent = "已填入会话。请先导入开发板配对码，或填写 Hub 与 Desktop Token 后再启动。";
    showToast("已填入会话，等待 Hub / Token");
    return;
  }
  showToast("已拖入会话，正在导入 Hub");
  await startBridge();
}

function setupImportDropZone() {
  const zone = $("importDropZone");
  if (!zone) return;
  const activate = (event) => {
    event.preventDefault();
    zone.classList.add("active");
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  };
  zone.addEventListener("dragenter", activate);
  zone.addEventListener("dragover", activate);
  zone.addEventListener("dragleave", (event) => {
    if (!zone.contains(event.relatedTarget)) zone.classList.remove("active");
  });
  zone.addEventListener("drop", async (event) => {
    event.preventDefault();
    zone.classList.remove("ready", "active");
    const session = parseDraggedSession(event);
    if (!session) {
      showToast("没有读到可导入的会话", true);
      return;
    }
    await importDroppedSession(session);
  });
}

function sessionSearchText(session) {
  return [
    session.provider,
    session.session_id,
    session.display_name,
    session.title,
    session.preview,
    session.first_user_message,
    session.last_user_message,
    session.cwd,
    session.path,
    session.modified_at,
  ].filter(Boolean).join(" ").toLowerCase();
}

function renderBridges(bridges) {
  if (!bridges.length) {
    $("bridgeList").innerHTML = emptyState("还没有通过本网站导入 worker。");
    return;
  }
  $("bridgeList").innerHTML = bridges.map((b) => `
    <article class="bridge-card">
      <div>
        <div class="row compact">
          <strong>${escapeHtml(b.agent_id)}</strong>
          <span class="badge ${b.running ? "ok" : "warn"}">${b.running ? "运行中" : "已退出"}</span>
        </div>
        <small>${providerName(b.provider)} · PID ${escapeHtml(String(b.pid || "-"))} · ${b.dry_run ? "dry-run" : "real-run"}</small>
        <code title="${escapeAttr(b.config_path || "")}">${escapeHtml(b.config_path || "")}</code>
      </div>
      <div class="bridge-actions">
        <button class="secondary" data-log="${escapeAttr(b.bridge_id)}">日志</button>
        <button class="danger" data-delete="${escapeAttr(b.bridge_id)}" title="停止 Bridge 并从已导入列表移除">删除</button>
      </div>
    </article>
  `).join("");
  document.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await api(`/api/bridges/${button.dataset.delete}`, { method: "DELETE" });
        showToast("已删除导入项");
        await refreshBridgesOnly();
      } catch (err) {
        showToast(String(err.message || err), true);
      }
    });
  });
  document.querySelectorAll("[data-log]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        const data = await api(`/api/bridges/${button.dataset.log}/log`);
        $("startResult").textContent = data.log || "暂无日志";
        location.hash = "#import";
      } catch (err) {
        showToast(String(err.message || err), true);
      }
    });
  });
}

async function refreshBridgesOnly() {
  const bridges = await api("/api/bridges");
  renderBridges(bridges.bridges || []);
}

async function checkHub() {
  saveInputs();
  $("hubCheck").textContent = "检测中...";
  try {
    const data = await api("/api/hub/check", {
      method: "POST",
      body: JSON.stringify({
        hub: $("hubInput").value,
        tool_token: $("toolTokenInput").value,
      }),
    });
    $("pairStatus").textContent = data.ok ? "已连接" : "待配对";
    $("pairStatus").className = `badge ${data.ok ? "ok" : "warn"}`;
    $("hubCheck").textContent = JSON.stringify(data, null, 2);
    showToast(data.ok ? "Linux Hub 检测通过" : "Hub 未完全就绪", !data.ok);
  } catch (err) {
    $("pairStatus").textContent = "检测失败";
    $("pairStatus").className = "badge warn";
    $("hubCheck").textContent = String(err.message || err);
    showToast("Hub 检测失败", true);
  }
}

function parsePairingCode(rawText) {
  const raw = String(rawText || "").trim();
  if (!raw) throw new Error("请先粘贴开发板配对码。");

  const candidates = [];
  candidates.push(raw);

  const envMatch = raw.match(/PVA_PAIRING_CODE\s*=\s*['"]?([A-Za-z0-9_-]+={0,2})['"]?/);
  if (envMatch) candidates.push(envMatch[1]);

  const urlMatch = raw.match(/pva:\/\/pair\?code=([A-Za-z0-9_-]+={0,2})/i);
  if (urlMatch) candidates.push(decodeURIComponent(urlMatch[1]));

  const jsonMatch = raw.match(/\{[\s\S]*\}/);
  if (jsonMatch) candidates.push(jsonMatch[0]);

  for (const candidate of candidates) {
    try {
      const trimmed = candidate.trim();
      const payload = trimmed.startsWith("{")
        ? JSON.parse(trimmed)
        : JSON.parse(decodeBase64UrlJson(trimmed));
      if (payload && typeof payload === "object") return normalizePairingPayload(payload);
    } catch {
      // Keep trying the next candidate.
    }
  }

  throw new Error("无法解析配对码，请确认粘贴的是 RK3588 脚本输出的 PVA_PAIRING_CODE。");
}

function decodeBase64UrlJson(value) {
  const normalized = String(value || "")
    .replace(/\s+/g, "")
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
  return decodeURIComponent(Array.from(atob(padded), (ch) => (
    `%${ch.charCodeAt(0).toString(16).padStart(2, "0")}`
  )).join(""));
}

function normalizePairingPayload(payload) {
  const hub = payload.hub || payload.hub_url || payload.linux_hub || payload.url;
  const desktopToken = payload.desktop_token || payload.desktop_bridge_token || payload.token || payload.pocket_vibe_token;
  const toolToken = payload.tool_token || payload.pocket_vibe_tool_token || "";
  if (!hub) throw new Error("配对码里缺少 Hub 地址。");
  if (!desktopToken) throw new Error("配对码里缺少 Desktop Bridge Token。");
  return {
    hub: String(hub),
    desktopToken: String(desktopToken),
    toolToken: String(toolToken || ""),
    device: payload.device || payload.hostname || "",
    createdAt: payload.created_at || payload.createdAt || "",
    version: payload.version || 1,
  };
}

async function applyPairingCode() {
  try {
    const pairing = parsePairingCode($("pairingCodeInput").value);
    $("hubInput").value = pairing.hub;
    $("desktopTokenInput").value = pairing.desktopToken;
    $("toolTokenInput").value = pairing.toolToken;
    $("pairStatus").textContent = "已导入";
    $("pairStatus").className = "badge ok";
    $("hubCheck").textContent = JSON.stringify({
      imported: true,
      hub: pairing.hub,
      device: pairing.device || undefined,
      created_at: pairing.createdAt || undefined,
      version: pairing.version,
    }, null, 2);
    saveInputs();
    showToast("配对码已应用，正在检测 Hub");
    await checkHub();
  } catch (err) {
    $("pairStatus").textContent = "导入失败";
    $("pairStatus").className = "badge warn";
    $("hubCheck").textContent = String(err.message || err);
    showToast("配对码导入失败", true);
  }
}

async function startBridge() {
  saveInputs();
  $("startResult").textContent = "启动中...";
  const provider = $("providerInput").value;
  const permissionValue = $("permissionInput").value.trim();
  const payload = {
    provider,
    hub: $("hubInput").value,
    desktop_token: $("desktopTokenInput").value,
    agent_id: $("agentIdInput").value,
    mode: $("modeInput").value,
    session_id: $("sessionIdInput").value,
    cwd: $("cwdInput").value,
    dry_run: $("dryRunInput").checked,
  };
  if (provider === "claude" && permissionValue) payload.permission_mode = permissionValue;
  if (provider === "codex" && permissionValue) payload.approval = permissionValue;
  try {
    const data = await api("/api/bridges/start", { method: "POST", body: JSON.stringify(payload) });
    $("startResult").textContent = JSON.stringify(data, null, 2);
    showToast("Bridge 已启动并导入 Hub");
    await refreshBridgesOnly();
  } catch (err) {
    $("startResult").textContent = String(err.message || err);
    showToast("Bridge 启动失败", true);
  }
}

function clearForm() {
  $("agentIdInput").value = "";
  $("sessionIdInput").value = "";
  $("cwdInput").value = "";
  $("permissionInput").value = "";
  $("dryRunInput").checked = false;
  saveInputs();
  showToast("导入表单已清空");
}

async function copyPairingPackage() {
  const payload = {
    linux_hub: $("hubInput").value,
    desktop_bridge_token: $("desktopTokenInput").value ? "<已在本机填写，不建议明文转发>" : "",
    tool_token: $("toolTokenInput").value ? "<已在本机填写，不建议明文转发>" : "",
    selected_provider: $("providerInput").value,
    selected_mode: $("modeInput").value,
    selected_session_id: $("sessionIdInput").value,
    selected_agent_id: $("agentIdInput").value,
    dry_run: $("dryRunInput").checked,
    note: "Linux 端需要启动 device/device_hub.py；本机网站会启动 Desktop Bridge 主动连入 Hub。",
  };
  await copyText(JSON.stringify(payload, null, 2));
  showToast("配对包已复制");
}

async function copyLinuxCommand() {
  const lines = ["cd /path/to/portable-vibe-agent-demo"];
  const token = $("desktopTokenInput").value.trim();
  const tool = $("toolTokenInput").value.trim();
  if (token) lines.push(`export POCKET_VIBE_TOKEN='${escapeShell(token)}'`);
  if (tool) lines.push(`export POCKET_VIBE_TOOL_TOKEN='${escapeShell(tool)}'`);
  lines.push("chmod +x scripts/start-rk3588-pairing.sh");
  lines.push("./scripts/start-rk3588-pairing.sh");
  const command = lines.join("\n");
  await copyText(command);
  showToast("Linux 启动命令已复制");
}

async function copySiteUrl() {
  const urls = state.siteInfo?.site?.lan_urls || [];
  const text = [location.origin, ...urls].filter(Boolean).join("\n");
  await copyText(text);
  showToast("网站地址已复制");
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  document.body.appendChild(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

function setupPwa() {
  if (location.protocol !== "file:" && "serviceWorker" in navigator) {
    if (["127.0.0.1", "localhost", "::1"].includes(location.hostname)) {
      navigator.serviceWorker.getRegistrations()
        .then((registrations) => registrations.forEach((registration) => registration.unregister()))
        .catch(() => {});
      if ("caches" in window) {
        caches.keys()
          .then((keys) => Promise.all(keys.map((key) => caches.delete(key))))
          .catch(() => {});
      }
    } else {
      navigator.serviceWorker.register("service-worker.js").catch(() => {});
    }
  }
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    state.deferredInstallPrompt = event;
    $("installBtn").classList.remove("hidden");
  });
  $("installBtn").addEventListener("click", async () => {
    if (!state.deferredInstallPrompt) return;
    state.deferredInstallPrompt.prompt();
    await state.deferredInstallPrompt.userChoice.catch(() => {});
    state.deferredInstallPrompt = null;
    $("installBtn").classList.add("hidden");
  });
}

function emptyState(message) {
  return `<div class="empty">${escapeHtml(message)}</div>`;
}

function providerName(provider) {
  return providerLabels[provider] || provider;
}

function showToast(message, isError = false) {
  const toast = $("toast");
  toast.textContent = message;
  toast.className = `toast show ${isError ? "error" : ""}`;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    toast.className = "toast";
  }, 2600);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[ch]);
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/\`/g, "&#96;");
}

function escapeShell(value) {
  return String(value).replace(/'/g, "'\\''");
}

function shortId(value) {
  const text = String(value || "");
  return text.length > 20 ? `${text.slice(0, 8)}…${text.slice(-8)}` : text;
}

function compactPath(value) {
  const text = String(value || "").replace(/\\\\/g, "/");
  const parts = text.split("/").filter(Boolean);
  if (parts.length <= 3) return text;
  return parts[0] + "/…/" + parts.slice(-2).join("/");
}

function makeAgentId(provider, label) {
  const normalized = String(label || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 36);
  return provider + "-" + (normalized || "session");
}

function formatBytes(value) {
  const n = Number(value) || 0;
  if (n > 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n > 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

function formatTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function wireEvents() {
  for (const id of [
    "hubInput", "panelKeyInput", "desktopTokenInput", "toolTokenInput",
    "pairingCodeInput",
    "providerInput", "modeInput", "agentIdInput", "sessionIdInput",
    "cwdInput", "permissionInput", "dryRunInput",
  ]) {
    $(id)?.addEventListener("change", saveInputs);
    $(id)?.addEventListener("input", saveInputs);
  }
  $("refreshBtn").addEventListener("click", refresh);
  $("refreshBridgeBtn").addEventListener("click", refreshBridgesOnly);
  $("applyPairingCodeBtn").addEventListener("click", applyPairingCode);
  $("checkHubBtn").addEventListener("click", checkHub);
  $("startBridgeBtn").addEventListener("click", startBridge);
  $("clearFormBtn").addEventListener("click", clearForm);
  $("copyPairingBtn").addEventListener("click", copyPairingPackage);
  $("copyLinuxCommandBtn").addEventListener("click", copyLinuxCommand);
  $("copySiteBtn").addEventListener("click", copySiteUrl);
  $("sessionSearchInput")?.addEventListener("input", (event) => {
    state.sessionFilter = event.target.value || "";
    if (state.scan) renderSessions(state.scan.sessions || {});
  });
  setupImportDropZone();
}

window.addEventListener("DOMContentLoaded", async () => {
  loadInputs();
  wireEvents();
  setupPwa();
  await refreshSiteInfo();
  await refresh();
});
