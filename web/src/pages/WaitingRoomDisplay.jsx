import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { getPublicDisplay } from "../api/client";
import { formatTime } from "../lib/format";

// Public lobby big-screen. Own dark full-screen styling — deliberately NOT
// wrapped in <Layout> (no nav, no auth, no max-width container). Polls the
// unauthenticated /display/{token} endpoint.
const DISPLAY_POLL_MS = 5000;

// P3.9: a short beep via the Web Audio oscillator — no audio
// asset/library, browsers already ship this. Silently no-ops if the
// AudioContext can't be created (unsupported browser, or blocked before the
// user has interacted with the page — see the "Enable sound" gate below).
function playChime(ctxRef) {
  try {
    if (!ctxRef.current) {
      ctxRef.current = new (window.AudioContext || window.webkitAudioContext)();
    }
    const ctx = ctxRef.current;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.2, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.6);
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.6);
  } catch {
    // Audio unavailable — the visual board still updates either way.
  }
}

function announce(text) {
  try {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  } catch {
    // speechSynthesis unavailable — visual-only fallback.
  }
}

const servingKey = (s) => `${s.room_name}|${s.queue_number}`;

export default function WaitingRoomDisplay() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  // Distinguish "revoked / unknown token" (a permanent 404 — show the
  // dead-link message) from a transient network blip (keep the last good
  // board on screen rather than blanking a lobby TV).
  const [revoked, setRevoked] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const dataRef = useRef(null);

  // Most browsers refuse to play audio/speech before a user gesture on the
  // page — a kiosk TV needs one tap on load to arm sound, same as any other
  // autoplay-gated site. Off by default so the FIRST poll (whatever is
  // already being served when the page loads) never triggers a surprise
  // announcement; only tickets that transition to "called" AFTER that get
  // announced.
  const [soundEnabled, setSoundEnabled] = useState(false);
  const soundEnabledRef = useRef(false);
  const audioCtxRef = useRef(null);
  const prevServingRef = useRef(null); // null = "haven't seen a first poll yet"

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const fresh = await getPublicDisplay(token);
        if (cancelled) return;

        const servingNow = fresh.now_serving || [];
        if (soundEnabledRef.current && prevServingRef.current !== null) {
          const newlyServing = servingNow.filter((s) => !prevServingRef.current.has(servingKey(s)));
          if (newlyServing.length > 0) {
            playChime(audioCtxRef);
            for (const s of newlyServing) {
              announce(`Number ${s.queue_number}, please proceed to ${s.room_name || "the counter"}`);
            }
          }
        }
        prevServingRef.current = new Set(servingNow.map(servingKey));

        dataRef.current = fresh;
        setData(fresh);
        setRevoked(false);
      } catch (err) {
        if (cancelled) return;
        if (err?.response?.status === 404) {
          setRevoked(true);
        }
        // Any other error (network drop, 429 rate-limit, 5xx): keep showing
        // whatever we last had — don't wipe the screen.
      }
    }

    poll();
    const t = setInterval(poll, DISPLAY_POLL_MS);
    return () => { cancelled = true; clearInterval(t); };
  }, [token]);

  // Local ticking clock in the header — independent of the poll so it stays
  // smooth even between (or through a stall in) network refreshes.
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  if (revoked && !dataRef.current) {
    return (
      <div className="min-h-screen bg-slate-900 text-white flex items-center justify-center p-8">
        <p className="text-2xl text-slate-300">This display link is no longer active.</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="min-h-screen bg-slate-900 text-white flex items-center justify-center p-8">
        <p className="text-2xl text-slate-400">Loading…</p>
      </div>
    );
  }

  const nowServing = data.now_serving || [];
  const upNext = data.up_next || [];
  const accent = data.brand_primary_color || undefined; // undefined -> CSS default (emerald)

  return (
    <div className="min-h-screen bg-slate-900 text-white p-8">
      {!soundEnabled && (
        <button
          type="button"
          onClick={() => {
            // The click itself is the user gesture that unlocks
            // audio/speech in the browser — prime both right here rather
            // than waiting for the next poll's chime to be the first call.
            try {
              audioCtxRef.current = new (window.AudioContext || window.webkitAudioContext)();
              window.speechSynthesis?.speak(new SpeechSynthesisUtterance(""));
            } catch { /* best-effort priming only */ }
            soundEnabledRef.current = true;
            setSoundEnabled(true);
          }}
          className="fixed top-4 right-4 z-10 bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-sm text-slate-200 hover:bg-slate-700"
        >
          🔊 Enable sound
        </button>
      )}

      <header className="flex items-end justify-between border-b border-slate-700 pb-4 mb-8" style={accent ? { borderColor: accent } : undefined}>
        <div className="flex items-center gap-4">
          {data.logo_data_url && (
            <img src={data.logo_data_url} alt="" className="h-14 w-14 object-contain rounded" />
          )}
          <div>
            <h1 className="text-4xl font-bold">{data.facility_display_name}</h1>
            {data.section && <p className="text-xl text-slate-400 mt-1">{data.section}</p>}
          </div>
        </div>
        <div className="text-right">
          <p className="text-3xl font-mono tabular-nums">{now.toLocaleTimeString()}</p>
          {revoked && <p className="text-xs text-amber-400 mt-1">Link revoked — showing last board</p>}
        </div>
      </header>

      <section className="mb-10">
        <h2 className="text-2xl font-semibold tracking-widest text-slate-400 mb-4">NOW SERVING</h2>
        {nowServing.length === 0 ? (
          <p className="text-xl text-slate-500">No one is being called right now.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {nowServing.map((s, i) => (
              <div key={`${s.room_name}-${i}`} className="bg-slate-800 rounded-2xl p-6 border border-slate-700">
                <p className="text-xl text-slate-400">{s.room_name}</p>
                <p className="text-7xl font-bold my-2 text-emerald-400" style={accent ? { color: accent } : undefined}>#{s.queue_number}</p>
                <p className="text-2xl text-slate-200">{s.patient_label}</p>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-2xl font-semibold tracking-widest text-slate-400 mb-4">WAITING</h2>
        {upNext.length === 0 ? (
          <p className="text-xl text-slate-500">No one waiting.</p>
        ) : (
          <div className="divide-y divide-slate-800">
            {upNext.map((u, i) => (
              <div key={`${u.queue_number}-${i}`} className="flex items-center gap-4 py-3 text-2xl">
                <span className="font-bold text-slate-100 w-20">#{u.queue_number}</span>
                <span className="flex-1 text-slate-200">{u.patient_label}</span>
                <span className="text-lg text-slate-500">{u.room_name}</span>
                <span className="text-lg text-slate-500 w-28 text-right">{formatTime(u.checked_in_at)}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
