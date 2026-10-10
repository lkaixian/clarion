import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { getCurrentUser, logout, getClockStatus, clockIn, clockOut } from "../api/client";
import { landingPathFor } from "../lib/access";
import Watermark from "./Watermark";

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
    <div className="flex items-center justify-between gap-2">
      <span className="text-xs text-blue-200">
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

// Grouped nav: [group label, [[page key, route label], ...]]. Group order is
// the order a clinic actually works in; a group with no visible link is hidden.
const NAV_GROUPS = [
  ["Care", [["patients", "Patients"], ["reception", "Reception"], ["ancillary", "Ancillary"], ["dental", "Dental"], ["pharmacy", "Pharmacy"]]],
  ["Business", [["billing", "Billing"], ["reporting", "Reporting"], ["dashboard", "Dashboard"]]],
  ["System", [["admin", "Admin Console"]]],
];

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white";

const linkCls = ({ isActive }) =>
  `block rounded-lg px-3 py-2 text-sm ${FOCUS} ` +
  (isActive ? "bg-blue-700 text-white font-medium" : "text-blue-200 hover:bg-blue-800 hover:text-white");

export default function Layout({ children }) {
  const user = getCurrentUser();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const menuBtn = useRef(null);
  const drawer = useRef(null);
  useEffect(() => setOpen(false), [pathname]); // close the mobile drawer on navigation

  // Drawer: Escape closes, focus moves in on open and back to the Menu button
  // on close, and it resets if the viewport grows past the md breakpoint.
  // ponytail: no full Tab trap (scrim covers pointer; add `inert` on <main> if needed).
  useEffect(() => {
    if (!open) return;
    const btn = menuBtn.current;
    drawer.current?.querySelector("a,button")?.focus();
    const onKey = (e) => e.key === "Escape" && setOpen(false);
    const mq = window.matchMedia("(min-width: 768px)");
    const onMq = (e) => e.matches && setOpen(false);
    document.addEventListener("keydown", onKey);
    mq.addEventListener("change", onMq);
    return () => {
      document.removeEventListener("keydown", onKey);
      mq.removeEventListener("change", onMq);
      btn?.focus();
    };
  }, [open]);

  // Nav links are driven by the backend's per-facility allowed_pages matrix;
  // an admin implicitly sees everything. Mirrors App.jsx's RequirePage guard,
  // so the nav never advertises a page that would bounce straight back.
  const pages = user?.allowed_pages || [];
  const canSee = (page) => user?.role === "admin" || pages.includes(page);
  const isPatient = user?.role === "patient";
  // Every post-login page carries the viewer watermark; on a patient record it
  // also names the patient.
  const watchedPatientId = pathname.match(/^\/patients\/([^/]+)/)?.[1];
  const homeHref = landingPathFor(user);

  const sidebar = (
    <div className="flex h-full flex-col gap-4 p-4">
      {/* Logo mark is dark-navy on transparent (public/Logo/Clarion.png), so
          it sits on a white pill against the dark sidebar. */}
      <Link to={homeHref} className="flex items-center justify-center bg-white rounded-lg px-3 py-2">
        <img src="/Logo/Clarion.png" alt="CLARION" className="h-7 w-auto" />
      </Link>

      <nav aria-label="Main" className="flex-1 space-y-4 overflow-y-auto">
        {isPatient ? (
          <NavLink to={homeHref} end className={linkCls}>My record</NavLink>
        ) : (
          NAV_GROUPS.map(([label, items]) => {
            const visible = items.filter(([page]) => canSee(page));
            if (!visible.length) return null;
            return (
              <div key={label}>
                <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-blue-300">{label}</p>
                {visible.map(([page, text]) => (
                  <NavLink key={page} to={`/${page}`} className={linkCls}>{text}</NavLink>
                ))}
              </div>
            );
          })
        )}
      </nav>

      <div className="space-y-2 border-t border-blue-800 pt-3">
        <ClockControl user={user} />
        {/* Name/role links to the profile page (signature management) for
            staff; a patient has no signature or profile, so it's a label. */}
        {isPatient ? (
          <div className="px-3 py-2 text-sm text-blue-200">{user.full_name}<span className="block text-xs text-blue-300">patient</span></div>
        ) : (
          user && (
            <NavLink to="/profile" className={linkCls}>
              {user.full_name}
              <span className="block text-xs text-blue-300">{user.role}</span>
            </NavLink>
          )
        )}
        <NavLink to="/security" className={linkCls}>Security</NavLink>
        <button
          onClick={() => { logout(); navigate("/login"); }}
          className={`w-full rounded-lg bg-blue-800 px-3 py-2 text-sm text-white hover:bg-blue-700 ${FOCUS}`}
        >
          Sign out
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-50 md:flex">
      <Watermark patientId={watchedPatientId} />
      {/* Desktop: fixed sidebar. Mobile: slim top bar + slide-over drawer. */}
      <aside className="hidden md:block md:w-60 md:shrink-0 bg-blue-900 text-white md:sticky md:top-0 md:h-screen">
        {sidebar}
      </aside>

      <header className="md:hidden flex items-center justify-between bg-blue-900 px-4 py-2 text-white">
        <Link to={homeHref} className="bg-white rounded-lg px-2 py-1">
          <img src="/Logo/Clarion.png" alt="CLARION" className="h-5 w-auto" />
        </Link>
        <button
          ref={menuBtn}
          onClick={() => setOpen(true)}
          aria-label="Open menu"
          aria-expanded={open}
          aria-controls="mobile-menu"
          className="rounded-lg bg-blue-800 px-3 py-1.5 text-sm"
        >
          Menu
        </button>
      </header>

      {open && (
        <div id="mobile-menu" ref={drawer} className="md:hidden fixed inset-0 z-40 flex" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="w-64 max-w-[80%] bg-blue-900 text-white">{sidebar}</div>
          <button className="flex-1 bg-black/40" aria-label="Close menu" onClick={() => setOpen(false)} />
        </div>
      )}

      <main className="min-w-0 flex-1 p-4 md:p-6">
        <div className="mx-auto max-w-5xl">{children}</div>
      </main>
    </div>
  );
}
