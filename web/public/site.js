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
  };
}

function paint(res) {
  for (const [id, v] of Object.entries(res)) {
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
