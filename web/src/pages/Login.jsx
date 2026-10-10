import { useRef, useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { login, mfaVerify, mfaEnrolStart, mfaEnrolConfirm, commitSession } from "../api/client";
import { landingPathFor } from "../lib/access";

const INPUT =
  "w-full border border-slate-300 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-blue-600";
const BUTTON =
  "w-full bg-blue-800 hover:bg-blue-900 text-white font-semibold py-2.5 rounded-lg transition disabled:opacity-50";

// Turn an axios error into one sentence a person can act on. 401 on the
// credential step is deliberately generic (no account enumeration).
function messageFor(err, fallback) {
  const status = err?.response?.status;
  const detail = err?.response?.data?.detail;
  if (!err?.response) return "Can't reach the server. Check your connection and try again.";
  if (status === 429) {
    const m = typeof detail === "string" && detail.match(/after (\S+)/);
    if (m) {
      const when = new Date(m[1]);
      if (!Number.isNaN(when.getTime())) return `Too many attempts. Try again after ${when.toLocaleTimeString()}.`;
    }
    return "Too many attempts. Please wait a few minutes and try again.";
  }
  if (status === 401) return fallback;
  return typeof detail === "string" ? detail : "Something went wrong. Please try again.";
}

function Field({ id, label, children, hint }) {
  return (
    <div className="mb-4">
      <label htmlFor={id} className="block text-sm font-medium text-slate-700 mb-1">{label}</label>
      {children}
      {hint && <p className="text-xs text-slate-500 mt-1">{hint}</p>}
    </div>
  );
}

export default function Login() {
  // Pre-filled demo account only in dev / when the demo hint is on; a public build starts empty.
  const demo = import.meta.env.DEV || import.meta.env.VITE_SHOW_DEMO_HINT === "1";
  const navigate = useNavigate();
  const location = useLocation();

  const [tab, setTab] = useState("patient"); // patient | staff -- UX only, the backend resolves the identifier
  const [step, setStep] = useState("credentials"); // credentials | mfa | enrol | recovery
  const [identifier, setIdentifier] = useState(demo ? "clinician@clarion.demo" : "");
  const [password, setPassword] = useState(demo ? "clinician123" : "");
  const [showPw, setShowPw] = useState(false);
  const [caps, setCaps] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [mfaToken, setMfaToken] = useState("");
  const [code, setCode] = useState("");
  const [enrol, setEnrol] = useState(null); // { secret, qr_png_base64 }
  const [recovery, setRecovery] = useState({ codes: [], session: null, saved: false });

  function finish(data) {
    // A temporary password must be replaced first; the API refuses everything else until then.
    navigate(data.user.must_change_password ? "/change-password" : landingPathFor(data.user));
  }

  function backToStart(message = "") {
    setStep("credentials");
    setMfaToken("");
    setCode("");
    setEnrol(null);
    setPassword("");
    setError(message);
  }

  // Guards against a double submit (auto-verify on the 6th digit + Enter).
  const inFlight = useRef(false);

  async function run(fn, fallback, onSessionExpired = true) {
    if (inFlight.current) return;
    inFlight.current = true;
    setError("");
    setLoading(true);
    try {
      await fn();
    } catch (err) {
      if (onSessionExpired && step !== "credentials" && err?.response?.status === 401
          && /expired|start again/i.test(String(err.response?.data?.detail))) {
        backToStart("Your sign-in timed out. Please sign in again.");
      } else {
        setError(messageFor(err, fallback));
        // A wrong code is cleared so the next 6 digits auto-verify again.
        if (step === "mfa" || step === "enrol") setCode("");
      }
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }

  const submitCredentials = (e) => {
    e.preventDefault();
    run(async () => {
      const data = await login(identifier.trim(), password);
      if (!data.mfa_required) return finish(data);
      setMfaToken(data.mfa_token);
      setPassword("");
      if (data.mfa_enrol) {
        setEnrol(await mfaEnrolStart(data.mfa_token));
        setStep("enrol");
      } else {
        setStep("mfa");
      }
    }, "Incorrect email/NRIC or password.");
  };

  const verifyWith = (value) =>
    run(async () => finish(await mfaVerify(mfaToken, value.trim())), "That code isn't valid. Try again.");

  const enrolWith = (value) =>
    run(async () => {
      const data = await mfaEnrolConfirm(mfaToken, value.trim());
      setRecovery({ codes: data.recovery_codes || [], session: data, saved: false });
      setStep("recovery");
    }, "That code didn't match. Check the time on your phone and try again.");

  const submitCode = (e) => { e.preventDefault(); verifyWith(code); };
  const submitEnrol = (e) => { e.preventDefault(); enrolWith(code); };

  // Exactly six digits = an authenticator code: verify without a button press.
  // (Recovery codes contain letters and a dash, so they still need Verify.)
  const onCodeChange = (submit) => (e) => {
    const v = e.target.value;
    setCode(v);
    if (/^\d{6}$/.test(v.trim())) submit(v);
  };

  const tabClass = (name) =>
    `flex-1 py-2 text-sm font-semibold rounded-lg transition ${
      tab === name ? "bg-white shadow text-blue-900" : "text-slate-600 hover:text-slate-900"
    }`;

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-b from-slate-100 to-white px-4 py-8">
      <div className="bg-white shadow-xl rounded-2xl p-6 sm:p-8 w-full max-w-md border border-slate-200">
        {/* A plain <a>, not <Link>: "/" is the static landing page served by the
            web container, so it needs a real page load -- inside the SPA the
            "/" route just redirects back to /login. */}
        <a href="/" aria-label="CLARION home">
          <img src="/brand/logo-full.png" alt="CLARION" className="h-14 w-auto mx-auto mb-4" />
        </a>

        {location.state?.resetSuccess && step === "credentials" && (
          <div role="status" className="bg-green-50 text-green-800 text-sm p-3 rounded-lg mb-4">
            Password updated. Sign in with your new password.
          </div>
        )}
        <div role="alert" aria-live="assertive">
          {error && <div className="bg-red-50 text-red-800 text-sm p-3 rounded-lg mb-4">{error}</div>}
        </div>

        {step === "credentials" && (
          <form onSubmit={submitCredentials} noValidate>
            <div role="tablist" aria-label="Who is signing in" className="flex gap-1 bg-slate-100 p-1 rounded-xl mb-5">
              <button type="button" role="tab" aria-selected={tab === "patient"} className={tabClass("patient")} onClick={() => setTab("patient")}>
                Patient / public
              </button>
              <button type="button" role="tab" aria-selected={tab === "staff"} className={tabClass("staff")} onClick={() => setTab("staff")}>
                Staff
              </button>
            </div>

            <Field
              id="identifier"
              label={tab === "patient" ? "NRIC or email" : "Work email"}
              hint={tab === "patient" ? "Your NRIC, with or without dashes (e.g. 520314-01-1234)." : undefined}
            >
              <input
                id="identifier" className={INPUT} value={identifier} onChange={(e) => setIdentifier(e.target.value)}
                // type="text": an NRIC would fail native email validation.
                type="text" autoComplete="username" inputMode={tab === "patient" ? "text" : "email"}
                autoCapitalize="none" autoCorrect="off" spellCheck={false} required autoFocus
              />
            </Field>

            <Field id="password" label="Password">
              <div className="relative">
                <input
                  id="password" className={`${INPUT} pr-16`} value={password} onChange={(e) => setPassword(e.target.value)}
                  onKeyUp={(e) => setCaps(e.getModifierState?.("CapsLock") === true)}
                  type={showPw ? "text" : "password"} autoComplete="current-password" required
                />
                <button
                  type="button" onClick={() => setShowPw((v) => !v)} aria-pressed={showPw}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-xs font-semibold text-blue-800 px-2 py-1"
                >
                  {showPw ? "Hide" : "Show"}
                </button>
              </div>
              {caps && <p className="text-xs text-amber-700 mt-1">Caps Lock is on.</p>}
            </Field>

            <button disabled={loading || !identifier || !password} className={BUTTON}>
              {loading ? "Signing in…" : "Sign in"}
            </button>

            <div className="text-sm text-slate-600 mt-5 text-center space-y-1">
              {tab === "patient" ? (
                <>
                  <p><Link to="/forgot-password" className="text-blue-800 hover:underline">Forgot your password?</Link></p>
                  <p>New patient? <a href="/get-app" className="text-blue-800 hover:underline">Get the CLARION app</a> and register there.</p>
                </>
              ) : (
                <>
                  <p>Staff sign-in uses an authenticator app.</p>
                  <p>Forgot your password? Ask your administrator to reset it.</p>
                </>
              )}
            </div>

            {demo && (
              <p className="text-xs text-slate-400 mt-4">
                Demo (staff): clinician@clarion.demo / clinician123<br />
                Demo (reception): receptionist@clarion.demo / receptionist123<br />
                Demo (patient): patient@clarion.demo / patient123 (or NRIC 520314-01-1234)
              </p>
            )}
          </form>
        )}

        {step === "mfa" && (
          <form onSubmit={submitCode} noValidate>
            <h1 className="text-lg font-semibold text-slate-800 text-center">Two-step verification</h1>
            <p className="text-sm text-slate-600 text-center mt-1 mb-5">
              Enter the 6-digit code from your authenticator app, or one of your recovery codes.
            </p>
            <Field id="code" label="Code">
              <input
                id="code" className={`${INPUT} text-center tracking-widest text-lg`} value={code}
                onChange={onCodeChange(verifyWith)} autoComplete="one-time-code" inputMode="text"
                maxLength={11} autoFocus required
              />
            </Field>
            <button disabled={loading || code.trim().length < 6} className={BUTTON}>
              {loading ? "Verifying…" : "Verify"}
            </button>
            <button type="button" onClick={() => backToStart()} className="w-full text-sm text-slate-600 hover:underline mt-4">
              Back to sign in
            </button>
          </form>
        )}

        {step === "enrol" && enrol && (
          <form onSubmit={submitEnrol} noValidate>
            <h1 className="text-lg font-semibold text-slate-800 text-center">Set up two-step verification</h1>
            <p className="text-sm text-slate-600 text-center mt-1 mb-4">
              Your role requires an authenticator app (Google Authenticator, Microsoft Authenticator, Authy…).
            </p>
            <ol className="text-sm text-slate-700 list-decimal ml-5 space-y-1 mb-4">
              <li>Scan this QR code with the app.</li>
              <li>Enter the 6-digit code it shows.</li>
            </ol>
            <img
              alt="QR code to add CLARION to your authenticator app"
              src={`data:image/png;base64,${enrol.qr_png_base64}`}
              className="mx-auto w-44 h-44 border border-slate-200 rounded-lg mb-3"
            />
            <details className="text-xs text-slate-600 mb-4">
              <summary className="cursor-pointer">Can't scan? Enter this key manually</summary>
              <code className="block mt-2 break-all bg-slate-50 p-2 rounded select-all">
                {enrol.secret.replace(/(.{4})/g, "$1 ").trim()}
              </code>
            </details>
            <Field id="code" label="6-digit code">
              <input
                id="code" className={`${INPUT} text-center tracking-widest text-lg`} value={code}
                onChange={onCodeChange(enrolWith)} autoComplete="one-time-code" inputMode="numeric"
                maxLength={6} required
              />
            </Field>
            <button disabled={loading || code.trim().length !== 6} className={BUTTON}>
              {loading ? "Checking…" : "Turn on and continue"}
            </button>
            <button type="button" onClick={() => backToStart()} className="w-full text-sm text-slate-600 hover:underline mt-4">
              Cancel
            </button>
          </form>
        )}

        {step === "recovery" && (
          <div>
            <h1 className="text-lg font-semibold text-slate-800 text-center">Save your recovery codes</h1>
            <p className="text-sm text-slate-600 text-center mt-1 mb-4">
              Each code works once if you lose your phone. They are shown only now — store them somewhere safe.
            </p>
            <ul className="grid grid-cols-2 gap-2 font-mono text-sm bg-slate-50 border border-slate-200 rounded-lg p-3 mb-3 select-all">
              {recovery.codes.map((c) => <li key={c}>{c}</li>)}
            </ul>
            <div className="flex gap-2 mb-4">
              <button
                type="button" className="flex-1 border border-slate-300 rounded-lg py-2 text-sm hover:bg-slate-50"
                onClick={() => navigator.clipboard?.writeText(recovery.codes.join("\n"))}
              >
                Copy
              </button>
              {/* Download is the step that unlocks Continue -- copying alone doesn't. */}
              <a
                className="flex-1 bg-blue-800 hover:bg-blue-900 text-white font-semibold rounded-lg py-2 text-sm text-center"
                download="clarion-recovery-codes.txt"
                href={`data:text/plain;charset=utf-8,${encodeURIComponent(recovery.codes.join("\n") + "\n")}`}
                onClick={() => setRecovery((r) => ({ ...r, saved: true }))}
              >
                Download codes
              </a>
            </div>
            <p className={`text-xs mb-4 ${recovery.saved ? "text-green-700" : "text-slate-500"}`}>
              {recovery.saved
                ? "Downloaded. Keep the file somewhere safe, away from this device if you can."
                : "Download the codes to continue."}
            </p>
            <button disabled={!recovery.saved} onClick={() => finish(commitSession(recovery.session))} className={BUTTON}>
              Continue
            </button>
          </div>
        )}
      </div>

      <p className="text-xs text-slate-500 mt-6">
        <a href="/" className="hover:underline">CLARION home</a>
        {" · "}
        <a href="/status.html" className="hover:underline">System status</a>
      </p>
    </div>
  );
}
