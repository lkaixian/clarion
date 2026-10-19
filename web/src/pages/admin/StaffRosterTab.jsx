import { useEffect, useRef, useState } from "react";
import {
  getSections,
  getStaffRoster, getStaffClockHistory, updateStaffMember,
  updateStaffProfile, uploadStaffPhoto, getStaffPhotoBlob, resetStaffPassword,
} from "../../api/client";
import { formatDateTime } from "../../lib/format";
import { Section } from "./_shared";
import StepUpForm from "./StepUpForm";
import AdminAccountsPanel from "./AdminAccountsPanel";
import { tr } from "../../lib/i18n";

// duration_minutes is server-computed (ClockEventOut) — never re-derive it
// client-side, this just formats what's already on the object. null means
// the pair is still open (no clock-out yet).
function formatDuration(minutes) {
  if (minutes == null) return "Still clocked in";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h === 0) return `${m}m`;
  if (m === 0) return `${h}h`;
  return `${h}h ${m}m`;
}

// ---------- Staff roster (read-only, plus on-demand clock history) ----------
// No account editing and no admin-side clock actions here — this tab is
// purely "see who's on shift right now and look up their recent history",
// per the task scope. Clock-in/out itself only ever happens from the staff
// member's own nav pill (Layout.jsx's ClockControl).
export default function StaffRosterTab() {
  const [staff, setStaff] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState(null);
  // Cache per-staff history once fetched so re-expanding the same row
  // doesn't re-hit the endpoint — a roster with many staff shouldn't turn
  // into repeated requests just from someone toggling a row a few times.
  const [historyById, setHistoryById] = useState({});
  const [historyLoading, setHistoryLoading] = useState(false);
  // Active section names for the per-row "Section" dropdown (receptionist /
  // clinician rows only). Fetched once alongside the roster.
  const [sectionNames, setSectionNames] = useState([]);
  // Per-row transient feedback after a section save: { [userId]: string }.
  const [sectionMsg, setSectionMsg] = useState({});
  const [sectionSavingId, setSectionSavingId] = useState(null);
  // Bio / contact-email draft per row, seeded from the roster row itself
  // the first time it's expanded (same lazy-on-expand ethos as
  // historyById above) — not saved until "Save profile" is clicked.
  const [profileDraftById, setProfileDraftById] = useState({});
  const [profileMsgById, setProfileMsgById] = useState({});
  const [profileSavingId, setProfileSavingId] = useState(null);
  // Photo: fetched as a blob (auth header required) -> object URL, same
  // pattern as Profile.jsx's own signature/photo preview. Cached per row;
  // every held URL is revoked on unmount.
  const [photoUrlById, setPhotoUrlById] = useState({});
  const [photoUploadingId, setPhotoUploadingId] = useState(null);
  const photoUrlsRef = useRef({});
  // One-time temporary password just issued: { id, email, password } | null.
  // Held only in this state (never stored), cleared when dismissed or replaced.
  const [resetResult, setResetResult] = useState(null);
  const [resettingId, setResettingId] = useState(null);
  const [resetError, setResetError] = useState({});
  const [stepUpFor, setStepUpFor] = useState(null); // staff id whose step-up form is open

  useEffect(
    () => () => {
      Object.values(photoUrlsRef.current).forEach((url) => url && URL.revokeObjectURL(url));
    },
    [],
  );

  useEffect(() => {
    setLoading(true);
    getStaffRoster().then(setStaff).finally(() => setLoading(false));
    getSections()
      .then((list) => setSectionNames(list.filter((s) => s.active).map((s) => s.name)))
      .catch(() => setSectionNames([]));
  }, []);

  // Only receptionists and clinicians can be pinned to a section (the
  // backend 400s anything else). value "" → send null (— All sections —).
  const SECTIONABLE_ROLES = ["clinician", "receptionist"];

  async function changeSection(member, value) {
    setSectionSavingId(member.id);
    setSectionMsg((prev) => ({ ...prev, [member.id]: "" }));
    try {
      const updated = await updateStaffMember(member.id, { section: value || null });
      setStaff((prev) => prev.map((x) => (x.id === member.id ? { ...x, ...updated } : x)));
      setSectionMsg((prev) => ({ ...prev, [member.id]: "Saved" }));
    } catch (err) {
      setSectionMsg((prev) => ({
        ...prev,
        [member.id]: err?.response?.data?.detail || "Failed to save section.",
      }));
    } finally {
      setSectionSavingId(null);
    }
  }

  async function issueTemporaryPassword(member, stepUp) {
    setResettingId(member.id);
    setResetError((prev) => ({ ...prev, [member.id]: "" }));
    try {
      const r = await resetStaffPassword(member.id, stepUp);
      setStepUpFor(null);
      setResetResult({ id: member.id, email: r.email, password: r.temporary_password });
      setStaff((prev) => prev.map((x) => (x.id === member.id ? { ...x, must_change_password: true } : x)));
    } catch (err) {
      setResetError((prev) => ({
        ...prev,
        [member.id]: err?.response?.data?.detail || "Could not reset the password.",
      }));
    } finally {
      setResettingId(null);
    }
  }

  async function toggleExpand(member) {
    if (expandedId === member.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(member.id);
    if (!profileDraftById[member.id]) {
      setProfileDraftById((prev) => ({
        ...prev,
        [member.id]: { bio: member.bio || "", contact_email: member.contact_email || "" },
      }));
    }
    if (member.has_photo && !(member.id in photoUrlById)) {
      getStaffPhotoBlob(member.id).then((url) => {
        photoUrlsRef.current[member.id] = url;
        setPhotoUrlById((prev) => ({ ...prev, [member.id]: url }));
      });
    }
    // Fetch on demand, only for the row actually being opened — not eagerly
    // for the whole roster up front (avoids N+1 requests).
    if (!historyById[member.id]) {
      setHistoryLoading(true);
      try {
        const events = await getStaffClockHistory(member.id);
        setHistoryById((prev) => ({ ...prev, [member.id]: events }));
      } finally {
        setHistoryLoading(false);
      }
    }
  }

  async function saveProfile(member) {
    const draft = profileDraftById[member.id] || { bio: "", contact_email: "" };
    setProfileSavingId(member.id);
    setProfileMsgById((prev) => ({ ...prev, [member.id]: "" }));
    try {
      const updated = await updateStaffProfile(member.id, {
        bio: draft.bio || null,
        contact_email: draft.contact_email || null,
      });
      setStaff((prev) => prev.map((x) => (x.id === member.id ? { ...x, ...updated } : x)));
      setProfileMsgById((prev) => ({ ...prev, [member.id]: "Saved" }));
    } catch (err) {
      setProfileMsgById((prev) => ({
        ...prev,
        [member.id]: err?.response?.data?.detail || "Failed to save profile.",
      }));
    } finally {
      setProfileSavingId(null);
    }
  }

  async function changePhoto(member, file) {
    if (!file) return;
    setPhotoUploadingId(member.id);
    try {
      await uploadStaffPhoto(member.id, file);
      const url = await getStaffPhotoBlob(member.id);
      if (photoUrlsRef.current[member.id]) URL.revokeObjectURL(photoUrlsRef.current[member.id]);
      photoUrlsRef.current[member.id] = url;
      setPhotoUrlById((prev) => ({ ...prev, [member.id]: url }));
      setStaff((prev) => prev.map((x) => (x.id === member.id ? { ...x, has_photo: true } : x)));
    } catch (err) {
      setProfileMsgById((prev) => ({
        ...prev,
        [member.id]: err?.response?.data?.detail || "Failed to upload photo.",
      }));
    } finally {
      setPhotoUploadingId(null);
    }
  }

  return (
    <>
    <Section title={tr("Staff Roster")}>
      {loading ? (
        <p className="text-sm text-slate-400">{tr("Loading...")}</p>
      ) : staff.length === 0 ? (
        <p className="text-sm text-slate-400">{tr("No clinicians or records officers on file for this facility yet.")}</p>
      ) : (
        <div className="space-y-2">
          {staff.map((s) => (
            <div key={s.id} className="border border-slate-200 rounded-lg overflow-hidden">
              <button
                onClick={() => toggleExpand(s)}
                className="w-full flex items-center justify-between gap-3 px-3 py-2 text-left hover:bg-slate-50"
              >
                <div className="text-sm text-slate-700 min-w-0">
                  <p className="font-medium">
                    {s.full_name}
                    <span className="ml-2 text-xs font-normal text-slate-400 capitalize">{s.role.replace("_", " ")}</span>
                    {/* Same amber "needs attention" convention as InventoryTab's
                        low-stock flag and WardsTab's high-occupancy badge. */}
                    {s.must_change_password && (
                      <span className="ml-2 text-xs font-semibold text-amber-700 uppercase">{tr("⚠ Pending first login")}</span>
                    )}
                  </p>
                  <p className="text-xs text-slate-400">{s.email}</p>
                </div>
                {/* Live status indicator — green for "clocked in" (same
                    green-for-good convention as WardsTab's low-occupancy
                    text), neutral grey otherwise. */}
                <span className="text-xs whitespace-nowrap shrink-0">
                  {s.clocked_in ? (
                    <span className="text-green-700 font-medium">Clocked in since {formatDateTime(s.since)}</span>
                  ) : s.last_clock_out_at ? (
                    <span className="text-slate-500">Last clocked out {formatDateTime(s.last_clock_out_at)}</span>
                  ) : (
                    <span className="text-slate-400">{tr("Clocked out")}</span>
                  )}
                </span>
              </button>

              {/* Section pin — only receptionists / clinicians can hold one.
                  Kept outside the toggle <button> (no nested interactives). */}
              {SECTIONABLE_ROLES.includes(s.role) && (
                <div className="border-t border-slate-200 px-3 py-2 flex flex-wrap items-center gap-2">
                  <label className="text-xs font-medium text-slate-500">{tr("Section")}</label>
                  <select
                    value={s.section || ""}
                    disabled={sectionSavingId === s.id}
                    onChange={(e) => changeSection(s, e.target.value)}
                    className="border border-slate-300 rounded-lg px-2 py-1 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
                  >
                    <option value="">{tr("— All sections —")}</option>
                    {/* Preserve an assigned-but-now-inactive section as an option. */}
                    {s.section && !sectionNames.includes(s.section) && (
                      <option value={s.section}>{s.section} (inactive)</option>
                    )}
                    {sectionNames.map((name) => <option key={name} value={name}>{name}</option>)}
                  </select>
                  {sectionMsg[s.id] && (
                    <span
                      className={`text-xs ${
                        sectionMsg[s.id] === "Saved" ? "text-green-700" : "text-red-700"
                      }`}
                    >
                      {sectionMsg[s.id]}
                    </span>
                  )}
                </div>
              )}

              <div className="border-t border-slate-200 px-3 py-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => { setResetError((p) => ({ ...p, [s.id]: "" })); setStepUpFor(s.id); }}
                  disabled={resettingId === s.id}
                  className="text-xs border border-slate-300 rounded-lg px-2 py-1 hover:bg-slate-50 disabled:opacity-50"
                >
                  Reset password
                </button>
              </div>
              {stepUpFor === s.id && (
                <StepUpForm
                  title={`Issue a temporary password for ${s.full_name}. Their current password stops working and they are signed out everywhere.`}
                  busy={resettingId === s.id}
                  error={resetError[s.id]}
                  onSubmit={(stepUp) => issueTemporaryPassword(s, stepUp)}
                  onCancel={() => setStepUpFor(null)}
                />
              )}
              {resetResult?.id === s.id && (
                <div className="border-t border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 space-y-1" role="status">
                  <p>
                    Temporary password for <b>{resetResult.email}</b> (shown once — give it to them in person):
                  </p>
                  <p className="font-mono text-sm break-all select-all">{resetResult.password}</p>
                  <p>{tr("They must choose a new password at their next sign-in.")}</p>
                  <button type="button" onClick={() => setResetResult(null)} className="underline">
                    Done, hide it
                  </button>
                </div>
              )}

              {expandedId === s.id && (
                <div className="border-t border-slate-200 bg-slate-50 px-3 py-2 space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="shrink-0">
                      {photoUrlById[s.id] ? (
                        <img
                          src={photoUrlById[s.id]}
                          alt=""
                          className="w-14 h-14 rounded-full object-cover border border-slate-200 bg-white"
                        />
                      ) : (
                        <div className="w-14 h-14 rounded-full border border-slate-200 bg-white" />
                      )}
                      <label className="block mt-1 text-xs text-blue-800 cursor-pointer text-center">
                        {photoUploadingId === s.id ? "Uploading…" : "Change"}
                        <input
                          type="file"
                          accept="image/png,image/jpeg,image/webp,image/heic"
                          className="hidden"
                          disabled={photoUploadingId === s.id}
                          onChange={(e) => changePhoto(s, e.target.files?.[0])}
                        />
                      </label>
                    </div>
                    <div className="flex-1 min-w-0 space-y-1.5">
                      <textarea
                        rows={2}
                        placeholder={tr("Bio / working experience (shown to patients on the booking screen)")}
                        value={profileDraftById[s.id]?.bio ?? ""}
                        onChange={(e) =>
                          setProfileDraftById((prev) => ({
                            ...prev,
                            [s.id]: { ...prev[s.id], bio: e.target.value },
                          }))
                        }
                        className="w-full border border-slate-300 rounded-lg px-2 py-1 text-xs"
                      />
                      <input
                        type="email"
                        placeholder={tr("Internal contact email (not shown to patients)")}
                        value={profileDraftById[s.id]?.contact_email ?? ""}
                        onChange={(e) =>
                          setProfileDraftById((prev) => ({
                            ...prev,
                            [s.id]: { ...prev[s.id], contact_email: e.target.value },
                          }))
                        }
                        className="w-full border border-slate-300 rounded-lg px-2 py-1 text-xs"
                      />
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => saveProfile(s)}
                          disabled={profileSavingId === s.id}
                          className="text-xs bg-blue-800 text-white px-2 py-1 rounded-lg disabled:opacity-50"
                        >
                          {profileSavingId === s.id ? "Saving…" : "Save profile"}
                        </button>
                        {profileMsgById[s.id] && (
                          <span
                            className={`text-xs ${
                              profileMsgById[s.id] === "Saved" ? "text-green-700" : "text-red-700"
                            }`}
                          >
                            {profileMsgById[s.id]}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {historyLoading && !historyById[s.id] ? (
                    <p className="text-xs text-slate-400">{tr("Loading history...")}</p>
                  ) : (historyById[s.id] || []).length === 0 ? (
                    <p className="text-xs text-slate-400">{tr("No clock events on file yet.")}</p>
                  ) : (
                    <ul className="space-y-1">
                      {historyById[s.id].map((ev) => (
                        <li key={ev.id} className="text-xs text-slate-600">
                          {formatDateTime(ev.clock_in_at)}
                          {" → "}
                          {ev.clock_out_at ? formatDateTime(ev.clock_out_at) : "still clocked in"}
                          {" · "}{formatDuration(ev.duration_minutes)}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </Section>
    <AdminAccountsPanel />
    </>
  );
}
