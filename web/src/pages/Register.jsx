import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { selfRegisterConfig, claimStart, claimVerifyOtp, claimVerifyPhotos, errorMessage } from "../api/client";
import { landingPathFor } from "../lib/access";
import PasswordRules, { passwordMeetsRules } from "../components/PasswordRules";
import { tr } from "../lib/i18n";

const INPUT =
  "w-full border border-slate-300 rounded-lg px-3 py-2.5 mb-4 focus:outline-none focus:ring-2 focus:ring-blue-600 focus:border-blue-600";
const BUTTON =
  "w-full bg-blue-800 hover:bg-blue-900 text-white font-semibold py-2.5 rounded-lg transition disabled:opacity-50";

// Patient sign-up in the browser (any phone, no app). It files a PENDING claim: own email +
// password, inbox proven by a code. If the email is the one already on the hospital record the
// account is created at once; otherwise it waits to be verified (IC photo scan here if the
// server offers it, or staff at a counter). The first verified claim wins; the rest are rejected.
export default function Register() {
  const navigate = useNavigate();
  const [step, setStep] = useState(1); // 1 details | 2 code | 3 waiting for verification
  const [photoCheck, setPhotoCheck] = useState(false);
  const [nric, setNric] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [code, setCode] = useState("");
  const [front, setFront] = useState(null);
  const [back, setBack] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => { selfRegisterConfig().then((c) => setPhotoCheck(!!c.photo_check)).catch(() => {}); }, []);

  async function run(fn, fallback) {
    setError("");
    setLoading(true);
    try { await fn(); } catch (err) { setError(errorMessage(err, fallback)); } finally { setLoading(false); }
  }

  // An approved result is already signed in; a pending one moves to the waiting screen.
  const handle = (d) => (d.status === "approved" ? navigate(landingPathFor(d.session.user)) : setStep(3));

  const start = (e) => {
    e.preventDefault();
    if (!nric || !name.trim() || !email.trim()) return setError("Enter your NRIC, full name and email.");
    run(async () => { await claimStart(nric, name.trim().replace(/\s+/g, " "), email.trim()); setStep(2); },
      "Could not start registration. Check your details and try again.");
  };

  const verify = (e) => {
    e.preventDefault();
    if (!passwordMeetsRules(pw)) return setError("Your password does not meet all the requirements.");
    if (pw !== pw2) return setError("Passwords don't match.");
    run(async () => handle(await claimVerifyOtp(nric, email.trim(), code.trim(), pw)), "That code is not valid. Check it and try again.");
  };

  const scan = (e) => {
    e.preventDefault();
    if (!front || !back) return setError("Add a photo of the front and back of your IC.");
    run(async () => handle(await claimVerifyPhotos(nric, email.trim(), front, back)), "We could not verify your IC. Try clearer photos.");
  };

  const label = "block text-sm font-medium text-slate-700 mb-1";
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4 py-8">
      <div className="bg-white shadow-lg rounded-2xl p-6 sm:p-8 w-full max-w-sm border border-slate-200">
        <h1 className="text-2xl font-bold text-blue-900 mb-1">{tr("Create your account")}</h1>
        <p className="text-sm text-slate-500 mb-6">
          {step === 1 && "No hospital record needed. We verify your identity before you can sign in."}
          {step === 2 && "We emailed a 6-digit code to the address you entered. Enter it and choose your password."}
          {step === 3 && "Email confirmed. One more step to verify it is you."}
        </p>

        <div role="alert" aria-live="assertive">
          {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-4">{error}</div>}
        </div>

        {step === 1 && (
          <form onSubmit={start} noValidate>
            <label htmlFor="nric" className={label}>{tr("NRIC")}</label>
            <input id="nric" className={INPUT} value={nric} onChange={(e) => setNric(e.target.value.replace(/[^0-9a-z]/gi, "").toUpperCase())}
              placeholder={tr("e.g. 520314011234 (no dashes needed)")} autoComplete="off" inputMode="numeric" autoCapitalize="characters" />
            <label htmlFor="fullname" className={label}>{tr("Full name")}</label>
            <input id="fullname" className={INPUT} value={name} onChange={(e) => setName(e.target.value.toUpperCase())}
              placeholder={tr("As printed on your IC")} autoComplete="name" autoCapitalize="characters" />
            <label htmlFor="email" className={label}>{tr("Email")}</label>
            <input id="email" className={INPUT} type="email" value={email} onChange={(e) => setEmail(e.target.value)}
              autoComplete="email" autoCapitalize="none" />
            <button disabled={loading} className={BUTTON}>{loading ? "Sending..." : "Send verification code"}</button>
          </form>
        )}

        {step === 2 && (
          <form onSubmit={verify}>
            <label htmlFor="code" className={label}>{tr("Verification code")}</label>
            <input id="code" className={INPUT} value={code} onChange={(e) => setCode(e.target.value)}
              inputMode="numeric" placeholder={tr("6-digit code")} autoComplete="one-time-code" />
            <label htmlFor="pw" className={label}>{tr("Password")}</label>
            <input id="pw" className={INPUT} type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" />
            <PasswordRules value={pw} />
            <label htmlFor="pw2" className={`${label} mt-3`}>{tr("Confirm password")}</label>
            <input id="pw2" className={INPUT} type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" />
            <button disabled={loading || !code.trim() || !pw} className={BUTTON}>{loading ? "Checking..." : "Verify and continue"}</button>
            <button type="button" onClick={() => { setStep(1); setCode(""); setError(""); }} className="w-full text-slate-500 text-sm mt-3">
              Wrong email or no code? Go back
            </button>
          </form>
        )}

        {step === 3 && (
          <div>
            <p className="text-sm text-slate-700 mb-3">
              Your sign-up is <b>{tr("waiting for verification")}</b>. You cannot sign in yet. It is approved once
              staff check your IC at a counter{photoCheck ? ", or as soon as the IC photos below match" : ""}.
              Only the first verified sign-up for an NRIC is kept; any others are rejected and their emails flagged.
            </p>
            {photoCheck && (
              <form onSubmit={scan}>
                <label htmlFor="front" className={label}>{tr("IC front")}</label>
                <input id="front" className={INPUT} type="file" accept="image/*" capture="environment" onChange={(e) => setFront(e.target.files[0] || null)} />
                <label htmlFor="back" className={label}>{tr("IC back")}</label>
                <input id="back" className={INPUT} type="file" accept="image/*" capture="environment" onChange={(e) => setBack(e.target.files[0] || null)} />
                <button disabled={loading} className={BUTTON}>{loading ? "Checking..." : "Verify with IC photos"}</button>
              </form>
            )}
          </div>
        )}

        <p className="text-xs text-slate-500 mt-6 text-center">
          <Link to="/login" className="text-blue-700 hover:underline">{tr("Back to sign in")}</Link>
        </p>
      </div>
    </div>
  );
}
