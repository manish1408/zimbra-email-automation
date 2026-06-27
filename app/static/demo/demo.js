const API_BASE = window.location.origin;
const NODE_LAYOUT = {
  ingest_mailbox: { x: 300, y: 10 },
  enrich_messages: { x: 300, y: 70 },
  classify_intent: { x: 300, y: 130 },
  urgent_escalation: { x: 20, y: 220 },
  compliance_review: { x: 120, y: 220 },
  sales_pipeline: { x: 220, y: 220 },
  support_agent: { x: 320, y: 220 },
  zimbra_tools: { x: 420, y: 300 },
  draft_support_reply: { x: 320, y: 360 },
  newsletter_batch: { x: 520, y: 220 },
  general_briefing: { x: 620, y: 220 },
  merge_insights: { x: 300, y: 430 },
  quality_review: { x: 300, y: 490 },
  refine_output: { x: 180, y: 550 },
  format_executive_report: { x: 300, y: 610 },
};

const state = {
  schema: null,
  nodeStatus: {},
  running: false,
};

const svg = document.getElementById("graph-canvas");
const userSelect = document.getElementById("user-select");
const instructionInput = document.getElementById("instruction");
const runBtn = document.getElementById("run-btn");
const clearBtn = document.getElementById("clear-btn");
const eventLog = document.getElementById("event-log");
const healthStatus = document.getElementById("health-status");

function setHealth(connected, host) {
  healthStatus.textContent = connected ? `Zimbra connected (${host})` : "Zimbra disconnected";
  healthStatus.className = `status-pill ${connected ? "ok" : "bad"}`;
}

async function fetchJson(path, options) {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

function appendLog(type, title, body, className = "") {
  const entry = document.createElement("div");
  entry.className = `log-entry ${className}`.trim();
  entry.innerHTML = `<div class="meta">${type}</div><strong>${title}</strong>${body ? `<div>${body}</div>` : ""}`;
  eventLog.prepend(entry);
  return entry;
}

function resetNodeStatus() {
  state.nodeStatus = {};
  if (state.schema) {
    state.schema.nodes.forEach((node) => {
      state.nodeStatus[node.name] = "pending";
    });
  }
  renderGraph();
}

function setNodeStatus(nodeName, status) {
  if (!nodeName || !state.nodeStatus[nodeName]) return;
  state.nodeStatus[nodeName] = status;
  renderGraph();
}

function nodeColor(status) {
  if (status === "active") return { fill: "#2d4a7a", stroke: "#5b8def" };
  if (status === "done") return { fill: "#1f3d32", stroke: "#3dd68c" };
  return { fill: "#1e2430", stroke: "#2a2f3a" };
}

function renderGraph() {
  if (!state.schema) return;
  const edges = state.schema.edges || [];
  const width = 800;
  const height = 680;
  let svgContent = "";

  edges.forEach((edge) => {
    const fromKey = edge.from === "__start__" ? "ingest_mailbox" : edge.from;
    const targets = edge.paths || (edge.to === "__end__" ? ["format_executive_report"] : [edge.to]);
    const from = NODE_LAYOUT[fromKey];
    if (!from) return;
    targets.forEach((target) => {
      const resolved = target === "__end__" ? "format_executive_report" : target;
      const to = NODE_LAYOUT[resolved];
      if (!to) return;
      const x1 = from.x + 70;
      const y1 = from.y + 24;
      const x2 = to.x + 70;
      const y2 = to.y;
      svgContent += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#3a4252" stroke-width="1.5" marker-end="url(#arrow)" />`;
      if (edge.condition) {
        svgContent += `<text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 6}" fill="#9aa0a6" font-size="10" text-anchor="middle">${edge.condition}</text>`;
      }
    });
  });

  state.schema.nodes.forEach((node) => {
    const pos = NODE_LAYOUT[node.name];
    if (!pos) return;
    const status = state.nodeStatus[node.name] || "pending";
    const colors = nodeColor(status);
    const label = node.name.replace(/_/g, " ");
    svgContent += `
      <rect x="${pos.x}" y="${pos.y}" width="140" height="48" rx="8"
        fill="${colors.fill}" stroke="${colors.stroke}" stroke-width="1.5" />
      <text x="${pos.x + 70}" y="${pos.y + 28}" fill="#e8eaed" font-size="11"
        text-anchor="middle">${label}</text>
    `;
  });

  svg.innerHTML = `
    <defs>
      <marker id="arrow" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto">
        <path d="M0,0 L6,3 L0,6 Z" fill="#3a4252" />
      </marker>
    </defs>
    ${svgContent}
  `;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
}

async function loadSchema() {
  state.schema = await fetchJson("/api/v1/agent/schema");
  resetNodeStatus();
}

async function loadUsers() {
  const data = await fetchJson("/api/v1/users");
  userSelect.innerHTML = "";
  if (!data.users.length) {
    userSelect.innerHTML = '<option value="">No users found</option>';
    return;
  }
  data.users.forEach((user) => {
    const option = document.createElement("option");
    option.value = user.email;
    option.textContent = user.display_name ? `${user.display_name} (${user.email})` : user.email;
    userSelect.appendChild(option);
  });
}

async function loadHealth() {
  try {
    const health = await fetchJson("/api/v1/system/health");
    setHealth(health.zimbra_connected, health.zimbra_host);
  } catch {
    setHealth(false, "unknown");
  }
}

function formatClassifications(items) {
  if (!items || !items.length) return "";
  return items
    .map((item) => `• ${item.subject || item.message_id}: ${item.intent || item.category} (p${item.priority})`)
    .join("<br>");
}

async function runAgent() {
  const userEmail = userSelect.value;
  if (!userEmail) {
    appendLog("Error", "Select a mailbox first", "", "error");
    return;
  }

  state.running = true;
  runBtn.disabled = true;
  resetNodeStatus();
  appendLog("Run", `Starting agent for ${userEmail}`, instructionInput.value || "No focus provided");

  const payload = {
    user_email: userEmail,
    instruction: instructionInput.value || null,
  };

  const response = await fetch(`${API_BASE}/api/v1/agent/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const message = await response.text();
    appendLog("Error", "Stream failed", message, "error");
    state.running = false;
    runBtn.disabled = false;
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";

    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith("data: ")) continue;
      const data = JSON.parse(line.slice(6));

      if (data.type === "node_start" && data.node) {
        setNodeStatus(data.node, "active");
        appendLog("Node", data.node, "Started", "active");
      } else if (data.type === "node_end" && data.node) {
        setNodeStatus(data.node, "done");
        let body = "";
        if (data.dominant_intent) body += `Dominant intent: ${data.dominant_intent}<br>`;
        if (data.dominant_category) body += `Category: ${data.dominant_category}<br>`;
        if (data.executive_report) body += `<br>${data.executive_report}`;
        if (data.classifications) body += formatClassifications(data.classifications);
        if (data.summary) body += `<br>${data.summary}`;
        if (data.draft_reply) body += `<br><em>Draft:</em> ${data.draft_reply}`;
        if (data.archive_suggestion) body += `<br>${data.archive_suggestion}`;
        appendLog("Node", data.node, body || "Completed", "done");
      } else if (data.type === "token" && data.content) {
        const first = eventLog.querySelector(".log-entry.token-stream");
        if (first) {
          first.querySelector("div:last-child").textContent += data.content;
        } else {
          appendLog("Token", "Model output", data.content, "token-stream");
        }
      } else if (data.type === "done") {
        const result = data.result || {};
        appendLog(
          "Done",
          "Agent finished",
          `Intent: ${result.dominant_intent || result.dominant_category || "n/a"} · Messages: ${result.message_count || 0}`,
          "done",
        );
      } else if (data.type === "error") {
        appendLog("Error", "Agent failed", data.message, "error");
      }
    }
  }

  state.running = false;
  runBtn.disabled = false;
}

clearBtn.addEventListener("click", () => {
  eventLog.innerHTML = "";
  resetNodeStatus();
});

runBtn.addEventListener("click", () => {
  runAgent().catch((error) => {
    appendLog("Error", "Unexpected failure", error.message, "error");
    state.running = false;
    runBtn.disabled = false;
  });
});

Promise.all([loadSchema(), loadUsers(), loadHealth()]).catch((error) => {
  appendLog("Error", "Initialization failed", error.message, "error");
});
