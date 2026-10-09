import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getCurrentUser, logout, getClockStatus, clockIn, clockOut } from "../api/client";
import { landingPathFor } from "../lib/access";

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

  // Clinicians clock in/out implicitly via Start/End consultation session
  // (PatientList.jsx's <MyConsultationRoom />), so they get no nav pill —
  // two competing clock controls would be confusing. Everyone else
  // (admin, records_officer, receptionist, pharmacist) keeps it.
  if (!user || user.role === "patient" || user.role === "clinician") return null;

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
  // "Home" = the first page this user's role is allowed to open at this
  // facility (a patient → their own record). Same helper Login.jsx and
  // App.jsx's RequirePage guard use, so the logo link can never point at a
  // page the guard would immediately bounce them off.
  const homeHref = landingPathFor(user);
  // Nav links are driven by the backend's per-facility allowed_pages matrix;
  // an admin implicitly sees everything.
  const pages = user?.allowed_pages || [];
  const canSee = (page) => user?.role === "admin" || pages.includes(page);

  return (
    <div className="min-h-screen bg-slate-50">
      <nav className="bg-blue-900 text-white px-6 py-3 flex items-center justify-between">
        {/* Logo mark is dark-navy on a transparent background (see
            public/Logo/Clarion.png) -- unreadable directly against this
            nav's own dark-navy background, so it sits on a small white
            pill rather than bare on the nav. */}
        <Link to={homeHref} className="flex items-center gap-2 bg-white rounded-lg px-3 py-1.5">
          <img src="/Logo/Clarion.png" alt="CLARION" className="h-6 w-auto" />
          <span className="font-bold text-lg sr-only">CLARION Console</span>
        </Link>
        <div className="flex items-center gap-4 text-sm">
          {/* Every link below mirrors App.jsx's RequirePage guard — shown only
              when the user's role is allowed that page at this facility, so
              the nav never advertises a page that would redirect straight
              back. A receptionist therefore sees only "Reception". */}
          {canSee("patients") && <Link to="/patients" className="text-blue-200 hover:text-white">Patients</Link>}
          {canSee("reception") && <Link to="/reception" className="text-blue-200 hover:text-white">Reception</Link>}
          {canSee("ancillary") && <Link to="/ancillary" className="text-blue-200 hover:text-white">Ancillary</Link>}
          {canSee("dental") && <Link to="/dental" className="text-blue-200 hover:text-white">Dental</Link>}
          {canSee("billing") && <Link to="/billing" className="text-blue-200 hover:text-white">Billing</Link>}
          {canSee("reporting") && <Link to="/reporting" className="text-blue-200 hover:text-white">Reporting</Link>}
          {canSee("dashboard") && <Link to="/dashboard" className="text-blue-200 hover:text-white">Dashboard</Link>}
          {canSee("pharmacy") && <Link to="/pharmacy" className="text-blue-200 hover:text-white">Pharmacy</Link>}
          {canSee("admin") && <Link to="/admin" className="text-blue-200 hover:text-white">Admin Console</Link>}
          <ClockControl user={user} />
          {/* Name/role doubles as the link to the profile page (signature
              management) — for every non-patient role. A patient account has
              no signature and no profile page, so it stays a plain label. */}
          {user && user.role !== "patient" && (
            <Link to="/profile" className="text-blue-200 hover:text-white">
              {user.full_name} · {user.role}
            </Link>
          )}
          {user && user.role === "patient" && (
            <span className="text-blue-200">{user.full_name} · {user.role}</span>
          )}
          <button
            onClick={() => { logout(); navigate("/login"); }}
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
