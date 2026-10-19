// Marks the page as scripted first (so scroll-reveal only hides things when it can also show them).
document.documentElement.classList.add("js");

// ---- live status -----------------------------------------------------------
// Each id maps to a number (up, latency in ms), null (down) or "off" (not enabled on this node).
const CORE = ["api", "database", "object_store", "cache"];

async function timed(url) {
  const t0 = performance.now();
  try {
    const r = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(5000) });
    if (!r.ok) return { ms: null };
    return { ms: Math.round(performance.now() - t0), body: await r.json() };
  } catch { return { ms: null }; }
}

async function sample() {
  const api = await timed("/api/status");
  const c = api.body && api.body.components;
  // No body (API unreachable) => components are unknown, not down.
  const part = k => !c ? undefined : !c[k] ? null : c[k].status === "up" ? (c[k].ms ?? 0) : c[k].status === "disabled" ? "off" : null;
  return {
    api: api.ms,
    database: part("database"),
    object_store: part("object_store"),
    cache: part("cache"),
    local_ai: part("local_ai"),
    __components: c,
    __server: c && c.api ? c.api.ms : undefined,
    __rtt: api.ms,
  };
}

// ---- maintenance log (static /maintenance/log.json, written by scripts/upgrade.sh) ----
// [{start, end|null, title}]. An entry with no `end` is an upgrade in progress. Static on
// purpose: it still answers while the backend is stopped.
let maintLog = [];
const activeMaint = () => maintLog.find(m => !m.end);

async function loadMaint() {
  try {
    const r = await fetch("/maintenance/log.json", { cache: "no-store", signal: AbortSignal.timeout(5000) });
    const j = r.ok ? await r.json() : [];
    maintLog = Array.isArray(j) ? j : [];
  } catch { /* no log => no maintenance */ }
}

function paintDetails(c) {
  if (!c) return;
  document.querySelectorAll("[data-typical]").forEach(e => {
    const x = c[e.dataset.typical];
    e.textContent = !x || x.status === "disabled" ? "Not enabled on this node."
      : x.typical_ms === undefined ? "Gathering a baseline… (needs a few checks)"
      : `Usually ${x.typical_ms} ms; 95% of recent checks under ${x.p95_ms} ms (last ${x.samples} checks).`;
  });
  const list = document.querySelector('[data-checks="api"]');
  if (list && c.api && c.api.checks) {
    list.replaceChildren(...c.api.checks.map(ch => {
      const li = document.createElement("li");
      const dot = document.createElement("span");
      dot.className = "dot " + (ch.status === "up" ? "up" : ch.status === "disabled" ? "off" : "down");
      const name = document.createElement("span");
      name.textContent = ch.label;
      const val = document.createElement("b");
      val.textContent = ch.status === "disabled" ? "Not enabled" : ch.status !== "up" ? "Down" : "Up";
      li.append(dot, name);
      if (ch.status !== "disabled") {
        const pct = document.createElement("span");
        pct.className = "st-pct"; pct.dataset.pct = "api." + ch.id;
        li.append(pct);
      }
      li.append(val);
      if (ch.status !== "disabled") {
        const bars = document.createElement("div");
        bars.className = "st-bars"; bars.dataset.bars = "api." + ch.id;
        li.append(bars);
      }
      return li;
    }));
    if (lastHist) paintBars();  // the list was just rebuilt; redraw its bars
  }
}

function paint(res) {
  paintDetails(res.__components);
  const rtt = document.querySelector("[data-metric=rtt]");
  if (rtt) rtt.textContent = res.__rtt == null ? "Unreachable" : res.__rtt + " ms";
  const srv = document.querySelector("[data-metric=server]");
  if (srv) srv.textContent = res.__server == null ? "\u2014" : res.__server + " ms";
  for (const [id, v] of Object.entries(res)) {
    if (id.startsWith("__")) continue;
    const m = activeMaint() && v !== "off";
    document.querySelectorAll(`[data-dot="${id}"]`).forEach(e => (e.className = "dot " + (m && v === null ? "maint" : v === "off" || v === undefined ? "off" : v === null ? "down" : "up")));
    document.querySelectorAll(`[data-val="${id}"]`).forEach(e => (e.textContent = m && v === null ? "Upgrading" : v === undefined ? "Unknown" : v === "off" ? "Not enabled" : v === null ? "Down"
      : (id === "api" && document.querySelector("[data-metric]") ? "Up" : "Up · " + v + " ms")));
  }
  const banner = document.getElementById("overall");
  if (banner) {
    const core = CORE.filter(k => res[k] !== "off");
    const down = core.filter(k => res[k] === null);
    const apiDown = res.api === null;
    const mt = activeMaint();
    const kind = mt ? "maint" : down.length === 0 ? "" : apiDown ? "down" : "warn";
    const title = mt ? "Upgrade in progress" : down.length === 0 ? "We're fully operational" : apiDown ? "Major outage" : "Partial outage";
    const sub = mt ? (mt.title || "We're upgrading CLARION. Some features may be unavailable for a few minutes.")
      : down.length === 0 ? "We're not aware of any issues affecting our systems."
      : "Some parts of CLARION are not responding. See the affected components below.";
    const t = banner.querySelector("[data-title]");
    if (t) {
      banner.className = "st-banner " + kind;
      t.textContent = title;
      banner.querySelector("[data-sub]").textContent = sub;
    } else {
      banner.className = "banner " + kind;
      banner.textContent = mt ? title : down.length === 0 ? "All systems operational" : title;
    }
  }
  document.querySelectorAll("[data-checked]").forEach(e => (e.textContent = "Checked " + new Date().toLocaleTimeString()));
}


// ---- 90-day history bars (server-side samples, GET /api/status/history) ----
function isoDay(d) { return d.toISOString().slice(0, 10); }

let lastHist = null;
function paintHistory(h) { lastHist = h; paintBars(); }

function paintBars() {
  const h = lastHist;
  const tip = document.getElementById("st-tip");
  const days = [];
  for (let i = 89; i >= 0; i--) days.push(isoDay(new Date(Date.now() - i * 86400000)));
  const incidents = [];
  const maintDays = new Set();
  for (const m of maintLog) {
    for (let t = Date.parse(m.start); t <= (m.end ? Date.parse(m.end) : Date.now()); t += 86400000) maintDays.add(isoDay(new Date(t)));
    maintDays.add(isoDay(new Date(m.end || Date.now())));
  }

  document.querySelectorAll("[data-bars]").forEach(el => {
    const comp = el.dataset.bars;
    const rows = (h.components && h.components[comp]) || {};
    let total = 0, bad = 0;
    el.replaceChildren(...days.map(d => {
      const r = rows[d];
      const i = document.createElement("i");
      i.tabIndex = 0;
      let label;
      if (!r || !r.total) {
        label = "No data";
      } else {
        const up = 100 * (1 - r.bad / r.total);
        total += r.total; bad += r.bad;
        i.className = maintDays.has(d) ? "maint" : up >= 99.9 ? "ok" : up >= 95 ? "part" : "out";
        label = maintDays.has(d) ? `${up.toFixed(2)}% uptime (scheduled upgrade)` : `${up.toFixed(2)}% uptime`;
        if (up < 99.9 && !maintDays.has(d) && !comp.includes(".")) incidents.push({ d, comp, up, kind: up >= 95 ? "Partial outage" : "Major outage" });
      }
      const show = e => {
        const r2 = i.getBoundingClientRect();
        tip.innerHTML = "";
        const b = document.createElement("b"); b.textContent = new Date(d + "T00:00:00Z").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
        tip.append(b, label);
        tip.hidden = false;
        const w = tip.offsetWidth;
        tip.style.left = Math.max(8, Math.min(innerWidth - w - 8, r2.left + r2.width / 2 - w / 2)) + "px";
        tip.style.top = (r2.top - tip.offsetHeight - 8) + "px";
      };
      i.addEventListener("mouseenter", show);
      i.addEventListener("focus", show);
      i.addEventListener("mouseleave", () => (tip.hidden = true));
      i.addEventListener("blur", () => (tip.hidden = true));
      return i;
    }));
    const pct = document.querySelector(`[data-pct="${comp}"]`);
    if (pct) pct.textContent = total ? `${(100 * (1 - bad / total)).toFixed(2)}% uptime` : "";
    if (comp.includes(".") && !total) el.title = "No history yet";
  });

  const list = document.getElementById("incidents");
  if (list) {
    const names = { api: "API", database: "Database", object_store: "File storage", cache: "Cache & rate limiting", local_ai: "Local AI" };
    incidents.sort((a, b) => (a.d < b.d ? 1 : -1));
    const fmt = s => new Date(s).toLocaleString(undefined, { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
    const upgrades = maintLog.slice().sort((a, b) => (a.start < b.start ? 1 : -1)).map(m => {
      const li = document.createElement("li");
      const b = document.createElement("b");
      b.textContent = (m.end ? "Scheduled upgrade" : "Upgrade in progress") + (m.title ? ": " + m.title : "");
      const w = document.createElement("span");
      w.className = "when";
      w.textContent = m.end ? `${fmt(m.start)} – ${fmt(m.end)} · ${Math.max(1, Math.round((Date.parse(m.end) - Date.parse(m.start)) / 60000))} min`
        : `Started ${fmt(m.start)} · still running`;
      li.append(b, w);
      return li;
    });
    list.replaceChildren(...upgrades, ...(incidents.length ? incidents.map(x => {
      const li = document.createElement("li");
      const b = document.createElement("b");
      b.textContent = `${names[x.comp] || x.comp}: ${x.kind}`;
      const w = document.createElement("span");
      w.className = "when";
      w.textContent = `${new Date(x.d + "T00:00:00Z").toLocaleDateString(undefined, { month: "long", day: "numeric", timeZone: "UTC" })} · ${x.up.toFixed(2)}% of checks passed that day`;
      li.append(b, w);
      return li;
    }) : upgrades.length ? [] : (() => { const li = document.createElement("li"); li.className = "muted"; li.textContent = "No incidents in the last 90 days."; return [li]; })()));
  }
}

async function loadHistory() {
  await loadMaint();
  try {
    const r = await fetch("/api/status/history?days=90", { cache: "no-store", signal: AbortSignal.timeout(5000) });
    if (r.ok) paintHistory(await r.json());
  } catch { /* history is a bonus; the live checks still work */ }
}

async function tick() {
  await loadMaint();
  paint(await sample());
}

document.addEventListener("DOMContentLoaded", () => {
  if (document.querySelector("[data-val]")) {
    tick();
    setInterval(tick, 15000);
    loadHistory();
    setInterval(loadHistory, 300000);
  }

  // ---- scroll reveal (siblings stagger a little) ----
  const items = [...document.querySelectorAll("[data-reveal]")];
  if ("IntersectionObserver" in window) {
    const io = new IntersectionObserver(es => es.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    }), { threshold: 0.12 });
    items.forEach(el => io.observe(el));
  } else {
    items.forEach(el => el.classList.add("in"));
  }

  // ---- get-app page: show the APK button only when the file is actually published ----
  const apkBtn = document.querySelector("[data-apk]");
  if (apkBtn) {
    fetch("/downloads/clarion.apk", { method: "HEAD", cache: "no-store" }).then(r => {
      const type = r.headers.get("content-type") || "";
      if (!r.ok || type.includes("text/html")) return; // SPA fallback => not published
      // Inline display + remove(): don't depend on the [hidden] rule in a
      // stylesheet a CDN/browser may still hold an older copy of.
      apkBtn.style.display = "inline-flex";
      document.getElementById("apk-pending")?.remove();
      const len = Number(r.headers.get("content-length"));
      if (len) document.getElementById("apk-size").textContent = `(${(len / 1048576).toFixed(0)} MB)`;
      document.getElementById("apk-meta").textContent = "Requires Android 10 or newer. Free. No account needed to download.";
      return fetch("/downloads/clarion.apk.sha256", { cache: "no-store" })
        .then(s => (s.ok ? s.text() : ""))
        .then(t => { const m = t.match(/[0-9a-f]{64}/i); if (m) document.getElementById("apk-sha").textContent = m[0].toLowerCase(); });
    }).catch(() => {});
  }

  // ---- nav shadow after scrolling ----
  const nav = document.querySelector(".nav");
  if (nav) {
    const onScroll = () => nav.classList.toggle("scrolled", window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
  }

  // ---- product tour tabs ----
  const tabs = [...document.querySelectorAll(".tab")];
  tabs.forEach(t => t.addEventListener("click", () => {
    tabs.forEach(x => x.setAttribute("aria-selected", String(x === t)));
    document.querySelectorAll(".panel-tour").forEach(p => (p.hidden = p.id !== t.getAttribute("aria-controls")));
  }));

  // ---- module screenshots: click a module to open its screen ----
  const mv = document.getElementById("modview");
  if (mv && mv.showModal) {
    document.querySelectorAll("button.mod").forEach(b => b.addEventListener("click", () => {
      document.getElementById("mv-t").textContent = b.dataset.title;
      document.getElementById("mv-d").textContent = b.dataset.desc;
      const i = document.getElementById("mv-i");
      i.src = b.dataset.img; i.alt = b.dataset.title + " screen";
      mv.showModal();
    }));
    mv.addEventListener("click", e => { if (e.target === mv) mv.close(); }); // click on backdrop
  }
});
