import { useEffect, useRef, useState } from "react";
import {
  getAdminInventory, createInventoryItem, updateInventoryItem, deleteInventoryItem,
  uploadMedicineImage, getMedicineImageBlob,
  getAdminProposals, approvePurchaseProposal, rejectPurchaseProposal,
  getBudget, setBudget,
  getDeleteRequests, approveDeleteRequest, rejectDeleteRequest,
} from "../../api/client";
import { formatDateTime } from "../../lib/format";
import { validateImageFile } from "../../lib/upload";
import { Section } from "./_shared";
import DrugHints, { CatalogueTag } from "../../components/DrugHints";
import { occupancyColor, occupancyTextColor } from "./occupancy";
import { tr } from "../../lib/i18n";

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
    <div className="modal-backdrop">
      <div className="modal-panel">
        <h3 className="font-semibold text-slate-800 mb-4">{mode === "add" ? "Add Inventory Item" : "Edit Inventory Item"}</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="alert-error">{error}</div>}
          {INVENTORY_FIELDS.map((f) => (
            <div key={f.key}>
              <label className="field-label">
                {f.label}{f.required && <span className="text-red-600"> *</span>}
              </label>
              {f.type === "textarea" ? (
                <textarea
                  className="field-input"
                  rows={2}
                  value={values[f.key]}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                />
              ) : (
                <input
                  className="field-input"
                  type={f.type}
                  min={f.type === "number" ? 0 : undefined}
                  step={f.step}
                  placeholder={f.placeholder}
                  value={values[f.key]}
                  list={f.key === "drug_name" ? "inventory-drug-hints" : undefined}
                  autoComplete={f.key === "drug_name" ? "off" : undefined}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                />
              )}
            </div>
          ))}
          <DrugHints id="inventory-drug-hints" query={values.drug_name} />
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
            <button disabled={saving} className="btn-primary">
              {saving ? "Saving..." : "Save"}
            </button>
            <button type="button" onClick={onClose} className="btn-secondary">
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

  if (loading) return <Section title={tr("Procurement Budget")}><p className="text-sm text-slate-400">{tr("Loading...")}</p></Section>;

  const allocated = budget?.allocated_amount ?? 0;
  const spend = budget?.procurement_spend ?? 0;
  const stockValue = budget?.current_stock_value ?? 0;
  const remaining = budget?.remaining ?? 0;
  const pct = allocated > 0 ? Math.round((spend / allocated) * 100) : 0;

  return (
    <Section title={tr("Procurement Budget")}>
      {error && <div className="alert-error mb-3">{error}</div>}

      <form onSubmit={save} className="flex flex-wrap items-end gap-3 mb-4">
        <div>
          <label className="field-label">Allocated (RM)</label>
          <input
            className="w-40 border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            type="number"
            min="0"
            step="0.01"
            value={editing}
            onChange={(e) => setEditing(e.target.value)}
          />
        </div>
        <button disabled={saving} className="btn-primary">
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
          <p className="text-xs text-slate-400">{tr("Allocated")}</p>
          <p className="font-medium text-slate-800">RM {allocated.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">{tr("Procurement spend")}</p>
          <p className={`font-medium ${occupancyTextColor(pct)}`}>RM {spend.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">{tr("Current stock value")}</p>
          <p className="font-medium text-slate-800">RM {stockValue.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-400">{tr("Remaining")}</p>
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
    <Section title={tr("Deletion Requests")}>
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
        <p className="text-sm text-slate-400">{tr("Loading...")}</p>
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
                  <span className="ml-2 text-xs text-slate-400">{tr("restock")}</span>
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

export default function InventoryTab() {
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
      title={tr("Medicine Inventory")}
      action={
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder={tr("Search name or barcode...")}
            className="border rounded-lg px-3 py-1.5 text-sm w-52"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button onClick={() => setModal({ mode: "add", initial: null })} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg whitespace-nowrap">{tr("+ Add Item")}</button>
        </div>
      }
    >
      {loading ? (
        <p className="text-sm text-slate-400">{tr("Loading...")}</p>
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
                    <CatalogueTag code={item.drug_code} />
                    {item.auto_approved && (
                      <span className="ml-2 text-xs font-semibold text-green-700 bg-green-100 rounded px-1.5 py-0.5">{tr("Auto-approved")}</span>
                    )}
                    {item.is_low_stock && <span className="ml-2 text-xs font-semibold text-amber-700 uppercase">{tr("⚠ Low stock")}</span>}
                  </p>
                  <p className="text-xs text-slate-400">
                    {item.quantity_on_hand} {item.unit}
                    {item.reorder_threshold != null && ` · reorder at ${item.reorder_threshold}`}
                    {item.unit_cost != null && ` · RM ${Number(item.unit_cost).toFixed(2)}/${item.unit}`}
                    {item.barcode && ` · barcode ${item.barcode}`}
                    {" · last restocked "}{item.last_restocked_at ? formatDateTime(item.last_restocked_at) : "never"}
                  </p>
                  {item.pending_delete_request && (
                    <p className="text-xs font-semibold text-amber-700 uppercase mt-0.5">{tr("Deletion requested")}</p>
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
                    title={tr("Decrease quantity by 1")}
                  >
                    −
                  </button>
                  <span className="text-xs text-slate-500 w-6 text-center">{item.quantity_on_hand}</span>
                  <button
                    onClick={() => adjustQuantity(item, 1)}
                    disabled={busyId === item.id}
                    className="w-6 h-6 text-sm border border-slate-300 rounded disabled:opacity-30"
                    title={tr("Increase quantity by 1 (restock)")}
                  >
                    +
                  </button>
                </div>
                <button onClick={() => setModal({ mode: "edit", initial: item })} className="text-xs text-blue-700 whitespace-nowrap">{tr("Edit")}</button>
                <button onClick={() => handleDelete(item)} className="text-xs text-red-700 whitespace-nowrap">{tr("Delete")}</button>
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
