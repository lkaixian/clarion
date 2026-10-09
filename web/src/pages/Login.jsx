import { useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import { login } from "../api/client";
import { landingPathFor } from "../lib/access";

export default function Login() {
  // Pre-filled demo account only in dev / when the demo hint is on; a public build starts empty.
  const demo = import.meta.env.DEV || import.meta.env.VITE_SHOW_DEMO_HINT === "1";
  const [email, setEmail] = useState(demo ? "clinician@clarion.demo" : "");
  const [password, setPassword] = useState(demo ? "clinician123" : "");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await login(email, password);
      // Land each user on the first page their facility actually lets their
      // role open (see landingPathFor / the backend's per-facility
      // allowed_pages matrix): an admin on /admin, a receptionist on
      // /reception, a pharmacist on /pharmacy, a clinician/records_officer on
      // /patients, and a patient on their own record (/patients/{id}, which
      // the backend scopes for them — they can't call the staff list).
      // A temporary password must be replaced first; the API refuses everything else until then.
      navigate(data.user.must_change_password ? "/change-password" : landingPathFor(data.user));
    } catch {
      setError("Login failed. Check credentials or that the API server is running.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <form onSubmit={handleSubmit} className="bg-white shadow-lg rounded-2xl p-8 w-full max-w-sm border border-slate-200">
        <img src="/Logo/Full Logo.png" alt="CLARION" className="w-48 mx-auto mb-2" />
        <p className="text-sm text-slate-500 text-center mb-6">Hospital Staff Console</p>

        {location.state?.resetSuccess && (
          <div className="bg-green-50 text-green-700 text-sm p-2 rounded mb-4">
            Password reset. Sign in with your new password.
          </div>
        )}
        {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-4">{error}</div>}

        <label className="block text-sm font-medium text-slate-700 mb-1">Email or NRIC</label>
        <input
          className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={email} onChange={(e) => setEmail(e.target.value)}
          // Deliberately type="text", not type="email" — a patient logs in
          // with their NRIC (e.g. 520314-01-1234), which native browser
          // email-format validation would block from ever submitting.
          type="text"
          autoComplete="username"
        />

        <div className="flex items-center justify-between mb-1">
          <label className="block text-sm font-medium text-slate-700">Password</label>
          <Link to="/forgot-password" className="text-xs text-blue-700 hover:underline">Forgot password?</Link>
        </div>
        <input
          className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-6 focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={password} onChange={(e) => setPassword(e.target.value)} type="password"
          autoComplete="current-password"
        />

        <button
          disabled={loading}
          className="w-full bg-blue-800 hover:bg-blue-900 text-white font-semibold py-2.5 rounded-lg transition disabled:opacity-50"
        >
          {loading ? "Signing in..." : "Sign In"}
        </button>

        {/* Demo logins only exist with APP_ENV=demo; hide them in container builds (set VITE_SHOW_DEMO_HINT=1 to show). */}
        {demo && (
        <p className="text-xs text-slate-400 mt-4">
          Demo (staff): clinician@clarion.demo / clinician123
          <br />
          Demo (reception): receptionist@clarion.demo / receptionist123
          <br />
          Demo (patient): patient@clarion.demo / patient123 (or NRIC 520314-01-1234)
        </p>
        )}
      </form>
    </div>
  );
}
