import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { refreshAccessToken, scanEmergencyCard, shareScanLocation } from "../api/client";
import { tr } from "../lib/i18n";

// Public page behind the card QR / NFC tag. No Layout, no login gate. The server
// decides how much to show; a stored staff token (if any) is sent by the api client.

function useMeta(name, content) {
  useEffect(() => {
    const el = document.createElement("meta");
    el.name = name; el.content = content;
    document.head.appendChild(el);
    return () => el.remove();
  }, [name, content]);
}

const CALL = "block w-full rounded-xl text-center font-bold";
const List = ({ items, empty }) => (
  items.length ? <ul className="list-disc space-y-1 pl-6 text-xl">{items}</ul>
    : <p className="text-xl text-slate-700">{empty}</p>
);

const LOC_MSG = {
  locating: "Getting your location…",
  shared: "Location shared with the patient's family. Thank you.",
  denied: "Location was not shared (permission denied). The medical information above is unaffected.",
  unavailable: "Could not get your location.",
  expired: "This location link has expired. Scan the card again to share your location.",
};

// Optional, user-initiated (or already-permitted) location share. It never blocks or hides the
// medical information and never throws. The server sends the contact one SMS per call, so
// the POST is guarded to run once per scan.
function ShareLocation({ token }) {
  const [st, setSt] = useState("idle");
  const sent = useRef(false);
  const alive = useRef(true);
  const set = (v) => { if (alive.current) setSt(v); };

  const share = useCallback(() => {
    if (sent.current) return;
    set("locating");
    try {
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          if (sent.current) return;
          sent.current = true;
          try {
            const { latitude: lat, longitude: lng, accuracy } = pos.coords;
            await shareScanLocation(token, { lat, lng, ...(Number.isFinite(accuracy) ? { accuracy_m: accuracy } : {}) });
            set("shared");
          } catch (e) {
            if (e?.response?.status === 400) set("expired");
            else { sent.current = false; set("unavailable"); }
          }
        },
        (err) => set(err?.code === 1 ? "denied" : "unavailable"),
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 },
      );
    } catch { set("unavailable"); }
  }, [token]);

  useEffect(() => {
    alive.current = true;
    // Never send silently: sharing always needs a deliberate tap, even if permission is granted.
    return () => { alive.current = false; };
  }, []);

  return (
    <section aria-labelledby="em-loc" className="rounded-lg border border-slate-300 p-3">
      <h2 id="em-loc" className="sr-only">{tr("Share location")}</h2>
      <p id="em-loc-note" className="mb-2 text-sm text-slate-700">{tr("Your position is sent to the patient's emergency contact as a map link, and shown to the patient and their care team. It is kept for 90 days and is only sent if you tap the button.")}</p>
      {(st === "idle" || st === "unavailable") && (
        <button type="button" onClick={share} aria-describedby="em-loc-note"className="rounded-lg bg-slate-900 px-4 py-2 text-base font-semibold text-white">
          {tr("Share my location with their family")}
        </button>
      )}
      <p role="status" aria-live="polite" className="mt-1 text-base">{LOC_MSG[st] ? tr(LOC_MSG[st]) : ""}</p>
    </section>
  );
}

export default function EmergencyPublic() {
  const { ref } = useParams();
  const { pathname } = useLocation();
  const [state, setState] = useState({ status: "loading" }); // loading | ok | invalid | error
  useMeta("robots", "noindex");
  useMeta("referrer", "no-referrer");

  const scan = useCallback(async () => {
    let data = await scanEmergencyCard(ref);
    // An expired access token is treated as anonymous by the server: refresh once, re-scan once.
    if (data.tier === "public" && localStorage.getItem("mb_token")) {
      try {
        await refreshAccessToken();
        data = await scanEmergencyCard(ref);
      } catch { /* keep the public view */ }
    }
    return data;
  }, [ref]);

  const load = useCallback(() => {
    setState({ status: "loading" });
    scan().then((data) => setState({ status: "ok", data }))
      .catch((e) => setState({ status: e?.response?.status === 404 ? "invalid" : "error" }));
  }, [scan]);

  // The scan is audited and alerts the patient's contact, so a prefetch/prerender or a
  // background tab must not trigger it: wait until the page has stayed visible for ~1s,
  // then scan once per mount. Retry (a user tap) calls load() directly.
  useEffect(() => {
    let timer = null;
    let done = false;
    const cancel = () => { clearTimeout(timer); timer = null; };
    const arm = () => {
      cancel();
      if (done || document.prerendering || document.visibilityState !== "visible") return;
      timer = setTimeout(() => { done = true; load(); }, 1000);
    };
    document.addEventListener("visibilitychange", arm);
    document.addEventListener("prerenderingchange", arm);
    arm();
    return () => {
      cancel();
      document.removeEventListener("visibilitychange", arm);
      document.removeEventListener("prerenderingchange", arm);
    };
  }, [load]);

  const d = state.data || {};
  const priv = d.tier === "responder" || d.tier === "clinical" || d.tier === "paramedic";
  const allergies = (d.allergies || []).map((a, i) => (
    <li key={i}><strong>{a.substance}</strong>{a.severity ? ` (${a.severity})` : ""}{a.reaction ? ` - ${a.reaction}` : ""}</li>
  ));
  const conditions = (d.conditions || []).map((c, i) => <li key={i}>{c}</li>);
  const meds = (d.medications || []).map((m, i) => (
    <li key={i}><strong>{m.drug_name}</strong>{[m.dosage, m.frequency].filter(Boolean).length ? ` - ${[m.dosage, m.frequency].filter(Boolean).join(", ")}` : ""}</li>
  ));
  const none = tr("None recorded as critical");
  const ec = d.emergency_contact;

  return (
    <main className="mx-auto min-h-screen max-w-xl bg-white p-4 text-slate-900">
      <a href="tel:999" className={`${CALL} bg-red-700 py-5 text-3xl text-white`}>{tr("Call 999")}</a>
      <a href="tel:112" className="mt-2 block text-center text-base font-semibold text-red-800 underline">{tr("Call 112")}</a>

      <h1 className="mt-6 text-2xl font-bold">{tr("Medical emergency card")}</h1>

      {state.status === "loading" && (
        <div aria-busy="true" role="status" className="mt-4 space-y-3">
          <span className="sr-only">{tr("Loading…")}</span>
          {[1, 2, 3].map((n) => <div key={n} className="h-8 animate-pulse rounded bg-slate-200" />)}
        </div>
      )}

      {state.status === "invalid" && (
        <p role="alert" className="mt-4 text-xl font-semibold">{tr("This card is not valid or has expired. If this is an emergency, call 999.")}</p>
      )}

      {state.status === "error" && (
        <div role="alert" className="mt-4">
          <p className="text-xl font-semibold">{tr("Could not load. Call 999 now.")}</p>
          <button type="button" onClick={load} className="mt-3 rounded-lg bg-slate-900 px-5 py-3 text-lg font-semibold text-white">{tr("Retry")}</button>
        </div>
      )}

      {state.status === "ok" && (
        <div className="mt-4 space-y-6">
          {priv && (
            <section aria-label={tr("Patient")} className="space-y-1 text-xl">
              {d.full_name && <p><strong>{d.full_name}</strong>{d.age != null ? `, ${d.age}` : ""}</p>}
              {d.blood_type && <p>{tr("Blood type")}: <strong>{d.blood_type}</strong></p>}
            </section>
          )}
          <section aria-labelledby="em-all">
            <h2 id="em-all" className="mb-2 text-xl font-bold">{tr("Allergies")}</h2>
            <List items={allergies} empty={none} />
          </section>
          <section aria-labelledby="em-cond">
            <h2 id="em-cond" className="mb-2 text-xl font-bold">{tr("Medical conditions")}</h2>
            <List items={conditions} empty={none} />
          </section>
          {(d.tier === "clinical" || d.tier === "paramedic") && (
            <section aria-labelledby="em-med">
              <h2 id="em-med" className="mb-2 text-xl font-bold">{tr("Medications")}</h2>
              <List items={meds} empty={none} />
            </section>
          )}
          {priv && ec && (
            <section aria-labelledby="em-ec">
              <h2 id="em-ec" className="mb-2 text-xl font-bold">{tr("Emergency contact")}</h2>
              <p className="text-xl">{ec.name}{ec.relationship ? ` (${ec.relationship})` : ""}</p>
              {ec.phone && <a href={`tel:${ec.phone.replace(/[^\d+]/g, "")}`} className={`${CALL} mt-2 bg-slate-900 py-3 text-xl text-white`}>{tr("Call")} {ec.phone}</a>}
            </section>
          )}
          {d.location_token && typeof navigator !== "undefined" && navigator.geolocation && <ShareLocation token={d.location_token} />}
          {!priv && (
            <p className="text-base text-slate-700">
              {tr("Viewing: basic information")}.{" "}
              <Link className="font-semibold underline" to={`/login?next=${encodeURIComponent(pathname)}`}>{tr("Responder? Sign in to see more")}</Link>
            </p>
          )}
        </div>
      )}

      <footer className="mt-10 border-t border-slate-300 pt-4 text-center">
        <a href="/get-app.html" className="text-base font-semibold underline">{tr("Get the CLARION app")}</a>
      </footer>
    </main>
  );
}
