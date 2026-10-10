import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { changePassword, getCurrentUser, logout, errorMessage } from "../api/client";
import PasswordRules, { passwordMeetsRules } from "../components/PasswordRules";


// Shown right after sign-in when the account must set its own password
// (every seeded production account, and staff-issued temporary passwords).
// The backend answers 403 to everything else until this succeeds.
export default function ChangePassword() {
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const user = getCurrentUser();
  const fields = [
    ["new", "New password", next, setNext, "new-password"],
    ["confirm", "Confirm new password", confirm, setConfirm, "new-password"],
  ];

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (!passwordMeetsRules(next)) return setError("Your new password does not meet all the requirements.");
    if (next !== confirm) return setError("The two new passwords do not match.");
    setLoading(true);
    try {
      await changePassword(next);
      // The backend revokes every session on a password change, so sign in again.
      logout();
      navigate("/login", { state: { resetSuccess: true } });
    } catch (err) {
      setError(errorMessage(err, "Could not change the password. Please try again."));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <form onSubmit={handleSubmit} className="bg-white shadow-lg rounded-2xl p-8 w-full max-w-sm border border-slate-200">
        <img src="/brand/logo-full.png" alt="CLARION" className="w-40 mx-auto mb-2" />
        <h1 className="text-lg font-semibold text-slate-800 text-center">Set your password</h1>
        <p className="text-sm text-slate-500 text-center mb-6">
          {user?.full_name ? `${user.full_name}, choose` : "Choose"} a new password before continuing.
        </p>
        {error && <div role="alert" className="bg-red-50 text-red-700 text-sm p-2 rounded mb-4">{error}</div>}

        {fields.map(([id, label, value, set, auto]) => (
          <div key={id} className="mb-4">
            <label htmlFor={id} className="block text-sm font-medium text-slate-700 mb-1">{label}</label>
            <input id={id} type="password" autoComplete={auto} value={value} onChange={(e) => set(e.target.value)}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
            {id === "new" && <PasswordRules value={next} />}
          </div>
        ))}

        <button disabled={loading || !passwordMeetsRules(next) || !confirm}
          className="w-full bg-blue-800 hover:bg-blue-900 text-white font-semibold py-2.5 rounded-lg transition disabled:opacity-50">
          {loading ? "Saving..." : "Change password"}
        </button>
      </form>
    </div>
  );
}
