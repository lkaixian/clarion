import { useCallback, useEffect, useRef, useState } from "react";
import Layout from "../components/Layout";
import {
  checkinToQueue, getQueue, callNextTicket, completeTicket, cancelTicket,
  getStation, createStation, revokeStation,
  assignTicketRoom, getReceptionRooms, claimRoom, releaseRoom, getMyRoom,
  getReceptionSections,
  getCurrentUser,
} from "../api/client";
import WardMap from "../components/WardMap";
import { formatTime } from "../lib/format";

// How often to re-poll today's queue board — same "short enough to feel
// responsive in a demo, long enough not to hammer the backend" reasoning,
// and the same naming convention, as PatientDetail.jsx's CARD_STATUS_POLL_MS.
const QUEUE_BOARD_POLL_MS = 4000;

// The local NFC-reader bridge (a small helper program running on the
// reception PC — see bridge/README). Runtime-overridable so a differently
// configured desk can point at another port without a rebuild.
const NFC_BRIDGE_URL = import.meta.env.VITE_NFC_BRIDGE_URL || "http://localhost:8770";

// Fallback list for a facility that hasn't defined any front-desk sections
// yet (GET /reception/sections returns []) — keeps a fresh demo working.
const DEPARTMENT_OPTIONS = ["General", "Emergency", "Pharmacy", "Lab"];

// The two QR payload schemes this app emits (see emergency.py /
// reception.py). A reception check-in only makes sense for an emergency
// card; a station QR is the patient-side self-check-in code.
const EMERGENCY_QR_PREFIX = "CLARION-EMERGENCY:";
const STATION_QR_PREFIX = "CLARION-STATION:";

// No "serving" status -- only waiting|called|done|cancelled are ever set
// server-side (see backend schemas.VALID_QUEUE_TICKET_STATUSES); a ticket
// goes straight from "called" to "done" with no intermediate state.
const STATUS_LABELS = {
  waiting: "Waiting",
  called: "Called",
  done: "Done",
  cancelled: "Cancelled",
};

const STATUS_BADGE_CLASSES = {
  waiting: "bg-slate-100 text-slate-600",
  called: "bg-amber-100 text-amber-700",
  done: "bg-green-100 text-green-700",
  cancelled: "bg-red-100 text-red-600",
};

function Section({ title, children }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 mb-4">
      <h2 className="font-semibold text-slate-800 mb-3">{title}</h2>
      {children}
    </div>
  );
}

// In-page tabs — same pattern and classes as AdminConsole.jsx / PatientDetail.jsx
// so staff bouncing between the consoles don't learn a second tab convention.
const TABS = [
  { key: "checkin", label: "Check In" },
  { key: "queue", label: "Queue Board" },
  { key: "myroom", label: "Rooms" },
  { key: "wardmap", label: "Ward Map" },
  { key: "station", label: "Self Check-in QR" },
];

function TabBar({ active, onChange, tabs = TABS }) {
  return (
    <div className="flex gap-1 border-b border-slate-200 mb-4 overflow-x-auto">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap ${
            active === t.key
              ? "border-blue-800 text-blue-800"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// ---------- Camera QR scanner ----------
// Wraps @zxing/browser's continuous decode. Stops the camera as soon as one
// code is read (or on unmount) so we never leave a video track live.
function QrScanner({ onResult, onCancel }) {
  const videoRef = useRef(null);
  const onResultRef = useRef(onResult);
  onResultRef.current = onResult;
  const [error, setError] = useState("");

  useEffect(() => {
    let controls;
    let stopped = false;
    // Lazy-load @zxing/browser — it's ~600kB, only worth pulling when a
    // staff member actually opens the scanner.
    import("@zxing/browser")
      .then(({ BrowserQRCodeReader }) => {
        if (stopped) return;
        const reader = new BrowserQRCodeReader();
        return reader.decodeFromVideoDevice(undefined, videoRef.current, (result, _err, ctrl) => {
          if (stopped || !result) return;
          stopped = true;
          try { ctrl.stop(); } catch { /* already stopped */ }
          onResultRef.current(result.getText());
        });
      })
      .then((c) => {
        controls = c;
        if (stopped && c) { try { c.stop(); } catch { /* noop */ } }
      })
      .catch((e) => setError(e?.message || "Could not access the camera — check browser permissions."));
    return () => {
      stopped = true;
      try { controls?.stop(); } catch { /* noop */ }
    };
  }, []);

  return (
    <div className="border border-slate-200 rounded-lg p-3 bg-slate-50">
      {error ? (
        <p className="text-sm text-red-700">{error}</p>
      ) : (
        <video
          ref={videoRef}
          className="w-full max-w-sm rounded-lg bg-black aspect-video"
          muted
          playsInline
        />
      )}
      <button
        type="button"
        onClick={onCancel}
        className="mt-2 text-xs border border-slate-300 px-3 py-1.5 rounded-lg"
      >
        Cancel scan
      </button>
    </div>
  );
}

// ---------- NFC bridge polling ----------
// Polls the local reader-bridge helper for its connection status and the
// most recent card tap. Only runs while the NFC tab is actually selected.
function useNfcBridge(active) {
  const [status, setStatus] = useState(null); // null = still checking | "unreachable" | { connected, com_port, device_name }
  const [lastScan, setLastScan] = useState(null); // { nfc_uid, scanned_at }

  useEffect(() => {
    if (!active) return undefined;
    let cancelled = false;

    async function poll() {
      try {
        const res = await fetch(`${NFC_BRIDGE_URL}/status`, { signal: AbortSignal.timeout(2000) });
        const data = await res.json();
        if (!cancelled) setStatus(data);
      } catch {
        if (!cancelled) setStatus("unreachable");
      }
      try {
        const res = await fetch(`${NFC_BRIDGE_URL}/last-scan`, { signal: AbortSignal.timeout(2000) });
        const data = await res.json();
        if (!cancelled && data?.nfc_uid) setLastScan(data);
      } catch { /* status already reflects reachability */ }
    }

    poll();
    const t = setInterval(poll, 1500);
    return () => { cancelled = true; clearInterval(t); };
  }, [active]);

  return { status, lastScan };
}

const IDENTIFIER_MODES = [
  { key: "ic", label: "IC Number" },
  { key: "qr", label: "Scan QR" },
  { key: "nfc", label: "NFC Card" },
  { key: "patient_id", label: "Patient ID" },
];

function CheckinForm({ onCheckedIn, departmentOptions, lockedSection }) {
  const [mode, setMode] = useState("ic");
  const [value, setValue] = useState("");       // the resolved identifier string for the current mode
  const [scanning, setScanning] = useState(false);
  const [department, setDepartment] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState(null);

  const nfc = useNfcBridge(mode === "nfc");

  // A fresh tap from the bridge auto-fills the field (staff still press Check In).
  useEffect(() => {
    if (mode === "nfc" && nfc.lastScan?.nfc_uid) setValue(nfc.lastScan.nfc_uid);
  }, [mode, nfc.lastScan]);

  function switchMode(next) {
    setMode(next);
    setValue("");
    setError("");
    setScanning(false);
  }

  const handleScanResult = useCallback((text) => {
    setScanning(false);
    const raw = (text || "").trim();
    if (raw.startsWith(STATION_QR_PREFIX)) {
      setError("That's a self-check-in station QR, not a patient card.");
      return;
    }
    setValue(raw.startsWith(EMERGENCY_QR_PREFIX) ? raw.slice(EMERGENCY_QR_PREFIX.length) : raw);
    setError("");
  }, []);

  function buildPayload() {
    const v = value.trim();
    if (mode === "ic") return { national_id: v };
    if (mode === "qr") return { card_reference: v };
    if (mode === "nfc") return { nfc_uid: v };
    return { patient_id: v };
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!value.trim()) {
      setError("Identify the patient first.");
      return;
    }
    setBusy(true);
    setError("");
    setConfirmation(null);
    try {
      const result = await checkinToQueue({
        ...buildPayload(),
        reason: reason.trim() || undefined,
        // A section-scoped user's ticket is forced into their section
        // server-side; don't send a department the backend will ignore.
        department: lockedSection ? undefined : department || undefined,
      });
      setConfirmation(result);
      setValue("");
      setReason("");
      setDepartment("");
      onCheckedIn();
    } catch (err) {
      setError(err?.response?.data?.detail || "Check-in failed — confirm the identifier is correct.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Check in a walk-in patient">
      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label className="block text-xs font-medium text-slate-500 mb-1">Identify patient by</label>
          <div className="flex flex-wrap gap-2 mb-2">
            {IDENTIFIER_MODES.map((opt) => (
              <button
                type="button"
                key={opt.key}
                onClick={() => switchMode(opt.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium border ${
                  mode === opt.key
                    ? "bg-blue-800 text-white border-blue-800"
                    : "bg-white text-slate-600 border-slate-300"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {mode === "ic" && (
            <input
              type="text"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="e.g. 520314-01-1234"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
              autoFocus
            />
          )}

          {mode === "patient_id" && (
            <input
              type="text"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder="Patient's internal ID (fallback)"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
          )}

          {mode === "qr" && (
            <div className="space-y-2">
              {scanning ? (
                <QrScanner onResult={handleScanResult} onCancel={() => setScanning(false)} />
              ) : (
                <button
                  type="button"
                  onClick={() => { setScanning(true); setError(""); }}
                  className="text-sm border border-slate-300 px-3 py-2 rounded-lg"
                >
                  {value ? "Scan a different code" : "Start camera"}
                </button>
              )}
              {value && (
                <p className="text-xs text-slate-500">
                  Scanned: <code className="bg-slate-100 px-1 rounded break-all">{value}</code>
                </p>
              )}
            </div>
          )}

          {mode === "nfc" && (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">
                {nfc.status === null && "Checking for the reader bridge…"}
                {nfc.status === "unreachable" && (
                  <span className="text-amber-700">
                    Reader bridge not detected on {NFC_BRIDGE_URL} — start the bridge helper, or type the UID below.
                  </span>
                )}
                {nfc.status && nfc.status !== "unreachable" && (
                  nfc.status.connected
                    ? <span className="text-green-700">
                        Reader {nfc.status.device_name || "connected"} on {nfc.status.com_port || "—"} — tap a card.
                      </span>
                    : <span className="text-amber-700">
                        Bridge running but no reader on a COM port yet.
                      </span>
                )}
              </p>
              <input
                type="text"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="NFC UID (auto-fills on tap, or type it)"
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
              />
              {nfc.lastScan?.scanned_at && (
                <p className="text-xs text-slate-400">Last tap {formatTime(nfc.lastScan.scanned_at)}</p>
              )}
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">
              {lockedSection ? "Department" : "Department (optional)"}
            </label>
            {lockedSection ? (
              // Scoped user: their counter is fixed, field is read-only.
              <input
                type="text"
                value={lockedSection}
                readOnly
                className="w-full border border-slate-200 bg-slate-50 text-slate-500 rounded-lg px-3 py-2 text-sm"
                title="Check-ins at your counter always go to this section"
              />
            ) : (
              <select
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
              >
                <option value="">— none —</option>
                {departmentOptions.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-500 mb-1">Reason for visit (optional)</label>
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. Fever and cough"
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            />
          </div>
        </div>

        {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error}</div>}

        <button
          type="submit"
          disabled={busy}
          className="bg-blue-800 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm disabled:opacity-50"
        >
          {busy ? "Checking in…" : "Check In"}
        </button>
      </form>

      {confirmation && (
        <div className="mt-4 bg-green-50 border border-green-200 rounded-lg p-4">
          <p className="text-sm text-green-800">
            Checked in <strong>{confirmation.patient_full_name}</strong> (DOB {confirmation.patient_date_of_birth})
          </p>
          <p className="text-3xl font-bold text-green-900 mt-1">
            Number {confirmation.ticket.queue_number}
          </p>
        </div>
      )}
    </Section>
  );
}

// Facility-scoped self check-in QR — patients scan this on-site to check
// themselves into today's queue without a staff member typing in their
// identifier. Fetched once on mount (unlike the queue board, a station only
// changes when a staff member explicitly generates/revokes one).
function SelfCheckinQrSection({ departmentOptions, lockedSection }) {
  const [station, setStation] = useState(null); // StationOut | null (not loaded yet)
  const [department, setDepartment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // A scoped receptionist's station is their counter — force the department.
  const stationDepartment = lockedSection || department || undefined;

  function refreshStation() {
    getStation()
      .then((res) => setStation(res.active ? res.station : null))
      .catch(() => {
        /* leave whatever was last shown; staff can retry via the buttons */
      });
  }

  useEffect(() => {
    refreshStation();
  }, []);

  async function handleGenerate() {
    setBusy(true);
    setError("");
    try {
      const created = await createStation({ department: stationDepartment });
      setStation(created);
      setDepartment("");
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to generate QR.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRegenerate() {
    if (!confirm("Generate a new QR? The current one will stop working immediately.")) return;
    setBusy(true);
    setError("");
    try {
      const created = await createStation({ department: stationDepartment });
      setStation(created);
      setDepartment("");
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to regenerate QR.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRevoke() {
    if (!confirm("Revoke this QR? It will stop working immediately.")) return;
    setBusy(true);
    setError("");
    try {
      await revokeStation();
      setStation(null);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to revoke QR.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="Self Check-in QR">
      {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}

      {station ? (
        <div className="flex items-start gap-4">
          <img
            src={station.qr_base64}
            alt="Self check-in QR"
            className="border border-slate-200 rounded-lg"
            style={{ width: 220, height: 220 }}
          />
          <div className="text-sm text-slate-600 space-y-1">
            <p>Department: {station.department || "All departments"}</p>
            <p className="text-xs text-slate-400">Created {formatTime(station.created_at)}</p>
            <p>
              Token: <code className="bg-slate-100 px-1 rounded break-all">{station.token}</code>
            </p>
            <p className="text-xs text-slate-400">
              If a patient's phone camera can't scan the code, they can type this token in manually.
            </p>
            <div className="flex gap-2 pt-2">
              <button
                onClick={handleRegenerate}
                disabled={busy}
                className="bg-blue-800 hover:bg-blue-700 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-50"
              >
                {busy ? "Working…" : "Regenerate"}
              </button>
              <button
                onClick={handleRevoke}
                disabled={busy}
                className="border border-red-700 text-red-700 text-xs px-3 py-1.5 rounded-lg disabled:opacity-50"
              >
                {busy ? "Working…" : "Revoke"}
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div>
          <p className="text-sm text-slate-500 mb-3">
            Generate a QR code for this facility that patients can scan on-site to check themselves
            into today's queue, instead of a staff member typing in their identifier.
          </p>
          <div className="flex items-end gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-500 mb-1">
                {lockedSection ? "Department" : "Department (optional)"}
              </label>
              {lockedSection ? (
                <input
                  type="text"
                  value={lockedSection}
                  readOnly
                  className="border border-slate-200 bg-slate-50 text-slate-500 rounded-lg px-3 py-2 text-sm"
                  title="This station is for your counter"
                />
              ) : (
                <select
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                  className="border border-slate-300 rounded-lg px-3 py-2 text-sm"
                >
                  <option value="">— none —</option>
                  {departmentOptions.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              )}
            </div>
            <button
              onClick={handleGenerate}
              disabled={busy}
              className="bg-blue-800 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm disabled:opacity-50"
            >
              {busy ? "Generating…" : "Generate QR"}
            </button>
          </div>
        </div>
      )}
    </Section>
  );
}

function NowServingStrip({ board }) {
  return (
    <div className="bg-blue-900 text-white rounded-xl px-4 py-3 mb-4 flex items-center justify-between">
      <span className="text-xs uppercase tracking-wide text-blue-200">Now Serving</span>
      <span className="text-2xl font-bold">{board?.now_serving ?? "—"}</span>
      <span className="text-xs text-blue-200">{board?.waiting_count ?? 0} waiting</span>
    </div>
  );
}

function QueueBoard({ board, rooms, onAssignRoom, onCall, onComplete, onCancel, busyTicketId, sectionLabel }) {
  return (
    <Section title="Today's queue">
      {sectionLabel && (
        <p className="text-xs text-slate-500 mb-3">Showing the {sectionLabel} queue</p>
      )}
      <div className="text-center bg-blue-900 text-white rounded-xl py-6 mb-4">
        <p className="text-sm uppercase tracking-wide text-blue-200">Now Serving</p>
        <p className="text-5xl font-bold">{board?.now_serving ?? "—"}</p>
        <p className="text-xs text-blue-200 mt-1">{board?.waiting_count ?? 0} waiting</p>
      </div>

      {(!board || board.tickets.length === 0) && (
        <p className="text-sm text-slate-400">No tickets checked in yet today.</p>
      )}

      <div className="space-y-2">
        {board?.tickets.map((ticket) => (
          <div
            key={ticket.id}
            className="flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2 gap-3"
          >
            <div className="min-w-0">
              <span className="font-semibold text-slate-800 mr-2">#{ticket.queue_number}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_BADGE_CLASSES[ticket.status] || ""}`}>
                {STATUS_LABELS[ticket.status] || ticket.status}
              </span>
              <p className="text-xs text-slate-400 mt-1">
                {ticket.department || "—"} · checked in {formatTime(ticket.checked_in_at)}
                {ticket.reason ? ` · ${ticket.reason}` : ""}
              </p>
              <div className="text-xs text-slate-500 mt-1 flex items-center gap-1">
                <span>Room:</span>
                {rooms && rooms.length > 0 ? (
                  <select
                    value={ticket.room_id || ""}
                    onChange={(e) => onAssignRoom(ticket.id, e.target.value)}
                    disabled={busyTicketId === ticket.id}
                    className="border border-slate-300 rounded px-1 py-0.5 text-xs bg-white"
                  >
                    <option value="" disabled>{ticket.room_name || "unassigned"}</option>
                    {rooms.map((r) => (
                      <option key={r.id} value={r.id}>{r.room_name}</option>
                    ))}
                  </select>
                ) : (
                  <span className="text-slate-400">{ticket.room_name || "—"}</span>
                )}
              </div>
            </div>
            <div className="flex gap-2 shrink-0">
              {(ticket.status === "waiting" || ticket.status === "called") && (
                <button
                  onClick={() => onCall(ticket.id)}
                  disabled={busyTicketId === ticket.id}
                  className="bg-amber-600 hover:bg-amber-500 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-50"
                >
                  Call Next
                </button>
              )}
              {ticket.status !== "done" && ticket.status !== "cancelled" && (
                <>
                  <button
                    onClick={() => onComplete(ticket.id)}
                    disabled={busyTicketId === ticket.id}
                    className="bg-green-700 hover:bg-green-600 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-50"
                  >
                    Complete
                  </button>
                  <button
                    onClick={() => onCancel(ticket.id)}
                    disabled={busyTicketId === ticket.id}
                    className="bg-red-600 hover:bg-red-500 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-50"
                  >
                    Cancel
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

// The clinician's own worklist: today's patients for the Bilik they've
// claimed, shown only while they're clocked in (the backend enforces both —
// see routers/reception.py::_my_room). Purely additive: this doesn't limit
// which records they can open elsewhere, it's just a focused list.
function MyRoomTab() {
  const [state, setState] = useState(null); // MyRoomOut | null (loading)
  const [rooms, setRooms] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Claiming a consultation room is a clinician action (backend:
  // CONSULT_ROOM_ROLES). A receptionist sees the room board but can't hold a
  // room, so no Claim button and no "clock in to claim" prompt for them.
  const canClaimRoom = ["admin", "clinician", "records_officer"].includes(getCurrentUser()?.role);

  function refresh() {
    getMyRoom().then(setState).catch(() => {});
    getReceptionRooms().then(setRooms).catch(() => {});
  }

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, QUEUE_BOARD_POLL_MS);
    return () => clearInterval(t);
  }, []);

  async function handleClaim(roomId) {
    setBusy(true);
    setError("");
    try {
      await claimRoom(roomId);
      refresh();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not claim that room.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRelease() {
    setBusy(true);
    setError("");
    try {
      await releaseRoom();
      refresh();
    } catch (err) {
      setError(err?.response?.data?.detail || "Could not release the room.");
    } finally {
      setBusy(false);
    }
  }

  async function handleTicket(action, ticketId) {
    setBusy(true);
    setError("");
    try {
      await action(ticketId);
      refresh();
    } catch (err) {
      setError(err?.response?.data?.detail || "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  if (state === null) {
    return <Section title="Consultation Rooms"><p className="text-sm text-slate-400">Loading…</p></Section>;
  }

  // Not in a room yet (or not clocked in at all): show every consultation
  // room and its live status. The room LIST is visible to any reception-desk
  // staff — a receptionist routing walk-ins wants to see which rooms are
  // staffed and how busy they are, without clocking in. CLAIMING a room still
  // needs a clock-in (that's a clinician sitting down to see patients).
  if (!state.room) {
    return (
      <Section title="Consultation Rooms">
        {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}
        {canClaimRoom ? (
          !state.clocked_in && (
            <p className="text-xs text-slate-500 mb-3">
              Clock in (top-right of the page) to claim a room and see its patient queue.
            </p>
          )
        ) : (
          <p className="text-xs text-slate-500 mb-3">
            Live status of every consultation room. Assign walk-ins to a room from the Queue Board.
          </p>
        )}
        {rooms.length === 0 ? (
          <p className="text-sm text-slate-400">No consultation rooms configured for this facility yet.</p>
        ) : (
          <div className="space-y-2">
            {rooms.map((r) => {
              const taken = r.claim;
              return (
                <div key={r.id} className="flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2">
                  <div className="text-sm text-slate-700">
                    <p className="font-medium">{r.room_name}</p>
                    <p className="text-xs text-slate-400">
                      {r.department || "Any department"} · {r.waiting_today} in queue today
                      {taken ? ` · held by ${r.claim.claimed_by_name || "another clinician"}` : " · free"}
                    </p>
                  </div>
                  {canClaimRoom && state.clocked_in && (
                    <button
                      onClick={() => handleClaim(r.id)}
                      disabled={busy || !!taken}
                      className="bg-blue-800 hover:bg-blue-700 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-40"
                    >
                      {taken ? "Taken" : "Claim"}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Section>
    );
  }

  return (
    <Section title={`My Room — ${state.room.room_name}`}>
      {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs text-slate-500">
          {state.room.department || "Any department"} · {state.tickets.length} patient(s) today
        </p>
        <button
          onClick={handleRelease}
          disabled={busy}
          className="border border-slate-300 text-slate-600 text-xs px-3 py-1.5 rounded-lg disabled:opacity-50"
        >
          Release room
        </button>
      </div>

      {state.tickets.length === 0 ? (
        <p className="text-sm text-slate-400">No patients routed to this room yet today.</p>
      ) : (
        <div className="space-y-2">
          {state.tickets.map((ticket) => (
            <div key={ticket.id} className="flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2 gap-3">
              <div className="min-w-0">
                <span className="font-semibold text-slate-800 mr-2">#{ticket.queue_number}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_BADGE_CLASSES[ticket.status] || ""}`}>
                  {STATUS_LABELS[ticket.status] || ticket.status}
                </span>
                <p className="text-xs text-slate-400 mt-1">
                  {ticket.department || "—"} · checked in {formatTime(ticket.checked_in_at)}
                  {ticket.reason ? ` · ${ticket.reason}` : ""}
                </p>
              </div>
              <div className="flex gap-2 shrink-0">
                {(ticket.status === "waiting" || ticket.status === "called") && (
                  <button
                    onClick={() => handleTicket(callNextTicket, ticket.id)}
                    disabled={busy}
                    className="bg-amber-600 hover:bg-amber-500 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-50"
                  >
                    Call
                  </button>
                )}
                {ticket.status !== "done" && ticket.status !== "cancelled" && (
                  <button
                    onClick={() => handleTicket(completeTicket, ticket.id)}
                    disabled={busy}
                    className="bg-green-700 hover:bg-green-600 text-white text-xs px-3 py-1.5 rounded-lg disabled:opacity-50"
                  >
                    Complete
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

export default function Reception() {
  const [activeTab, setActiveTab] = useState("checkin");
  const [board, setBoard] = useState(null);
  const [rooms, setRooms] = useState([]);
  const [busyTicketId, setBusyTicketId] = useState(null);
  const [error, setError] = useState("");
  // Active front-desk section names → the check-in / QR department dropdowns.
  // Falls back to the hardcoded list when the facility has none defined yet.
  const [sectionNames, setSectionNames] = useState([]);

  // The counter this user is pinned to (null = unscoped, sees everything).
  const userSection = getCurrentUser()?.section || null;
  const departmentOptions = sectionNames.length > 0 ? sectionNames : DEPARTMENT_OPTIONS;
  // The self-check-in QR is one facility-level resource; a section-scoped
  // account can't manage it (the backend 403s create/revoke), so hide the tab.
  const visibleTabs = userSection ? TABS.filter((t) => t.key !== "station") : TABS;
  // The queue-board caption: prefer the server-echoed section, fall back to
  // the user's own pin.
  const queueSectionLabel = board?.section || userSection || null;

  function refreshQueue() {
    getQueue()
      .then(setBoard)
      .catch(() => {
        /* transient poll failure — try again next interval, same as
           PatientDetail.jsx's refreshCardStatus */
      });
  }

  useEffect(() => {
    refreshQueue();
    getReceptionRooms().then(setRooms).catch(() => {});
    // Any reception staff can call this (not admin-only); [] when the
    // facility has no sections defined.
    getReceptionSections().then(setSectionNames).catch(() => setSectionNames([]));
    const interval = setInterval(refreshQueue, QUEUE_BOARD_POLL_MS);
    return () => clearInterval(interval);
  }, []);

  async function handleAssignRoom(ticketId, roomId) {
    if (!roomId) return;
    setBusyTicketId(ticketId);
    setError("");
    try {
      await assignTicketRoom(ticketId, roomId);
      refreshQueue();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to reassign room.");
    } finally {
      setBusyTicketId(null);
    }
  }

  async function handleCall(ticketId) {
    setBusyTicketId(ticketId);
    setError("");
    try {
      await callNextTicket(ticketId);
      refreshQueue();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to call ticket.");
    } finally {
      setBusyTicketId(null);
    }
  }

  async function handleComplete(ticketId) {
    setBusyTicketId(ticketId);
    setError("");
    try {
      await completeTicket(ticketId);
      refreshQueue();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to complete ticket.");
    } finally {
      setBusyTicketId(null);
    }
  }

  async function handleCancel(ticketId) {
    setBusyTicketId(ticketId);
    setError("");
    try {
      await cancelTicket(ticketId);
      refreshQueue();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to cancel ticket.");
    } finally {
      setBusyTicketId(null);
    }
  }

  return (
    <Layout>
      <h1 className="text-xl font-bold text-slate-800 mb-4">
        Reception{userSection ? ` — ${userSection} counter` : ""}
      </h1>
      {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}

      <TabBar active={activeTab} onChange={setActiveTab} tabs={visibleTabs} />

      {activeTab === "checkin" && (
        <>
          <NowServingStrip board={board} />
          <CheckinForm
            onCheckedIn={refreshQueue}
            departmentOptions={departmentOptions}
            lockedSection={userSection}
          />
        </>
      )}

      {activeTab === "queue" && (
        <QueueBoard
          board={board}
          rooms={rooms}
          onAssignRoom={handleAssignRoom}
          onCall={handleCall}
          onComplete={handleComplete}
          onCancel={handleCancel}
          busyTicketId={busyTicketId}
          sectionLabel={queueSectionLabel}
        />
      )}

      {activeTab === "myroom" && <MyRoomTab />}

      {activeTab === "wardmap" && <WardMap />}

      {activeTab === "station" && (
        <SelfCheckinQrSection
          departmentOptions={departmentOptions}
          lockedSection={userSection}
        />
      )}
    </Layout>
  );
}
