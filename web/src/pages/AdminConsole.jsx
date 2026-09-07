import { useEffect, useRef, useState } from "react";
import Layout from "../components/Layout";
import {
  getAdminAppointments,
  getAdminInventory, createInventoryItem, updateInventoryItem, deleteInventoryItem,
  uploadMedicineImage, getMedicineImageBlob,
  getAdminProposals, approvePurchaseProposal, rejectPurchaseProposal,
  getBudget, setBudget,
  getDeleteRequests, approveDeleteRequest, rejectDeleteRequest,
  getWards, createWard, updateWard, deleteWard,
  getFloors, createFloor, updateFloor, deleteFloor,
  getRooms, createRoom, updateRoom, deleteRoom,
  getSections, createSection, updateSection, deleteSection,
  getStaffRoster, getStaffClockHistory, updateStaffMember,
  getHospitalSettings, updateHospitalSettings,
  getRolePermissions, updateRolePermissions,
  getWaitingRoomDisplays, createWaitingRoomDisplay, revokeWaitingRoomDisplay,
} from "../api/client";
import WardMap from "../components/WardMap";
import { formatDateTime } from "../lib/format";
import { validateImageFile } from "../lib/upload";

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
  // Floors + standalone ward capacity + the bed-level ward map used to be
  // three separate tabs; they're now one "Wards" tab with an internal
  // Floors / Heat map / Full details view switcher (see WardsTab).
  { key: "wards", label: "Wards" },
  { key: "rooms", label: "Consultation Rooms" },
  { key: "sections", label: "Sections" },
  { key: "displays", label: "Waiting Room Displays" },
  { key: "staff", label: "Staff Roster" },
  { key: "hospital", label: "Hospital Settings" },
  { key: "access", label: "Access Control" },
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
  { key: "unit_cost", label: "Unit cost (RM)", type: "number", step: "0.01", placeholder: "Procurement cost per unit — drives the budget rollup" },
  { key: "barcode", label: "Barcode", type: "text", placeholder: "Scanned/keyed code — searchable from the pharmacy console" },
  { key: "notes", label: "Notes", type: "textarea" },
];

// 40px inventory-row thumbnail. Loads the photo as an auth blob (object URL,
// revoked on unmount / image change) or shows a pill placeholder. Admins
// upload via the admin image route. The parent applies the returned row.
function MedicineThumb({ item, onUploaded }) {
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    let objectUrl = null;
    if (item.has_image && item.image_url) {
      getMedicineImageBlob(item.image_url)
        .then((u) => {
          if (cancelled) {
            URL.revokeObjectURL(u);
            return;
          }
          objectUrl = u;
          setUrl(u);
        })
        .catch(() => setUrl(null));
    } else {
      setUrl(null);
    }
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [item.has_image, item.image_url]);

  async function handleFile(file) {
    const localErr = validateImageFile(file);
    if (localErr) {
      setErr(localErr);
      return;
    }
    setErr("");
    setBusy(true);
    try {
      const updated = await uploadMedicineImage(item.id, file, { admin: true });
      onUploaded(updated);
    } catch (e) {
      setErr(e?.response?.data?.detail || "Upload failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="shrink-0">
      <button
        type="button"
        onClick={() => !busy && fileRef.current?.click()}
        disabled={busy}
        className="block w-10 h-10 rounded-lg border border-slate-200 overflow-hidden bg-white disabled:opacity-50"
        title={item.has_image ? "Replace photo" : "Add photo"}
      >
        {url ? (
          <img src={url} alt={item.drug_name} className="w-full h-full object-cover" />
        ) : (
          <svg viewBox="0 0 24 24" className="w-full h-full text-slate-300" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="3" y="9" width="18" height="6" rx="3" transform="rotate(45 12 12)" />
          </svg>
        )}
      </button>
      <button
        type="button"
        onClick={() => !busy && fileRef.current?.click()}
        disabled={busy}
        className="mt-0.5 block text-[10px] text-blue-700 disabled:opacity-40"
      >
        {item.has_image ? "Replace" : "Add photo"}
      </button>
      {err && <p className="text-[10px] text-red-600 w-24">{err}</p>}
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) handleFile(file);
        }}
      />
    </div>
  );
}

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
    unit_cost: initial?.unit_cost ?? "",
    notes: initial?.notes ?? "",
    barcode: initial?.barcode ?? "",
  }));
  const [autoApproved, setAutoApproved] = useState(initial?.auto_approved ?? false);
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
      unit_cost: values.unit_cost === "" ? null : Number(values.unit_cost),
      notes: values.notes.trim() || null,
      barcode: values.barcode.trim() || null,
    };
    try {
      if (mode === "add") {
        // MedicineInventoryCreate has no auto_approved field (it's an
        // admin-only toggle reachable only through PATCH), so a create that
        // wants it on has to follow up with a PATCH on the new row's id.
        const created = await createInventoryItem(payload);
        if (autoApproved) await updateInventoryItem(created.id, { auto_approved: true });
      } else {
        await updateInventoryItem(initial.id, { ...payload, auto_approved: autoApproved });
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
                  step={f.step}
                  placeholder={f.placeholder}
                  value={values[f.key]}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                />
              )}
            </div>
          ))}
          <label className="flex items-start gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={autoApproved}
              onChange={(e) => setAutoApproved(e.target.checked)}
            />
            <span>
              Auto-approved
              <span className="block text-xs text-slate-400">
                Pharmacists can restock this item without admin approval.
              </span>
            </span>
          </label>
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

// ---------- Medicine procurement budget ----------
// Allocated amount is admin-editable; procurement spend accrues
// automatically on every pharmacy restock (routers/pharmacy.py). The bar
// reuses occupancyColor's green/amber/red vocabulary — here keyed on the
// spend-vs-allocated ratio rather than bed occupancy.
function BudgetPanel() {
  const [budget, setBudgetState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function refresh() {
    setLoading(true);
    getBudget()
      .then((b) => {
        setBudgetState(b);
        setEditing(String(b.allocated_amount ?? 0));
      })
      .catch((err) => setError(err?.response?.data?.detail || "Failed to load budget."))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  async function save(e) {
    e.preventDefault();
    const amount = Number(editing);
    if (!Number.isFinite(amount) || amount < 0) {
      setError("Allocated amount must be a non-negative number.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const updated = await setBudget({ allocated_amount: amount });
      setBudgetState(updated);
      setEditing(String(updated.allocated_amount ?? 0));
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save budget.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Section title="Procurement Budget"><p className="text-sm text-slate-400">Loading...</p></Section>;

  const allocated = budget?.allocated_amount ?? 0;
  const spend = budget?.procurement_spend ?? 0;
  const stockValue = budget?.current_stock_value ?? 0;
  const remaining = budget?.remaining ?? 0;
  const pct = allocated > 0 ? Math.round((spend / allocated) * 100) : 0;

  return (
    <Section title="Procurement Budget">
      {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}

      <form onSubmit={save} className="flex flex-wrap items-end gap-3 mb-4">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Allocated (RM)</label>
          <input
            className="w-40 border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            type="number"
            min="0"
            step="0.01"
            value={editing}
            onChange={(e) => setEditing(e.target.value)}
          />
        </div>
        <button disabled={saving} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50">
          {saving ? "Saving..." : "Save"}
        </button>
      </form>

      <div className="w-full bg-slate-100 rounded-full h-2 overflow-hidden">
        <div
          className={`h-2 rounded-full ${occupancyColor(pct)}`}
          style={{ width: `${Math.min(100, pct)}%` }}
        />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-3 text-sm">
        <div>
          <p className="text-xs text-slate-400">Allocated</p>
          <p className="font-medium text-slate-800">RM {allocated.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Procurement spend</p>
          <p className={`font-medium ${occupancyTextColor(pct)}`}>RM {spend.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Current stock value</p>
          <p className="font-medium text-slate-800">RM {stockValue.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">Remaining</p>
          <p className={`font-medium ${remaining < 0 ? "text-red-700" : "text-slate-800"}`}>
            RM {remaining.toFixed(2)}
          </p>
        </div>
      </div>
    </Section>
  );
}

// ---------- Shared review-queue row ----------
// The deletion-request and purchase-proposal panels are visually the same
// thing — an amber "waiting on you" card with a left info column and a right
// action column — so they share this shell. `tone` lets a resolved
// (approved/rejected) proposal render calmer than a pending one.
const REVIEW_TONE = {
  amber: "bg-amber-50 border-amber-200",
  slate: "bg-slate-50 border-slate-200",
};
function ReviewCard({ tone = "amber", children, actions }) {
  return (
    <div className={`border rounded-lg px-3 py-2 ${REVIEW_TONE[tone] || REVIEW_TONE.amber}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm text-slate-700 min-w-0">{children}</div>
        {actions && <div className="flex items-center gap-3 shrink-0">{actions}</div>}
      </div>
    </div>
  );
}

// ---------- Inventory deletion requests (pharmacist → admin approval) ----------
// Only rendered when there is at least one pending request. Approve performs
// the hard delete of the item on the backend; reject prompts for an optional
// note. Both refresh the inventory list (an approved item disappears from it).
function DeleteRequestsSection({ onResolved }) {
  const [requests, setRequests] = useState([]);
  const [busyId, setBusyId] = useState(null);

  function refresh() {
    getDeleteRequests("pending").then(setRequests).catch(() => setRequests([]));
  }

  useEffect(refresh, []);

  async function approve(req) {
    if (!confirm(`Approve deletion of "${req.item_name}"? The item is permanently removed.`)) return;
    setBusyId(req.id);
    try {
      await approveDeleteRequest(req.id);
      refresh();
      onResolved?.();
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to approve.");
    } finally {
      setBusyId(null);
    }
  }

  async function reject(req) {
    const note = prompt(`Reject the deletion request for "${req.item_name}"?\nOptional note for the pharmacist:`);
    if (note === null) return;
    setBusyId(req.id);
    try {
      await rejectDeleteRequest(req.id, { admin_note: note.trim() || null });
      refresh();
      onResolved?.();
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to reject.");
    } finally {
      setBusyId(null);
    }
  }

  if (requests.length === 0) return null;

  return (
    <Section title="Deletion Requests">
      <div className="space-y-2">
        {requests.map((req) => (
          <ReviewCard
            key={req.id}
            actions={
              <>
                <button
                  onClick={() => approve(req)}
                  disabled={busyId === req.id}
                  className="text-xs text-red-700 whitespace-nowrap disabled:opacity-40"
                >
                  Approve
                </button>
                <button
                  onClick={() => reject(req)}
                  disabled={busyId === req.id}
                  className="text-xs text-blue-700 whitespace-nowrap disabled:opacity-40"
                >
                  Reject
                </button>
              </>
            }
          >
            <p className="font-medium">{req.item_name}</p>
            <p className="text-xs text-slate-500">
              Requested by {req.requested_by_name || "—"} · {formatDateTime(req.created_at)}
            </p>
            {req.reason && <p className="text-xs text-slate-600 mt-0.5">Reason: {req.reason}</p>}
          </ReviewCard>
        ))}
      </div>
    </Section>
  );
}

// ---------- Purchase proposals (pharmacist → admin approval) ----------
// A pharmacist's request to restock a non-auto-approved item, or to add a
// brand-new medicine (item_id === null). Approve applies the restock / item
// creation server-side, so both actions refresh the inventory list. A status
// toggle also exposes the approved/rejected history.
const PROPOSAL_STATUSES = ["pending", "approved", "rejected"];

function PurchaseProposalsSection({ onResolved }) {
  const [status, setStatus] = useState("pending");
  const [proposals, setProposals] = useState([]);
  const [busyId, setBusyId] = useState(null);
  const [loading, setLoading] = useState(true);

  function refresh() {
    setLoading(true);
    getAdminProposals(status)
      .then(setProposals)
      .catch(() => setProposals([]))
      .finally(() => setLoading(false));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(refresh, [status]);

  async function approve(p) {
    if (!confirm(`Approve "${p.proposed_drug_name}" — ${p.quantity} ${p.proposed_unit}? This updates stock and the budget.`)) return;
    setBusyId(p.id);
    try {
      await approvePurchaseProposal(p.id);
      refresh();
      onResolved?.();
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to approve.");
    } finally {
      setBusyId(null);
    }
  }

  async function reject(p) {
    const reason = prompt(`Reject the proposal for "${p.proposed_drug_name}"?\nOptional reason for the pharmacist:`);
    if (reason === null) return;
    setBusyId(p.id);
    try {
      await rejectPurchaseProposal(p.id, reason.trim() || null);
      refresh();
      onResolved?.();
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to reject.");
    } finally {
      setBusyId(null);
    }
  }

  const pendingCount = status === "pending" ? proposals.length : null;

  return (
    <Section
      title={
        <span className="flex items-center gap-2">
          Purchase Proposals
          {pendingCount ? (
            <span className="text-xs font-semibold bg-amber-100 text-amber-800 rounded-full px-2 py-0.5">
              {pendingCount}
            </span>
          ) : null}
        </span>
      }
      action={
        <div className="inline-flex rounded-lg border border-slate-200 p-0.5 bg-slate-50">
          {PROPOSAL_STATUSES.map((s) => (
            <button
              key={s}
              onClick={() => setStatus(s)}
              className={`px-2.5 py-1 text-xs font-medium rounded-md capitalize ${
                status === s ? "bg-white text-blue-800 shadow-sm" : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      }
    >
      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : proposals.length === 0 ? (
        <p className="text-sm text-slate-400">No {status} proposals.</p>
      ) : (
        <div className="space-y-2">
          {proposals.map((p) => (
            <ReviewCard
              key={p.id}
              tone={p.status === "pending" ? "amber" : "slate"}
              actions={
                p.status === "pending" ? (
                  <>
                    <button
                      onClick={() => approve(p)}
                      disabled={busyId === p.id}
                      className="text-xs text-green-700 whitespace-nowrap disabled:opacity-40"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => reject(p)}
                      disabled={busyId === p.id}
                      className="text-xs text-red-700 whitespace-nowrap disabled:opacity-40"
                    >
                      Reject
                    </button>
                  </>
                ) : (
                  <span className="text-xs text-slate-400 capitalize">{p.status}</span>
                )
              }
            >
              <p className="font-medium">
                {p.proposed_drug_name}
                {(p.is_new_item || p.item_id === null) ? (
                  <span className="ml-2 text-xs font-semibold text-blue-700 bg-blue-100 rounded px-1.5 py-0.5">
                    New item
                  </span>
                ) : (
                  <span className="ml-2 text-xs text-slate-400">restock</span>
                )}
              </p>
              <p className="text-xs text-slate-500">
                {p.quantity} {p.proposed_unit}
                {p.unit_cost != null && ` · RM ${Number(p.unit_cost).toFixed(2)}/unit`}
                {" · "}by {p.requested_by_name || "—"} · {formatDateTime(p.created_at)}
              </p>
              {p.proposed_barcode && (
                <p className="text-xs text-slate-500 mt-0.5">Barcode: {p.proposed_barcode}</p>
              )}
              {p.reason && <p className="text-xs text-slate-600 mt-0.5">Reason: {p.reason}</p>}
              {p.admin_note && <p className="text-xs text-slate-500 mt-0.5">Admin note: {p.admin_note}</p>}
              {p.reviewed_at && (
                <p className="text-xs text-slate-400 mt-0.5">Reviewed {formatDateTime(p.reviewed_at)}</p>
              )}
            </ReviewCard>
          ))}
        </div>
      )}
    </Section>
  );
}

function InventoryTab() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null); // { mode: 'add'|'edit', initial } | null
  // Bumped after a delete-request is resolved so BudgetPanel /
  // DeleteRequestsSection remount and re-fetch alongside the inventory list.
  const [reloadKey, setReloadKey] = useState(0);
  // Per-row id currently mid-request — disables that row's +/- stepper so a
  // double click can't fire two overlapping PATCHes against the same item.
  const [busyId, setBusyId] = useState(null);
  // Search — raw input plus its debounced copy (same drug-name/barcode
  // filter the pharmacy console uses).
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");

  function refresh() {
    setLoading(true);
    getAdminInventory({ q: debouncedQuery.trim() || undefined })
      .then(setItems)
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(refresh, [debouncedQuery]);

  function replaceRow(updated) {
    setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
  }

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
    <>
      <BudgetPanel key={`budget-${reloadKey}`} />
      <DeleteRequestsSection
        key={`delreq-${reloadKey}`}
        onResolved={() => { refresh(); setReloadKey((k) => k + 1); }}
      />
      <PurchaseProposalsSection
        key={`proposals-${reloadKey}`}
        onResolved={() => { refresh(); setReloadKey((k) => k + 1); }}
      />
    <Section
      title="Medicine Inventory"
      action={
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Search name or barcode..."
            className="border rounded-lg px-3 py-1.5 text-sm w-52"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button onClick={() => setModal({ mode: "add", initial: null })} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg whitespace-nowrap">+ Add Item</button>
        </div>
      }
    >
      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : items.length === 0 ? (
        <p className="text-sm text-slate-400">
          {debouncedQuery.trim() ? "No items match that search." : "No inventory items yet — add one above."}
        </p>
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
              <div className="flex items-center gap-3 min-w-0">
                <MedicineThumb item={item} onUploaded={replaceRow} />
                <div className="text-sm text-slate-700 min-w-0">
                  <p className="font-medium">
                    {item.drug_name}
                    {item.auto_approved && (
                      <span className="ml-2 text-xs font-semibold text-green-700 bg-green-100 rounded px-1.5 py-0.5">Auto-approved</span>
                    )}
                    {item.is_low_stock && <span className="ml-2 text-xs font-semibold text-amber-700 uppercase">⚠ Low stock</span>}
                  </p>
                  <p className="text-xs text-slate-400">
                    {item.quantity_on_hand} {item.unit}
                    {item.reorder_threshold != null && ` · reorder at ${item.reorder_threshold}`}
                    {item.unit_cost != null && ` · RM ${Number(item.unit_cost).toFixed(2)}/${item.unit}`}
                    {item.barcode && ` · barcode ${item.barcode}`}
                    {" · last restocked "}{item.last_restocked_at ? formatDateTime(item.last_restocked_at) : "never"}
                  </p>
                  {item.pending_delete_request && (
                    <p className="text-xs font-semibold text-amber-700 uppercase mt-0.5">Deletion requested</p>
                  )}
                  {item.notes && <p className="text-xs text-slate-500 mt-0.5">{item.notes}</p>}
                </div>
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
    </>
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

// The non-floor "Ward Capacity" cards — standalone Ward rows with aggregate
// total/occupied bed counts (as opposed to floor-generated wards). Shown
// under the "Floors" view of WardsTab.
function StandaloneWardsTab() {
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

// ---------- Floors (auto-generated wards) ----------
// A floor is a number-driven block of uniform wards: set ward_count +
// beds_per_ward and the backend creates/adjusts that many general Ward rows
// (routers/admin.py). gender_restriction is a soft routing rule applied at
// admission time only — changing it never moves patients already in a bed.
// Mirrors WardModal's shell exactly.
const FLOOR_GENDER_OPTIONS = [
  { value: "", label: "— mixed —" },
  { value: "male", label: "Male only" },
  { value: "female", label: "Female only" },
];

function FloorModal({ mode, initial, onClose, onSaved }) {
  const [floorLabel, setFloorLabel] = useState(initial?.floor_label ?? "");
  const [gender, setGender] = useState(initial?.gender_restriction ?? "");
  const [wardCount, setWardCount] = useState(initial?.ward_count ?? "");
  const [bedsPerWard, setBedsPerWard] = useState(initial?.beds_per_ward ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!floorLabel.trim()) {
      setError("Floor label is required.");
      return;
    }
    if (!wardCount || Number(wardCount) < 1) {
      setError("Ward count must be at least 1.");
      return;
    }
    if (!bedsPerWard || Number(bedsPerWard) < 1) {
      setError("Beds per ward must be at least 1.");
      return;
    }
    setSaving(true);
    setError("");
    const payload = {
      floor_label: floorLabel.trim(),
      gender_restriction: gender || null,
      ward_count: Number(wardCount),
      beds_per_ward: Number(bedsPerWard),
    };
    try {
      if (mode === "add") await createFloor(payload);
      else await updateFloor(initial.id, payload);
      onSaved();
    } catch (err) {
      // Surfaces the backend's cross-field 400s inline (e.g. "can't reduce
      // ward_count: a ward still has an admitted patient").
      setError(err?.response?.data?.detail || "Failed to save. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl p-6 max-w-md w-full max-h-[90vh] overflow-y-auto">
        <h3 className="font-semibold text-slate-800 mb-4">{mode === "add" ? "Add Floor" : "Edit Floor"}</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error}</div>}

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Floor label<span className="text-red-600"> *</span></label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              type="text"
              placeholder="e.g. Level 3 Male Medical"
              value={floorLabel}
              onChange={(e) => setFloorLabel(e.target.value)}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Gender restriction</label>
            <select
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={gender}
              onChange={(e) => setGender(e.target.value)}
            >
              {FLOOR_GENDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Ward count<span className="text-red-600"> *</span></label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              type="number"
              min="1"
              value={wardCount}
              onChange={(e) => setWardCount(e.target.value)}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Beds per ward<span className="text-red-600"> *</span></label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              type="number"
              min="1"
              value={bedsPerWard}
              onChange={(e) => setBedsPerWard(e.target.value)}
            />
          </div>

          {mode === "edit" && (
            <p className="text-xs text-slate-400">
              Lowering the ward count or shrinking beds per ward is refused while a patient still
              occupies an affected bed. Changing the label or gender rule never moves anyone.
            </p>
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

function FloorsTab() {
  const [floors, setFloors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null); // { mode: 'add'|'edit', initial } | null
  const [busyId, setBusyId] = useState(null);

  function refresh() {
    setLoading(true);
    getFloors().then(setFloors).finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  async function handleDelete(floor) {
    if (!confirm(`Remove "${floor.floor_label}" and its ${floor.ward_count} ward(s)? This can't be undone.`)) return;
    setBusyId(floor.id);
    try {
      await deleteFloor(floor.id);
      refresh();
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to delete floor.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Section
      title="Floors"
      action={<button onClick={() => setModal({ mode: "add", initial: null })} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">+ Add Floor</button>}
    >
      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : floors.length === 0 ? (
        <p className="text-sm text-slate-400">No floors yet — add one above (e.g. Level 3 Male Medical).</p>
      ) : (
        <div className="space-y-2">
          {floors.map((f) => {
            const pct = f.total_beds ? Math.round((f.occupied_beds / f.total_beds) * 100) : 0;
            return (
              <div key={f.id} className="border border-slate-200 rounded-lg px-3 py-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm text-slate-700 min-w-0">
                    <p className="font-medium">{f.floor_label}</p>
                    <p className="text-xs text-slate-400">
                      {f.gender_restriction ? `${f.gender_restriction} only` : "Mixed"}
                      {" · "}{f.ward_count} ward(s) × {f.beds_per_ward} beds
                      {" · "}<span className={occupancyTextColor(pct)}>{f.occupied_beds} / {f.total_beds} beds used</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <button onClick={() => setModal({ mode: "edit", initial: f })} className="text-xs text-blue-700">Edit</button>
                    <button onClick={() => handleDelete(f)} disabled={busyId === f.id} className="text-xs text-red-700 disabled:opacity-40">Delete</button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {modal && (
        <FloorModal
          mode={modal.mode}
          initial={modal.initial}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); refresh(); }}
        />
      )}
    </Section>
  );
}

// ---------- Wards (Floors + Heat map + Full details) ----------
// One tab replacing the former "Ward Capacity", "Floors" and "Ward Map"
// tabs. A segmented control switches between three views of the same
// facility layout:
//   floors  — structure: add/edit floors and standalone wards
//   heatmap — read-only, wards tinted by occupancy (at-a-glance board)
//   full    — bed-level admit / discharge / move (the old Ward Map)
const WARD_VIEWS = [
  { key: "floors", label: "Floors" },
  { key: "heatmap", label: "Heat map" },
  { key: "full", label: "Full details" },
];

function WardsTab() {
  const [view, setView] = useState("floors");
  return (
    <div>
      <div className="inline-flex rounded-lg border border-slate-200 p-0.5 mb-4 bg-slate-50">
        {WARD_VIEWS.map((v) => (
          <button
            key={v.key}
            onClick={() => setView(v.key)}
            className={`px-3 py-1.5 text-sm font-medium rounded-md ${
              view === v.key ? "bg-white text-blue-800 shadow-sm" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      {view === "floors" && (
        <>
          <FloorsTab />
          <StandaloneWardsTab />
        </>
      )}
      {view === "heatmap" && (
        <Section title="Occupancy heat map">
          <WardMap mode="heatmap" />
        </Section>
      )}
      {view === "full" && (
        <Section title="Bed board">
          <WardMap />
        </Section>
      )}
    </div>
  );
}

// ---------- Consultation rooms ("Bilik") ----------
// Physical consult rooms reception round-robins walk-in check-ins across
// (routers/reception.py::_assign_room) and clinicians claim from the
// Reception "My Room" tab. `department` is an optional tag — leaving it
// blank means the room takes any department's overflow. The options are the
// facility's active section names (passed down from RoomsTab).
function RoomModal({ mode, initial, onClose, onSaved, sectionNames = [] }) {
  const [roomName, setRoomName] = useState(initial?.room_name ?? "");
  const [department, setDepartment] = useState(initial?.department ?? "");
  const [active, setActive] = useState(initial?.active ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!roomName.trim()) {
      setError("Room name is required.");
      return;
    }
    setSaving(true);
    setError("");
    const payload = {
      room_name: roomName.trim(),
      department: department || null,
      active,
    };
    try {
      if (mode === "add") await createRoom(payload);
      else await updateRoom(initial.id, payload);
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
        <h3 className="font-semibold text-slate-800 mb-4">{mode === "add" ? "Add Consultation Room" : "Edit Consultation Room"}</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error}</div>}

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Room name<span className="text-red-600"> *</span></label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              type="text"
              placeholder="e.g. Bilik A"
              value={roomName}
              onChange={(e) => setRoomName(e.target.value)}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Department tag (optional)</label>
            <select
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
            >
              <option value="">— any department —</option>
              {/* Keep an existing out-of-list value selectable so a PATCH
                  doesn't silently wipe a room tagged before sections changed. */}
              {department && !sectionNames.includes(department) && (
                <option value={department}>{department} (not a current section)</option>
              )}
              {sectionNames.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Active (available for round-robin and claiming)
          </label>

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

function RoomsTab() {
  const [rooms, setRooms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  // Active section names — the option set for a room's department tag.
  const [sectionNames, setSectionNames] = useState([]);

  function refresh() {
    setLoading(true);
    getRooms().then(setRooms).finally(() => setLoading(false));
  }

  useEffect(() => {
    refresh();
    getSections()
      .then((list) => setSectionNames(list.filter((s) => s.active).map((s) => s.name)))
      .catch(() => setSectionNames([]));
  }, []);

  async function handleDelete(room) {
    if (!confirm(`Remove "${room.room_name}"? Any clinician currently in it is released. This can't be undone.`)) return;
    await deleteRoom(room.id);
    refresh();
  }

  return (
    <Section
      title="Consultation Rooms"
      action={<button onClick={() => setModal({ mode: "add", initial: null })} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">+ Add Room</button>}
    >
      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : rooms.length === 0 ? (
        <p className="text-sm text-slate-400">No consultation rooms yet — add one above (e.g. Bilik A–E).</p>
      ) : (
        <div className="space-y-2">
          {rooms.map((room) => (
            <div
              key={room.id}
              className={`flex items-center justify-between gap-3 rounded-lg px-3 py-2 border ${
                room.active ? "bg-slate-50 border-slate-200" : "bg-white border-slate-200 opacity-60"
              }`}
            >
              <div className="text-sm text-slate-700 min-w-0">
                <p className="font-medium">
                  {room.room_name}
                  {!room.active && <span className="ml-2 text-xs font-semibold text-slate-500 uppercase">Inactive</span>}
                </p>
                <p className="text-xs text-slate-400">
                  {room.department || "Any department"} · {room.waiting_today} in queue today
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <button onClick={() => setModal({ mode: "edit", initial: room })} className="text-xs text-blue-700">Edit</button>
                <button onClick={() => handleDelete(room)} className="text-xs text-red-700">Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {modal && (
        <RoomModal
          mode={modal.mode}
          initial={modal.initial}
          sectionNames={sectionNames}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); refresh(); }}
        />
      )}
    </Section>
  );
}

// ---------- Sections (front-desk registration counters) ----------
// Admin-managed list of the hospital's front-desk counters (e.g. General
// Registration, O&G, ICU). A receptionist/clinician pinned to a section in
// the Staff Roster tab only ever sees that section's reception queue; the
// backend hard-scopes them server-side. Mirrors RoomsTab / RoomModal.
function SectionModal({ mode, initial, onClose, onSaved }) {
  const [name, setName] = useState(initial?.name ?? "");
  const [active, setActive] = useState(initial?.active ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Section name is required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (mode === "add") await createSection({ name: name.trim() });
      // active is only collected on edit — a brand-new section is active.
      else await updateSection(initial.id, { name: name.trim(), active });
      onSaved();
    } catch (err) {
      if (err?.response?.status === 409) {
        setError("A section with that name already exists at this facility.");
      } else {
        setError(err?.response?.data?.detail || "Failed to save. Check the name and try again.");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl p-6 max-w-md w-full max-h-[90vh] overflow-y-auto">
        <h3 className="font-semibold text-slate-800 mb-4">{mode === "add" ? "Add Section" : "Edit Section"}</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error}</div>}

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Section name<span className="text-red-600"> *</span></label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              type="text"
              placeholder="e.g. General Registration, O&G, ICU"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {mode === "edit" && (
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
              Active (assignable to staff and offered as a check-in counter)
            </label>
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

function SectionsTab() {
  const [sections, setSections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);

  function refresh() {
    setLoading(true);
    getSections().then(setSections).finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  async function handleDelete(section) {
    if (!confirm(`Delete section "${section.name}"? Staff assigned to it will be unassigned.`)) return;
    await deleteSection(section.id);
    refresh();
  }

  return (
    <Section
      title="Sections"
      action={<button onClick={() => setModal({ mode: "add", initial: null })} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">+ Add section</button>}
    >
      <p className="text-sm text-slate-500 mb-4 max-w-2xl">
        Front-desk registration counters for this hospital (e.g. General Registration, O&G, ICU).
        Assign staff to a section in the Staff Roster tab; a section-assigned receptionist only
        sees that section's queue.
      </p>

      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : sections.length === 0 ? (
        <p className="text-sm text-slate-400">No sections yet — add one above (e.g. General Registration).</p>
      ) : (
        <div className="space-y-2">
          {sections.map((section) => (
            <div
              key={section.id}
              className={`flex items-center justify-between gap-3 rounded-lg px-3 py-2 border ${
                section.active ? "bg-slate-50 border-slate-200" : "bg-white border-slate-200 opacity-60"
              }`}
            >
              <div className="text-sm text-slate-700 min-w-0">
                <p className="font-medium">
                  {section.name}
                  <span className={`ml-2 text-xs font-semibold uppercase ${section.active ? "text-green-700" : "text-slate-500"}`}>
                    {section.active ? "Active" : "Inactive"}
                  </span>
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <button onClick={() => setModal({ mode: "edit", initial: section })} className="text-xs text-blue-700">Edit</button>
                <button onClick={() => handleDelete(section)} className="text-xs text-red-700">Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {modal && (
        <SectionModal
          mode={modal.mode}
          initial={modal.initial}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); refresh(); }}
        />
      )}
    </Section>
  );
}

// ---------- Waiting Room Displays ----------
// Shareable, revocable tokens for a public lobby big-screen (/display/{token}
// — no auth). Each display is scoped to the whole facility or one section,
// and either masks patient names (recommended for a public screen) or shows
// them in full. The list includes revoked rows (greyed, no copy).
function DisplayRow({ display, onRevoke }) {
  const [copied, setCopied] = useState(false);
  const url = `${window.location.origin}/display/${display.token}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API blocked (e.g. non-HTTPS origin) — the URL is still
      // shown in full for a manual copy.
    }
  }

  return (
    <div
      className={`rounded-lg px-3 py-2 border ${
        display.revoked ? "bg-white border-slate-200 opacity-60" : "bg-slate-50 border-slate-200"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm text-slate-700 min-w-0">
          <p className="font-medium">
            {display.section || "Whole facility"}
            <span className="ml-2 text-xs font-semibold uppercase text-slate-500">
              {display.show_full_names ? "Full names" : "Masked names"}
            </span>
            {display.revoked && (
              <span className="ml-2 text-xs font-semibold uppercase text-red-700">Revoked</span>
            )}
          </p>
          <p className="text-xs text-slate-400">Created {formatDateTime(display.created_at)}</p>
          {!display.revoked && (
            <p className="text-xs text-slate-500 mt-1 font-mono break-all">{url}</p>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {!display.revoked && (
            <>
              <button onClick={copy} className="text-xs text-blue-700">
                {copied ? "Copied" : "Copy"}
              </button>
              <button onClick={() => onRevoke(display)} className="text-xs text-red-700">Revoke</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function WaitingRoomDisplaysTab() {
  const [displays, setDisplays] = useState([]);
  const [sectionNames, setSectionNames] = useState([]);
  const [loading, setLoading] = useState(true);
  const [section, setSection] = useState("");
  const [showFullNames, setShowFullNames] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [newUrl, setNewUrl] = useState(""); // prominently surfaced right after a create

  function refresh() {
    setLoading(true);
    getWaitingRoomDisplays().then(setDisplays).finally(() => setLoading(false));
  }

  useEffect(() => {
    refresh();
    getSections()
      .then((list) => setSectionNames(list.filter((s) => s.active).map((s) => s.name)))
      .catch(() => setSectionNames([]));
  }, []);

  async function create(e) {
    e.preventDefault();
    setCreating(true);
    setError("");
    try {
      const row = await createWaitingRoomDisplay({ section: section || null, show_full_names: showFullNames });
      setNewUrl(`${window.location.origin}/display/${row.token}`);
      setSection("");
      setShowFullNames(false);
      refresh();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to create display.");
    } finally {
      setCreating(false);
    }
  }

  async function revoke(display) {
    if (!confirm(`Revoke this display link? Any screen using it goes dark immediately.`)) return;
    try {
      await revokeWaitingRoomDisplay(display.id);
      refresh();
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to revoke.");
    }
  }

  return (
    <Section title="Waiting Room Displays">
      <p className="text-sm text-slate-500 mb-4 max-w-2xl">
        Generate a shareable link for a public lobby screen. It shows who's being called and who's
        waiting, refreshing on its own — no login needed. Revoke a link to kill it instantly.
      </p>

      <form onSubmit={create} className="flex flex-wrap items-end gap-3 mb-4">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Scope</label>
          <select
            className="border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={section}
            onChange={(e) => setSection(e.target.value)}
          >
            <option value="">Whole facility</option>
            {sectionNames.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <label className="flex items-start gap-2 text-sm text-slate-700 max-w-xs">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={showFullNames}
            onChange={(e) => setShowFullNames(e.target.checked)}
          />
          <span>
            Show full patient names
            <span className="block text-xs text-slate-400">
              Off = names are masked, e.g. "Ahmad I." — recommended for a public screen
            </span>
          </span>
        </label>
        <button disabled={creating} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50">
          {creating ? "Creating..." : "Create"}
        </button>
      </form>

      {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}
      {newUrl && (
        <div className="bg-green-50 border border-green-200 text-green-800 text-sm p-3 rounded mb-3">
          <p className="font-medium mb-1">New display link created</p>
          <p className="font-mono break-all">{newUrl}</p>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : displays.length === 0 ? (
        <p className="text-sm text-slate-400">No displays yet — create one above.</p>
      ) : (
        <div className="space-y-2">
          {displays.map((d) => <DisplayRow key={d.id} display={d} onRevoke={revoke} />)}
        </div>
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

// ---------- Hospital Settings ----------
// Facility profile (display name / address / contact / timezone) plus the
// CLARION network records-sharing switch. The backend lazily creates the
// settings row with defaults on first GET, so there's always something to
// render; PUT takes only the changed subset and rejects unknown keys.
// facility_name is the immutable registered name — shown read-only for
// context, never sent. Visual weight mirrors BudgetPanel's simple settings
// form rather than the modal-driven CRUD tabs.
const COMMON_TIMEZONES = [
  "Asia/Kuala_Lumpur",
  "Asia/Kuching",
  "Asia/Singapore",
  "Asia/Jakarta",
  "Asia/Bangkok",
  "Asia/Manila",
  "Asia/Hong_Kong",
  "Asia/Kolkata",
  "UTC",
];

function hospitalFormFrom(s) {
  return {
    display_name: s.display_name ?? "",
    address: s.address ?? "",
    contact_phone: s.contact_phone ?? "",
    timezone: s.timezone ?? "Asia/Kuala_Lumpur",
    records_shared_publicly: !!s.records_shared_publicly,
  };
}

function HospitalSettingsTab() {
  const [settings, setSettings] = useState(null);
  const [form, setForm] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    setLoading(true);
    getHospitalSettings()
      .then((s) => {
        setSettings(s);
        setForm(hospitalFormFrom(s));
      })
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load hospital settings."))
      .finally(() => setLoading(false));
  }, []);

  // Only send fields that actually changed (text fields compared trimmed) —
  // the backend rejects unknown keys and applies only what's present.
  function changedFields() {
    if (!settings || !form) return {};
    const diff = {};
    for (const k of ["display_name", "address", "contact_phone", "timezone"]) {
      const next = form[k].trim();
      if (next !== (settings[k] ?? "")) diff[k] = next;
    }
    if (form.records_shared_publicly !== !!settings.records_shared_publicly) {
      diff.records_shared_publicly = form.records_shared_publicly;
    }
    return diff;
  }

  const diff = changedFields();
  const dirty = Object.keys(diff).length > 0;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!dirty) return;
    setSaving(true);
    setError("");
    setJustSaved(false);
    try {
      const updated = await updateHospitalSettings(diff);
      setSettings(updated);
      setForm(hospitalFormFrom(updated));
      setJustSaved(true);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save hospital settings.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <Section title="Hospital Settings"><p className="text-sm text-slate-400">Loading...</p></Section>;
  }
  if (!form) {
    return (
      <Section title="Hospital Settings">
        <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error || "Failed to load hospital settings."}</div>
      </Section>
    );
  }

  return (
    <Section title="Hospital Settings">
      {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}
      {justSaved && !dirty && (
        <div className="bg-green-50 text-green-700 text-sm p-2 rounded mb-3">Hospital settings saved.</div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4 max-w-lg">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Facility name</label>
          <input
            className="w-full border border-slate-200 bg-slate-50 text-slate-500 rounded-lg px-3 py-1.5 text-sm"
            type="text"
            value={settings.facility_name || ""}
            disabled
          />
          <p className="text-xs text-slate-400 mt-1">The registered facility name can't be changed here.</p>
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Display name</label>
          <input
            className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            type="text"
            value={form.display_name}
            onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Address</label>
          <textarea
            className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={3}
            value={form.address}
            onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Contact phone</label>
          <input
            className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            type="tel"
            value={form.contact_phone}
            onChange={(e) => setForm((f) => ({ ...f, contact_phone: e.target.value }))}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Timezone</label>
          <select
            className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={form.timezone}
            onChange={(e) => setForm((f) => ({ ...f, timezone: e.target.value }))}
          >
            {/* Keep whatever the backend already stores even if it's outside
                our shortlist, so opening the form never silently rewrites it. */}
            {form.timezone && !COMMON_TIMEZONES.includes(form.timezone) && (
              <option value={form.timezone}>{form.timezone}</option>
            )}
            {COMMON_TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
          </select>
        </div>

        <div className="border border-slate-200 rounded-lg p-3 bg-slate-50">
          <label className="flex items-start gap-3 text-sm text-slate-700">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={form.records_shared_publicly}
              onChange={(e) => setForm((f) => ({ ...f, records_shared_publicly: e.target.checked }))}
            />
            <span>
              <span className="font-medium">Share records with other hospitals in the network</span>
              <span className="block text-xs text-slate-500 mt-0.5">
                When on, hospitals across the CLARION network can view clinical records your facility
                authored (they still can't edit them). When off, only your facility — and emergency
                responders during an emergency scan — can see records you authored.
              </span>
            </span>
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            disabled={saving || !dirty}
            className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
          {settings.updated_at && (
            <span className="text-xs text-slate-400">
              Last updated {formatDateTime(settings.updated_at)}
              {settings.updated_by ? ` by ${settings.updated_by}` : ""}
            </span>
          )}
        </div>
      </form>
    </Section>
  );
}

// ---------- Access Control (role → console-page matrix) ----------
// Per-facility control over which console pages each staff role can open
// (routers/admin.py::role-permissions). Rows are roles; columns are the
// configurable pages the backend hands back (always Patients / Reception /
// Pharmacy — `admin` is never an editable cell). The `admin` row is shown
// read-only and all-checked ("Admin always has full access"). Edits only
// affect a user the next time they sign in, because the client caches
// allowed_pages from login / GET /auth/me. Visual weight mirrors
// BudgetPanel / HospitalSettingsTab rather than the modal-driven CRUD tabs.
const PAGE_LABELS = { patients: "Patients", reception: "Reception", pharmacy: "Pharmacy" };

function roleLabel(role) {
  return role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Order-independent comparison of two allowed_pages lists.
function samePages(a, b) {
  if (a.length !== b.length) return false;
  const set = new Set(a);
  return b.every((p) => set.has(p));
}

function AccessControlTab() {
  const [entries, setEntries] = useState([]); // server truth, as returned
  const [edited, setEdited] = useState({}); // role -> allowed_pages[] (editable rows only)
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [justSaved, setJustSaved] = useState(false);

  function hydrate(data) {
    setEntries(data);
    const next = {};
    for (const e of data) {
      if (e.editable) next[e.role] = [...e.allowed_pages];
    }
    setEdited(next);
  }

  function refresh() {
    setLoading(true);
    getRolePermissions()
      .then(hydrate)
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load access control."))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  // Column set — identical on every entry per the backend contract, but read
  // it off an editable row rather than hard-coding in case that ever changes.
  const columns =
    entries.find((e) => e.editable)?.configurable_pages ||
    entries[0]?.configurable_pages ||
    ["patients", "reception", "pharmacy"];

  function toggle(role, page) {
    setJustSaved(false);
    setEdited((prev) => {
      const current = prev[role] || [];
      const nextPages = current.includes(page)
        ? current.filter((p) => p !== page)
        : [...current, page];
      return { ...prev, [role]: nextPages };
    });
  }

  // Only the editable rows whose selection actually differs from the server.
  const changedRoles = entries
    .filter((e) => e.editable && !samePages(edited[e.role] || [], e.allowed_pages))
    .map((e) => e.role);
  const dirty = changedRoles.length > 0;

  async function save() {
    if (!dirty) return;
    setSaving(true);
    setError("");
    setJustSaved(false);
    try {
      // Bulk PUT — send every editable role (not just the changed ones) so
      // the payload is a full, self-describing snapshot of the matrix.
      const body = entries
        .filter((e) => e.editable)
        .map((e) => ({ role: e.role, allowed_pages: edited[e.role] || [] }));
      const fresh = await updateRolePermissions(body);
      hydrate(fresh);
      setJustSaved(true);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save access control.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <Section title="Access Control"><p className="text-sm text-slate-400">Loading...</p></Section>;
  }

  return (
    <Section title="Access Control">
      <p className="text-sm text-slate-500 mb-4 max-w-2xl">
        Controls which console pages each staff role can open at this facility.
        Changes take effect the next time that user signs in.
      </p>

      {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}
      {justSaved && !dirty && (
        <div className="bg-green-50 text-green-700 text-sm p-2 rounded mb-3">Access control saved.</div>
      )}

      <div className="overflow-x-auto">
        <table className="text-sm border-collapse">
          <thead>
            <tr className="text-slate-500">
              <th className="text-left font-medium px-3 py-2">Role</th>
              {columns.map((page) => (
                <th key={page} className="font-medium px-3 py-2 text-center">
                  {PAGE_LABELS[page] || roleLabel(page)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => {
              const isAdmin = !entry.editable;
              const selected = isAdmin ? entry.allowed_pages : edited[entry.role] || [];
              return (
                <tr
                  key={entry.role}
                  className={`border-t border-slate-200 ${isAdmin ? "bg-slate-50 text-slate-400" : "text-slate-700"}`}
                >
                  <td className="px-3 py-2 font-medium capitalize whitespace-nowrap">
                    {roleLabel(entry.role)}
                    {isAdmin && (
                      <span className="block text-xs font-normal text-slate-400">
                        Admin always has full access.
                      </span>
                    )}
                  </td>
                  {columns.map((page) => (
                    <td key={page} className="px-3 py-2 text-center">
                      <input
                        type="checkbox"
                        checked={isAdmin ? true : selected.includes(page)}
                        disabled={isAdmin || saving}
                        onChange={() => toggle(entry.role, page)}
                      />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-3 mt-4">
        <button
          onClick={save}
          disabled={saving || !dirty}
          className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save changes"}
        </button>
        {dirty && (
          <span className="text-xs text-slate-400">
            Unsaved changes to: {changedRoles.map(roleLabel).join(", ")}
          </span>
        )}
      </div>
    </Section>
  );
}

// Facility-scoped admin console — appointments monitoring, medicine
// inventory, ward/bed capacity, and staff roster, all auto-scoped
// server-side to the current admin's own facility (routers/admin.py).
// Access itself is gated one level up by App.jsx's <RequirePage page="admin">
// route guard; nothing here needs to re-check the role.
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
      {activeTab === "rooms" && <RoomsTab />}
      {activeTab === "sections" && <SectionsTab />}
      {activeTab === "displays" && <WaitingRoomDisplaysTab />}
      {activeTab === "staff" && <StaffRosterTab />}
      {activeTab === "hospital" && <HospitalSettingsTab />}
      {activeTab === "access" && <AccessControlTab />}
    </Layout>
  );
}
