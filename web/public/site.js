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
      val.textContent = ch.status === "disabled" ? "Not enabled"
        : ch.status !== "up" ? "Down"
        : "Up · " + ch.ms + " ms" + (ch.typical_ms !== undefined ? ` (usually ${ch.typical_ms} ms)` : "");
      li.append(dot, name, val);
      return li;
    }));
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
    document.querySelectorAll(`[data-dot="${id}"]`).forEach(e => (e.className = "dot " + (v === "off" || v === undefined ? "off" : v === null ? "down" : "up")));
    document.querySelectorAll(`[data-val="${id}"]`).forEach(e => (e.textContent = v === undefined ? "Unknown" : v === "off" ? "Not enabled" : v === null ? "Down"
      : (id === "api" && document.querySelector("[data-metric]") ? "Up" : "Up · " + v + " ms")));
  }
  const banner = document.getElementById("overall");
  if (banner) {
    const core = CORE.filter(k => res[k] !== "off");
    const down = core.filter(k => res[k] === null);
    const apiDown = res.api === null;
    const kind = down.length === 0 ? "" : apiDown ? "down" : "warn";
    const title = down.length === 0 ? "We're fully operational" : apiDown ? "Major outage" : "Partial outage";
    const sub = down.length === 0 ? "We're not aware of any issues affecting our systems."
      : "Some parts of CLARION are not responding. See the affected components below.";
    const t = banner.querySelector("[data-title]");
    if (t) {
      banner.className = "st-banner " + kind;
      t.textContent = title;
      banner.querySelector("[data-sub]").textContent = sub;
    } else {
      banner.className = "banner " + kind;
      banner.textContent = down.length === 0 ? "All systems operational" : title;
    }
  }
  document.querySelectorAll("[data-checked]").forEach(e => (e.textContent = "Checked " + new Date().toLocaleTimeString()));
}


// ---- 90-day history bars (server-side samples, GET /api/status/history) ----
function isoDay(d) { return d.toISOString().slice(0, 10); }

function paintHistory(h) {
  const tip = document.getElementById("st-tip");
  const days = [];
  for (let i = 89; i >= 0; i--) days.push(isoDay(new Date(Date.now() - i * 86400000)));
  const incidents = [];

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
        i.className = up >= 99.9 ? "ok" : up >= 95 ? "part" : "out";
        label = `${up.toFixed(2)}% uptime`;
        if (up < 99.9) incidents.push({ d, comp, up, kind: up >= 95 ? "Partial outage" : "Major outage" });
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
  });

  const list = document.getElementById("incidents");
  if (list) {
    const names = { api: "API", database: "Database", object_store: "File storage", cache: "Cache & rate limiting", local_ai: "Local AI" };
    incidents.sort((a, b) => (a.d < b.d ? 1 : -1));
    list.replaceChildren(...(incidents.length ? incidents.map(x => {
      const li = document.createElement("li");
      const b = document.createElement("b");
      b.textContent = `${names[x.comp] || x.comp}: ${x.kind}`;
      const w = document.createElement("span");
      w.className = "when";
      w.textContent = `${new Date(x.d + "T00:00:00Z").toLocaleDateString(undefined, { month: "long", day: "numeric", timeZone: "UTC" })} · ${x.up.toFixed(2)}% of checks passed that day`;
      li.append(b, w);
      return li;
    }) : (() => { const li = document.createElement("li"); li.className = "muted"; li.textContent = "No incidents in the last 90 days."; return [li]; })()));
  }
}

async function loadHistory() {
  try {
    const r = await fetch("/api/status/history?days=90", { cache: "no-store", signal: AbortSignal.timeout(5000) });
    if (r.ok) paintHistory(await r.json());
  } catch { /* history is a bonus; the live checks still work */ }
}

async function tick() {
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
});
