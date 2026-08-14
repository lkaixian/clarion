import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import {
  getAdminAppointments,
  getAdminInventory, createInventoryItem, updateInventoryItem, deleteInventoryItem,
  getWards, createWard, updateWard, deleteWard,
  getStaffRoster, getStaffClockHistory,
} from "../api/client";

// No date library in this codebase (see PatientDetail.jsx's identical
// comment on formatAppointmentTime) — a plain toLocaleString() matches
// every other timestamp rendered here.
function formatDateTime(iso) {
  return iso ? new Date(iso).toLocaleString() : "—";
}

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

function Section({ title, children, action }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 mb-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-slate-800">{title}</h2>
        {action}
      </div>
      {children}
    </div>
  );
}

// In-page tabs, same pattern (and same classes, for visual consistency) as
// PatientDetail.jsx's TABS/TabBar — a clinician bouncing between that page
// and this one shouldn't have to learn a second tab convention.
const TABS = [
  { key: "appointments", label: "Appointments" },
  { key: "inventory", label: "Medicine Inventory" },
  { key: "wards", label: "Ward Capacity" },
  { key: "staff", label: "Staff Roster" },
];

function TabBar({ active, onChange }) {
  return (
    <div className="flex gap-1 border-b border-slate-200 mb-4 overflow-x-auto">
      {TABS.map((t) => (
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

// ---------- Appointments (read-only monitoring) ----------
// Deliberately no create/edit/cancel here — appointments are still made
// from a specific patient's own record (PatientDetail.jsx's
// AppointmentsSection); this tab exists so an admin can see the whole
// facility's queue at a glance, not to duplicate that flow.
function AppointmentsTab() {
  const [appointments, setAppointments] = useState([]);
  const [includeAll, setIncludeAll] = useState(false);
  const [loading, setLoading] = useState(true);

  function refresh() {
    setLoading(true);
    getAdminAppointments(includeAll).then(setAppointments).finally(() => setLoading(false));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(refresh, [includeAll]);

  return (
    <Section
      title="Facility Appointments"
      action={
        <label className="flex items-center gap-2 text-xs text-slate-600">
          <input type="checkbox" checked={includeAll} onChange={(e) => setIncludeAll(e.target.checked)} />
          Show cancelled &amp; completed too
        </label>
      }
    >
      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : appointments.length === 0 ? (
        <p className="text-sm text-slate-400">
          {includeAll ? "No appointments on file for this facility." : "No upcoming appointments scheduled."}
        </p>
      ) : (
        <div className="space-y-2">
          {appointments.map((a) => {
            const cancelled = a.status === "cancelled";
            return (
              <div
                key={a.id}
                // Same "dim it but keep it visible, with an explicit label"
                // treatment PatientDetail.jsx's AppointmentsSection uses for
                // a cancelled row — reused here rather than inventing a
                // different cancelled-state convention.
                className={`bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 ${cancelled ? "opacity-50" : ""}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm text-slate-700">
                    {cancelled && <p className="text-xs font-semibold text-red-700 uppercase mb-0.5">Cancelled</p>}
                    {a.status === "completed" && (
                      <p className="text-xs font-semibold text-slate-500 uppercase mb-0.5">Completed</p>
                    )}
                    <p className={cancelled ? "line-through" : ""}>
                      {a.patient_name} — {a.venue || a.facility_name}
                    </p>
                    <p className="text-xs text-slate-400">
                      {formatDateTime(a.scheduled_at)} · Booked by {a.created_by_name || "—"}
                    </p>
                    {a.reason && <p className="text-xs text-slate-600 mt-0.5">Reason: {a.reason}</p>}
                    {/* Same fasting-precaution callout convention as
                        PatientDetail.jsx's AppointmentsSection. */}
                    {a.fasting_required && (
                      <p className="text-xs text-amber-700 font-medium mt-0.5">
                        ⚠ Fasting required{a.fasting_hours ? `: ${a.fasting_hours}h before` : ""}
                      </p>
                    )}
                    {a.precaution_notes && (
                      <p className="text-xs text-slate-500 mt-0.5">Note: {a.precaution_notes}</p>
                    )}
                  </div>
                  <span className="text-xs text-slate-400 whitespace-nowrap capitalize">{a.status}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}

// ---------- Medicine inventory ----------
const INVENTORY_FIELDS = [
  { key: "drug_name", label: "Drug name", type: "text", required: true },
  { key: "quantity_on_hand", label: "Quantity on hand", type: "number" },
  { key: "unit", label: "Unit", type: "text", placeholder: "e.g. tablets, boxes, vials" },
  { key: "reorder_threshold", label: "Reorder threshold", type: "number", placeholder: "Flag as low stock at or below this" },
  { key: "notes", label: "Notes", type: "textarea" },
];

// Mirrors RecordModal/AppointmentModal's shell exactly (same overlay/panel
// classes) so it doesn't look like a different app bolted on, without
// pulling in PatientDetail.jsx's kind-specific RECORD_FIELD_CONFIG (this
// only ever handles one kind of record).
function InventoryModal({ mode, initial, onClose, onSaved }) {
  const [values, setValues] = useState(() => ({
    drug_name: initial?.drug_name ?? "",
    quantity_on_hand: initial?.quantity_on_hand ?? 0,
    unit: initial?.unit ?? "units",
    reorder_threshold: initial?.reorder_threshold ?? "",
    notes: initial?.notes ?? "",
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!values.drug_name.trim()) {
      setError("Drug name is required.");
      return;
    }
    setSaving(true);
    setError("");
    const payload = {
      drug_name: values.drug_name.trim(),
      quantity_on_hand: Number(values.quantity_on_hand) || 0,
      unit: values.unit.trim() || "units",
      reorder_threshold: values.reorder_threshold === "" ? null : Number(values.reorder_threshold),
      notes: values.notes.trim() || null,
    };
    try {
      if (mode === "add") {
        await createInventoryItem(payload);
      } else {
        await updateInventoryItem(initial.id, payload);
      }
      onSaved();
    } catch (err) {
      // Surfaces the backend's "your account has no facility assigned" 400
      // (see routers/admin.py's _require_facility) the same way every other
      // modal in this app surfaces a save error — inline, not a crash.
      setError(err?.response?.data?.detail || "Failed to save. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl p-6 max-w-md w-full max-h-[90vh] overflow-y-auto">
        <h3 className="font-semibold text-slate-800 mb-4">{mode === "add" ? "Add Inventory Item" : "Edit Inventory Item"}</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error}</div>}
          {INVENTORY_FIELDS.map((f) => (
            <div key={f.key}>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                {f.label}{f.required && <span className="text-red-600"> *</span>}
              </label>
              {f.type === "textarea" ? (
                <textarea
                  className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  rows={2}
                  value={values[f.key]}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                />
              ) : (
                <input
                  className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  type={f.type}
                  min={f.type === "number" ? 0 : undefined}
                  placeholder={f.placeholder}
                  value={values[f.key]}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                />
              )}
            </div>
          ))}
          <div className="flex gap-2 pt-2">
            <button disabled={saving} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50">
              {saving ? "Saving..." : "Save"}
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

function InventoryTab() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null); // { mode: 'add'|'edit', initial } | null
  // Per-row id currently mid-request — disables that row's +/- stepper so a
  // double click can't fire two overlapping PATCHes against the same item.
  const [busyId, setBusyId] = useState(null);

  function refresh() {
    setLoading(true);
    getAdminInventory(false).then(setItems).finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  // Fast restock/consume affordance — a full "edit everything" modal for
  // every single unit dispensed or delivered would make the common case
  // slow, so quantity alone gets a dedicated +/-1 stepper. The full modal
  // (below) still exists for name/unit/threshold/notes edits and for
  // jumping the quantity by more than one at a time.
  async function adjustQuantity(item, delta) {
    const next = item.quantity_on_hand + delta;
    if (next < 0) return;
    setBusyId(item.id);
    try {
      const updated = await updateInventoryItem(item.id, { quantity_on_hand: next });
      setItems((prev) => prev.map((i) => (i.id === item.id ? updated : i)));
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to update quantity.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(item) {
    if (!confirm(`Remove "${item.drug_name}" from inventory? This can't be undone.`)) return;
    await deleteInventoryItem(item.id);
    refresh();
  }

  return (
    <Section
      title="Medicine Inventory"
      action={<button onClick={() => setModal({ mode: "add", initial: null })} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">+ Add Item</button>}
    >
      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-400">No inventory items yet — add one above.</p>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <div
              key={item.id}
              // Low-stock flag reuses the same amber "needs attention"
              // convention as PatientDetail.jsx's fasting-required callout
              // and its missing-profile-fields banner, rather than
              // inventing a new warning color for this page.
              className={`flex items-center justify-between gap-3 rounded-lg px-3 py-2 border ${
                item.is_low_stock ? "bg-amber-50 border-amber-200" : "bg-slate-50 border-slate-200"
              }`}
            >
              <div className="text-sm text-slate-700 min-w-0">
                <p className="font-medium">
                  {item.drug_name}
                  {item.is_low_stock && <span className="ml-2 text-xs font-semibold text-amber-700 uppercase">⚠ Low stock</span>}
                </p>
                <p className="text-xs text-slate-400">
                  {item.quantity_on_hand} {item.unit}
                  {item.reorder_threshold != null && ` · reorder at ${item.reorder_threshold}`}
                  {" · last restocked "}{item.last_restocked_at ? formatDateTime(item.last_restocked_at) : "never"}
                </p>
                {item.notes && <p className="text-xs text-slate-500 mt-0.5">{item.notes}</p>}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => adjustQuantity(item, -1)}
                    disabled={busyId === item.id || item.quantity_on_hand <= 0}
                    className="w-6 h-6 text-sm border border-slate-300 rounded disabled:opacity-30"
                    title="Decrease quantity by 1"
                  >
                    −
                  </button>
                  <span className="text-xs text-slate-500 w-6 text-center">{item.quantity_on_hand}</span>
                  <button
                    onClick={() => adjustQuantity(item, 1)}
                    disabled={busyId === item.id}
                    className="w-6 h-6 text-sm border border-slate-300 rounded disabled:opacity-30"
                    title="Increase quantity by 1 (restock)"
                  >
                    +
                  </button>
                </div>
                <button onClick={() => setModal({ mode: "edit", initial: item })} className="text-xs text-blue-700 whitespace-nowrap">Edit</button>
                <button onClick={() => handleDelete(item)} className="text-xs text-red-700 whitespace-nowrap">Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {modal && (
        <InventoryModal
          mode={modal.mode}
          initial={modal.initial}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); refresh(); }}
        />
      )}
    </Section>
  );
}

// ---------- Ward capacity ----------
const WARD_TYPE_OPTIONS = ["general", "icu", "pediatric", "maternity", "emergency", "other"];

function WardModal({ mode, initial, onClose, onSaved }) {
  const [wardName, setWardName] = useState(initial?.ward_name ?? "");
  const [wardType, setWardType] = useState(initial?.ward_type ?? "general");
  const [totalBeds, setTotalBeds] = useState(initial?.total_beds ?? "");
  // occupied_beds is only collected here on CREATE (defaults to 0 if left
  // blank) — on EDIT it's deliberately left out of this modal in favor of
  // the day-to-day +/- stepper on the ward card, per the task's "fastest
  // possible interaction" requirement for that field.
  const [occupiedBeds, setOccupiedBeds] = useState(initial?.occupied_beds ?? 0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!wardName.trim()) {
      setError("Ward name is required.");
      return;
    }
    if (!totalBeds || Number(totalBeds) <= 0) {
      setError("Total beds must be greater than 0.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (mode === "add") {
        await createWard({
          ward_name: wardName.trim(),
          ward_type: wardType,
          total_beds: Number(totalBeds),
          occupied_beds: Number(occupiedBeds) || 0,
        });
      } else {
        await updateWard(initial.id, {
          ward_name: wardName.trim(),
          ward_type: wardType,
          total_beds: Number(totalBeds),
        });
      }
      onSaved();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl p-6 max-w-md w-full max-h-[90vh] overflow-y-auto">
        <h3 className="font-semibold text-slate-800 mb-4">{mode === "add" ? "Add Ward" : "Edit Ward"}</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error}</div>}

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Ward name<span className="text-red-600"> *</span></label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              type="text"
              value={wardName}
              onChange={(e) => setWardName(e.target.value)}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Ward type</label>
            <select
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={wardType}
              onChange={(e) => setWardType(e.target.value)}
            >
              {WARD_TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Total beds<span className="text-red-600"> *</span></label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              type="number"
              min="1"
              value={totalBeds}
              onChange={(e) => setTotalBeds(e.target.value)}
            />
          </div>

          {mode === "add" && (
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">Occupied beds (at creation)</label>
              <input
                className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                type="number"
                min="0"
                value={occupiedBeds}
                onChange={(e) => setOccupiedBeds(e.target.value)}
              />
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <button disabled={saving} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50">
              {saving ? "Saving..." : "Save"}
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

// Occupancy thresholds for the proportional bar/badge below — this codebase
// has no charting library (see task constraints), so this is a plain
// Tailwind-colored div sized by percentage width. Colors extend the same
// amber="needs attention" / red="critical" vocabulary already established
// by the fasting-required callout and cancelled/revoked states elsewhere in
// this app, rather than introducing a new palette just for this bar.
function occupancyColor(pct) {
  if (pct >= 90) return "bg-red-600";
  if (pct >= 75) return "bg-amber-500";
  return "bg-green-600";
}
function occupancyTextColor(pct) {
  if (pct >= 90) return "text-red-700";
  if (pct >= 75) return "text-amber-700";
  return "text-green-700";
}

function WardsTab() {
  const [wards, setWards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null); // { mode: 'add'|'edit', initial } | null
  const [busyId, setBusyId] = useState(null);

  function refresh() {
    setLoading(true);
    getWards().then(setWards).finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  // Same "fast, no modal" reasoning as InventoryTab's quantity stepper —
  // occupied_beds is a day-to-day ward-board update, not an occasional edit,
  // so it gets a dedicated +/-1 affordance instead of requiring the full
  // edit modal every time a bed turns over.
  async function adjustOccupied(ward, delta) {
    const next = ward.occupied_beds + delta;
    if (next < 0 || next > ward.total_beds) return;
    setBusyId(ward.id);
    try {
      const updated = await updateWard(ward.id, { occupied_beds: next });
      setWards((prev) => prev.map((w) => (w.id === ward.id ? updated : w)));
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to update bed count.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(ward) {
    if (!confirm(`Remove ward "${ward.ward_name}"? This can't be undone.`)) return;
    await deleteWard(ward.id);
    refresh();
  }

  return (
    <Section
      title="Ward Capacity"
      action={<button onClick={() => setModal({ mode: "add", initial: null })} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">+ Add Ward</button>}
    >
      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : wards.length === 0 ? (
        <p className="text-sm text-slate-400">No wards on file yet — add one above.</p>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {wards.map((w) => (
            <div key={w.id} className="border border-slate-200 rounded-lg p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-slate-800">{w.ward_name}</p>
                  <p className="text-xs text-slate-400 capitalize">{w.ward_type || "unspecified type"}</p>
                </div>
                <span className={`text-xs font-semibold whitespace-nowrap ${occupancyTextColor(w.occupancy_pct)}`}>
                  {w.occupancy_pct}%
                </span>
              </div>

              <div className="w-full bg-slate-100 rounded-full h-2 mt-2 overflow-hidden">
                <div
                  className={`h-2 rounded-full ${occupancyColor(w.occupancy_pct)}`}
                  style={{ width: `${Math.min(100, w.occupancy_pct)}%` }}
                />
              </div>
              <p className="text-xs text-slate-500 mt-1">
                {w.occupied_beds} / {w.total_beds} beds occupied · {w.available_beds} available
              </p>

              <div className="flex items-center justify-between mt-3">
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => adjustOccupied(w, -1)}
                    disabled={busyId === w.id || w.occupied_beds <= 0}
                    className="w-6 h-6 text-sm border border-slate-300 rounded disabled:opacity-30"
                    title="Discharge one bed"
                  >
                    −
                  </button>
                  <span className="text-xs text-slate-500 w-6 text-center">{w.occupied_beds}</span>
                  <button
                    onClick={() => adjustOccupied(w, 1)}
                    disabled={busyId === w.id || w.occupied_beds >= w.total_beds}
                    className="w-6 h-6 text-sm border border-slate-300 rounded disabled:opacity-30"
                    title="Admit one bed"
                  >
                    +
                  </button>
                </div>
                <div className="flex items-center gap-3">
                  <button onClick={() => setModal({ mode: "edit", initial: w })} className="text-xs text-blue-700">Edit</button>
                  <button onClick={() => handleDelete(w)} className="text-xs text-red-700">Delete</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {modal && (
        <WardModal
          mode={modal.mode}
          initial={modal.initial}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); refresh(); }}
        />
      )}
    </Section>
  );
}

// ---------- Staff roster (read-only, plus on-demand clock history) ----------
// No account editing and no admin-side clock actions here — this tab is
// purely "see who's on shift right now and look up their recent history",
// per the task scope. Clock-in/out itself only ever happens from the staff
// member's own nav pill (Layout.jsx's ClockControl).
function StaffRosterTab() {
  const [staff, setStaff] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState(null);
  // Cache per-staff history once fetched so re-expanding the same row
  // doesn't re-hit the endpoint — a roster with many staff shouldn't turn
  // into repeated requests just from someone toggling a row a few times.
  const [historyById, setHistoryById] = useState({});
  const [historyLoading, setHistoryLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    getStaffRoster().then(setStaff).finally(() => setLoading(false));
  }, []);

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

// Facility-scoped admin console — appointments monitoring, medicine
// inventory, ward/bed capacity, and staff roster, all auto-scoped
// server-side to the current admin's own facility (routers/admin.py).
// Access itself is gated one level up by App.jsx's AdminOnly route guard;
// nothing here needs to re-check the role.
export default function AdminConsole() {
  const [activeTab, setActiveTab] = useState("appointments");

  return (
    <Layout>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Admin Console</h1>
        <p className="text-sm text-slate-500">Facility-wide monitoring and management for your hospital.</p>
      </div>

      <TabBar active={activeTab} onChange={setActiveTab} />

      {activeTab === "appointments" && <AppointmentsTab />}
      {activeTab === "inventory" && <InventoryTab />}
      {activeTab === "wards" && <WardsTab />}
      {activeTab === "staff" && <StaffRosterTab />}
    </Layout>
  );
}
