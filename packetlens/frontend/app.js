// PacketLens frontend — plain JS, no build step required.

const state = {
  packets: [],
  filtered: [],
  selected: null,
  liveActive: false,
  eventSource: null,
  langMode: "plain", // "plain" | "technical" — controls the packet-list Info column
};

const $ = (sel) => document.querySelector(sel);
const tbody = $("#packet-tbody");
const table = $("#packet-table");
const detailPanel = $("#detail-panel");
const statusPill = $("#status-pill");
const aiStatusPill = $("#ai-status-pill");
const filterInput = $("#filter-input");
const narrativeBox = $("#narrative-box");

// ---------------------------------------------------------------------
// AI status (Claude API vs offline templates)
// ---------------------------------------------------------------------

fetch("/api/ai/status")
  .then((r) => r.json())
  .then((d) => {
    if (d.ai_enabled) {
      aiStatusPill.textContent = "🤖 AI explanations: ON (" + d.model + ")";
      aiStatusPill.classList.add("ai-on");
    } else {
      aiStatusPill.textContent = "🤖 AI explanations: OFF — set ANTHROPIC_API_KEY";
      aiStatusPill.classList.add("ai-off");
    }
  })
  .catch(() => {
    aiStatusPill.textContent = "🤖 AI status unknown";
  });

// ---------------------------------------------------------------------
// Plain English / Technical toggle
// ---------------------------------------------------------------------

$("#btn-plain").addEventListener("click", () => setLangMode("plain"));
$("#btn-technical").addEventListener("click", () => setLangMode("technical"));

function setLangMode(mode) {
  state.langMode = mode;
  $("#btn-plain").classList.toggle("active", mode === "plain");
  $("#btn-technical").classList.toggle("active", mode === "technical");
  table.classList.toggle("technical", mode === "technical");
  renderTable();
  if (state.selected) renderDetail(state.selected);
}

// ---------------------------------------------------------------------
// Loading captures
// ---------------------------------------------------------------------

async function loadFromResponse(promise) {
  setStatus("loading…");
  try {
    const res = await promise;
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      throw new Error(err.error || "request failed");
    }
    const data = await res.json();
    state.packets = data.packets;
    applyFilter();
    safeRenderSummary(data.stats);
    setStatus(`${data.meta.packet_count} packets loaded`);
  } catch (e) {
    setStatus("error: " + e.message, true);
  }
}

$("#btn-sample").addEventListener("click", () => {
  loadFromResponse(fetch("/api/sample"));
});

$("#btn-upload").addEventListener("click", () => $("#file-input").click());

$("#file-input").addEventListener("change", (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  loadFromResponse(
    file.arrayBuffer().then((buf) =>
      fetch("/api/upload", {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: buf,
      })
    )
  );
});

// ---------------------------------------------------------------------
// Live mode (SSE). In this demo environment there is no privileged
// capture agent running, so "live" replays the sample capture over the
// same streaming channel a real agent would use (see agent/capture_agent.py).
// Each replayed/live packet is explained server-side (AI if configured,
// else the offline template) before it reaches the browser.
// ---------------------------------------------------------------------

$("#btn-live").addEventListener("click", () => {
  if (state.liveActive) {
    stopLive();
  } else {
    startLive();
  }
});

function startLive() {
  state.packets = [];
  applyFilter();
  safeRenderSummary({ protocol_counts: {}, total_packets: 0, total_bytes: 0, top_conversations: [] });

  state.eventSource = new EventSource("/api/live/stream");
  state.eventSource.onmessage = (ev) => {
    const pkt = JSON.parse(ev.data);
    state.packets.push(pkt);
    applyFilter();
    safeRenderSummary(computeStatsClientSide());
  };
  state.eventSource.onerror = () => {
    setStatus("live stream error / disconnected", true);
  };

  fetch("/api/live/replay", { method: "POST" });

  state.liveActive = true;
  $("#btn-live").textContent = "■ Stop live";
  $("#btn-live").classList.add("live-active");
  statusPill.textContent = "live";
  statusPill.classList.add("live");
}

function stopLive() {
  if (state.eventSource) state.eventSource.close();
  // Tell the server to actually stop the replay loop -- otherwise it would
  // keep looping (and explaining/broadcasting packets) in the background
  // even with no one watching, since it now runs continuously by design.
  fetch("/api/live/stop", { method: "POST" }).catch(() => {});
  state.liveActive = false;
  $("#btn-live").textContent = "▶ Start live (demo)";
  $("#btn-live").classList.remove("live-active");
  statusPill.textContent = "idle";
  statusPill.classList.remove("live");
}

function computeStatsClientSide() {
  const proto_counts = {};
  let total_bytes = 0;
  const convo = {};
  for (const p of state.packets) {
    const proto = p.summary.protocol;
    proto_counts[proto] = (proto_counts[proto] || 0) + 1;
    total_bytes += p.length || 0;
    const a = p.summary.src, b = p.summary.dst;
    if (a && b) {
      const key = [a, b].sort().join("|");
      convo[key] = (convo[key] || 0) + 1;
    }
  }
  const top_conversations = Object.entries(convo)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([key, packets]) => {
      const [a, b] = key.split("|");
      return { a, b, packets };
    });
  return { protocol_counts: proto_counts, total_packets: state.packets.length, total_bytes, top_conversations };
}

// ---------------------------------------------------------------------
// Filtering (a small subset of Wireshark display-filter syntax)
// ---------------------------------------------------------------------

filterInput.addEventListener("input", () => applyFilter());

function packetMatchesFilter(pkt, filterText) {
  const f = filterText.trim().toLowerCase();
  if (!f) return true;

  // ip==x.x.x.x  or  port==N
  const eqMatch = f.match(/^(ip|port)\s*==\s*(.+)$/);
  if (eqMatch) {
    const [, key, val] = eqMatch;
    if (key === "ip") {
      return pkt.summary.src === val || pkt.summary.dst === val;
    }
    if (key === "port") {
      const layers = pkt.layers || {};
      const tcp = layers.tcp, udp = layers.udp;
      const p = Number(val);
      return (tcp && (tcp.src_port === p || tcp.dst_port === p)) ||
             (udp && (udp.src_port === p || udp.dst_port === p));
    }
  }

  // bare protocol/keyword match against protocol name, technical info, or
  // the plain-English sentence (so e.g. typing "ping" or "webpage" works)
  const proto = (pkt.summary.protocol || "").toLowerCase();
  const info = (pkt.summary.info || "").toLowerCase();
  const plain = (pkt.summary.plain || "").toLowerCase();
  return proto.includes(f) || info.includes(f) || plain.includes(f) ||
         (pkt.summary.src || "").toLowerCase().includes(f) ||
         (pkt.summary.dst || "").toLowerCase().includes(f);
}

function applyFilter() {
  const f = filterInput.value;
  state.filtered = state.packets.filter((p) => packetMatchesFilter(p, f));
  renderTable();
}

// ---------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------

function renderTable() {
  if (state.filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty-hint">No packets match.</td></tr>`;
    return;
  }
  const rows = state.filtered.map((p) => {
    const proto = p.summary.protocol || "";
    const protoClass = "proto-" + proto.replace(/[^A-Za-z0-9]/g, "");
    const infoText = state.langMode === "plain"
      ? (p.summary.plain || p.summary.info || "")
      : (p.summary.info || "");
    return `<tr data-num="${p.number}">
      <td>${p.number}</td>
      <td>${formatTime(p.timestamp)}</td>
      <td>${escapeHtml(p.summary.src || "")}</td>
      <td>${escapeHtml(p.summary.dst || "")}</td>
      <td><span class="proto-badge ${protoClass}">${escapeHtml(proto)}</span></td>
      <td>${p.length}</td>
      <td class="info-cell">${escapeHtml(infoText)}</td>
    </tr>`;
  });
  tbody.innerHTML = rows.join("");

  tbody.querySelectorAll("tr[data-num]").forEach((tr) => {
    tr.addEventListener("click", () => selectPacket(Number(tr.dataset.num)));
  });

  // auto-scroll to bottom during live capture
  if (state.liveActive) {
    document.getElementById("packet-table-wrap").scrollTop = 1e9;
  }
}

function selectPacket(num) {
  const pkt = state.packets.find((p) => p.number === num);
  if (!pkt) return;
  state.selected = pkt;

  tbody.querySelectorAll("tr").forEach((tr) => tr.classList.remove("selected"));
  const row = tbody.querySelector(`tr[data-num="${num}"]`);
  if (row) row.classList.add("selected");

  renderDetail(pkt);
}

function renderDetail(pkt) {
  const layers = pkt.layers || {};
  const blocks = [];

  if (pkt.summary && pkt.summary.plain) {
    const source = pkt.summary.plain_source === "ai" ? "AI-generated" : "offline template";
    blocks.push(
      `<div class="plain-banner"><span class="label">In plain English · ${escapeHtml(source)}</span>${escapeHtml(pkt.summary.plain)}</div>`
    );
  }

  blocks.push(layerBlock("Frame", {
    "Number": pkt.number,
    "Timestamp": pkt.timestamp_iso || pkt.timestamp,
    "Length on wire": pkt.length + " bytes",
    "Captured length": pkt.captured_length + " bytes",
  }));

  const order = ["ethernet", "arp", "ipv4", "ipv6", "tcp", "udp", "icmp"];
  const labels = {
    ethernet: "Ethernet II", arp: "Address Resolution Protocol",
    ipv4: "Internet Protocol Version 4", ipv6: "Internet Protocol Version 6",
    tcp: "Transmission Control Protocol", udp: "User Datagram Protocol",
    icmp: "Internet Control Message Protocol",
  };
  for (const key of order) {
    if (layers[key]) blocks.push(layerBlock(labels[key], layers[key]));
  }

  detailPanel.innerHTML = blocks.join("");
}

function layerBlock(title, obj) {
  const rows = Object.entries(obj).map(([k, v]) => {
    const val = Array.isArray(v) ? v.join(", ") : String(v);
    return `<div class="k">${escapeHtml(prettyKey(k))}</div><div>${escapeHtml(val)}</div>`;
  }).join("");
  return `<div class="layer-block"><h3>${escapeHtml(title)}</h3><div class="kv">${rows}</div></div>`;
}

function prettyKey(k) {
  return k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const PROTO_PLAIN_NAMES = {
  HTTP: "web page loading (HTTP)",
  "TLS/HTTPS": "secure web browsing (HTTPS)",
  DNS: "looking up website addresses (DNS)",
  SSH: "a secure remote terminal session (SSH)",
  FTP: "file transfer (FTP)",
  ARP: "devices finding each other's hardware addresses on the local network (ARP)",
  ICMP: "connectivity checks / pings (ICMP)",
  TCP: "general data exchange (TCP)",
  UDP: "general data exchange (UDP)",
};
const NARRATIVE_ORDER = ["HTTP", "TLS/HTTPS", "DNS", "SSH", "FTP", "ARP", "ICMP", "TCP", "UDP"];

// Mirrors backend/plain_english.py's capture_narrative(), for live mode
// where stats are computed client-side and never touch the backend.
function buildNarrativeClientSide(stats) {
  const total = stats.total_packets || 0;
  if (total === 0) return "No packets captured yet.";

  const sentences = [`This capture contains ${total} packet${total !== 1 ? "s" : ""}.`];

  const top = (stats.top_conversations || [])[0];
  if (top) {
    sentences.push(`Most of the traffic (${top.packets} packet${top.packets !== 1 ? "s" : ""}) is between ${top.a} and ${top.b}.`);
  }

  const counts = stats.protocol_counts || {};
  const seen = new Set();
  const parts = [];
  for (const proto of NARRATIVE_ORDER) {
    if (counts[proto] != null) {
      const c = counts[proto];
      parts.push(`${PROTO_PLAIN_NAMES[proto] || proto} (${c} packet${c !== 1 ? "s" : ""})`);
      seen.add(proto);
    }
  }
  for (const [proto, c] of Object.entries(counts)) {
    if (!seen.has(proto)) parts.push(`${proto} traffic (${c} packet${c !== 1 ? "s" : ""})`);
  }
  if (parts.length) sentences.push("What's happening: " + parts.join("; ") + ".");

  return sentences.join(" ");
}

function safeRenderSummary(stats) {
  try {
    renderSummary(stats);
  } catch (e) {
    console.error("renderSummary failed (continuing anyway):", e);
  }
}

function renderSummary(stats) {
  $("#stat-count").textContent = stats.total_packets;
  $("#stat-bytes").textContent = formatBytes(stats.total_bytes);

  narrativeBox.className = "narrative-box";
  narrativeBox.textContent = stats.narrative || buildNarrativeClientSide(stats);

  const convoEl = $("#conversations-list");
  if (!stats.top_conversations || stats.top_conversations.length === 0) {
    convoEl.className = "empty-hint";
    convoEl.textContent = "—";
  } else {
    convoEl.className = "";
    convoEl.innerHTML = stats.top_conversations.map((c) =>
      `<div class="stat-row"><span>${escapeHtml(c.a)} ↔ ${escapeHtml(c.b)}</span><span>${c.packets}</span></div>`
    ).join("");
  }

  renderChart(stats.protocol_counts || {});
}

// Dependency-free protocol-distribution visualization: a proportional
// segmented bar plus a legend, built with plain HTML/CSS. Deliberately NOT
// using a charting library loaded from a CDN — on locked-down/corporate
// networks an external script can silently fail to load, and (before this
// fix) that took the rest of the summary panel and live-capture startup
// down with it. This has zero external dependencies, so it always renders.
const CHART_PALETTE = ["#3fb6f2", "#4fd68a", "#f2b53f", "#f25f5f", "#b58cf2", "#f27ca0", "#8298a8", "#5ad1c9"];

function renderChart(protoCounts) {
  const container = document.getElementById("proto-chart");
  const entries = Object.entries(protoCounts);
  const total = entries.reduce((sum, [, count]) => sum + count, 0);

  if (total === 0) {
    container.innerHTML = '<div class="chart-empty">No traffic yet.</div>';
    return;
  }

  const sorted = entries.sort((a, b) => b[1] - a[1]);

  const segments = sorted.map(([proto, count], i) => {
    const pct = (count / total) * 100;
    const color = CHART_PALETTE[i % CHART_PALETTE.length];
    return `<div class="chart-segment" style="width:${pct}%;background:${color}" title="${escapeHtml(proto)}: ${count} (${pct.toFixed(1)}%)"></div>`;
  }).join("");

  const legend = sorted.map(([proto, count], i) => {
    const pct = (count / total) * 100;
    const color = CHART_PALETTE[i % CHART_PALETTE.length];
    return `<div class="chart-legend-row">
      <span class="chart-swatch" style="background:${color}"></span>
      <span class="chart-legend-label">${escapeHtml(proto)}</span>
      <span class="chart-legend-value">${count} (${pct.toFixed(1)}%)</span>
    </div>`;
  }).join("");

  container.innerHTML = `<div class="chart-bar">${segments}</div><div class="chart-legend">${legend}</div>`;
}

// ---------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------

function formatTime(ts) {
  const d = new Date(ts * 1000);
  return d.toISOString().split("T")[1].replace("Z", "");
}

function formatBytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / (1024 * 1024)).toFixed(2) + " MB";
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function setStatus(msg, isError) {
  statusPill.textContent = msg;
  statusPill.style.color = isError ? "#f25f5f" : "";
}
