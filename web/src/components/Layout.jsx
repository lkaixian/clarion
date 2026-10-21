import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { getCurrentUser, logout, getClockStatus, clockIn, clockOut, getMyPhotoBlob, getMyHospital, getUnreadCount } from "../api/client";
import { landingPathFor } from "../lib/access";
import { roleLabel } from "../lib/role";
import Watermark from "./Watermark";
import LanguageSelect from "./LanguageSelect";
import { tr, useLang } from "../lib/i18n";
import ProfileSwitcher, { ActingBanner } from "./ProfileSwitcher";
import RoleSwitcher from "./RoleSwitcher";

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
    return <span className="text-xs text-blue-300">{tr("Loading status…")}</span>;
  }

  return (
    <div className="flex items-center justify-between gap-2">
      <span role="status" className="text-xs text-blue-200">
        {status.clocked_in ? (
          <>Clocked in since {formatClockTime(status.since)}</>
        ) : status.last_clock_out_at ? (
          <>Last clocked out {formatClockTime(status.last_clock_out_at)}</>
        ) : (
          <>{tr("Clocked out")}</>
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

// Every page renders its own <Layout>, so the sidebar remounts on each route change and its scroll
// position would reset to the top. Remember it here and put it back when the nav mounts.
let savedNavScroll = 0;
const restoreNavScroll = (el) => { if (el) el.scrollTop = savedNavScroll; };
const rememberNavScroll = (e) => { savedNavScroll = e.currentTarget.scrollTop; };

// Grouped nav: [group label, [[page key, route label], ...]]. Group order is
// the order a clinic actually works in; a group with no visible link is hidden.
const NAV_GROUPS = [
  ["Care", [["patients", "Patients"], ["reception", "Reception"], ["orders", "Orders"], ["ancillary", "Ancillary"], ["dental", "Dental"], ["pharmacy", "Pharmacy"], ["purchasing", "Purchasing"], ["catalogue", "Catalogue"]]],
  ["Business", [["billing", "Billing"], ["cashier", "Cashier"], ["reporting", "Reporting"], ["dashboard", "Dashboard"]]],
  ["System", [["forms", "Forms"], ["admin", "Admin Console"]]],
];

// Round profile photo (or a generic person icon) beside the signed-in staff
// name. The photo is a Bearer-auth blob fetch; it re-fetches on the
// "mb-profile-updated" event Profile fires after an upload/delete, and reads
// has_photo from the cached user at that moment (Layout itself doesn't re-render).
function Avatar() {
  const [url, setUrl] = useState(null);
  const [ver, setVer] = useState(0);
  const prev = useRef(null);
  useEffect(() => {
    const bump = () => setVer((v) => v + 1);
    window.addEventListener("mb-profile-updated", bump);
    return () => {
      window.removeEventListener("mb-profile-updated", bump);
      if (prev.current) URL.revokeObjectURL(prev.current);
    };
  }, []);
  useEffect(() => {
    if (!getCurrentUser()?.has_photo) {
      if (prev.current) URL.revokeObjectURL(prev.current);
      prev.current = null;
      setUrl(null);
      return undefined;
    }
    let cancelled = false;
    getMyPhotoBlob()
      .then((u) => {
        if (cancelled) { if (u) URL.revokeObjectURL(u); return; }
        if (prev.current) URL.revokeObjectURL(prev.current);
        prev.current = u;
        setUrl(u);
      })
      .catch(() => {}); // keep the icon; a missing photo isn't worth an error banner
    return () => { cancelled = true; };
  }, [ver]);
  if (url) {
    return <img src={url} alt="" className="h-9 w-9 shrink-0 rounded-full object-cover ring-1 ring-blue-300/40" />;
  }
  return (
    <span aria-hidden="true" className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-blue-800 text-blue-200">
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
        <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0 2c-3.3 0-8 1.7-8 5v1h16v-1c0-3.3-4.7-5-8-5z" />
      </svg>
    </span>
  );
}

// "Inbox" nav link with an unread badge. Polls (no websockets on a small
// node); a failed poll just leaves the last number.
function InboxLink({ className }) {
  const [unread, setUnread] = useState(0);
  const { pathname } = useLocation();
  useEffect(() => {
    let cancelled = false;
    const tick = () => getUnreadCount().then((n) => { if (!cancelled) setUnread(n); }).catch(() => {});
    tick();
    const t = setInterval(tick, 45000);
    return () => { cancelled = true; clearInterval(t); };
  }, [pathname]); // also refresh on every navigation, so opening a note clears it at once
  return (
    <NavLink to="/inbox" className={className}>
      <span className="flex items-center justify-between">
        Inbox
        {unread > 0 && (
          <span className="ml-2 min-w-5 rounded-full bg-red-600 px-1.5 text-center text-[11px] font-bold leading-5 text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        )}
      </span>
    </NavLink>
  );
}

// Under the CLARION mark: which hospital this staff member works under, as a
// tab with that hospital's own logo (set in Admin > Hospital Settings) or a
// building icon until one is uploaded.
function HospitalTab() {
  const [h, setH] = useState(null);
  useEffect(() => {
    getMyHospital().then(setH).catch(() => {}); // cosmetic: stay hidden on failure
  }, []);
  if (!h?.name) return null;
  return (
    <div className="flex items-center gap-2 rounded-lg bg-blue-800/70 px-3 py-2" title={h.name}>
      {h.logo_data_url ? (
        <img src={h.logo_data_url} alt="" className="h-9 w-9 shrink-0 rounded bg-white object-contain p-0.5" />
      ) : (
        <span aria-hidden="true" className="grid h-9 w-9 shrink-0 place-items-center rounded bg-blue-900 text-blue-200">
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
            <path d="M4 21V5l8-3 8 3v16h-6v-5h-4v5H4zm6-12h4V7h-4v2z" />
          </svg>
        </span>
      )}
      <span className="min-w-0 break-words text-sm font-medium leading-tight text-white">{h.name}</span>
    </div>
  );
}

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white";

const linkCls = ({ isActive }) =>
  `block rounded-lg px-3 py-2 text-sm ${FOCUS} ` +
  (isActive ? "bg-blue-700 text-white font-medium" : "text-blue-200 hover:bg-blue-800 hover:text-white");

export default function Layout({ children }) {
  const { t } = useLang();
  const user = getCurrentUser();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const [askClockOut, setAskClockOut] = useState(false);

  // Staff only (a patient has no shift). If they're still clocked in, ask
  // before leaving; a failed status check never blocks signing out.
  async function handleSignOut() {
    if (user && user.role !== "patient") {
      try {
        const status = await getClockStatus();
        if (status?.clocked_in) {
          setAskClockOut(true);
          return;
        }
      } catch { /* fall through to a plain sign-out */ }
    }
    finishSignOut(false);
  }

  async function finishSignOut(alsoClockOut) {
    if (alsoClockOut) {
      try { await clockOut(); } catch { /* sign out regardless; the shift can be closed from the roster */ }
    }
    logout();
    navigate("/login");
  }
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
  // "catalogue" is open to all staff; "cashier" rides on the billing permission.
  const riding = { cashier: "billing", purchasing: "pharmacy" };
  const canSee = (page) => {
    if (page === "catalogue") return true;
    if (user?.role === "admin") return true;
    if (page === "orders") return user?.role === "clinician" || user?.role === "pharmacist";
    if (page === "forms") return false; // admin only (the form builder)
    return pages.includes(riding[page] || page);
  };
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
        <img src="/Logo/Clarion.png" alt={tr("CLARION")} className="h-7 w-auto" />
      </Link>
      {!isPatient && <HospitalTab />}
      <RoleSwitcher />
      <ProfileSwitcher />

      <nav aria-label={tr("Main")} ref={restoreNavScroll} onScroll={rememberNavScroll} className="flex-1 space-y-4 overflow-y-auto">
        {isPatient ? (
          <>
            <NavLink to={homeHref} end className={linkCls}>{t("My record")}</NavLink>
            <NavLink to="/my-bills" className={linkCls}>{t("My bills")}</NavLink>
            <NavLink to="/family" className={linkCls}>{t("My family")}</NavLink>
          </>
        ) : (
          NAV_GROUPS.map(([label, items]) => {
            const visible = items.filter(([page]) => canSee(page));
            if (!visible.length) return null;
            return (
              <div key={label}>
                <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-blue-300">{t(label)}</p>
                {visible.map(([page, text]) => (
                  <NavLink key={page} to={`/${page}`} className={linkCls}>{t(text)}</NavLink>
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
          <div className="px-3 py-2 text-sm text-blue-200">{user.full_name}<span className="block text-xs text-blue-300">{tr("patient")}</span></div>
        ) : (
          user && (
            <NavLink to="/profile" className={(s) => linkCls(s).replace("block", "flex items-center gap-3")}>
              <Avatar />
              <span className="min-w-0">
                <span className="block truncate">{user.full_name}</span>
                <span className="block text-xs text-blue-300">{roleLabel(user.role)}</span>
              </span>
            </NavLink>
          )
        )}
        {!isPatient && <InboxLink className={linkCls} />}
        {isPatient && user.acting_for ? (
          <p className="px-3 text-xs text-blue-300">{tr("Account settings are available on your own profile.")}</p>
        ) : (
          <NavLink to="/security" className={linkCls}>{tr("Security")}</NavLink>
        )}
        <p className="px-3 text-center text-[11px] text-blue-300/80" title={tr("Web console version and build")}>
          v{import.meta.env.VITE_APP_VERSION} &middot; build {import.meta.env.VITE_APP_BUILD}
        </p>
        <LanguageSelect className="w-full" />
        <button
          onClick={handleSignOut}
          className={`w-full rounded-lg bg-blue-800 px-3 py-2 text-sm text-white hover:bg-blue-700 ${FOCUS}`}
        >
          {t("Sign out")}
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-slate-50 md:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-white focus:p-2 focus:text-blue-800">{t("Skip to main content")}</a>
      <Watermark patientId={watchedPatientId} />
      {askClockOut && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/50 p-4" role="dialog" aria-modal="true" aria-labelledby="signout-title">
          <div className="w-full max-w-sm rounded-xl bg-white p-5 shadow-xl">
            <h2 id="signout-title" className="text-base font-semibold text-slate-900">You&apos;re still clocked in</h2>
            <p className="mt-1 text-sm text-slate-600">{tr("Clock out as well? Clocking out also releases your consultation room.")}</p>
            <div className="mt-4 flex flex-col gap-2">
              <button autoFocus onClick={() => finishSignOut(true)} className="rounded-lg bg-blue-700 px-3 py-2 text-sm font-medium text-white hover:bg-blue-600">Clock out &amp; sign out</button>
              <button onClick={() => finishSignOut(false)} className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50">{tr("Sign out, stay clocked in")}</button>
              <button onClick={() => setAskClockOut(false)} className="px-3 py-2 text-sm text-slate-500 hover:text-slate-700">{tr("Cancel")}</button>
            </div>
          </div>
        </div>
      )}
      {/* Desktop: fixed sidebar. Mobile: slim top bar + slide-over drawer. */}
      <aside className="hidden md:block md:w-60 md:shrink-0 bg-blue-900 text-white md:sticky md:top-0 md:h-screen print:hidden">
        {sidebar}
      </aside>

      <header className="md:hidden flex items-center justify-between bg-blue-900 px-4 py-2 text-white print:hidden">
        <Link to={homeHref} className="bg-white rounded-lg px-2 py-1">
          <img src="/Logo/Clarion.png" alt={tr("CLARION")} className="h-5 w-auto" />
        </Link>
        <button
          ref={menuBtn}
          onClick={() => setOpen(true)}
          aria-label={tr("Open menu")}
          aria-expanded={open}
          aria-controls="mobile-menu"
          className="rounded-lg bg-blue-800 px-3 py-1.5 text-sm"
        >
          Menu
        </button>
      </header>

      {open && (
        <div id="mobile-menu" ref={drawer} className="md:hidden fixed inset-0 z-40 flex" role="dialog" aria-modal="true" aria-label={tr("Menu")}>
          <div className="w-64 max-w-[80%] bg-blue-900 text-white">{sidebar}</div>
          <button className="flex-1 bg-black/40" aria-label={tr("Close menu")} onClick={() => setOpen(false)} />
        </div>
      )}

      <main id="main" className="min-w-0 flex-1 p-4 md:p-6 print:p-0">
        <div className="mx-auto max-w-5xl">
          <ActingBanner />
          {children}
        </div>
      </main>
    </div>
  );
}
