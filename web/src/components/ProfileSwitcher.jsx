import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { getCurrentUser, getProfiles, switchProfile, errorMessage } from "../api/client";
import { landingPathFor } from "../lib/access";
import { tr } from "../lib/i18n";

const FOCUS = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white";

// Switch to a profile, store the new session (done by switchProfile), then land on
// that profile's home. Pages fetch on mount, so the route change drops stale data;
// if we are already on that page, reload it.
export function useProfileSwitch() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  return async (patientId) => {
    await switchProfile(patientId);
    const home = landingPathFor(getCurrentUser());
    if (home === pathname) navigate(0);
    else navigate(home);
  };
}

// Shown on every page while acting for someone else.
export function ActingBanner() {
  const user = getCurrentUser();
  const doSwitch = useProfileSwitch();
  const [err, setErr] = useState("");
  const [notice] = useState(() => {
    const n = sessionStorage.getItem("mb_notice");
    if (n) sessionStorage.removeItem("mb_notice");
    return n;
  });
  const acting = user?.role === "patient" && user.acting_for;
  if (!acting && !notice) return null;
  async function back() {
    setErr("");
    try { await doSwitch(user.home_patient_id); } catch (e) { setErr(errorMessage(e, tr("Could not switch profile."))); }
  }
  return (
    <div role="status" aria-live="polite" className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900">
      {notice && <span>{tr(notice)}</span>}
      {acting && (
        <>
          <span>{tr("Acting for")} <strong>{user.full_name}</strong></span>
          <button type="button" onClick={back} className="rounded-lg border border-amber-400 bg-white px-3 py-1 font-medium hover:bg-amber-100">
            {tr("Back to my profile")}
          </button>
        </>
      )}
      {err && <span role="alert" className="text-red-700">{err}</span>}
    </div>
  );
}

export default function ProfileSwitcher() {
  const user = getCurrentUser();
  const doSwitch = useProfileSwitch();
  const [open, setOpen] = useState(false);
  const [profiles, setProfiles] = useState(null);
  const [err, setErr] = useState("");
  const btn = useRef(null);
  const menu = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    getProfiles()
      .then((d) => { if (!cancelled) setProfiles(d.profiles); })
      .catch((e) => { if (!cancelled) setErr(errorMessage(e, tr("Could not load profiles."))); });
    return () => { cancelled = true; };
  }, [open]);

  // Focus moves into the menu when it opens (once the list has loaded).
  useEffect(() => {
    if (open) menu.current?.querySelector("button:not(:disabled), a")?.focus();
  }, [open, profiles]);

  if (user?.role !== "patient") return null;

  const close = () => { setOpen(false); btn.current?.focus(); };
  const onKeyDown = (e) => {
    if (e.key === "Escape") { e.stopPropagation(); close(); }
  };

  async function pick(p) {
    setErr("");
    if (p.patient_id === user.patient_id) { close(); return; }
    try { await doSwitch(p.patient_id); setOpen(false); }
    catch (e) { setErr(errorMessage(e, tr("Could not switch profile."))); }
  }

  return (
    <div className="relative px-1" onKeyDown={onKeyDown}>
      <button
        ref={btn}
        type="button"
        aria-expanded={open}
        aria-controls="profile-menu"
        onClick={() => setOpen((o) => !o)}
        className={`flex w-full items-center justify-between gap-2 rounded-lg bg-blue-800 px-3 py-2 text-left text-sm text-white hover:bg-blue-700 ${FOCUS}`}
      >
        <span className="min-w-0">
          <span className="block text-[11px] text-blue-300">{user.acting_for ? tr("Acting for") : tr("Profile")}</span>
          <span className="block truncate">{user.full_name}</span>
        </span>
        <span aria-hidden="true">&#9662;</span>
      </button>
      {open && (
        <div id="profile-menu" ref={menu} role="group" aria-label={tr("Switch profile")} className="mt-1 space-y-1 rounded-lg bg-blue-950 p-2 text-sm">
          {!profiles && !err && <p className="px-2 py-1 text-blue-200">{tr("Loading…")}</p>}
          {profiles?.map((p) => (
            <button
              key={p.patient_id}
              type="button"
              onClick={() => pick(p)}
              disabled={p.pending_approval}
              aria-current={p.patient_id === user.patient_id ? "true" : undefined}
              className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-white hover:bg-blue-800 ${FOCUS} ${p.patient_id === user.patient_id ? "bg-blue-800" : ""}`}
            >
              <span className="truncate">{p.full_name}</span>
              {p.is_self && <span className="shrink-0 text-xs text-blue-300">{tr("You")}</span>}
              {p.pending_approval && <span className="shrink-0 text-xs text-amber-300">{tr("Waiting for their approval")}</span>}
            </button>
          ))}
          {err && <p role="alert" className="px-2 py-1 text-red-300">{err}</p>}
          <Link to="/family" onClick={() => setOpen(false)} className={`block rounded px-2 py-1.5 text-blue-100 hover:bg-blue-800 ${FOCUS}`}>
            {tr("Add a family member")}
          </Link>
        </div>
      )}
    </div>
  );
}
