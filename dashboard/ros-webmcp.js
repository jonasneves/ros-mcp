/* ros-webmcp.js — roslibjs connection + WebMCP tool registration + UI logic */

// ── State ────────────────────────────────────────────────────────────────────

const state = {
  ros: null,
  connected: false,
  url: "ws://localhost:9090",
  topics: [],
  topicTypes: {},         // topic -> type string
  nodes: [],
  services: [],
  selected: null,         // { kind: "topic"|"node"|"service", name: string }
  watching: null,         // active ROSLIB.Topic subscription for watch mode
  filter: "",             // sidebar substring filter
  publishHistory: {},     // topic -> string[] (max 10, newest first)
  continuousPublish: null,// { timer, rosTopic } | null
  pinnedTopics: {},       // topic -> { msgType, sub, lastMsg, trail[] }
  toolLog: [],            // { id, toolName, params, result, ts, durationMs }[]
  reconnect: null,        // { attempts, timer } | null
  sidebarCollapsed: { topics: false, nodes: false, services: false },
  hideSystemServices: false,
  hideSystemNodes: false,
};

let _toolLogId = 0;

// ── Helpers ──────────────────────────────────────────────────────────────────

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function callRosapi(serviceName, serviceType, request) {
  return new Promise((resolve, reject) => {
    if (!state.ros || !state.connected) {
      reject(new Error("Not connected to rosbridge"));
      return;
    }
    const svc = new ROSLIB.Service({ ros: state.ros, name: serviceName, serviceType });
    const req = new ROSLIB.ServiceRequest(request);
    svc.callService(req, resolve, reject);
  });
}

function toast(msg, kind = "default", durationMs = 3000) {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast${kind !== "default" ? " " + kind : ""}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.remove(), durationMs);
}

function cssId(str) {
  return str.replace(/[^a-zA-Z0-9_-]/g, "_");
}

// ── Auto-reconnect ────────────────────────────────────────────────────────────

const RECONNECT_MAX = 8;
const RECONNECT_BASE_MS = 1000;
const RECONNECT_CAP_MS = 30000;

function scheduleReconnect() {
  if (!state.reconnect) state.reconnect = { attempts: 0, timer: null };
  if (state.reconnect.attempts >= RECONNECT_MAX) {
    state.reconnect = null;
    toast("Max reconnect attempts reached", "error");
    document.getElementById("status-text").textContent = "Disconnected";
    return;
  }
  const delay = Math.min(RECONNECT_BASE_MS * Math.pow(2, state.reconnect.attempts), RECONNECT_CAP_MS);
  state.reconnect.attempts++;
  document.getElementById("status-text").textContent =
    `Reconnecting in ${Math.round(delay / 1000)}s… (${state.reconnect.attempts}/${RECONNECT_MAX})`;
  state.reconnect.timer = setTimeout(() => {
    if (!state.connected) connect(state.url);
  }, delay);
}

function cancelReconnect() {
  if (!state.reconnect) return;
  clearTimeout(state.reconnect.timer);
  state.reconnect = null;
}

// ── Connection ────────────────────────────────────────────────────────────────

function connect(url) {
  cancelReconnect();
  if (state.ros) {
    state.ros.close();
    state.ros = null;
  }
  stopWatching();

  state.url = url;
  const ros = new ROSLIB.Ros({ url });
  state.ros = ros;

  ros.on("connection", () => {
    cancelReconnect();
    state.connected = true;
    updateStatusDot(true, false);
    document.getElementById("status-text").textContent = url;
    refreshAll();
  });

  ros.on("error", (err) => {
    state.connected = false;
    updateStatusDot(false, true);
    document.getElementById("status-text").textContent = "Error";
    toast(`Connection error: ${err}`, "error");
  });

  ros.on("close", () => {
    state.connected = false;
    updateStatusDot(false, false);
    Object.assign(state, { topics: [], nodes: [], services: [], selected: null });
    unpinAllTopics();
    renderSidebar();
    renderMainPlaceholder();
    scheduleReconnect();
  });
}

function updateStatusDot(connected, error) {
  const dot = document.getElementById("status-dot");
  let modifier = "";
  if (connected) modifier = " connected";
  else if (error) modifier = " error";
  dot.className = "status-dot" + modifier;
}

// ── Discovery ─────────────────────────────────────────────────────────────────

async function refreshAll() {
  await Promise.all([loadTopics(), loadNodes(), loadServices()]);
  renderSidebar();
  if (!state.selected) renderMainPlaceholder();
}

async function loadTopics() {
  try {
    const res = await callRosapi("/rosapi/topics", "rosapi/Topics", {});
    state.topics = res.topics || [];
    const types = res.types || [];
    state.topicTypes = Object.fromEntries(state.topics.map((t, i) => [t, types[i] || ""]));
  } catch {
    state.topics = [];
  }
}

async function loadNodes() {
  try {
    const res = await callRosapi("/rosapi/nodes", "rosapi/Nodes", {});
    state.nodes = res.nodes || [];
  } catch {
    state.nodes = [];
  }
}

async function loadServices() {
  try {
    const res = await callRosapi("/rosapi/services", "rosapi/Services", {});
    state.services = res.services || [];
  } catch {
    state.services = [];
  }
}

// ── Sidebar rendering ─────────────────────────────────────────────────────────

function isSystemNode(name) {
  return name.startsWith("/rosapi") ||
    name.startsWith("/rosbridge") ||
    name.startsWith("/_");
}

const SYSTEM_SERVICE_SUFFIXES = [
  "/describe_parameters",
  "/get_parameter_types",
  "/get_parameters",
  "/list_parameters",
  "/set_parameters",
  "/set_parameters_atomically",
];

function isSystemService(name) {
  return name.startsWith("/rosapi/") ||
    name.startsWith("/rosbridge_websocket/") ||
    SYSTEM_SERVICE_SUFFIXES.some(s => name.endsWith(s));
}

function renderMainPlaceholder() {
  const main = document.getElementById("main-panel");
  if (!state.connected) {
    main.innerHTML = `<div class="panel-placeholder" id="panel-placeholder"><div>Connect to rosbridge to get started.</div></div>`;
    return;
  }
  const nodeCount = state.hideSystemNodes
    ? state.nodes.filter(n => !isSystemNode(n)).length
    : state.nodes.length;
  const svcCount = state.hideSystemServices
    ? state.services.filter(s => !isSystemService(s)).length
    : state.services.length;
  main.innerHTML = `
    <div class="conn-summary">
      <div class="conn-summary-title">Connected</div>
      <div class="conn-url">${escHtml(state.url)}</div>
      <div class="conn-stats">
        <div class="conn-stat">
          <span class="conn-stat-value">${state.topics.length}</span>
          <span class="conn-stat-label">Topics</span>
        </div>
        <div class="conn-stat">
          <span class="conn-stat-value">${nodeCount}</span>
          <span class="conn-stat-label">Nodes</span>
        </div>
        <div class="conn-stat">
          <span class="conn-stat-value">${svcCount}</span>
          <span class="conn-stat-label">Services</span>
        </div>
      </div>
      <div class="conn-hint">← select a topic, node, or service to inspect</div>
    </div>
  `;
}

function renderSidebar() {
  renderList("topics-list", state.topics, "topic");
  renderList("nodes-list", state.nodes, "node");
  renderList("services-list", state.services, "service");
  for (const section of ["topics", "nodes", "services"]) {
    const listEl = document.getElementById(`${section}-list`);
    const btn = document.getElementById(`section-toggle-${section}`);
    const chevron = btn?.parentElement?.querySelector(".sidebar-heading-chevron");
    if (listEl) listEl.hidden = state.sidebarCollapsed[section];
    if (btn) btn.setAttribute("aria-expanded", String(!state.sidebarCollapsed[section]));
    if (chevron) chevron.classList.toggle("collapsed", state.sidebarCollapsed[section]);
  }
}

function renderList(containerId, items, kind) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";

  let filtered = state.filter
    ? items.filter(n => n.toLowerCase().includes(state.filter.toLowerCase()))
    : items;

  if (kind === "node" && state.hideSystemNodes) {
    filtered = filtered.filter(n => !isSystemNode(n));
  }
  if (kind === "service" && state.hideSystemServices) {
    filtered = filtered.filter(n => !isSystemService(n));
  }

  if (!filtered.length) {
    if (!state.connected) return;
    const el = document.createElement("div");
    el.className = "sidebar-empty";
    el.textContent = state.filter ? "No matches" : "None found";
    container.appendChild(el);
    return;
  }

  filtered.forEach(name => {
    const isActive = state.selected?.kind === kind && state.selected?.name === name;
    const btn = document.createElement("button");
    btn.className = "sidebar-item" + (isActive ? " active" : "");
    btn.textContent = name;
    btn.title = name;
    btn.addEventListener("click", () => selectEntity(kind, name));

    if (kind === "topic") {
      const row = document.createElement("div");
      row.className = "sidebar-item-row";

      const pinBtn = document.createElement("button");
      const isPinned = !!state.pinnedTopics[name];
      pinBtn.className = "pin-btn" + (isPinned ? " pinned" : "");
      pinBtn.title = isPinned ? "Unpin" : "Pin to watch strip";
      pinBtn.setAttribute("aria-pressed", String(isPinned));
      pinBtn.textContent = "⊕";
      pinBtn.addEventListener("click", (e) => { e.stopPropagation(); togglePin(name); });

      row.appendChild(btn);
      row.appendChild(pinBtn);
      container.appendChild(row);
    } else {
      container.appendChild(btn);
    }
  });
}

// ── Entity selection ──────────────────────────────────────────────────────────

const PANEL_RENDERERS = {
  topic: renderTopicPanel,
  node: renderNodePanel,
  service: renderServicePanel,
};

function selectEntity(kind, name) {
  stopWatching();
  stopContinuousPublish();
  state.selected = { kind, name };
  renderSidebar();
  PANEL_RENDERERS[kind]?.(name);
}

// ── Topic panel ────────────────────────────────────────────────────────────────

function renderTopicPanel(topic) {
  const msgType = state.topicTypes[topic] || "unknown";
  const main = document.getElementById("main-panel");

  main.innerHTML = `
    <div class="detail-header">
      <div class="detail-title">${escHtml(topic)}</div>
      <div class="detail-type">${escHtml(msgType)}</div>
    </div>

    <div>
      <div class="section-label">Last message</div>
      <div class="data-card empty" id="last-msg">No data yet</div>
    </div>

    <div class="controls-row">
      <button class="btn btn-sm" id="btn-subscribe-once">Subscribe once</button>
      <button class="btn btn-sm" id="btn-watch">Watch</button>
      <button class="btn btn-sm" id="btn-stop-watch" style="display:none">Stop</button>
      <span class="watch-indicator" id="watch-indicator" style="display:none">
        <span class="watch-dot"></span> Watching
      </span>
    </div>

    <div class="divider-label">Publish</div>

    <div class="input-group" id="publish-history-group" style="display:none">
      <label class="input-label" for="publish-history">History</label>
      <select class="input-field" id="publish-history"></select>
    </div>

    <div class="input-group">
      <label class="input-label" for="publish-msg">Message (JSON) <span style="color:var(--text-muted);font-weight:400">— ⌘↵ to send</span></label>
      <textarea class="textarea-field" id="publish-msg" rows="3" placeholder='{}'></textarea>
    </div>

    <div class="controls-row">
      <button class="btn btn-primary btn-sm" id="btn-publish">Publish</button>
    </div>

    <div class="controls-row repeat-row">
      <label class="repeat-label">
        <input type="checkbox" class="repeat-check" id="repeat-checkbox">
        Repeat at
      </label>
      <input type="number" class="input-field hz-input" id="repeat-hz" value="1" min="0.1" max="100" step="0.1">
      <span class="repeat-unit">Hz</span>
    </div>
  `;

  document.getElementById("btn-subscribe-once").addEventListener("click", () =>
    doSubscribeOnce(topic, msgType)
  );
  document.getElementById("btn-watch").addEventListener("click", () =>
    startWatching(topic, msgType)
  );
  document.getElementById("btn-stop-watch").addEventListener("click", stopWatching);
  document.getElementById("btn-publish").addEventListener("click", () =>
    doPublish(topic, msgType)
  );

  // Cmd/Ctrl+Enter to publish
  document.getElementById("publish-msg").addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      doPublish(topic, msgType);
    }
  });

  // History select
  document.getElementById("publish-history").addEventListener("change", (e) => {
    if (e.target.value) {
      document.getElementById("publish-msg").value = e.target.value;
      e.target.value = "";
    }
  });
  renderPublishHistory(topic);

  // Continuous publish
  document.getElementById("repeat-checkbox").addEventListener("change", (e) => {
    if (e.target.checked) {
      const hz = parseFloat(document.getElementById("repeat-hz").value) || 1;
      startContinuousPublish(topic, msgType, hz);
    } else {
      stopContinuousPublish();
    }
  });
  document.getElementById("repeat-hz").addEventListener("change", () => {
    if (document.getElementById("repeat-checkbox")?.checked) {
      const hz = parseFloat(document.getElementById("repeat-hz").value) || 1;
      startContinuousPublish(topic, msgType, hz);
    }
  });

  attachJsonFormatter("publish-msg");
}

// ── Publish history ───────────────────────────────────────────────────────────

function pushPublishHistory(topic, jsonStr) {
  if (!state.publishHistory[topic]) state.publishHistory[topic] = [];
  const hist = state.publishHistory[topic];
  const existing = hist.indexOf(jsonStr);
  if (existing !== -1) hist.splice(existing, 1);
  hist.unshift(jsonStr);
  if (hist.length > 10) hist.pop();
}

function renderPublishHistory(topic) {
  const sel = document.getElementById("publish-history");
  const group = document.getElementById("publish-history-group");
  if (!sel || !group) return;
  const hist = state.publishHistory[topic] || [];
  group.style.display = hist.length ? "" : "none";
  sel.innerHTML = `<option value="">— History —</option>`;
  hist.forEach(entry => {
    const opt = document.createElement("option");
    opt.value = entry;
    const label = entry.replace(/\s+/g, " ");
    opt.textContent = label.length > 50 ? label.slice(0, 50) + "…" : label;
    sel.appendChild(opt);
  });
}

// ── Continuous publish ────────────────────────────────────────────────────────

function startContinuousPublish(topic, msgType, hz) {
  stopContinuousPublish();
  let lastValidMsg = {};
  try {
    lastValidMsg = JSON.parse(document.getElementById("publish-msg")?.value || "{}");
  } catch {
    toast("Invalid JSON for continuous publish", "error");
    const cb = document.getElementById("repeat-checkbox");
    if (cb) cb.checked = false;
    return;
  }
  const rosTopic = new ROSLIB.Topic({ ros: state.ros, name: topic, messageType: msgType });
  rosTopic.advertise();
  const interval = Math.max(50, Math.round(1000 / hz));
  const timer = setInterval(() => {
    try {
      lastValidMsg = JSON.parse(document.getElementById("publish-msg")?.value || "{}");
    } catch { /* keep last valid */ }
    rosTopic.publish(new ROSLIB.Message(lastValidMsg));
  }, interval);
  state.continuousPublish = { timer, rosTopic };
}

function stopContinuousPublish() {
  if (!state.continuousPublish) return;
  clearInterval(state.continuousPublish.timer);
  state.continuousPublish.rosTopic.unadvertise();
  state.continuousPublish = null;
  const cb = document.getElementById("repeat-checkbox");
  if (cb) cb.checked = false;
}

// ── Subscribe / watch ─────────────────────────────────────────────────────────

async function doSubscribeOnce(topic, msgType) {
  const btn = document.getElementById("btn-subscribe-once");
  btn.disabled = true;
  btn.textContent = "Waiting…";
  try {
    const msg = await subscribeOnce(topic, msgType, 5000);
    showMsgCard(msg);
    toast("Message received", "ok");
  } catch (err) {
    toast(String(err), "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Subscribe once"; }
  }
}

function startWatching(topic, msgType) {
  stopWatching();
  const rosTopic = new ROSLIB.Topic({ ros: state.ros, name: topic, messageType: msgType });
  rosTopic.subscribe(msg => showMsgCard(msg));
  state.watching = rosTopic;

  const btnWatch = document.getElementById("btn-watch");
  const btnStop = document.getElementById("btn-stop-watch");
  const indicator = document.getElementById("watch-indicator");
  if (btnWatch) btnWatch.style.display = "none";
  if (btnStop) btnStop.style.display = "";
  if (indicator) indicator.style.display = "";
}

function stopWatching() {
  stopContinuousPublish();
  if (state.watching) {
    state.watching.unsubscribe();
    state.watching = null;
  }
  const btnWatch = document.getElementById("btn-watch");
  const btnStop = document.getElementById("btn-stop-watch");
  const indicator = document.getElementById("watch-indicator");
  if (btnWatch) btnWatch.style.display = "";
  if (btnStop) btnStop.style.display = "none";
  if (indicator) indicator.style.display = "none";
}

function showMsgCard(msg) {
  const card = document.getElementById("last-msg");
  if (!card) return;
  card.className = "data-card";
  card.textContent = JSON.stringify(msg, null, 2);
}

async function doPublish(topic, msgType) {
  const textarea = document.getElementById("publish-msg");
  let msg;
  try {
    msg = JSON.parse(textarea.value || "{}");
  } catch {
    toast("Invalid JSON", "error");
    return;
  }
  pushPublishHistory(topic, JSON.stringify(msg, null, 2));
  renderPublishHistory(topic);

  const rosTopic = new ROSLIB.Topic({ ros: state.ros, name: topic, messageType: msgType });
  rosTopic.advertise();
  rosTopic.publish(new ROSLIB.Message(msg));
  await sleep(100);
  rosTopic.unadvertise();
  toast("Published", "ok");
}

// ── Pinned topics ─────────────────────────────────────────────────────────────

function togglePin(topic) {
  if (state.pinnedTopics[topic]) unpinTopic(topic);
  else pinTopic(topic);
}

function pinTopic(topic) {
  if (state.pinnedTopics[topic] || !state.ros || !state.connected) return;
  const msgType = state.topicTypes[topic] || "";
  const sub = new ROSLIB.Topic({ ros: state.ros, name: topic, messageType: msgType });
  const entry = { msgType, sub, lastMsg: null, trail: [] };
  state.pinnedTopics[topic] = entry;

  sub.subscribe(msg => {
    entry.lastMsg = msg;
    const pos = extractPosition(msg);
    if (pos) {
      entry.trail.push(pos);
      if (entry.trail.length > 100) entry.trail.shift();
    }
    updateWatchCard(topic);
  });

  renderPinnedRow();
  renderSidebar();
}

function unpinTopic(topic) {
  const entry = state.pinnedTopics[topic];
  if (!entry) return;
  entry.sub.unsubscribe();
  delete state.pinnedTopics[topic];
  renderPinnedRow();
  renderSidebar();
}

function unpinAllTopics() {
  for (const entry of Object.values(state.pinnedTopics)) {
    entry.sub.unsubscribe();
  }
  state.pinnedTopics = {};
  renderPinnedRow();
}

function renderPinnedRow() {
  const row = document.getElementById("pinned-row");
  const pinned = Object.entries(state.pinnedTopics);
  row.hidden = !pinned.length;
  row.innerHTML = "";

  pinned.forEach(([topic, entry]) => {
    const isPose = isPoseTopic(entry.msgType);
    const card = document.createElement("div");
    card.className = "watch-card";
    card.id = `watch-card-${cssId(topic)}`;

    card.innerHTML = `
      <div class="watch-card-header">
        <span class="watch-card-name" title="${escHtml(topic)}">${escHtml(topic)}</span>
        <button class="watch-card-unpin" aria-label="Unpin ${escHtml(topic)}">✕</button>
      </div>
      ${isPose
        ? `<canvas class="pose-canvas" id="pose-canvas-${cssId(topic)}" width="180" height="160" aria-label="Pose visualization for ${escHtml(topic)}"></canvas>`
        : `<div class="watch-card-msg" id="watch-msg-${cssId(topic)}">${entry.lastMsg ? escHtml(JSON.stringify(entry.lastMsg, null, 2)) : "Waiting…"}</div>`
      }
    `;

    card.querySelector(".watch-card-unpin").addEventListener("click", () => unpinTopic(topic));
    row.appendChild(card);

    if (isPose && entry.lastMsg) renderPoseCanvas(topic);
  });
}

function updateWatchCard(topic) {
  const entry = state.pinnedTopics[topic];
  if (!entry) return;
  if (isPoseTopic(entry.msgType)) {
    renderPoseCanvas(topic);
  } else {
    const el = document.getElementById(`watch-msg-${cssId(topic)}`);
    if (el && entry.lastMsg) el.textContent = JSON.stringify(entry.lastMsg, null, 2);
  }
}

function isPoseTopic(msgType) {
  return msgType.toLowerCase().includes("pose");
}

// ── Pose visualizer ───────────────────────────────────────────────────────────

function extractPosition(msg) {
  if (msg.pose?.pose?.position) {
    return { x: msg.pose.pose.position.x, y: msg.pose.pose.position.y, theta: yawFromQuaternion(msg.pose.pose.orientation) };
  }
  if (msg.pose?.position) {
    return { x: msg.pose.position.x, y: msg.pose.position.y, theta: yawFromQuaternion(msg.pose.orientation) };
  }
  if (msg.position) {
    return { x: msg.position.x, y: msg.position.y, theta: yawFromQuaternion(msg.orientation) };
  }
  if (typeof msg.x === "number" && typeof msg.y === "number") {
    return { x: msg.x, y: msg.y, theta: msg.theta ?? 0 };
  }
  return null;
}

function yawFromQuaternion(q) {
  if (!q) return 0;
  const siny = 2 * (q.w * q.z + q.x * q.y);
  const cosy = 1 - 2 * (q.y * q.y + q.z * q.z);
  return Math.atan2(siny, cosy);
}

function renderPoseCanvas(topic) {
  const entry = state.pinnedTopics[topic];
  if (!entry) return;
  const canvas = document.getElementById(`pose-canvas-${cssId(topic)}`);
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;

  const s = getComputedStyle(document.documentElement);
  const cBorder  = s.getPropertyValue("--border").trim();
  const cAccent  = s.getPropertyValue("--accent").trim();
  const cMuted   = s.getPropertyValue("--text-muted").trim();
  const cDanger  = s.getPropertyValue("--danger").trim();
  const cSurface = s.getPropertyValue("--surface").trim();

  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = cSurface;
  ctx.fillRect(0, 0, W, H);

  const pos = extractPosition(entry.lastMsg);
  const allPts = pos ? [...entry.trail, pos] : entry.trail;
  if (!allPts.length) return;

  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  allPts.forEach(p => {
    minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
  });

  const pad = Math.max(maxX - minX, maxY - minY, 0.5) * 0.2;
  const wx0 = minX - pad, wx1 = maxX + pad;
  const wy0 = minY - pad, wy1 = maxY + pad;

  const toC = (wx, wy) => ({
    x: ((wx - wx0) / (wx1 - wx0)) * W,
    y: H - ((wy - wy0) / (wy1 - wy0)) * H,
  });

  // Grid
  ctx.strokeStyle = cBorder;
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 5; i++) {
    const f = i / 5;
    const cx = toC(wx0 + (wx1 - wx0) * f, wy0).x;
    const cy = toC(wx0, wy0 + (wy1 - wy0) * f).y;
    ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, H); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(W, cy); ctx.stroke();
  }

  // Trail
  if (entry.trail.length > 1) {
    for (let i = 1; i < entry.trail.length; i++) {
      ctx.globalAlpha = 0.3 + 0.7 * (i / entry.trail.length);
      ctx.strokeStyle = cMuted;
      ctx.lineWidth = 1.5;
      const a = toC(entry.trail[i - 1].x, entry.trail[i - 1].y);
      const b = toC(entry.trail[i].x, entry.trail[i].y);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    ctx.globalAlpha = 1;
  }

  // Current position
  if (pos) {
    const cp = toC(pos.x, pos.y);
    const theta = pos.theta ?? 0;
    const arrowLen = 14;
    const headLen = 5;
    const headAngle = 0.45;

    ctx.strokeStyle = cAccent;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cp.x, cp.y);
    ctx.lineTo(cp.x + Math.cos(theta) * arrowLen, cp.y - Math.sin(theta) * arrowLen);
    ctx.stroke();

    const tipX = cp.x + Math.cos(theta) * arrowLen;
    const tipY = cp.y - Math.sin(theta) * arrowLen;
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(cp.x + Math.cos(theta - headAngle) * (arrowLen - headLen), cp.y - Math.sin(theta - headAngle) * (arrowLen - headLen));
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(cp.x + Math.cos(theta + headAngle) * (arrowLen - headLen), cp.y - Math.sin(theta + headAngle) * (arrowLen - headLen));
    ctx.stroke();

    ctx.fillStyle = cDanger;
    ctx.beginPath();
    ctx.arc(cp.x, cp.y, 4, 0, Math.PI * 2);
    ctx.fill();
  }
}

// ── Node panel ────────────────────────────────────────────────────────────────

async function renderNodePanel(node) {
  const main = document.getElementById("main-panel");
  main.innerHTML = `
    <div class="detail-header">
      <div class="detail-title">${escHtml(node)}</div>
      <div class="detail-type">Node</div>
    </div>
    <div class="section-label">Loading details…</div>
  `;

  try {
    const res = await callRosapi("/rosapi/node_details", "rosapi/NodeDetails", { node });
    const { publishing = [], subscribing = [], services = [] } = res;
    main.innerHTML = `
      <div class="detail-header">
        <div class="detail-title">${escHtml(node)}</div>
        <div class="detail-type">Node</div>
      </div>
      <div>
        <div class="section-label">Publishes</div>
        ${chipList(publishing)}
      </div>
      <div>
        <div class="section-label">Subscribes</div>
        ${chipList(subscribing)}
      </div>
      <div>
        <div class="section-label">Services</div>
        ${chipList(services)}
      </div>
    `;
  } catch (err) {
    main.innerHTML += `<div class="banner banner-error">Failed to load node details: ${escHtml(String(err))}</div>`;
  }
}

// ── Service panel ──────────────────────────────────────────────────────────────

async function renderServicePanel(service) {
  const main = document.getElementById("main-panel");
  main.innerHTML = `
    <div class="detail-header">
      <div class="detail-title">${escHtml(service)}</div>
      <div class="detail-type">Service</div>
    </div>
    <div class="section-label">Loading type…</div>
  `;

  let svcType = "unknown";
  try {
    const res = await callRosapi("/rosapi/service_type", "rosapi/ServiceType", { service });
    svcType = res.type || "unknown";
  } catch { /* leave as unknown */ }

  main.innerHTML = `
    <div class="detail-header">
      <div class="detail-title">${escHtml(service)}</div>
      <div class="detail-type">${escHtml(svcType)}</div>
    </div>

    <div class="divider-label">Call service</div>

    <div class="input-group">
      <label class="input-label" for="svc-type-input">Service type</label>
      <input class="input-field" id="svc-type-input" type="text" value="${escHtml(svcType)}" spellcheck="false">
    </div>
    <div class="input-group">
      <label class="input-label" for="svc-request">Request (JSON)</label>
      <textarea class="textarea-field" id="svc-request" rows="4" placeholder='{}'></textarea>
    </div>
    <div class="controls-row">
      <button class="btn btn-primary btn-sm" id="btn-call-svc">Call</button>
    </div>

    <div id="svc-response-section" style="display:none">
      <div class="section-label">Response</div>
      <div class="data-card" id="svc-response"></div>
    </div>
  `;

  attachJsonFormatter("svc-request");

  document.getElementById("btn-call-svc").addEventListener("click", async () => {
    const type = document.getElementById("svc-type-input").value.trim();
    let req;
    try {
      req = JSON.parse(document.getElementById("svc-request").value || "{}");
    } catch {
      toast("Invalid JSON", "error");
      return;
    }
    const btn = document.getElementById("btn-call-svc");
    btn.disabled = true; btn.textContent = "Calling…";
    try {
      const result = await callRosapi(service, type, req);
      const section = document.getElementById("svc-response-section");
      const card = document.getElementById("svc-response");
      section.style.display = "";
      card.textContent = JSON.stringify(result, null, 2);
      toast("Service called", "ok");
    } catch (err) {
      toast(`Service error: ${err}`, "error");
    } finally {
      btn.disabled = false; btn.textContent = "Call";
    }
  });
}

// ── Core ROS tool implementations ─────────────────────────────────────────────

function subscribeOnce(topic, msgType, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    if (!state.ros || !state.connected) { reject(new Error("Not connected")); return; }
    const rosTopic = new ROSLIB.Topic({ ros: state.ros, name: topic, messageType: msgType });
    const timer = setTimeout(() => {
      rosTopic.unsubscribe();
      reject(new Error(`Timeout waiting for message on ${topic}`));
    }, timeoutMs);
    rosTopic.subscribe(msg => {
      clearTimeout(timer);
      rosTopic.unsubscribe();
      resolve(msg);
    });
  });
}

async function subscribeForDuration(topic, msgType, durationSec, maxMessages = 100) {
  if (!state.ros || !state.connected) throw new Error("Not connected");
  const collected = [];
  const rosTopic = new ROSLIB.Topic({ ros: state.ros, name: topic, messageType: msgType });
  await new Promise(resolve => {
    rosTopic.subscribe(msg => {
      collected.push(msg);
      if (collected.length >= maxMessages) { rosTopic.unsubscribe(); resolve(); }
    });
    setTimeout(() => { rosTopic.unsubscribe(); resolve(); }, durationSec * 1000);
  });
  return collected;
}

async function publishForDurations(topic, msgType, messages, durations) {
  if (!state.ros || !state.connected) throw new Error("Not connected");
  const rosTopic = new ROSLIB.Topic({ ros: state.ros, name: topic, messageType: msgType });
  rosTopic.advertise();
  for (let i = 0; i < messages.length; i++) {
    rosTopic.publish(new ROSLIB.Message(messages[i]));
    await sleep((durations[i] || 0) * 1000);
  }
  rosTopic.unadvertise();
}

async function getTopicDetails(topic) {
  const [typeRes, pubRes, subRes] = await Promise.all([
    callRosapi("/rosapi/topic_type", "rosapi/TopicType", { topic }),
    callRosapi("/rosapi/publishers", "rosapi/Publishers", { topic }),
    callRosapi("/rosapi/subscribers", "rosapi/Subscribers", { topic }),
  ]);
  return {
    topic,
    type: typeRes.type,
    publishers: pubRes.publishers || [],
    subscribers: subRes.subscribers || [],
  };
}

async function getServiceDetails(service) {
  const [typeRes, nodesRes] = await Promise.all([
    callRosapi("/rosapi/service_type", "rosapi/ServiceType", { service }),
    callRosapi("/rosapi/service_node", "rosapi/ServiceNode", { service }).catch(() => ({ node: "" })),
  ]);
  return { service, type: typeRes.type, node: nodesRes.node };
}

async function getNodeDetails(node) {
  const res = await callRosapi("/rosapi/node_details", "rosapi/NodeDetails", { node });
  return {
    node,
    publishing: res.publishing || [],
    subscribing: res.subscribing || [],
    services: res.services || [],
  };
}

// ── WebMCP tool registration ───────────────────────────────────────────────────

const TOOLS = [
  {
    name: "connect_to_robot",
    description: "Set the rosbridge WebSocket URL and reconnect.",
    parameters: {
      type: "object",
      properties: {
        ip:   { type: "string", description: "rosbridge host IP or hostname", default: "127.0.0.1" },
        port: { type: "number", description: "rosbridge port", default: 9090 },
      },
      required: ["ip", "port"],
    },
    handler: async ({ ip, port }) => {
      const url = `ws://${ip}:${port}`;
      document.getElementById("url-input").value = url;
      connect(url);
      return { status: "connecting", url };
    },
  },
  {
    name: "get_topics",
    description: "List all ROS topics.",
    parameters: { type: "object", properties: {} },
    handler: async () => {
      await loadTopics();
      renderSidebar();
      return { topics: state.topics, types: state.topics.map(t => state.topicTypes[t] || "") };
    },
  },
  {
    name: "get_topic_type",
    description: "Get the message type for a ROS topic.",
    parameters: {
      type: "object",
      properties: { topic: { type: "string", description: "Full topic name, e.g. /turtle1/cmd_vel" } },
      required: ["topic"],
    },
    handler: async ({ topic }) => {
      const res = await callRosapi("/rosapi/topic_type", "rosapi/TopicType", { topic });
      return { topic, type: res.type };
    },
  },
  {
    name: "get_topic_details",
    description: "Get publishers, subscribers, and type for a topic.",
    parameters: {
      type: "object",
      properties: { topic: { type: "string" } },
      required: ["topic"],
    },
    handler: async ({ topic }) => getTopicDetails(topic),
  },
  {
    name: "subscribe_once",
    description: "Subscribe to a topic and return the first message received.",
    parameters: {
      type: "object",
      properties: {
        topic:    { type: "string" },
        msg_type: { type: "string", description: "ROS message type, e.g. turtlesim/msg/Pose" },
        timeout:  { type: "number", description: "Timeout in seconds (default 5)", default: 5 },
      },
      required: ["topic", "msg_type"],
    },
    handler: async ({ topic, msg_type, timeout = 5 }) => {
      const msg = await subscribeOnce(topic, msg_type, timeout * 1000);
      if (state.selected?.kind === "topic" && state.selected?.name === topic) showMsgCard(msg);
      return msg;
    },
  },
  {
    name: "subscribe_for_duration",
    description: "Subscribe to a topic and collect messages for a given duration.",
    parameters: {
      type: "object",
      properties: {
        topic:        { type: "string" },
        msg_type:     { type: "string" },
        duration:     { type: "number", description: "Duration in seconds" },
        max_messages: { type: "number", description: "Stop after this many messages", default: 100 },
      },
      required: ["topic", "msg_type", "duration"],
    },
    handler: async ({ topic, msg_type, duration, max_messages = 100 }) =>
      subscribeForDuration(topic, msg_type, duration, max_messages),
  },
  {
    name: "publish_once",
    description: "Publish a single message to a topic.",
    parameters: {
      type: "object",
      properties: {
        topic:    { type: "string" },
        msg_type: { type: "string" },
        msg:      { type: "object", description: "Message payload as JSON object" },
      },
      required: ["topic", "msg_type", "msg"],
    },
    handler: async ({ topic, msg_type, msg }) => {
      const rosTopic = new ROSLIB.Topic({ ros: state.ros, name: topic, messageType: msg_type });
      rosTopic.advertise();
      rosTopic.publish(new ROSLIB.Message(msg));
      await sleep(100);
      rosTopic.unadvertise();
      return { published: true, topic, msg };
    },
  },
  {
    name: "publish_for_durations",
    description: "Publish a sequence of messages with delays between each.",
    parameters: {
      type: "object",
      properties: {
        topic:     { type: "string" },
        msg_type:  { type: "string" },
        messages:  { type: "array", items: { type: "object" }, description: "Array of message payloads" },
        durations: { type: "array", items: { type: "number" }, description: "Delay in seconds after each message" },
      },
      required: ["topic", "msg_type", "messages", "durations"],
    },
    handler: async ({ topic, msg_type, messages, durations }) => {
      await publishForDurations(topic, msg_type, messages, durations);
      return { published: messages.length, topic };
    },
  },
  {
    name: "get_services",
    description: "List all available ROS services.",
    parameters: { type: "object", properties: {} },
    handler: async () => {
      await loadServices();
      renderSidebar();
      return { services: state.services };
    },
  },
  {
    name: "get_service_details",
    description: "Get the request/response type and provider node for a service.",
    parameters: {
      type: "object",
      properties: { service: { type: "string" } },
      required: ["service"],
    },
    handler: async ({ service }) => getServiceDetails(service),
  },
  {
    name: "call_service",
    description: "Call a ROS service with a request payload.",
    parameters: {
      type: "object",
      properties: {
        service_name: { type: "string" },
        service_type: { type: "string" },
        request:      { type: "object", description: "Request payload as JSON object" },
      },
      required: ["service_name", "service_type", "request"],
    },
    handler: async ({ service_name, service_type, request }) =>
      callRosapi(service_name, service_type, request),
  },
  {
    name: "get_nodes",
    description: "List all running ROS nodes.",
    parameters: { type: "object", properties: {} },
    handler: async () => {
      await loadNodes();
      renderSidebar();
      return { nodes: state.nodes };
    },
  },
  {
    name: "get_node_details",
    description: "Get publishers, subscribers, and services for a node.",
    parameters: {
      type: "object",
      properties: { node: { type: "string" } },
      required: ["node"],
    },
    handler: async ({ node }) => getNodeDetails(node),
  },
];

let _webmcpActive = false;

function registerWebMCPTools() {
  const badge = document.getElementById("webmcp-badge");

  if (!navigator.modelContext) {
    badge.className = "webmcp-badge";
    badge.textContent = "WebMCP · inactive";
    console.info("[WebMCP] navigator.modelContext not available — tools not registered");
    return;
  }

  let registered = 0;
  let lastError = null;
  for (const tool of TOOLS) {
    try {
      navigator.modelContext.registerTool({
        name: tool.name,
        description: tool.description,
        inputSchema: tool.parameters,
        execute: async (params) => {
          const t0 = Date.now();
          const id = ++_toolLogId;
          let result;
          try {
            result = await tool.handler(params);
          } catch (err) {
            result = { error: String(err) };
          }
          appendToolLog({ id, toolName: tool.name, params, result, ts: new Date(), durationMs: Date.now() - t0 });
          return result;
        },
      });
      registered++;
    } catch (err) {
      lastError = err;
      console.warn(`[WebMCP] Failed to register tool "${tool.name}":`, err);
    }
  }

  if (registered === 0) {
    badge.className = "webmcp-badge";
    badge.textContent = "WebMCP · inactive";
    console.error("[WebMCP] No tools registered. Last error:", lastError);
  } else {
    _webmcpActive = true;
    badge.className = "webmcp-badge ok";
    badge.textContent = `WebMCP · ${registered} tools`;
    console.info(`[WebMCP] Registered ${registered} tools`);
  }
}

// ── Tool call log ─────────────────────────────────────────────────────────────

function appendToolLog(entry) {
  state.toolLog.unshift(entry);
  if (state.toolLog.length > 50) state.toolLog.pop();

  const badge = document.getElementById("tool-log-badge");
  if (badge) {
    badge.textContent = state.toolLog.length;
    badge.hidden = false;
  }

  const list = document.getElementById("tool-log-list");
  const body = document.getElementById("log-body");

  if (state.toolLog.length === 1 && body?.hidden) {
    body.hidden = false;
    document.getElementById("log-toggle")?.setAttribute("aria-expanded", "true");
    const chevron = document.getElementById("log-chevron");
    if (chevron) chevron.textContent = "▲";
  }

  if (list && body && !body.hidden) {
    list.insertBefore(createLogEntryEl(entry), list.firstChild);
  }
}

function createLogEntryEl(entry) {
  const el = document.createElement("div");
  el.className = "log-entry";

  const timeStr = entry.ts.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const isError = !!entry.result?.error;

  el.innerHTML = `
    <div class="log-entry-header">
      <span class="log-tool-name">${escHtml(entry.toolName)}</span>
      <span class="log-duration">${entry.durationMs}ms</span>
      <span class="log-time">${escHtml(timeStr)}</span>
      <button class="btn btn-sm log-replay-btn" title="Replay" aria-label="Replay ${escHtml(entry.toolName)}">↺</button>
    </div>
    <div class="log-params">${escHtml(JSON.stringify(entry.params))}</div>
    <div class="log-result${isError ? " log-result-error" : ""}">${escHtml(JSON.stringify(entry.result))}</div>
  `;

  el.querySelector(".log-replay-btn").addEventListener("click", () => replayToolCall(entry));
  return el;
}

async function replayToolCall(entry) {
  const tool = TOOLS.find(t => t.name === entry.toolName);
  if (!tool) { toast(`Tool "${entry.toolName}" not found`, "error"); return; }
  const result = await chatExecuteToolCall(entry.toolName, entry.params);
  toast(result.error ? `Replay failed: ${result.error}` : `Replayed ${entry.toolName}`, result.error ? "error" : "ok");
}

// ── UI helpers ─────────────────────────────────────────────────────────────────

function attachJsonFormatter(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("blur", () => {
    const val = el.value.trim();
    if (!val) return;
    try { el.value = JSON.stringify(JSON.parse(val), null, 2); } catch { /* leave as-is */ }
  });
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function chipList(items) {
  if (!items.length) return `<div class="sidebar-empty" style="padding:0">None</div>`;
  return `<div class="list-chips">${items.map(i => `<span class="chip">${escHtml(i)}</span>`).join("")}</div>`;
}

// ── Chat ──────────────────────────────────────────────────────────────────────

const GITHUB_CLIENT_ID = "Ov23lioKDt8Os7hdiSEh";
const CORS_PROXY_URL = "https://cors-proxy.jonasneves.workers.dev";
const OAUTH_CALLBACK_ORIGIN = "https://neevs.io";

const chatState = {
  provider: "anthropic",
  model: "claude-sonnet-4-6",
  claudeKey: localStorage.getItem("webmcp-claude-key") || "",
  githubAuth: JSON.parse(localStorage.getItem("webmcp-gh-auth") || "null"), // {token, username}
  convMsgs: [],  // raw API message history (provider-specific format)
  abortCtrl: null,
  busy: false,
};

function initChat() {
  const keyInput = document.getElementById("chat-api-key");
  keyInput.value = chatState.claudeKey;

  const sel = document.getElementById("chat-model-select");
  const saved = localStorage.getItem("webmcp-chat-model") || "anthropic:claude-sonnet-4-6";
  sel.value = saved;
  applyModelSelection(saved);

  sel.addEventListener("change", () => {
    localStorage.setItem("webmcp-chat-model", sel.value);
    applyModelSelection(sel.value);
    chatState.convMsgs = [];
    document.getElementById("chat-messages").innerHTML = "";
  });

  document.getElementById("chat-key-save").addEventListener("click", () => {
    chatState.claudeKey = keyInput.value.trim();
    localStorage.setItem("webmcp-claude-key", chatState.claudeKey);
    toast("API key saved", "ok");
  });

  document.getElementById("chat-send").addEventListener("click", sendChatMsg);
  document.getElementById("chat-input").addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") { e.preventDefault(); sendChatMsg(); }
  });
  document.getElementById("chat-abort").addEventListener("click", () => chatState.abortCtrl?.abort());
  document.getElementById("chat-clear").addEventListener("click", () => {
    chatState.convMsgs = [];
    document.getElementById("chat-messages").innerHTML = "";
  });
  document.addEventListener("keydown", (e) => {
    const panel = document.getElementById("chat-panel");
    if (!panel || panel.hidden) return;
    if (e.key.length !== 1 || e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || document.activeElement?.isContentEditable) return;
    const chatInput = document.getElementById("chat-input");
    if (chatInput && !chatInput.disabled) chatInput.focus();
  });

  document.getElementById("robot-view-btn").addEventListener("click", () => {
    const wsUrl = document.getElementById("url-input").value.trim();
    const { hostname } = new URL(wsUrl.replace(/^wss?/, "http"));
    window.open(`http://${hostname}:8080/vnc.html`, "_blank", "noopener");
  });

  document.getElementById("chat-panel-toggle").addEventListener("click", () => {
    const panel = document.getElementById("chat-panel");
    const btn = document.getElementById("chat-panel-toggle");
    const open = panel.hidden;
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    btn.textContent = open ? "Close Chat" : "AI Chat";
  });
}

function applyModelSelection(value) {
  const [provider, ...rest] = value.split(":");
  chatState.provider = provider;
  chatState.model = rest.join(":");
  const isGitHub = chatState.provider === "github";
  document.getElementById("chat-claude-bar").style.display = isGitHub ? "none" : "";
  document.getElementById("chat-github-bar").style.display = isGitHub ? "" : "none";
  const noticeDismissed = !!localStorage.getItem("webmcp-github-notice-dismissed");
  document.getElementById("github-notice").hidden = !isGitHub || noticeDismissed;
  if (isGitHub) updateGitHubAuthBar();
}

async function connectGitHub() {
  const oauthState = crypto.randomUUID();
  const redirectUri = OAUTH_CALLBACK_ORIGIN + "/";

  const authUrl = new URL("https://github.com/login/oauth/authorize");
  authUrl.searchParams.set("client_id", GITHUB_CLIENT_ID);
  authUrl.searchParams.set("redirect_uri", redirectUri);
  authUrl.searchParams.set("state", oauthState);
  authUrl.searchParams.set("scope", "read:user");

  const width = 500, height = 600;
  const left = window.screenX + (window.innerWidth - width) / 2;
  const top = window.screenY + (window.innerHeight - height) / 2;

  return new Promise((resolve, reject) => {
    const popup = window.open(
      authUrl.toString(), "github-oauth",
      `width=${width},height=${height},left=${left},top=${top},popup=yes`
    );
    if (!popup) { reject(new Error("Popup blocked — allow popups for this site")); return; }

    const handleMessage = async (event) => {
      if (event.origin !== OAUTH_CALLBACK_ORIGIN) return;
      const { type, code, error } = event.data || {};
      if (type !== "oauth-callback") return;
      window.removeEventListener("message", handleMessage);
      clearInterval(pollTimer);
      if (error) { reject(new Error(error)); return; }
      if (!code) { reject(new Error("No code received")); return; }
      try {
        const res = await fetch(`${CORS_PROXY_URL}/token`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ client_id: GITHUB_CLIENT_ID, code, redirect_uri: redirectUri }),
        });
        const data = await res.json();
        if (data.error || !data.access_token) throw new Error(data.error_description || data.error || "Token exchange failed");
        let username = data.username;
        if (!username) {
          const userRes = await fetch("https://api.github.com/user", {
            headers: { Authorization: `Bearer ${data.access_token}`, Accept: "application/vnd.github+json" },
          });
          if (userRes.ok) username = (await userRes.json()).login;
        }
        resolve({ token: data.access_token, username: username || "" });
      } catch (err) {
        reject(err);
      }
    };

    window.addEventListener("message", handleMessage);
    const pollTimer = setInterval(() => {
      if (popup.closed) {
        clearInterval(pollTimer);
        window.removeEventListener("message", handleMessage);
        reject(new Error("OAuth flow cancelled"));
      }
    }, 500);
  });
}

function updateGitHubAuthBar() {
  const bar = document.getElementById("chat-github-bar");
  if (!bar) return;
  bar.innerHTML = "";
  if (chatState.githubAuth) {
    const label = document.createElement("span");
    label.className = "github-user-label";
    label.textContent = `@${chatState.githubAuth.username}`;
    const disconnectBtn = document.createElement("button");
    disconnectBtn.className = "btn btn-sm github-disconnect-btn";
    disconnectBtn.textContent = "Disconnect";
    disconnectBtn.addEventListener("click", () => {
      chatState.githubAuth = null;
      localStorage.removeItem("webmcp-gh-auth");
      chatState.convMsgs = [];
      document.getElementById("chat-messages").innerHTML = "";
      updateGitHubAuthBar();
    });
    bar.appendChild(label);
    bar.appendChild(disconnectBtn);
  } else {
    const connectBtn = document.createElement("button");
    connectBtn.className = "btn btn-sm github-connect-btn";
    connectBtn.textContent = "Connect GitHub";
    connectBtn.addEventListener("click", async () => {
      connectBtn.textContent = "Connecting…";
      connectBtn.disabled = true;
      try {
        chatState.githubAuth = await connectGitHub();
        localStorage.setItem("webmcp-gh-auth", JSON.stringify(chatState.githubAuth));
        updateGitHubAuthBar();
      } catch (err) {
        if (err.message !== "OAuth flow cancelled") toast(err.message, "error");
        connectBtn.textContent = "Connect GitHub";
        connectBtn.disabled = false;
      }
    });
    bar.appendChild(connectBtn);
  }
}

function getSystemPrompt() {
  const lines = [
    "You are an AI assistant embedded in the ROS WebMCP Dashboard.",
    "You have access to ROS tools to inspect and control a robot via rosbridge.",
  ];
  if (state.connected) {
    lines.push(`Connected to rosbridge at ${state.url}.`);
    lines.push(`Topics (${state.topics.length}): ${state.topics.slice(0, 20).join(", ")}${state.topics.length > 20 ? "…" : ""}`);
    if (state.nodes.length) lines.push(`Nodes: ${state.nodes.slice(0, 10).join(", ")}`);
    if (state.services.length) lines.push(`Services: ${state.services.slice(0, 10).join(", ")}`);
  } else {
    lines.push("The robot is not currently connected. Use connect_to_robot to connect first.");
  }
  if (state.selected) lines.push(`User is currently viewing ${state.selected.kind} "${state.selected.name}".`);
  lines.push("Use the provided tools to answer questions. Be concise.");
  return lines.join("\n");
}

function getClaudeTools() {
  return TOOLS.map(t => ({ name: t.name, description: t.description, input_schema: t.parameters }));
}

function getOpenAITools() {
  return TOOLS.map(t => ({
    type: "function",
    function: { name: t.name, description: t.description, parameters: t.parameters },
  }));
}

async function chatExecuteToolCall(name, input) {
  const tool = TOOLS.find(t => t.name === name);
  const t0 = Date.now();
  const id = ++_toolLogId;
  let result;
  if (!tool) {
    result = { error: `Unknown tool: ${name}` };
  } else {
    try { result = await tool.handler(input); }
    catch (err) { result = { error: String(err) }; }
  }
  appendToolLog({ id, toolName: name, params: input, result, ts: new Date(), durationMs: Date.now() - t0 });
  return result;
}

async function sendChatMsg() {
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text || chatState.busy) return;

  const key = chatState.provider === "github" ? chatState.githubAuth?.token : chatState.claudeKey;
  if (!key) {
    toast(chatState.provider === "github" ? "Connect GitHub above" : "Enter your Anthropic API key first", "error");
    return;
  }

  input.value = "";
  appendChatMsg("user", text);
  chatState.convMsgs.push({ role: "user", content: text });
  chatState.busy = true;
  chatState.abortCtrl = new AbortController();
  document.getElementById("chat-send").disabled = true;
  document.getElementById("chat-abort").hidden = false;
  showChatSpinner();

  try {
    if (chatState.provider === "github") {
      await runConversationGitHub(key, chatState.abortCtrl.signal);
    } else {
      await runConversationClaude(key, chatState.abortCtrl.signal);
    }
  } catch (err) {
    if (err.name !== "AbortError") { hideChatSpinner(); appendChatMsg("error", err.message); }
  } finally {
    chatState.busy = false;
    chatState.abortCtrl = null;
    document.getElementById("chat-send").disabled = false;
    document.getElementById("chat-abort").hidden = true;
  }
}

// ── Claude conversation ───────────────────────────────────────────────────────

async function runConversationClaude(apiKey, signal) {
  while (true) {
    let body;
    try {
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        signal,
        headers: {
          "content-type": "application/json",
          "x-api-key": apiKey,
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true",
        },
        body: JSON.stringify({
          model: chatState.model,
          max_tokens: 4096,
          system: getSystemPrompt(),
          messages: chatState.convMsgs,
          tools: getClaudeTools(),
          stream: true,
        }),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`API ${res.status}: ${txt.slice(0, 200)}`);
      }
      body = res.body;
    } catch (err) {
      hideChatSpinner();
      if (err.name === "AbortError") return;
      appendChatMsg("error", err.message);
      return;
    }

    const contentBlocks = [];
    let currentTextEl = null;
    let currentTextContent = "";
    let currentToolInput = "";
    let currentBlockType = null;
    let rafId = 0;

    try {
      for await (const { event, data } of parseSSEStream(body)) {
        switch (event) {
          case "content_block_start": {
            const block = data.content_block;
            currentBlockType = block.type;
            if (block.type === "text") {
              hideChatSpinner();
              currentTextContent = block.text || "";
              currentTextEl = appendChatMsg("assistant", currentTextContent);
            } else if (block.type === "tool_use") {
              contentBlocks.push({ type: "tool_use", id: block.id, name: block.name, input: {} });
              currentToolInput = "";
              appendChatToolCall(block.id, block.name);
            }
            break;
          }
          case "content_block_delta": {
            if (data.delta.type === "text_delta") {
              currentTextContent += data.delta.text;
              if (currentTextEl && !rafId) {
                rafId = requestAnimationFrame(() => {
                  rafId = 0;
                  if (currentTextEl) currentTextEl.innerHTML = renderMarkdown(currentTextContent);
                  scrollChatBottom();
                });
              }
            } else if (data.delta.type === "input_json_delta") {
              currentToolInput += data.delta.partial_json;
            }
            break;
          }
          case "content_block_stop": {
            if (currentBlockType === "text" && currentTextContent) {
              if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
              if (currentTextEl) currentTextEl.innerHTML = renderMarkdown(currentTextContent);
              contentBlocks.push({ type: "text", text: currentTextContent });
              currentTextEl = null;
              currentTextContent = "";
            } else if (currentBlockType === "tool_use") {
              const toolBlock = contentBlocks[contentBlocks.length - 1];
              try { toolBlock.input = currentToolInput ? JSON.parse(currentToolInput) : {}; }
              catch { toolBlock.input = {}; }
              currentToolInput = "";
            }
            currentBlockType = null;
            break;
          }
        }
      }
    } catch (err) {
      hideChatSpinner();
      if (err.name === "AbortError") return;
      appendChatMsg("error", "Stream error: " + err.message);
      return;
    }

    chatState.convMsgs.push({ role: "assistant", content: contentBlocks });
    const toolUses = contentBlocks.filter(b => b.type === "tool_use");
    if (toolUses.length === 0) { hideChatSpinner(); return; }

    const toolResults = [];
    for (const tu of toolUses) {
      const result = await chatExecuteToolCall(tu.name, tu.input);
      updateChatToolCall(tu.id, result, tu.input);
      toolResults.push({ type: "tool_result", tool_use_id: tu.id, content: JSON.stringify(result) });
    }
    chatState.convMsgs.push({ role: "user", content: toolResults });
    showChatSpinner();
  }
}

async function* readStreamLines(body) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) yield line;
    }
  } finally {
    reader.releaseLock();
  }
}

async function* parseSSEStream(body) {
  let currentEvent = null;
  for await (const line of readStreamLines(body)) {
    if (line.startsWith("event: ")) {
      currentEvent = line.slice(7).trim();
    } else if (line.startsWith("data: ") && currentEvent) {
      try { yield { event: currentEvent, data: JSON.parse(line.slice(6)) }; } catch {}
      currentEvent = null;
    }
  }
}

// ── GitHub Models conversation ────────────────────────────────────────────────

async function runConversationGitHub(token, signal) {
  while (true) {
    let body;
    try {
      const res = await fetch("https://models.github.ai/inference/chat/completions", {
        method: "POST",
        signal,
        headers: {
          "content-type": "application/json",
          "authorization": `Bearer ${token}`,
        },
        body: JSON.stringify({
          model: chatState.model,
          messages: [{ role: "system", content: getSystemPrompt() }, ...chatState.convMsgs],
          tools: getOpenAITools(),
          tool_choice: "auto",
          max_completion_tokens: 4096,
          stream: true,
        }),
      });
      if (!res.ok) {
        hideChatSpinner();
        if (res.status === 429) { appendRateLimitMsg(); return; }
        const txt = await res.text();
        throw new Error(`API ${res.status}: ${txt.slice(0, 200)}`);
      }
      body = res.body;
    } catch (err) {
      hideChatSpinner();
      if (err.name === "AbortError") return;
      appendChatMsg("error", err.message);
      return;
    }

    let currentTextEl = null;
    let currentTextContent = "";
    let rafId = 0;
    const tcMap = {};

    try {
      for await (const chunk of parseOpenAIStream(body)) {
        const delta = chunk.choices?.[0]?.delta;
        if (!delta) continue;

        if (delta.content) {
          if (!currentTextEl) {
            hideChatSpinner();
            currentTextContent = "";
            currentTextEl = appendChatMsg("assistant", "");
          }
          currentTextContent += delta.content;
          if (!rafId) {
            rafId = requestAnimationFrame(() => {
              rafId = 0;
              if (currentTextEl) currentTextEl.innerHTML = renderMarkdown(currentTextContent);
              scrollChatBottom();
            });
          }
        }

        if (delta.tool_calls) {
          for (const tc of delta.tool_calls) {
            if (!tcMap[tc.index]) tcMap[tc.index] = { id: "", name: "", arguments: "", _shown: false };
            if (tc.id) tcMap[tc.index].id = tc.id;
            if (tc.function?.name) tcMap[tc.index].name = tc.function.name;
            if (tc.function?.arguments) tcMap[tc.index].arguments += tc.function.arguments;
            if (!tcMap[tc.index]._shown && tcMap[tc.index].id && tcMap[tc.index].name) {
              tcMap[tc.index]._shown = true;
              appendChatToolCall(tcMap[tc.index].id, tcMap[tc.index].name);
            }
          }
        }
      }
    } catch (err) {
      hideChatSpinner();
      if (err.name === "AbortError") return;
      appendChatMsg("error", "Stream error: " + err.message);
      return;
    }

    if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
    if (currentTextEl) currentTextEl.innerHTML = renderMarkdown(currentTextContent);

    const toolCalls = Object.values(tcMap);
    const assistantMsg = { role: "assistant", content: currentTextContent || null };
    if (toolCalls.length) {
      assistantMsg.tool_calls = toolCalls.map(tc => ({
        id: tc.id, type: "function",
        function: { name: tc.name, arguments: tc.arguments },
      }));
    }
    chatState.convMsgs.push(assistantMsg);

    if (toolCalls.length === 0) { hideChatSpinner(); return; }

    for (const tc of toolCalls) {
      let parsedArgs;
      try { parsedArgs = JSON.parse(tc.arguments || "{}"); } catch { parsedArgs = {}; }
      const result = await chatExecuteToolCall(tc.name, parsedArgs);
      updateChatToolCall(tc.id, result, parsedArgs);
      chatState.convMsgs.push({ role: "tool", tool_call_id: tc.id, content: JSON.stringify(result) });
    }
    showChatSpinner();
  }
}

async function* parseOpenAIStream(body) {
  for await (const line of readStreamLines(body)) {
    if (!line.startsWith("data: ")) continue;
    const data = line.slice(6).trim();
    if (data === "[DONE]") return;
    try { yield JSON.parse(data); } catch {}
  }
}

// ── Chat UI helpers ───────────────────────────────────────────────────────────

function appendChatMsg(role, text) {
  const container = document.getElementById("chat-messages");
  const el = document.createElement("div");
  el.className = `chat-msg chat-msg-${role}`;
  if (role === "assistant") {
    el.innerHTML = renderMarkdown(text);
  } else {
    el.textContent = text;
  }
  container.appendChild(el);
  scrollChatBottom();
  return el;
}

function nextGptModel() {
  const sel = document.getElementById("chat-model-select");
  const opts = Array.from(sel.options);
  const current = `${chatState.provider}:${chatState.model}`;
  const idx = opts.findIndex(o => o.value === current);
  for (let i = idx + 1; i < opts.length; i++) {
    if (opts[i].value.startsWith("github:openai/gpt")) return opts[i];
  }
  return null;
}

function appendRateLimitMsg() {
  const next = nextGptModel();
  const container = document.getElementById("chat-messages");
  const el = document.createElement("div");
  el.className = "chat-msg chat-msg-error";
  if (next) {
    el.innerHTML = `Rate limit reached. <a href="#" class="chat-rate-limit-link">Switch to ${escHtml(next.text)}</a>`;
    el.querySelector("a").addEventListener("click", e => {
      e.preventDefault();
      const sel = document.getElementById("chat-model-select");
      sel.value = next.value;
      localStorage.setItem("webmcp-chat-model", next.value);
      applyModelSelection(next.value);
      el.remove();
    });
  } else {
    el.textContent = "Rate limit reached. No fallback model available.";
  }
  container.appendChild(el);
  scrollChatBottom();
}

function appendChatToolCall(toolId, toolName) {
  const container = document.getElementById("chat-messages");
  const el = document.createElement("details");
  el.className = "chat-tool-call";
  el.dataset.toolId = toolId;
  el.innerHTML = `
    <summary class="chat-tool-call-header">
      <span class="chat-tool-call-icon">⚙</span>
      <span class="chat-tool-call-name">${escHtml(toolName)}</span>
      <span class="chat-tool-call-subtitle"></span>
      <span class="chat-tool-call-status">running…</span>
    </summary>
    <div class="chat-tool-call-body">Waiting for result…</div>
  `;
  container.appendChild(el);
  scrollChatBottom();
}

function updateChatToolCall(toolId, result, params) {
  const el = document.querySelector(`.chat-tool-call[data-tool-id="${CSS.escape(toolId)}"]`);
  if (!el) return;
  const status = el.querySelector(".chat-tool-call-status");
  const subtitle = el.querySelector(".chat-tool-call-subtitle");
  const body = el.querySelector(".chat-tool-call-body");
  const isError = !!result?.error;
  if (status) {
    status.textContent = isError ? "error" : "done";
    status.className = `chat-tool-call-status ${isError ? "error" : "ok"}`;
  }
  if (subtitle && params) {
    const key = params.topic || params.service || params.service_name || params.node || params.url || "";
    if (key) subtitle.textContent = key;
  }
  if (body) body.textContent = JSON.stringify(result, null, 2);
}

function showChatSpinner() {
  hideChatSpinner();
  const container = document.getElementById("chat-messages");
  const el = document.createElement("div");
  el.className = "chat-spinner";
  el.id = "chat-spinner";
  el.innerHTML = "<span></span><span></span><span></span>";
  container.appendChild(el);
  scrollChatBottom();
}

function hideChatSpinner() {
  document.getElementById("chat-spinner")?.remove();
}

function scrollChatBottom() {
  const el = document.getElementById("chat-messages");
  if (el) el.scrollTop = el.scrollHeight;
}

marked.use({ gfm: true, breaks: true });

function renderMarkdown(text) {
  if (!text) return "";
  return DOMPurify.sanitize(marked.parse(text));
}

// ── Init ───────────────────────────────────────────────────────────────────────

document.getElementById("connect-btn").addEventListener("click", () => {
  const url = document.getElementById("url-input").value.trim();
  if (url) { cancelReconnect(); connect(url); }
});

document.getElementById("url-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("connect-btn").click();
});

document.getElementById("sidebar-filter").addEventListener("input", (e) => {
  state.filter = e.target.value;
  renderSidebar();
});

document.querySelectorAll("[data-section]").forEach(btn => {
  btn.addEventListener("click", () => {
    const section = btn.dataset.section;
    state.sidebarCollapsed[section] = !state.sidebarCollapsed[section];
    renderSidebar();
  });
});

function initSysFilterBtn(btnId, stateKey) {
  document.getElementById(btnId).addEventListener("click", () => {
    state[stateKey] = !state[stateKey];
    const btn = document.getElementById(btnId);
    btn.setAttribute("aria-pressed", String(state[stateKey]));
    btn.classList.toggle("active", state[stateKey]);
    renderSidebar();
    if (!state.selected) renderMainPlaceholder();
  });
}

initSysFilterBtn("sys-filter-btn", "hideSystemServices");
initSysFilterBtn("node-sys-filter-btn", "hideSystemNodes");

document.getElementById("github-notice-dismiss").addEventListener("click", () => {
  localStorage.setItem("webmcp-github-notice-dismissed", "1");
  document.getElementById("github-notice").hidden = true;
});

document.getElementById("log-toggle").addEventListener("click", () => {
  const body = document.getElementById("log-body");
  const toggle = document.getElementById("log-toggle");
  const chevron = document.getElementById("log-chevron");
  const willExpand = body.hidden;
  body.hidden = !willExpand;
  toggle.setAttribute("aria-expanded", String(willExpand));
  chevron.textContent = willExpand ? "▲" : "▼";

  if (willExpand) {
    const list = document.getElementById("tool-log-list");
    list.innerHTML = "";
    state.toolLog.forEach(entry => list.appendChild(createLogEntryEl(entry)));
  }
});

registerWebMCPTools();
initChat();

// ── WebMCP badge popover ───────────────────────────────────────────────────────

document.getElementById("webmcp-badge").addEventListener("click", () => {
  const popover = document.getElementById("webmcp-popover");
  if (!popover) return;
  if (!popover.hidden) { popover.hidden = true; return; }

  popover.innerHTML = "";

  // Header section
  const header = document.createElement("div");
  header.className = "webmcp-popover-header";
  if (_webmcpActive) {
    header.innerHTML = `
      <div class="webmcp-popover-title">WebMCP · active</div>
      <div class="webmcp-popover-explain">These ${TOOLS.length} tools are registered with your browser's AI context, so native browser AI agents can call them directly. The <strong>AI chat panel</strong> on this page uses the same tools independently via the Anthropic/GitHub API — no flag needed.</div>
    `;
  } else {
    header.innerHTML = `
      <div class="webmcp-popover-title">WebMCP · inactive</div>
      <div class="webmcp-popover-explain">The <strong>AI chat panel</strong> on this page already uses these ${TOOLS.length} tools directly via the Anthropic/GitHub API — no flag needed. WebMCP would <em>also</em> expose them to native browser AI agents (e.g. a Claude browser integration) without the chat panel. Requires Chrome 146+ Canary → <code>chrome://flags/#webmcp-for-testing</code>.</div>
    `;
  }
  popover.appendChild(header);

  // Tool list
  const divider = document.createElement("div");
  divider.className = "webmcp-popover-divider";
  divider.textContent = "Tools";
  popover.appendChild(divider);

  TOOLS.forEach(tool => {
    const item = document.createElement("div");
    item.className = "webmcp-popover-item";
    item.innerHTML = `
      <div class="webmcp-popover-name">${escHtml(tool.name)}</div>
      <div class="webmcp-popover-desc">${escHtml(tool.description)}</div>
    `;
    popover.appendChild(item);
  });

  popover.hidden = false;
});

document.addEventListener("click", (e) => {
  const popover = document.getElementById("webmcp-popover");
  if (!popover || popover.hidden) return;
  if (!e.target.closest(".webmcp-badge-wrap")) popover.hidden = true;
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const popover = document.getElementById("webmcp-popover");
    if (popover && !popover.hidden) { popover.hidden = true; }
  }
});
