import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/client";

export default function Login() {
  const [email, setEmail] = useState("clinician@medibridge.demo");
  const [password, setPassword] = useState("clinician123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const data = await login(email, password);
      // BUG FIX: this console used to always navigate to /patients (the
      // staff patient-list page, GET /patients on the backend requires
      // admin/records_officer/clinician) regardless of who just logged in.
      // A patient account would land there and immediately get a 403 from
      // the backend, with no way to actually reach their own record. A
      // patient's own record view is /patients/{their own patient_id},
      // which the backend already scopes correctly for them.
      if (data.user.role === "patient" && data.user.patient_id) {
        navigate(`/patients/${data.user.patient_id}`);
      } else {
        navigate("/patients");
      }
    } catch (err) {
      setError("Login failed. Check credentials or that the API server is running.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <form onSubmit={handleSubmit} className="bg-white shadow-lg rounded-2xl p-8 w-full max-w-sm border border-slate-200">
        <h1 className="text-2xl font-bold text-blue-900 mb-1">MediBridge</h1>
        <p className="text-sm text-slate-500 mb-6">Hospital Staff Console</p>

        {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-4">{error}</div>}

        <label className="block text-sm font-medium text-slate-700 mb-1">Email</label>
        <input
          className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={email} onChange={(e) => setEmail(e.target.value)} type="email"
        />

        <label className="block text-sm font-medium text-slate-700 mb-1">Password</label>
        <input
          className="w-full border border-slate-300 rounded-lg px-3 py-2 mb-6 focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={password} onChange={(e) => setPassword(e.target.value)} type="password"
        />

        <button
          disabled={loading}
          className="w-full bg-blue-800 hover:bg-blue-900 text-white font-semibold py-2.5 rounded-lg transition disabled:opacity-50"
        >
          {loading ? "Signing in..." : "Sign In"}
        </button>

        <p className="text-xs text-slate-400 mt-4">
          Demo (staff): clinician@medibridge.demo / clinician123
          <br />
          Demo (patient): patient@medibridge.demo / patient123
        </p>
      </form>
    </div>
  );
}
