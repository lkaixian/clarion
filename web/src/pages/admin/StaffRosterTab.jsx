import { useEffect, useState } from "react";
import {
  getSections,
  getStaffRoster, getStaffClockHistory, updateStaffMember,
} from "../../api/client";
import { formatDateTime } from "../../lib/format";
import { Section } from "./_shared";

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

  async function toggleExpand(member) {
    if (expandedId === member.id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(member.id);
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

  return (
    <Section title="Staff Roster">
      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : staff.length === 0 ? (
        <p className="text-sm text-slate-400">No clinicians or records officers on file for this facility yet.</p>
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
                      <span className="ml-2 text-xs font-semibold text-amber-700 uppercase">⚠ Pending first login</span>
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
                    <span className="text-slate-400">Clocked out</span>
                  )}
                </span>
              </button>

              {/* Section pin — only receptionists / clinicians can hold one.
                  Kept outside the toggle <button> (no nested interactives). */}
              {SECTIONABLE_ROLES.includes(s.role) && (
                <div className="border-t border-slate-200 px-3 py-2 flex flex-wrap items-center gap-2">
                  <label className="text-xs font-medium text-slate-500">Section</label>
                  <select
                    value={s.section || ""}
                    disabled={sectionSavingId === s.id}
                    onChange={(e) => changeSection(s, e.target.value)}
                    className="border border-slate-300 rounded-lg px-2 py-1 text-xs bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
                  >
                    <option value="">— All sections —</option>
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

              {expandedId === s.id && (
                <div className="border-t border-slate-200 bg-slate-50 px-3 py-2">
                  {historyLoading && !historyById[s.id] ? (
                    <p className="text-xs text-slate-400">Loading history...</p>
                  ) : (historyById[s.id] || []).length === 0 ? (
                    <p className="text-xs text-slate-400">No clock events on file yet.</p>
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
  );
}
