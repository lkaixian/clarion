import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getCurrentUser, logout, getClockStatus, clockIn, clockOut } from "../api/client";

// Small nav pill only ever needs the time-of-day, not a full date — same
// "no date library, plain built-in formatting" approach as
// PatientDetail.jsx's formatAppointmentTime, just toLocaleTimeString()
// instead of toLocaleString() since the pill has little room and the shift
// in question is overwhelmingly the one that started today.
function formatClockTime(iso) {
  return iso ? new Date(iso).toLocaleTimeString() : "—";
}

// Nav-level clock-in/out pill — visible to any logged-in staff role
// (admin/clinician/records_officer), not a patient account (which has no
// /staff/clock-* access on the backend to begin with). Status is always
// read from the server on mount rather than guessed from nothing, same
// "don't trust local-only state" principle PatientDetail.jsx already uses
// for its emergency-card polling.
function ClockControl({ user }) {
  const [status, setStatus] = useState(null); // null = still loading initial status
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getClockStatus()
      .then((data) => { if (!cancelled) setStatus(data); })
      .catch(() => {}); // leave it in the loading/hidden state rather than showing a broken pill
    return () => { cancelled = true; };
  }, []);

  async function resync() {
    try {
      setStatus(await getClockStatus());
    } catch {
      // Nothing more we can do here — leave whatever state we last had.
    }
  }

  async function handleClick() {
    setBusy(true);
    try {
      const fresh = status?.clocked_in ? await clockOut() : await clockIn();
      setStatus(fresh);
    } catch (err) {
      // A 409 here just means the clocked-in/out state changed underneath
      // us between render and click (e.g. a double click, or another tab) —
      // a harmless race, not a real error worth surfacing. Re-sync from the
      // server and show whatever it actually says instead.
      if (err?.response?.status === 409) {
        await resync();
      }
    } finally {
      setBusy(false);
    }
  }

  if (!user || user.role === "patient") return null;

  if (status === null) {
    return <span className="text-xs text-blue-300">Loading status…</span>;
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-blue-200 whitespace-nowrap">
        {status.clocked_in ? (
          <>Clocked in since {formatClockTime(status.since)}</>
        ) : status.last_clock_out_at ? (
          <>Last clocked out {formatClockTime(status.last_clock_out_at)}</>
        ) : (
          <>Clocked out</>
        )}
      </span>
      <button
        onClick={handleClick}
        disabled={busy}
        className="bg-blue-800 hover:bg-blue-700 px-2.5 py-1 rounded-lg text-xs disabled:opacity-50"
      >
        {status.clocked_in ? "Clock Out" : "Clock In"}
      </button>
    </div>
  );
}

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
          {/* /admin is role==="admin"-only on the backend (routers/admin.py) —
              hidden for every other role rather than shown as a dead-end link;
              App.jsx's AdminOnly guard is the actual enforcement, this is just
              keeping the nav from advertising a page that would redirect away. */}
          {user?.role === "admin" && <Link to="/admin" className="text-blue-200 hover:text-white">Admin Console</Link>}
          <ClockControl user={user} />
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
