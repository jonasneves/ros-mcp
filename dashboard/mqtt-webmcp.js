/* mqtt-webmcp.js — MQTT.js connection + WebMCP tool registration + UI logic */

// ── State ────────────────────────────────────────────────────────────────────

const state = {
  mqttClient: null,
  connected: false,
  url: "ws://localhost:9001",
  seenTopics: [],           // topics seen via '#' subscription
  watching: null,           // topic name currently being live-watched
  topicListeners: {},       // topic -> Set<callback> for persistent listeners
  onceCallbacks: {},        // topic -> callback[] for one-shot receives
  selected: null,           // { kind: "topic", name: string }
  filter: "",
  publishHistory: {},       // topic -> string[] (max 10, newest first)
  continuousPublish: null,  // { timer } | null
  pinnedTopics: {},         // topic -> { lastMsg: string | null }
  toolLog: [],
  reconnect: null,
  sidebarCollapsed: { topics: false },
};

let _toolLogId = 0;

// ── Helpers ──────────────────────────────────────────────────────────────────

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
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

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function prettyJson(str) {
  try { return JSON.stringify(JSON.parse(str), null, 2); }
  catch { return str; }
}

function isConnected() {
  return !!(state.mqttClient && state.connected);
}

function trackTopic(topic) {
  if (state.seenTopics.includes(topic)) return false;
  state.seenTopics.push(topic);
  renderSidebar();
  if (!state.selected) renderMainPlaceholder();
  return true;
}

function attachJsonFormatter(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("blur", () => {
    const val = el.value.trim();
    if (val) el.value = prettyJson(val);
  });
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
  const delay = Math.min(RECONNECT_BASE_MS * 2 ** state.reconnect.attempts, RECONNECT_CAP_MS);
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
  if (state.mqttClient) {
    state.mqttClient.end(true);
    state.mqttClient = null;
  }
  stopWatching();

  state.url = url;
  const client = mqtt.connect(url, { reconnectPeriod: 0 }); // manual reconnect
  state.mqttClient = client;

  client.on("connect", () => {
    cancelReconnect();
    state.connected = true;
    updateStatusDot(true, false);
    document.getElementById("status-text").textContent = url;
    client.subscribe("#");         // passively discover all active topics
    client.subscribe("devices/#"); // device announcements (retained, replayed immediately)
    renderSidebar();
    renderMainPlaceholder();
  });

  client.on("message", (topic, message) => {
    const msg = message.toString();

    // Handle device announcements — auto-add advertised topics
    if (topic.startsWith("devices/")) {
      try {
        const { topics } = JSON.parse(msg);
        for (const t of topics) trackTopic(t);
      } catch { /* ignore malformed announcements */ }
      return;
    }

    // Track seen topics
    trackTopic(topic);

    // Persistent listeners (e.g. duration-based subscriptions)
    if (state.topicListeners[topic]) {
      for (const cb of state.topicListeners[topic]) cb(msg);
    }

    // One-shot callbacks
    if (state.onceCallbacks[topic]?.length) {
      const toCall = state.onceCallbacks[topic].splice(0);
      for (const cb of toCall) cb(msg);
    }

    // Live watch panel
    if (state.watching === topic) showMsgCard(msg);

    // Pinned cards
    if (state.pinnedTopics[topic]) {
      state.pinnedTopics[topic].lastMsg = msg;
      updateWatchCard(topic);
    }
  });

  client.on("error", (err) => {
    updateStatusDot(false, true);
    document.getElementById("status-text").textContent = "Error";
    toast(`Connection error: ${err.message || err}`, "error");
  });

  client.on("close", () => {
    state.connected = false;
    updateStatusDot(false, false);
    state.seenTopics = [];
    state.watching = null;
    state.onceCallbacks = {};
    state.topicListeners = {};
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

// ── Sidebar rendering ─────────────────────────────────────────────────────────

function renderMainPlaceholder() {
  const main = document.getElementById("main-panel");
  if (!state.connected) {
    main.innerHTML = `<div class="panel-placeholder" id="panel-placeholder"><div>Connect to MQTT broker to get started.</div></div>`;
    return;
  }
  main.innerHTML = `
    <div class="conn-summary">
      <div class="conn-summary-title">Connected</div>
      <div class="conn-url">${escHtml(state.url)}</div>
      <div class="conn-stats">
        <div class="conn-stat">
          <span class="conn-stat-value">${state.seenTopics.length}</span>
          <span class="conn-stat-label">Topics</span>
        </div>
      </div>
      <div class="conn-hint">← select a topic to inspect or publish</div>
    </div>
  `;
}

function renderSidebar() {
  renderTopicList();
  const listEl = document.getElementById("topics-list");
  const btn = document.getElementById("section-toggle-topics");
  const chevron = btn?.parentElement?.querySelector(".sidebar-heading-chevron");
  if (listEl) listEl.hidden = state.sidebarCollapsed.topics;
  if (btn) btn.setAttribute("aria-expanded", String(!state.sidebarCollapsed.topics));
  if (chevron) chevron.classList.toggle("collapsed", state.sidebarCollapsed.topics);
}

function renderTopicList() {
  const container = document.getElementById("topics-list");
  container.innerHTML = "";

  let filtered = state.filter
    ? state.seenTopics.filter(t => t.toLowerCase().includes(state.filter.toLowerCase()))
    : state.seenTopics;

  if (!filtered.length) {
    if (!state.connected) return;
    const el = document.createElement("div");
    el.className = "sidebar-empty";
    el.textContent = state.filter ? "No matches" : "Waiting for messages…";
    container.appendChild(el);
    return;
  }

  for (const topic of filtered) {
    const isActive = state.selected?.name === topic;
    const btn = document.createElement("button");
    btn.className = "sidebar-item" + (isActive ? " active" : "");
    btn.textContent = topic;
    btn.title = topic;
    btn.addEventListener("click", () => selectTopic(topic));

    const row = document.createElement("div");
    row.className = "sidebar-item-row";

    const pinBtn = document.createElement("button");
    const isPinned = !!state.pinnedTopics[topic];
    pinBtn.className = "pin-btn" + (isPinned ? " pinned" : "");
    pinBtn.title = isPinned ? "Unpin" : "Pin to watch strip";
    pinBtn.setAttribute("aria-pressed", String(isPinned));
    pinBtn.textContent = "⊕";
    pinBtn.addEventListener("click", (e) => { e.stopPropagation(); togglePin(topic); });

    row.appendChild(btn);
    row.appendChild(pinBtn);
    container.appendChild(row);
  }
}

// ── Topic selection ───────────────────────────────────────────────────────────

function selectTopic(topic) {
  stopWatching();
  stopContinuousPublish();
  state.selected = { kind: "topic", name: topic };
  renderSidebar();
  renderTopicPanel(topic);
}

// ── Topic panel ────────────────────────────────────────────────────────────────

function renderTopicPanel(topic) {
  const main = document.getElementById("main-panel");

  main.innerHTML = `
    <div class="detail-header">
      <div class="detail-title">${escHtml(topic)}</div>
      <div class="detail-type">MQTT topic</div>
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
      <label class="input-label" for="publish-msg">Payload <span style="color:var(--text-muted);font-weight:400">— ⌘↵ to send</span></label>
      <textarea class="textarea-field" id="publish-msg" rows="3" placeholder='true'></textarea>
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
    doSubscribeOnce(topic)
  );
  document.getElementById("btn-watch").addEventListener("click", () => startWatching(topic));
  document.getElementById("btn-stop-watch").addEventListener("click", stopWatching);
  document.getElementById("btn-publish").addEventListener("click", () => doPublish(topic));

  document.getElementById("publish-msg").addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      doPublish(topic);
    }
  });

  document.getElementById("publish-history").addEventListener("change", (e) => {
    if (e.target.value) {
      document.getElementById("publish-msg").value = e.target.value;
      e.target.value = "";
    }
  });
  renderPublishHistory(topic);

  document.getElementById("repeat-checkbox").addEventListener("change", (e) => {
    if (e.target.checked) {
      const hz = parseFloat(document.getElementById("repeat-hz").value) || 1;
      startContinuousPublish(topic, hz);
    } else {
      stopContinuousPublish();
    }
  });
  document.getElementById("repeat-hz").addEventListener("change", () => {
    if (document.getElementById("repeat-checkbox")?.checked) {
      const hz = parseFloat(document.getElementById("repeat-hz").value) || 1;
      startContinuousPublish(topic, hz);
    }
  });

  attachJsonFormatter("publish-msg");
}

// ── Publish history ───────────────────────────────────────────────────────────

function pushPublishHistory(topic, payload) {
  if (!state.publishHistory[topic]) state.publishHistory[topic] = [];
  const hist = state.publishHistory[topic];
  const existing = hist.indexOf(payload);
  if (existing !== -1) hist.splice(existing, 1);
  hist.unshift(payload);
  if (hist.length > 10) hist.pop();
}

function renderPublishHistory(topic) {
  const sel = document.getElementById("publish-history");
  const group = document.getElementById("publish-history-group");
  if (!sel || !group) return;
  const hist = state.publishHistory[topic] || [];
  group.style.display = hist.length ? "" : "none";
  sel.innerHTML = `<option value="">— History —</option>`;
  for (const entry of hist) {
    const opt = document.createElement("option");
    opt.value = entry;
    const label = entry.replace(/\s+/g, " ");
    opt.textContent = label.length > 50 ? label.slice(0, 50) + "…" : label;
    sel.appendChild(opt);
  }
}

// ── Continuous publish ────────────────────────────────────────────────────────

function startContinuousPublish(topic, hz) {
  stopContinuousPublish();
  const interval = Math.max(50, Math.round(1000 / hz));
  const timer = setInterval(() => {
    const payload = document.getElementById("publish-msg")?.value || "";
    state.mqttClient?.publish(topic, payload);
  }, interval);
  state.continuousPublish = { timer };
}

function stopContinuousPublish() {
  if (!state.continuousPublish) return;
  clearInterval(state.continuousPublish.timer);
  state.continuousPublish = null;
  const cb = document.getElementById("repeat-checkbox");
  if (cb) cb.checked = false;
}

// ── Subscribe / watch ─────────────────────────────────────────────────────────

async function doSubscribeOnce(topic) {
  const btn = document.getElementById("btn-subscribe-once");
  btn.disabled = true;
  btn.textContent = "Waiting…";
  try {
    const msg = await subscribeOnce(topic, 5000);
    showMsgCard(msg);
    toast("Message received", "ok");
  } catch (err) {
    toast(String(err), "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Subscribe once"; }
  }
}

function setWatchUI(watching) {
  const btnWatch = document.getElementById("btn-watch");
  const btnStop = document.getElementById("btn-stop-watch");
  const indicator = document.getElementById("watch-indicator");
  if (btnWatch) btnWatch.style.display = watching ? "none" : "";
  if (btnStop) btnStop.style.display = watching ? "" : "none";
  if (indicator) indicator.style.display = watching ? "" : "none";
}

function startWatching(topic) {
  stopWatching();
  state.watching = topic;
  setWatchUI(true);
}

function stopWatching() {
  stopContinuousPublish();
  state.watching = null;
  setWatchUI(false);
}

function showMsgCard(msg) {
  const card = document.getElementById("last-msg");
  if (!card) return;
  card.className = "data-card";
  card.textContent = prettyJson(msg);
}

async function doPublish(topic) {
  const textarea = document.getElementById("publish-msg");
  const payload = textarea.value;
  if (!payload) {
    toast("Enter a payload to publish", "error");
    return;
  }
  pushPublishHistory(topic, payload);
  renderPublishHistory(topic);
  state.mqttClient.publish(topic, payload);
  toast("Published", "ok");
}

// ── Pinned topics ─────────────────────────────────────────────────────────────

function togglePin(topic) {
  if (state.pinnedTopics[topic]) unpinTopic(topic);
  else pinTopic(topic);
}

function pinTopic(topic) {
  if (state.pinnedTopics[topic] || !isConnected()) return;
  state.pinnedTopics[topic] = { lastMsg: null };
  renderPinnedRow();
  renderSidebar();
}

function unpinTopic(topic) {
  if (!state.pinnedTopics[topic]) return;
  delete state.pinnedTopics[topic];
  renderPinnedRow();
  renderSidebar();
}

function unpinAllTopics() {
  state.pinnedTopics = {};
  renderPinnedRow();
}

function renderPinnedRow() {
  const row = document.getElementById("pinned-row");
  const pinned = Object.entries(state.pinnedTopics);
  row.hidden = !pinned.length;
  row.innerHTML = "";

  for (const [topic, entry] of pinned) {
    const id = cssId(topic);
    const safe = escHtml(topic);
    const msg = entry.lastMsg !== null ? escHtml(entry.lastMsg) : "Waiting…";

    const card = document.createElement("div");
    card.className = "watch-card";
    card.id = `watch-card-${id}`;
    card.innerHTML = `
      <div class="watch-card-header">
        <span class="watch-card-name" title="${safe}">${safe}</span>
        <button class="watch-card-unpin" aria-label="Unpin ${safe}">✕</button>
      </div>
      <div class="watch-card-msg" id="watch-msg-${id}">${msg}</div>
    `;
    card.querySelector(".watch-card-unpin").addEventListener("click", () => unpinTopic(topic));
    row.appendChild(card);
  }
}

function updateWatchCard(topic) {
  const entry = state.pinnedTopics[topic];
  if (!entry) return;
  const el = document.getElementById(`watch-msg-${cssId(topic)}`);
  if (el && entry.lastMsg !== null) {
    el.textContent = prettyJson(entry.lastMsg);
  }
}

// ── Core MQTT tool implementations ────────────────────────────────────────────

function subscribeOnce(topic, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    if (!isConnected()) return reject(new Error("Not connected"));
    let cb;
    const timer = setTimeout(() => {
      if (state.onceCallbacks[topic]) {
        state.onceCallbacks[topic] = state.onceCallbacks[topic].filter(c => c !== cb);
      }
      reject(new Error(`Timeout waiting for message on ${topic}`));
    }, timeoutMs);
    cb = (msg) => { clearTimeout(timer); resolve(msg); };
    if (!state.onceCallbacks[topic]) state.onceCallbacks[topic] = [];
    state.onceCallbacks[topic].push(cb);
  });
}

async function subscribeForDuration(topic, durationSec, maxMessages = 100) {
  if (!isConnected()) throw new Error("Not connected");
  const collected = [];
  if (!state.topicListeners[topic]) state.topicListeners[topic] = new Set();

  return new Promise(resolve => {
    const cb = (msg) => {
      collected.push(msg);
      if (collected.length >= maxMessages) {
        state.topicListeners[topic]?.delete(cb);
        resolve(collected);
      }
    };
    state.topicListeners[topic].add(cb);
    setTimeout(() => {
      state.topicListeners[topic]?.delete(cb);
      resolve(collected);
    }, durationSec * 1000);
  });
}

// ── Tools ─────────────────────────────────────────────────────────────────────

const TOOLS = [
  {
    name: "connect_to_broker",
    description: "Set the MQTT broker WebSocket URL and reconnect.",
    parameters: {
      type: "object",
      properties: {
        ip:   { type: "string", description: "MQTT broker host IP or hostname", default: "127.0.0.1" },
        port: { type: "number", description: "MQTT WebSocket port", default: 9001 },
      },
      required: ["ip"],
    },
    handler: async ({ ip, port = 9001 }) => {
      const url = `ws://${ip}:${port}`;
      document.getElementById("url-input").value = url;
      connect(url);
      return { status: "connecting", url };
    },
  },
  {
    name: "get_topics",
    description: "List all MQTT topics seen since connecting (via wildcard # subscription).",
    parameters: { type: "object", properties: {} },
    handler: async () => ({ topics: state.seenTopics }),
  },
  {
    name: "subscribe_once",
    description: "Wait for the next message on an MQTT topic and return its payload.",
    parameters: {
      type: "object",
      properties: {
        topic:   { type: "string", description: "MQTT topic, e.g. devices/d4e9f4a2a044/led/command" },
        timeout: { type: "number", description: "Timeout in seconds (default 5)", default: 5 },
      },
      required: ["topic"],
    },
    handler: async ({ topic, timeout = 5 }) => {
      const msg = await subscribeOnce(topic, timeout * 1000);
      if (state.selected?.name === topic) showMsgCard(msg);
      return { topic, payload: msg };
    },
  },
  {
    name: "subscribe_for_duration",
    description: "Collect all messages on an MQTT topic for a given duration.",
    parameters: {
      type: "object",
      properties: {
        topic:        { type: "string" },
        duration:     { type: "number", description: "Duration in seconds" },
        max_messages: { type: "number", description: "Stop after this many messages", default: 100 },
      },
      required: ["topic", "duration"],
    },
    handler: async ({ topic, duration, max_messages = 100 }) => {
      const msgs = await subscribeForDuration(topic, duration, max_messages);
      return { topic, messages: msgs, count: msgs.length };
    },
  },
  {
    name: "publish",
    description: "Publish a message to an MQTT topic.",
    parameters: {
      type: "object",
      properties: {
        topic:   { type: "string", description: "MQTT topic to publish to" },
        payload: { type: "string", description: "Message payload, e.g. 'true', 'false', or a JSON string" },
      },
      required: ["topic", "payload"],
    },
    handler: async ({ topic, payload }) => {
      if (!isConnected()) throw new Error("Not connected");
      state.mqttClient.publish(topic, payload);
      return { published: true, topic, payload };
    },
  },
  {
    name: "publish_sequence",
    description: "Publish a sequence of messages to a topic with delays between each.",
    parameters: {
      type: "object",
      properties: {
        topic:     { type: "string" },
        payloads:  { type: "array", items: { type: "string" }, description: "Array of message payloads" },
        durations: { type: "array", items: { type: "number" }, description: "Delay in seconds after each message" },
      },
      required: ["topic", "payloads", "durations"],
    },
    handler: async ({ topic, payloads, durations }) => {
      if (!isConnected()) throw new Error("Not connected");
      for (let i = 0; i < payloads.length; i++) {
        state.mqttClient.publish(topic, payloads[i]);
        await sleep((durations[i] || 0) * 1000);
      }
      return { published: payloads.length, topic };
    },
  },
];

// ── WebMCP tool registration ───────────────────────────────────────────────────

let _webmcpActive = false;

function registerWebMCPTools() {
  const badge = document.getElementById("webmcp-badge");

  if (!navigator.modelContext) {
    console.info("[WebMCP] navigator.modelContext not available — tools not registered");
    updateWebMCPBadge(badge, 0);
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
        execute: (params) => chatExecuteToolCall(tool.name, params),
      });
      registered++;
    } catch (err) {
      lastError = err;
      console.warn(`[WebMCP] Failed to register tool "${tool.name}":`, err);
    }
  }

  if (registered === 0) {
    console.error("[WebMCP] No tools registered. Last error:", lastError);
  } else {
    console.info(`[WebMCP] Registered ${registered} tools`);
  }
  updateWebMCPBadge(badge, registered);
}

function updateWebMCPBadge(badge, registered) {
  _webmcpActive = registered > 0;
  badge.className = "webmcp-badge" + (_webmcpActive ? " ok" : "");
  badge.textContent = _webmcpActive ? `WebMCP · ${registered} tools` : "WebMCP · inactive";
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
  if (result.error) {
    toast(`Replay failed: ${result.error}`, "error");
  } else {
    toast(`Replayed ${entry.toolName}`, "ok");
  }
}

// ── Chat ──────────────────────────────────────────────────────────────────────

function clearChatHistory() {
  chatState.convMsgs = [];
  document.getElementById("chat-messages").innerHTML = "";
}

const GITHUB_CLIENT_ID = "Ov23lioKDt8Os7hdiSEh";
const CORS_PROXY_URL = "https://cors-proxy.jonasneves.workers.dev";
const OAUTH_CALLBACK_ORIGIN = "https://neevs.io";

const chatState = {
  provider: "anthropic",
  model: "claude-sonnet-4-6",
  claudeKey: (window.DASHBOARD_CONFIG?.anthropicApiKey) || localStorage.getItem("webmcp-claude-key") || "",
  githubAuth: JSON.parse(localStorage.getItem("webmcp-gh-auth") || "null"),
  convMsgs: [],
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
    clearChatHistory();
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
  document.getElementById("chat-clear").addEventListener("click", clearChatHistory);
  document.addEventListener("keydown", (e) => {
    const panel = document.getElementById("chat-panel");
    if (!panel || panel.hidden) return;
    if (e.key.length !== 1 || e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = document.activeElement?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || document.activeElement?.isContentEditable) return;
    const chatInput = document.getElementById("chat-input");
    if (chatInput && !chatInput.disabled) chatInput.focus();
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
  const isGitHub = provider === "github";
  document.getElementById("chat-claude-bar").style.display = isGitHub ? "none" : "";
  document.getElementById("chat-github-bar").style.display = isGitHub ? "" : "none";
  document.getElementById("github-notice").hidden = !isGitHub || !!localStorage.getItem("webmcp-github-notice-dismissed");
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
      clearChatHistory();
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
    "You are an AI assistant embedded in the MQTT AI Dashboard.",
    "You have access to MQTT tools to inspect and control a robot via an MQTT broker.",
  ];
  if (isConnected()) {
    lines.push(`Connected to MQTT broker at ${state.url}.`);
    lines.push(`Known topics (${state.seenTopics.length}): ${state.seenTopics.slice(0, 20).join(", ")}${state.seenTopics.length > 20 ? "…" : ""}`);
  } else {
    lines.push("The broker is not currently connected. Use connect_to_broker to connect first.");
  }
  if (state.selected) lines.push(`User is currently viewing topic "${state.selected.name}".`);
  lines.push("Publish payloads as plain strings (e.g. 'true', 'false', '42') or JSON strings.");
  lines.push("Use the provided tools to answer questions and control the robot. Be concise.");
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
    handleStreamError(err);
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
      handleStreamError(err);
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
      handleStreamError(err, "Stream error: ");
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
      handleStreamError(err);
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
            const entry = tcMap[tc.index] ??= { id: "", name: "", arguments: "", _shown: false };
            if (tc.id) entry.id = tc.id;
            if (tc.function?.name) entry.name = tc.function.name;
            if (tc.function?.arguments) entry.arguments += tc.function.arguments;
            if (!entry._shown && entry.id && entry.name) {
              entry._shown = true;
              appendChatToolCall(entry.id, entry.name);
            }
          }
        }
      }
    } catch (err) {
      handleStreamError(err, "Stream error: ");
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
    const key = params.topic || params.url || "";
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

function handleStreamError(err, prefix = "") {
  hideChatSpinner();
  if (err.name !== "AbortError") {
    appendChatMsg("error", prefix + err.message);
  }
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

document.getElementById("topic-add-input").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  const topic = e.target.value.trim();
  if (!topic) return;
  if (!state.seenTopics.includes(topic)) {
    state.seenTopics.push(topic);
    renderSidebar();
  }
  selectTopic(topic);
  e.target.value = "";
});

for (const btn of document.querySelectorAll("[data-section]")) {
  btn.addEventListener("click", () => {
    const section = btn.dataset.section;
    if (section in state.sidebarCollapsed) {
      state.sidebarCollapsed[section] = !state.sidebarCollapsed[section];
      renderSidebar();
    }
  });
}

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
    for (const entry of state.toolLog) list.appendChild(createLogEntryEl(entry));
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
      <div class="webmcp-popover-explain">The <strong>AI chat panel</strong> on this page already uses these ${TOOLS.length} tools directly via the Anthropic/GitHub API — no flag needed. WebMCP would <em>also</em> expose them to native browser AI agents. Requires Chrome 146+ Canary → <code>chrome://flags/#webmcp-for-testing</code>.</div>
    `;
  }
  popover.appendChild(header);

  const divider = document.createElement("div");
  divider.className = "webmcp-popover-divider";
  divider.textContent = "Tools";
  popover.appendChild(divider);

  for (const tool of TOOLS) {
    const item = document.createElement("div");
    item.className = "webmcp-popover-item";
    item.innerHTML = `
      <div class="webmcp-popover-name">${escHtml(tool.name)}</div>
      <div class="webmcp-popover-desc">${escHtml(tool.description)}</div>
    `;
    popover.appendChild(item);
  }

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
