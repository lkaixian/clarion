import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { changePassword, getCurrentUser, logout } from "../api/client";

const MIN_LENGTH = 12; // matches the backend's MIN_PASSWORD_LENGTH

// Shown right after sign-in when the account must set its own password
// (every seeded production account, and staff-issued temporary passwords).
// The backend answers 403 to everything else until this succeeds.
export default function ChangePassword() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const user = getCurrentUser();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (next.length < MIN_LENGTH) return setError(`New password must be at least ${MIN_LENGTH} characters.`);
    if (next !== confirm) return setError("The two new passwords do not match.");
    setLoading(true);
    try {
      await changePassword(current, next);
      // The backend revokes every session on a password change, so sign in again.
      logout();
      navigate("/login", { state: { resetSuccess: true } });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Could not change the password. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <form onSubmit={handleSubmit} className="bg-white shadow-lg rounded-2xl p-8 w-full max-w-sm border border-slate-200">
        <img src="/Logo/Full Logo.png" alt="CLARION" className="w-40 mx-auto mb-2" />
        <h1 className="text-lg font-semibold text-slate-800 text-center">Set your password</h1>
        <p className="text-sm text-slate-500 text-center mb-6">
          {user?.full_name ? `${user.full_name}, choose` : "Choose"} a new password before continuing.
        </p>
        {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-4">{error}</div>}

        <label className="block text-sm font-medium text-slate-700 mb-1">Current (temporary) password</label>
        <input className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-blue-500"
          type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />

        <label className="block text-sm font-medium text-slate-700 mb-1">New password</label>
        <input className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-1 focus:outline-none focus:ring-2 focus:ring-blue-500"
          type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
        <p className="text-xs text-slate-400 mb-4">At least {MIN_LENGTH} characters.</p>

        <label className="block text-sm font-medium text-slate-700 mb-1">Confirm new password</label>
        <input className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-6 focus:outline-none focus:ring-2 focus:ring-blue-500"
          type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />

        <button disabled={loading || !current || !next || !confirm}
          className="w-full bg-blue-800 hover:bg-blue-900 text-white font-semibold py-2.5 rounded-lg transition disabled:opacity-50">
          {loading ? "Saving..." : "Change password"}
        </button>
      </form>
    </div>
  );
}
