import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { requestPasswordResetOtp, resetPasswordWithOtp } from "../api/client";

// Two-step self-service reset: NRIC only (no date of birth — DOB is
// guessable/knowable PII, same weakness NRIC itself has, so it was dropped
// in favour of a one-time code emailed to whatever contact address the
// patient has on file). Step 1's response is intentionally the same
// whether or not the NRIC/account/email actually exists — the UI copy
// below reflects that on purpose, don't tighten it to imply success/failure.
export default function ForgotPassword() {
  const [step, setStep] = useState(1);
  const [nationalId, setNationalId] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleRequestCode(e) {
    e.preventDefault();
    setError("");
    if (!nationalId.trim()) {
      setError("Enter your NRIC.");
      return;
    }
    setLoading(true);
    try {
      await requestPasswordResetOtp(nationalId.trim());
      setInfo("If this NRIC has a registered account with an email on file, a verification code has been sent to it.");
      setStep(2);
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not request a verification code. Try again shortly.");
    } finally {
      setLoading(false);
    }
  }

  async function handleResetPassword(e) {
    e.preventDefault();
    setError("");
    if (!otpCode.trim() || !newPassword) {
      setError("Enter the code and a new password.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    setLoading(true);
    try {
      await resetPasswordWithOtp(nationalId.trim(), otpCode.trim(), newPassword);
      navigate("/", { state: { resetSuccess: true } });
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not reset your password. Check the code and try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="bg-white shadow-lg rounded-2xl p-8 w-full max-w-sm border border-slate-200">
        <h1 className="text-2xl font-bold text-blue-900 mb-1">Reset Password</h1>
        <p className="text-sm text-slate-500 mb-6">
          {step === 1
            ? "Patients only. Enter your NRIC — with or without dashes."
            : "Enter the code and choose a new password."}
        </p>

        {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-4">{error}</div>}
        {info && step === 2 && <div className="bg-blue-50 text-blue-800 text-sm p-2 rounded mb-4">{info}</div>}

        {step === 1 ? (
          <form onSubmit={handleRequestCode}>
            <label className="block text-sm font-medium text-slate-700 mb-1">NRIC</label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-6 focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={nationalId}
              onChange={(e) => setNationalId(e.target.value)}
              placeholder="e.g. 520314-01-1234 or 520314011234"
              autoComplete="off"
            />
            <button
              disabled={loading}
              className="w-full bg-blue-800 hover:bg-blue-900 text-white font-semibold py-2.5 rounded-lg transition disabled:opacity-50"
            >
              {loading ? "Sending..." : "Send verification code"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleResetPassword}>
            <label className="block text-sm font-medium text-slate-700 mb-1">Verification code</label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={otpCode}
              onChange={(e) => setOtpCode(e.target.value)}
              inputMode="numeric"
              placeholder="6-digit code"
              autoComplete="one-time-code"
            />
            <label className="block text-sm font-medium text-slate-700 mb-1">New password</label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              type="password"
              autoComplete="new-password"
            />
            <label className="block text-sm font-medium text-slate-700 mb-1">Confirm new password</label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              type="password"
              autoComplete="new-password"
            />
            <p className="text-xs text-slate-400 mb-4">At least 8 characters.</p>
            <button
              disabled={loading}
              className="w-full bg-blue-800 hover:bg-blue-900 text-white font-semibold py-2.5 rounded-lg transition disabled:opacity-50"
            >
              {loading ? "Resetting..." : "Reset password"}
            </button>
            <button
              type="button"
              onClick={() => { setStep(1); setOtpCode(""); setError(""); }}
              className="w-full text-slate-500 text-sm mt-3"
            >
              Didn't get a code? Try again
            </button>
          </form>
        )}

        <p className="text-xs text-slate-400 mt-6 text-center">
          <Link to="/" className="text-blue-700 hover:underline">Back to sign in</Link>
        </p>
      </div>
    </div>
  );
}
