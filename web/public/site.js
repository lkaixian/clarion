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
  for (const [id, v] of Object.entries(res)) {
    if (id.startsWith("__")) continue;
    document.querySelectorAll(`[data-dot="${id}"]`).forEach(e => (e.className = "dot " + (v === "off" || v === undefined ? "off" : v === null ? "down" : "up")));
    document.querySelectorAll(`[data-val="${id}"]`).forEach(e => (e.textContent = v === undefined ? "Unknown" : v === "off" ? "Not enabled" : v === null ? "Down" : "Up · " + v + " ms"));
  }
  const banner = document.getElementById("overall");
  if (banner) {
    const core = CORE.filter(k => res[k] !== "off");
    const down = core.filter(k => res[k] === null);
    const apiDown = res.api === null;
    banner.className = "banner " + (down.length === 0 ? "" : apiDown ? "down" : "warn");
    banner.textContent = down.length === 0 ? "All systems operational" : apiDown ? "Major outage" : "Partial outage";
  }
  document.querySelectorAll("[data-checked]").forEach(e => (e.textContent = "Checked " + new Date().toLocaleTimeString()));
}

async function tick() {
  paint(await sample());
}

document.addEventListener("DOMContentLoaded", () => {
  if (document.querySelector("[data-val]")) {
    tick();
    setInterval(tick, 15000);
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
      document.getElementById("apk-meta").textContent = "Android 6.0 or newer. Free. No account needed to download.";
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
