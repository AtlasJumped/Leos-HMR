/* Mission Control shell (DESIGN.md §5). Zero build step, vanilla JS.
 * - views + lazy iframe mount/unmount from state/layout.json (Claude panel pinned)
 * - SSE client: per-panel reloads, CSS cache-buster swaps, mode/fx state refresh
 * - kiosk heartbeat → watcherd (probe-kiosk-pingback reads it)
 * - keyboard guards (Ctrl+W/T/N/F5) at the top level
 * - Claude iframe: never reloaded by the SSE path; remounted ONLY when its endpoint dies
 *   (the one sanctioned exception, §6)
 */
"use strict";

const grid = document.getElementById("grid");
const viewbar = document.getElementById("viewbar");
let layout = { views: {} };
let currentView = "default";
let token = "";
const mounted = new Map(); // panelId -> iframe

async function j(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

async function boot() {
  try { token = (await (await fetch("/token", {cache:"no-store"})).text()).trim(); } catch {}
  try { layout = await j("/state/layout.json"); } catch (e) { banner("layout.json unreadable: " + e); }
  buildViewbar();
  mountView(localStorage.getItem("mc-view") || layout.default_view || "default");
  refreshModeState();
  refreshSimPanel();
  connectSSE();
  setInterval(heartbeat, 20000); heartbeat();
  setInterval(gpuStrip, 10000); gpuStrip();
  checkSession();
  guardKeys();
  watchClaude();
}

function buildViewbar() {
  viewbar.textContent = "";
  for (const name of Object.keys(layout.views)) {
    const b = document.createElement("button");
    b.textContent = name;
    b.onclick = () => mountView(name);
    viewbar.appendChild(b);
  }
}

function mountView(name) {
  if (!layout.views[name]) name = Object.keys(layout.views)[0] || "default";
  currentView = name;
  localStorage.setItem("mc-view", name);
  document.documentElement.dataset.view = name;
  const want = layout.views[name].panels || [];
  const wantIds = new Set(want.map(p => p.id));
  // unmount panels not in this view — EXCEPT the pinned Claude panel (§5 lazy mount)
  for (const [id, el] of mounted) {
    if (id !== "claude" && !wantIds.has(id)) { el.parentElement.remove(); mounted.delete(id); }
  }
  grid.style.gridTemplateAreas = layout.views[name].areas || "";
  for (const p of want) mountPanel(p);
  if (!mounted.has("claude")) mountPanel({ id: "claude", src: "/claude/", area: "claude" });
}

function mountPanel(p) {
  let frame = mounted.get(p.id);
  if (!frame) {
    const cell = document.createElement("section");
    cell.className = "panel";
    cell.dataset.panel = p.id;
    const h = document.createElement("header");
    h.textContent = p.title || p.id;
    const f = document.createElement("iframe");
    f.src = p.src;
    f.loading = "lazy";
    f.allow = "clipboard-read; clipboard-write";
    cell.append(h, f);
    grid.appendChild(cell);
    mounted.set(p.id, f);
    // focus management: clicking a panel visibly focuses its iframe (§5)
    cell.addEventListener("mousedown", () => {
      document.querySelectorAll(".panel.focused").forEach(x => x.classList.remove("focused"));
      cell.classList.add("focused");
      f.focus();
    });
    frame = f;
  }
  frame.parentElement.style.gridArea = p.area || p.id;
}

function connectSSE() {
  const es = new EventSource("/events");
  es.onmessage = (ev) => {
    let m; try { m = JSON.parse(ev.data); } catch { return; }
    handleEvent(m.panel, m.action);
  };
  es.onerror = () => { es.close(); setTimeout(connectSSE, 3000); };
}

let intentionalReload = false;
function reloadShell() { intentionalReload = true; location.reload(); }

function handleEvent(panel, action) {
  if (action === "none") return;          // watch-map's suppression escape hatch (review)
  if (panel === "shell-css") {            // swap stylesheet with cache-buster — no reload
    const link = document.getElementById("persona-css");
    link.href = "/shell/persona.css?ts=" + Date.now();
    refreshModeState();
    return;
  }
  if (panel === "shell") { reloadShell(); return; }       // shell page itself changed
  if (panel === "state") { refreshModeState(); return; }
  if (panel === "claude") return;         // NEVER reload the Claude panel from SSE (§2)
  if (panel === "sim") { refreshSimPanel(); return; }     // consumer end of §10 (review)
  const f = mounted.get(panel);
  if (f && action === "reload") f.src = f.src.split("#")[0];
}

async function refreshSimPanel() {
  const f = mounted.get("sim");
  if (!f) return;
  try {
    const meta = await j("/state/sim.json");
    const url = meta.viewer_url || "about:blank";
    if (!/^http:\/\/127\.0\.0\.1:\d+/.test(url) && url !== "about:blank") return;
    if (f.src !== url) f.src = url;
  } catch { f.src = "about:blank"; }
}

async function refreshModeState() {
  try {
    const mode = await j("/state/mode.json");
    document.getElementById("mode-name").textContent = mode.mode || "—";
    const bg = document.getElementById("motion-bg");
    if (mode.shellbg) {
      const src = (mode.assets_base || "") + mode.shellbg;
      if (!bg.src.endsWith(src)) bg.src = src;
    } else { bg.removeAttribute("src"); }
  } catch {}
  try {
    const fx = await j("/state/fx.json");
    document.getElementById("fx-level").textContent = "fx: " + fx.level;
    const bg = document.getElementById("motion-bg");
    if (fx.level === "full" && bg.src) bg.play().catch(() => {});
    else bg.pause();
  } catch {}
}

async function heartbeat() {
  // token-gated (review: an open heartbeat is CSRF-able and would let any local page fake
  // kiosk liveness, suppressing the §4.3 recovery path)
  try {
    await fetch("/heartbeat", { method: "POST",
      headers: { "X-Aletheon-Token": token } });
  } catch {}
}

async function gpuStrip() {
  // GPU telemetry lives here (same-origin via the gateway), NOT in Glance — a bridge-mode
  // container cannot reach host-loopback watcherd (review).
  try {
    const m = await j("/metrics/gpu");
    document.getElementById("gpu-strip").textContent = (m.gpus || []).map(g =>
      `GPU${g.index} ${g.pstate} ${g.util}% dec${g.dec}% ${g.mem_used}/${g.mem_total}MiB ` +
      `${g.temp}°C ${g.power}W`).join("  ·  ") || "gpu: —";
  } catch {}
}

async function checkSession() {
  try {
    const s = await j("/session");
    document.getElementById("session-warn").hidden = s.session_type === "wayland";
  } catch {}
}

function guardKeys() {
  // Chrome kiosk does NOT suppress these (§5). This covers shell focus; the systemd
  // Restart=always unit is the backstop while an iframe has focus.
  window.addEventListener("keydown", (e) => {
    const k = e.key.toLowerCase();
    if ((e.ctrlKey && ["w", "t", "n"].includes(k)) ||
        (e.ctrlKey && e.shiftKey && k === "q") || e.key === "F5") {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);
  // Block only UNINTENDED navigation: preventDefault here pops Chrome's leave dialog,
  // which must never fire for our own programmatic reloads (review).
  window.addEventListener("beforeunload", (e) => {
    if (!intentionalReload) e.preventDefault();
  });
}

function watchClaude() {
  // The sanctioned remount exception (§6): if the ttyd endpoint stops answering,
  // remount ONLY the Claude iframe, with backoff.
  let failures = 0;
  setInterval(async () => {
    try {
      const r = await fetch("/claude/token", { cache: "no-store" });
      if (!r.ok && r.status !== 401) throw new Error("status " + r.status);
      failures = 0;
    } catch {
      failures++;
      if (failures >= 3) {
        failures = 0;
        const f = mounted.get("claude");
        if (f) { banner("Claude panel endpoint died — remounting"); f.src = "/claude/"; }
      }
    }
  }, 15000);
}

function banner(msg) {
  const el = document.getElementById("session-warn");
  el.textContent = "⚠ " + msg;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; checkSession(); }, 15000);
}

boot();
