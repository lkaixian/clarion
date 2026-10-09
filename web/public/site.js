// Marks the page as scripted first (so scroll-reveal only hides things when it can also show them).
document.documentElement.classList.add("js");

// ---- live status -----------------------------------------------------------
// Each id maps to a number (up, latency in ms), null (down) or "off" (not enabled on this node).
const KEY = "clarion-status-v2", MAX = 48, CORE = ["web", "api", "database", "object_store", "cache"];

async function timed(url, json) {
  const t0 = performance.now();
  try {
    const r = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout(5000) });
    if (!r.ok) return { ms: null };
    return { ms: Math.round(performance.now() - t0), body: json ? await r.json() : null };
  } catch { return { ms: null }; }
}

async function sample() {
  const [web, api] = await Promise.all([timed("/brand/icon-32.png"), timed("/api/status", true)]);
  const c = api.body && api.body.components;
  const part = k => (!c || !c[k]) ? null : c[k].status === "up" ? (c[k].ms ?? 0) : c[k].status === "disabled" ? "off" : null;
  return {
    web: web.ms,
    api: api.ms,
    database: part("database"),
    object_store: part("object_store"),
    cache: part("cache"),
    local_ai: part("local_ai"),
  };
}

function paint(res) {
  for (const [id, v] of Object.entries(res)) {
    document.querySelectorAll(`[data-dot="${id}"]`).forEach(e => (e.className = "dot " + (v === "off" ? "off" : v === null ? "down" : "up")));
    document.querySelectorAll(`[data-val="${id}"]`).forEach(e => (e.textContent = v === "off" ? "Not enabled" : v === null ? "Down" : "Up · " + v + " ms"));
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

function loadHistory() {
  try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch { return []; }
}
function saveHistory(h) {
  try { localStorage.setItem(KEY, JSON.stringify(h.slice(-MAX))); } catch { /* private mode: history just won't persist */ }
}

// Bar height follows latency (capped at 400 ms); red = down, grey = not enabled.
function paintHistory(h) {
  document.querySelectorAll("[data-hist]").forEach(box => {
    const id = box.dataset.hist;
    box.replaceChildren(...h.map(s => {
      const v = s[id], i = document.createElement("i");
      i.className = v === null ? "down" : v === "off" ? "" : "up";
      i.style.height = v === null ? "100%" : v === "off" ? "20%" : Math.max(18, Math.min(100, 18 + (v / 400) * 82)) + "%";
      i.title = new Date(s.t).toLocaleTimeString() + " - " + (v === null ? "down" : v === "off" ? "not enabled" : v + " ms");
      return i;
    }));
  });
}

async function tick() {
  const res = await sample();
  paint(res);
  const h = loadHistory();
  h.push({ t: Date.now(), ...res });
  saveHistory(h);
  paintHistory(h.slice(-MAX));
}

document.addEventListener("DOMContentLoaded", () => {
  if (document.querySelector("[data-val],[data-hist]")) {
    paintHistory(loadHistory());
    tick();
    setInterval(tick, 15000);
  }

  // ---- scroll reveal (siblings stagger a little) ----
  const items = [...document.querySelectorAll("[data-reveal]")];
  items.forEach(el => {
    const sibs = [...el.parentElement.children].filter(n => n.hasAttribute("data-reveal"));
    el.style.setProperty("--d", Math.min(sibs.indexOf(el), 8) * 0.07 + "s");
  });
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
