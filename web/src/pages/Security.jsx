import { useCallback, useEffect, useState } from "react";
import Layout from "../components/Layout";
import {
  getMfaStatus, mfaSetupStart, mfaSetupConfirm, mfaDisable, mfaRegenerateRecoveryCodes,
  getSessions, revokeSession, revokeOtherSessions,
} from "../api/client";

const INPUT = "border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-600";
const BTN = "bg-blue-800 hover:bg-blue-900 text-white text-sm font-semibold px-4 py-2 rounded-lg disabled:opacity-50";
const BTN2 = "border border-slate-300 text-sm px-4 py-2 rounded-lg hover:bg-slate-50 disabled:opacity-50";

const errText = (e) => {
  const d = e?.response?.data?.detail;
  return typeof d === "string" ? d : "Something went wrong. Please try again.";
};

function deviceLabel(ua) {
  if (!ua) return "Unknown device";
  for (const [needle, label] of [["Edg/", "Edge"], ["Chrome/", "Chrome"], ["Firefox/", "Firefox"],
    ["Safari/", "Safari"], ["okhttp", "CLARION mobile app"], ["Dart/", "CLARION mobile app"]]) {
    if (ua.includes(needle)) return label;
  }
  return ua.slice(0, 40);
}

function RecoveryCodes({ codes, onDone }) {
  return (
    <div className="mt-4">
      <p className="text-sm text-slate-700 mb-2">Save these recovery codes now — they are shown only once. Each works one time.</p>
      <ul className="grid grid-cols-2 gap-2 font-mono text-sm bg-slate-50 border border-slate-200 rounded-lg p-3 mb-3 select-all">
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <div className="flex gap-2">
        <button className={BTN2} onClick={() => navigator.clipboard?.writeText(codes.join("\n"))}>Copy</button>
        <button className={BTN} onClick={onDone}>I have saved them</button>
      </div>
    </div>
  );
}

function MfaCard() {
  const [status, setStatus] = useState(null);
  const [setup, setSetup] = useState(null); // { secret, qr_png_base64 }
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState(null);
  const [action, setAction] = useState(null); // "disable" | "regen"
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => getMfaStatus().then(setStatus).catch(() => setMsg("Could not load MFA status.")), []);
  useEffect(() => { load(); }, [load]);

  async function run(fn) {
    setBusy(true);
    setMsg("");
    try { await fn(); } catch (e) { setMsg(errText(e)); } finally { setBusy(false); }
  }

  if (!status) return <section className="bg-white border border-slate-200 rounded-xl p-5">Loading…</section>;

  return (
    <section className="bg-white border border-slate-200 rounded-xl p-5">
      <h2 className="font-semibold text-slate-800">Two-step verification (authenticator app)</h2>
      <p className="text-sm text-slate-600 mt-1">
        {status.enabled ? "On." : "Off."}{" "}
        {status.required && "Required for your role."}
        {status.enabled && ` ${status.recovery_codes_remaining} recovery code(s) left.`}
      </p>
      {msg && <p role="alert" className="text-sm text-red-700 mt-2">{msg}</p>}

      {codes && <RecoveryCodes codes={codes} onDone={() => { setCodes(null); load(); }} />}

      {!status.enabled && !setup && !codes && (
        <form className="mt-3" onSubmit={(e) => {
          e.preventDefault();
          run(async () => { setSetup(await mfaSetupStart(password)); setPassword(""); });
        }}>
          <label htmlFor="sec-pw" className="block text-sm text-slate-700 mb-1">Confirm your password to begin</label>
          <div className="flex gap-2 flex-wrap">
            <input id="sec-pw" type="password" autoComplete="current-password" className={INPUT}
              value={password} onChange={(e) => setPassword(e.target.value)} />
            <button className={BTN} disabled={busy || !password}>Set up</button>
          </div>
        </form>
      )}

      {setup && (
        <form className="mt-4" onSubmit={(e) => {
          e.preventDefault();
          run(async () => {
            const r = await mfaSetupConfirm(code.trim());
            setSetup(null); setCode(""); setCodes(r.recovery_codes);
          });
        }}>
          <img alt="QR code for your authenticator app" className="w-40 h-40 border border-slate-200 rounded-lg"
            src={`data:image/png;base64,${setup.qr_png_base64}`} />
          <details className="text-xs text-slate-600 my-2">
            <summary className="cursor-pointer">Enter the key manually</summary>
            <code className="block mt-1 break-all select-all">{setup.secret}</code>
          </details>
          <label htmlFor="sec-code" className="block text-sm text-slate-700 mb-1">6-digit code</label>
          <input id="sec-code" className={`${INPUT} w-40 tracking-widest`} value={code} maxLength={6}
            inputMode="numeric" autoComplete="one-time-code" onChange={(e) => setCode(e.target.value)} />
          <div className="mt-3 flex gap-2">
            <button className={BTN} disabled={busy || code.trim().length !== 6}>Turn on</button>
            <button type="button" className={BTN2} onClick={() => { setSetup(null); setCode(""); }}>Cancel</button>
          </div>
        </form>
      )}

      {status.enabled && !codes && (
        <div className="mt-3">
          {!action ? (
            <div className="flex gap-2 flex-wrap">
              <button className={BTN2} onClick={() => setAction("regen")}>New recovery codes</button>
              {!status.required && <button className={BTN2} onClick={() => setAction("disable")}>Turn off</button>}
            </div>
          ) : (
            <form onSubmit={(e) => {
              e.preventDefault();
              run(async () => {
                if (action === "disable") await mfaDisable(password, code.trim());
                else setCodes((await mfaRegenerateRecoveryCodes(password, code.trim())).recovery_codes);
                setAction(null); setPassword(""); setCode("");
                load();
              });
            }}>
              <p className="text-sm text-slate-700 mb-2">Confirm with your password and a current code.</p>
              <div className="flex gap-2 flex-wrap">
                <input aria-label="Password" type="password" autoComplete="current-password" className={INPUT}
                  value={password} onChange={(e) => setPassword(e.target.value)} />
                <input aria-label="Code" className={`${INPUT} w-36`} value={code} inputMode="text" maxLength={11}
                  autoComplete="one-time-code" onChange={(e) => setCode(e.target.value)} />
              </div>
              <div className="mt-3 flex gap-2">
                <button className={BTN} disabled={busy || !password || code.trim().length < 6}>
                  {action === "disable" ? "Turn off" : "Generate"}
                </button>
                <button type="button" className={BTN2} onClick={() => { setAction(null); setPassword(""); setCode(""); }}>Cancel</button>
              </div>
            </form>
          )}
        </div>
      )}
    </section>
  );
}

function SessionsCard() {
  const [sessions, setSessions] = useState(null);
  const [msg, setMsg] = useState("");
  const load = useCallback(() => getSessions().then(setSessions).catch(() => setMsg("Could not load sessions.")), []);
  useEffect(() => { load(); }, [load]);

  const act = (fn) => async () => {
    setMsg("");
    try { await fn(); await load(); } catch (e) { setMsg(errText(e)); }
  };

  return (
    <section className="bg-white border border-slate-200 rounded-xl p-5">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h2 className="font-semibold text-slate-800">Signed-in devices</h2>
        <button className={BTN2} disabled={!sessions || sessions.length < 2} onClick={act(revokeOtherSessions)}>
          Sign out everywhere else
        </button>
      </div>
      {msg && <p role="alert" className="text-sm text-red-700 mt-2">{msg}</p>}
      {!sessions ? <p className="text-sm text-slate-600 mt-2">Loading…</p> : (
        <ul className="divide-y divide-slate-100 mt-2">
          {sessions.map((s) => (
            <li key={s.id} className="py-2 flex items-center justify-between gap-3 text-sm">
              <div>
                <div className="font-medium text-slate-800">
                  {deviceLabel(s.user_agent)} {s.current && <span className="text-green-700 text-xs ml-1">(this device)</span>}
                </div>
                <div className="text-xs text-slate-500">
                  {s.ip || "unknown IP"} · last active {s.issued_at ? new Date(s.issued_at).toLocaleString() : "—"}
                </div>
              </div>
              {!s.current && <button className={BTN2} onClick={act(() => revokeSession(s.id))}>Sign out</button>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function Security() {
  return (
    <Layout>
      <h1 className="text-xl font-semibold text-slate-900 mb-4">Account security</h1>
      <div className="space-y-4 max-w-2xl">
        <MfaCard />
        <SessionsCard />
      </div>
    </Layout>
  );
}
