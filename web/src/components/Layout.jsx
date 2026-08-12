import { Link, useNavigate } from "react-router-dom";
import { getCurrentUser, logout } from "../api/client";

export default function Layout({ children }) {
  const user = getCurrentUser();
  const navigate = useNavigate();
  // A patient account has no access to GET /patients (the staff list) —
  // send them "home" to their own record instead, same fix as Login.jsx.
  const homeHref = user?.role === "patient" && user?.patient_id ? `/patients/${user.patient_id}` : "/patients";

  return (
    <div className="min-h-screen bg-slate-50">
      <nav className="bg-blue-900 text-white px-6 py-3 flex items-center justify-between">
        <Link to={homeHref} className="font-bold text-lg">MediBridge Console</Link>
        <div className="flex items-center gap-4 text-sm">
          {user && <span className="text-blue-200">{user.full_name} · {user.role}</span>}
          <button
            onClick={() => { logout(); navigate("/"); }}
            className="bg-blue-800 hover:bg-blue-700 px-3 py-1.5 rounded-lg"
          >
            Sign out
          </button>
        </div>
      </nav>
      <main className="max-w-5xl mx-auto p-6">{children}</main>
    </div>
  );
}
