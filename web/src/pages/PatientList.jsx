import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Layout from "../components/Layout";
import {
  listPatients, createPatient, getCurrentUser,
  getConsultationRooms, getMyConsultationRoom, startConsultationSession,
  endConsultationSession, callConsultationTicket, completeConsultationTicket,
  cancelConsultationTicket,
} from "../api/client";
import SignaturePad from "../components/SignaturePad";

// Re-poll the clinician's own consultation worklist on this cadence — same
// constant convention as Reception.jsx's QUEUE_BOARD_POLL_MS.
const MY_ROOM_POLL_MS = 4000;

function formatTime(iso) {
  return iso ? new Date(iso).toLocaleTimeString() : "—";
}

// Ticket status vocabulary mirrors Reception.jsx's STATUS_* maps (a
// consultation ticket is the same queue ticket, seen from the room side).
const TICKET_STATUS = {
  waiting: { label: "Waiting", cls: "bg-slate-100 text-slate-600" },
  called: { label: "Called", cls: "bg-amber-100 text-amber-700" },
  done: { label: "Done", cls: "bg-green-100 text-green-700" },
  cancelled: { label: "Cancelled", cls: "bg-red-100 text-red-600" },
};

// Modal: mark a ticket done + record a signed outpatient encounter. The
// backend requires a signature — if the clinician has a saved one it's used
// automatically; otherwise they draw one here (which also saves to their
// profile, backend-side).
function CompleteConsultationModal({ ticket, onClose, onDone }) {
  const user = getCurrentUser();
  const hasSignature = !!user?.has_signature;
  const [note, setNote] = useState("");
  const [soap, setSoap] = useState({ subjective: "", objective: "", assessment: "", plan: "", treatment_plan: "" });
  const [sigDataUrl, setSigDataUrl] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await completeConsultationTicket(ticket.id, {
        note: note.trim() || undefined,
        ...Object.fromEntries(Object.entries(soap).map(([key, value]) => [key, value.trim() || undefined])),
        // JSON field wants RAW base64 — strip the "data:image/png;base64,"
        // prefix the canvas produced.
        signature_b64: sigDataUrl ? sigDataUrl.split(",").pop() : undefined,
      });
      onDone();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to complete the consultation.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl p-6 max-w-md w-full max-h-[90vh] overflow-y-auto">
        <h3 className="font-semibold text-slate-800 mb-1">Complete consultation</h3>
        <p className="text-xs text-slate-500 mb-4">
          #{ticket.queue_number} · {ticket.patient_full_name}
        </p>
        <form onSubmit={submit} className="space-y-3">
          {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error}</div>}
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Note (optional)</label>
            <textarea
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>
          <div className="grid gap-2">
            {[
              ["subjective", "Subjective"], ["objective", "Objective"],
              ["assessment", "Assessment"], ["plan", "Plan"], ["treatment_plan", "Treatment plan"],
            ].map(([key, label]) => (
              <label key={key} className="block text-xs font-medium text-slate-600">
                {label}
                <textarea
                  className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  rows={2}
                  value={soap[key]}
                  onChange={(e) => setSoap((current) => ({ ...current, [key]: e.target.value }))}
                />
              </label>
            ))}
          </div>
          <p className="text-xs text-slate-500">Signing as {user?.full_name}</p>
          {!hasSignature && (
            <div>
              <SignaturePad onChange={setSigDataUrl} />
              <p className="text-xs text-slate-400 mt-1">
                You have no saved signature — draw one (also saved to your profile).
              </p>
            </div>
          )}
          <div className="flex gap-2 pt-2">
            <button disabled={saving} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50">
              {saving ? "Saving..." : "Complete & sign"}
            </button>
            <button type="button" onClick={onClose} className="text-sm border border-slate-300 px-3 py-1.5 rounded-lg">
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function MyConsultationRoom() {
  const [state, setState] = useState(null); // my-room payload, or null while loading
  const [rooms, setRooms] = useState([]);
  const [roomId, setRoomId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [completing, setCompleting] = useState(null); // ticket being completed
  const pollRef = useRef(null);

  async function refresh() {
    try {
      const data = await getMyConsultationRoom();
      setState(data);
    } catch {
      // Leave the last-known state rather than flashing an error on a poll blip.
    }
  }

  const active = !!(state?.clocked_in && state?.room);

  useEffect(() => {
    refresh();
    pollRef.current = setInterval(refresh, MY_ROOM_POLL_MS);
    return () => clearInterval(pollRef.current);
  }, []);

  // Only load the room picker when there's no active session (that's the
  // only time it's shown).
  useEffect(() => {
    if (state && !active) {
      getConsultationRooms().then(setRooms).catch(() => setRooms([]));
    }
  }, [state, active]);

  async function start() {
    if (!roomId) return;
    setBusy(true);
    setError("");
    try {
      const data = await startConsultationSession({ room_id: Number(roomId) });
      setState(data);
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not start the session.");
    } finally {
      setBusy(false);
    }
  }

  async function end() {
    if (!confirm("End your consultation session? This clocks you out and releases the room.")) return;
    setBusy(true);
    setError("");
    try {
      const data = await endConsultationSession();
      setState(data);
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not end the session.");
    } finally {
      setBusy(false);
    }
  }

  async function call(ticket) {
    setBusy(true);
    setError("");
    try {
      await callConsultationTicket(ticket.id);
      await refresh();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not call that patient.");
    } finally {
      setBusy(false);
    }
  }

  async function markNoShow(ticket) {
    if (!confirm(`Mark #${ticket.queue_number} ${ticket.patient_full_name} as a no-show?`)) return;
    setBusy(true);
    setError("");
    try {
      await cancelConsultationTicket(ticket.id);
      await refresh();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not update that ticket.");
    } finally {
      setBusy(false);
    }
  }

  if (!state) {
    return (
      <div className="bg-white border border-slate-200 rounded-xl p-5 mb-6">
        <p className="text-sm text-slate-400">Loading your consultation room…</p>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 mb-6">
      {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}

      {!active ? (
        <>
          <h2 className="font-semibold text-slate-800 mb-1">Start your consultation session</h2>
          <p className="text-xs text-slate-500 mb-3">
            Pick a room to clock in and claim it. Your waiting list appears once you start.
          </p>
          <div className="flex items-center gap-2">
            <select
              className="border border-slate-300 rounded-lg px-3 py-2 text-sm flex-1"
              value={roomId}
              onChange={(e) => setRoomId(e.target.value)}
            >
              <option value="">Select a room…</option>
              {rooms.map((r) => {
                const held = !!r.claim;
                return (
                  <option key={r.id} value={r.id} disabled={held}>
                    {r.room_name} · {r.department || "Any"}
                    {held ? ` · held by ${r.claim.claimed_by_name}` : " · free"}
                  </option>
                );
              })}
            </select>
            <button
              onClick={start}
              disabled={busy || !roomId}
              className="bg-blue-800 hover:bg-blue-900 text-white px-4 py-2 rounded-lg text-sm font-medium disabled:opacity-50 whitespace-nowrap"
            >
              Start session
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-slate-800">
              You're in {state.room.room_name}
              <span className="ml-2 text-xs font-normal text-slate-400">
                {state.room.department || "Any"} · {state.room.waiting_today} waiting today
              </span>
            </h2>
            <button
              onClick={end}
              disabled={busy}
              className="border border-slate-300 hover:bg-slate-50 px-3 py-1.5 rounded-lg text-sm disabled:opacity-50"
            >
              End session
            </button>
          </div>

          {state.tickets.length === 0 ? (
            <p className="text-sm text-slate-400">No patients in the queue yet.</p>
          ) : (
            <div className="space-y-2">
              {state.tickets.map((t) => {
                const badge = TICKET_STATUS[t.status] || { label: t.status, cls: "bg-slate-100 text-slate-600" };
                const actionable = t.status === "waiting" || t.status === "called";
                return (
                  <div key={t.id} className="flex items-center justify-between gap-3 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
                    <div className="text-sm text-slate-700 min-w-0">
                      <p className="font-medium">
                        #{t.queue_number} · {t.patient_full_name}
                        <span className="ml-2 text-xs text-slate-500">{t.reason || "—"}</span>
                        <span className={`ml-2 text-xs px-2 py-0.5 rounded-full ${badge.cls}`}>{badge.label}</span>
                      </p>
                      <p className="text-xs text-slate-400">checked in {formatTime(t.checked_in_at)}</p>
                    </div>
                    {actionable && (
                      <div className="flex items-center gap-3 shrink-0">
                        <button onClick={() => call(t)} disabled={busy} className="text-xs text-blue-700 disabled:opacity-40">
                          Call
                        </button>
                        <button onClick={() => setCompleting(t)} disabled={busy} className="text-xs text-green-700 disabled:opacity-40">
                          Complete
                        </button>
                        <button onClick={() => markNoShow(t)} disabled={busy} className="text-xs text-slate-500 hover:text-red-700 disabled:opacity-40">
                          No-show
                        </button>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}

      {completing && (
        <CompleteConsultationModal
          ticket={completing}
          onClose={() => setCompleting(null)}
          onDone={() => { setCompleting(null); refresh(); }}
        />
      )}
    </div>
  );
}

// Best-effort client mirror of backend/app/ai/nric_ocr.py::_resolve_dob_from_yymmdd
// -- just for instant staff feedback as they type. The server recomputes
// (and always wins) once the form is submitted, so this doesn't need to be
// pixel-perfect. Returns an ISO date string, or null if the NRIC doesn't
// parse to a plausible birthdate under either century guess.
function deriveDobFromNric(nric) {
  const digits = (nric || "").replace(/\D/g, "");
  if (digits.length !== 12) return null;
  const yy = Number(digits.slice(0, 2));
  const mm = Number(digits.slice(2, 4));
  const dd = Number(digits.slice(4, 6));
  const today = new Date();
  const candidates = [];
  for (const century of [2000, 1900]) {
    const year = century + yy;
    const candidate = new Date(Date.UTC(year, mm - 1, dd));
    // Guard against JS Date rollover (e.g. MM=13 or DD=32 silently wrapping)
    if (candidate.getUTCFullYear() !== year || candidate.getUTCMonth() !== mm - 1 || candidate.getUTCDate() !== dd) continue;
    if (candidate > today) continue; // future date -- can't be a real birthdate
    const ageYears = (today - candidate) / (1000 * 60 * 60 * 24 * 365.25);
    if (ageYears > 100 || ageYears < 0) continue;
    candidates.push(candidate);
  }
  if (candidates.length === 0) return null;
  candidates.sort((a, b) => b - a); // prefer the more recent (2000s) candidate if more than one survives
  return candidates[0].toISOString().slice(0, 10);
}

export default function PatientList() {
  const [patients, setPatients] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ national_id: "", full_name: "", date_of_birth: "", blood_type: "", senior_citizen_mode: false });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  // Client-side only — listPatients() fetches up to 200 (this project's
  // demo/clinic scale, not a national registry), so a dedicated backend
  // search endpoint would be scope creep. Filters as-you-type; no debounce
  // needed since it's just an in-memory Array.filter, not a network call.
  // NOTE: since backend P2.2, that array is scoped to patients THIS
  // facility actually has a relationship to (Security Audit H2) — this
  // filters within that scope, it does not search other facilities. See
  // crossFacilitySearch below for that.
  const [search, setSearch] = useState("");
  // Security Audit H2 break-glass: an explicit, audited override to browse
  // every patient in the system regardless of facility (see
  // backend/app/routers/patients.py::list_patients). Off by default —
  // this view is deliberately scoped now, unlike before P2.2.
  const [crossFacilitySearch, setCrossFacilitySearch] = useState(false);
  const [breakGlassReason, setBreakGlassReason] = useState("");

  function refresh(reason) {
    setLoading(true);
    listPatients({ breakGlassReason: reason })
      .then(setPatients)
      .finally(() => setLoading(false));
  }

  useEffect(() => refresh(), []);

  function submitCrossFacilitySearch(e) {
    e.preventDefault();
    if (!breakGlassReason.trim()) return;
    refresh(breakGlassReason);
  }

  function backToOwnFacility() {
    setCrossFacilitySearch(false);
    setBreakGlassReason("");
    refresh();
  }

  const filteredPatients = (() => {
    const q = search.trim().toLowerCase();
    if (!q) return patients;
    return patients.filter((p) =>
      p.full_name?.toLowerCase().includes(q) || p.national_id?.toLowerCase().includes(q)
    );
  })();

  async function handleCreate(e) {
    e.preventDefault();
    setError("");
    try {
      await createPatient(form);
      setShowForm(false);
      setForm({ national_id: "", full_name: "", date_of_birth: "", blood_type: "", senior_citizen_mode: false });
      refresh(crossFacilitySearch ? breakGlassReason : undefined);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to create patient. Check the fields and try again.");
    }
  }

  const derivedDob = deriveDobFromNric(form.national_id);

  // The consultation-room panel is only meaningful for roles that actually
  // run a clinic room. A receptionist/pharmacist who somehow lands here
  // shouldn't see it.
  const showConsultationRoom = ["clinician", "records_officer", "admin"].includes(getCurrentUser()?.role);

  return (
    <Layout>
      {showConsultationRoom && <MyConsultationRoom />}
      <div className="flex items-center justify-between mb-4 gap-4">
        <h1 className="text-xl font-bold text-slate-800">
          Patients
          {crossFacilitySearch && (
            <span className="ml-2 text-xs font-normal bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full align-middle">
              All facilities — audited
            </span>
          )}
        </h1>
        <div className="flex items-center gap-3">
          <input
            type="text"
            placeholder="Search by name or NRIC..."
            className="border rounded-lg px-3 py-2 text-sm w-64"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button
            onClick={() => setShowForm((s) => !s)}
            className="bg-blue-800 hover:bg-blue-900 text-white px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap"
          >
            {showForm ? "Cancel" : "+ New Patient (One-Click Intake)"}
          </button>
        </div>
      </div>

      {/* Security Audit H2: this list is now scoped to patients seen at
          your own facility. A genuine cross-facility need (e.g. tracking
          down a transferred patient) goes through this explicit, audited
          override rather than browsing everyone by default. */}
      <div className="mb-6">
        {!crossFacilitySearch ? (
          <button
            onClick={() => setCrossFacilitySearch(true)}
            className="text-xs text-slate-500 hover:text-blue-700 underline decoration-dotted"
          >
            Showing patients seen at your facility. Need someone from another facility?
          </button>
        ) : (
          <form onSubmit={submitCrossFacilitySearch} className="bg-amber-50 border border-amber-200 rounded-xl p-3 flex items-center gap-2">
            <input
              type="text"
              required
              autoFocus
              placeholder="Reason for looking across all facilities (logged to this patient's audit trail)…"
              className="border border-amber-300 rounded-lg px-3 py-1.5 text-sm flex-1"
              value={breakGlassReason}
              onChange={(e) => setBreakGlassReason(e.target.value)}
            />
            <button
              type="submit"
              disabled={!breakGlassReason.trim()}
              className="bg-amber-600 hover:bg-amber-700 text-white px-3 py-1.5 rounded-lg text-sm font-medium disabled:opacity-50 whitespace-nowrap"
            >
              Search all facilities
            </button>
            <button
              type="button"
              onClick={backToOwnFacility}
              className="text-sm text-slate-500 hover:text-slate-700 px-2 whitespace-nowrap"
            >
              Cancel
            </button>
          </form>
        )}
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="bg-white border border-slate-200 rounded-xl p-5 mb-6 grid grid-cols-2 gap-4">
          {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded col-span-2">{error}</div>}
          <input required placeholder="NRIC (e.g. 520314-01-1234)" className="border rounded-lg px-3 py-2 col-span-2"
            value={form.national_id} onChange={(e) => setForm({ ...form, national_id: e.target.value })} />
          <input required placeholder="Full name" className="border rounded-lg px-3 py-2 col-span-2"
            value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          {derivedDob ? (
            <div className="border rounded-lg px-3 py-2 text-sm text-slate-600 bg-slate-50 flex items-center">
              DOB {derivedDob} <span className="text-xs text-slate-400 ml-1">(auto-detected from NRIC)</span>
            </div>
          ) : (
            <input placeholder="Date of birth (YYYY-MM-DD)" className="border rounded-lg px-3 py-2"
              value={form.date_of_birth} onChange={(e) => setForm({ ...form, date_of_birth: e.target.value })} />
          )}
          <input placeholder="Blood type (e.g. O+)" className="border rounded-lg px-3 py-2"
            value={form.blood_type} onChange={(e) => setForm({ ...form, blood_type: e.target.value })} />
          <label className="flex items-center gap-2 col-span-2 text-sm text-slate-600">
            <input type="checkbox" checked={form.senior_citizen_mode}
              onChange={(e) => setForm({ ...form, senior_citizen_mode: e.target.checked })} />
            Enable senior-citizen mode (physical card fallback)
          </label>
          <button className="bg-blue-800 text-white rounded-lg py-2 col-span-2 font-medium">Create</button>
        </form>
      )}

      {loading ? (
        <p className="text-slate-400">Loading...</p>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl divide-y">
          {patients.length === 0 ? (
            <p className="p-5 text-slate-400 text-sm">No patients yet — create one above.</p>
          ) : filteredPatients.length === 0 ? (
            // Distinct from the "zero patients in the system" state above —
            // this means the search just didn't match anything, not that
            // the clinic has no patients on file.
            <p className="p-5 text-slate-400 text-sm">No patients match "{search}".</p>
          ) : null}
          {filteredPatients.map((p) => (
            <Link key={p.id} to={`/patients/${p.id}`} className="flex items-center justify-between p-4 hover:bg-slate-50">
              <div>
                <p className="font-medium text-slate-800">{p.full_name}</p>
                <p className="text-xs text-slate-400">
                  {p.national_id ? `NRIC ${p.national_id} · ` : ""}DOB {p.date_of_birth} · {p.blood_type || "blood type unknown"}
                </p>
              </div>
              {p.senior_citizen_mode && (
                <span className="text-xs bg-amber-100 text-amber-700 px-2 py-1 rounded-full">Senior mode</span>
              )}
            </Link>
          ))}
        </div>
      )}
    </Layout>
  );
}
