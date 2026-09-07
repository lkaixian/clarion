import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { getPublicDisplay } from "../api/client";

// Public lobby big-screen. Own dark full-screen styling — deliberately NOT
// wrapped in <Layout> (no nav, no auth, no max-width container). Polls the
// unauthenticated /display/{token} endpoint.
const DISPLAY_POLL_MS = 5000;

// No date library in this codebase — plain built-in formatting, same as
// every other timestamp in the app.
function formatTime(iso) {
  return iso ? new Date(iso).toLocaleTimeString() : "—";
}

export default function WaitingRoomDisplay() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  // Distinguish "revoked / unknown token" (a permanent 404 — show the
  // dead-link message) from a transient network blip (keep the last good
  // board on screen rather than blanking a lobby TV).
  const [revoked, setRevoked] = useState(false);
  const [now, setNow] = useState(() => new Date());
  const dataRef = useRef(null);

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const fresh = await getPublicDisplay(token);
        if (cancelled) return;
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

  return (
    <div className="min-h-screen bg-slate-900 text-white p-8">
      <header className="flex items-end justify-between border-b border-slate-700 pb-4 mb-8">
        <div>
          <h1 className="text-4xl font-bold">{data.facility_display_name}</h1>
          {data.section && <p className="text-xl text-slate-400 mt-1">{data.section}</p>}
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
                <p className="text-7xl font-bold my-2 text-emerald-400">#{s.queue_number}</p>
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
