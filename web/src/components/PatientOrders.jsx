import { useCallback, useEffect, useState } from "react";
import {
  listPatientOrders, createOrder, completeOrder, cancelOrder, listDrugs, errorMessage, getCurrentUser,
} from "../api/client";
import { formatDateTime } from "../lib/format";
import { tr } from "../lib/i18n";

export const ORDER_TYPES = [
  ["drug", "Drug"], ["investigation", "Investigation"], ["imaging", "Imaging"], ["procedure", "Procedure"], ["other", "Other"],
];
const STATUS_TONE = {
  ordered: "bg-blue-50 text-blue-800", completed: "bg-green-50 text-green-800", cancelled: "bg-slate-100 text-slate-600",
};
const empty = { order_type: "drug", description: "", product_code: "", quantity: 1, dosage: "", is_stat: false, notes: "" };

export function OrderRow({ order, canCancel, canComplete, onChanged, showPatient }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(fn) {
    setBusy(true);
    setError("");
    try { await fn(); onChanged(); } catch (e) { setError(errorMessage(e, "That did not work.")); } finally { setBusy(false); }
  }
  function cancel() {
    const reason = window.prompt("Why is this order being cancelled?");
    if (reason && reason.trim()) run(() => cancelOrder(order.id, reason.trim()));
  }

  return (
    <li className="record-row">
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-900">
          {order.description}
          {order.is_stat && <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-xs text-red-800">{tr("STAT")}</span>}
        </p>
        <p className="text-xs text-slate-500">
          {showPatient && order.patient_name ? `${order.patient_name} · ` : ""}
          {order.order_type} · qty {order.quantity}{order.dosage ? ` · ${order.dosage}` : ""}
          {" · "}{order.ordered_by_name || "unknown"} · {formatDateTime(order.created_at)}
        </p>
        {order.notes && <p className="text-xs text-slate-600">{order.notes}</p>}
        {order.status === "cancelled" && <p className="text-xs text-slate-500">Cancelled: {order.cancel_reason}</p>}
        {order.status === "completed" && (
          <p className="text-xs text-slate-500">
            Completed by {order.completed_by_name}{order.completion_note ? `: ${order.completion_note}` : ""}
          </p>
        )}
        {error && <p className="alert-error mt-1" role="alert">{error}</p>}
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[order.status] || ""}`}>{order.status}</span>
        {order.status === "ordered" && canComplete && (
          <button type="button" className="btn-chip" disabled={busy} onClick={() => run(() => completeOrder(order.id))}>
            {order.order_type === "drug" ? "Dispense" : "Mark done"}
          </button>
        )}
        {order.status === "ordered" && canCancel && (
          <button type="button" className="btn-chip" disabled={busy} onClick={cancel}>{tr("Cancel")}</button>
        )}
      </div>
    </li>
  );
}

// Orders for one patient at the signed-in facility, plus the form to place a new one.
export default function PatientOrders({ patientId }) {
  const user = getCurrentUser();
  const canOrder = user?.role === "clinician" || user?.role === "admin";
  const [orders, setOrders] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState(empty);
  const [suggestions, setSuggestions] = useState([]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const load = useCallback(() => {
    listPatientOrders(patientId).then(setOrders).catch((e) => setError(errorMessage(e, "Could not load orders.")));
  }, [patientId]);
  useEffect(load, [load]);

  // Drug name suggestions from the catalogue; free text is still accepted.
  useEffect(() => {
    if (form.order_type !== "drug" || form.description.trim().length < 3) { setSuggestions([]); return undefined; }
    let off = false;
    const t = setTimeout(() => {
      listDrugs({ q: form.description.trim(), limit: 8 }).then((r) => !off && setSuggestions(r.items || r)).catch(() => {});
    }, 250);
    return () => { off = true; clearTimeout(t); };
  }, [form.order_type, form.description]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setFormError("");
    try {
      await createOrder(patientId, {
        order_type: form.order_type,
        description: form.description.trim() || null,
        quantity: Number(form.quantity) || 1,
        dosage: form.dosage.trim() || null,
        is_stat: form.is_stat,
        notes: form.notes.trim() || null,
      });
      setForm(empty);
      setOpen(false);
      load();
    } catch (err) { setFormError(errorMessage(err, "Could not place the order.")); } finally { setSaving(false); }
  }

  return (
    <div className="space-y-3">
      {canOrder && !open && <button type="button" className="btn-primary" onClick={() => setOpen(true)}>{tr("New order")}</button>}
      {open && (
        <form onSubmit={submit} className="space-y-3 rounded-lg border border-slate-200 p-4" aria-label={tr("New order")}>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="ord-type" className="field-label">{tr("Type")}</label>
              <select id="ord-type" className="field-input" value={form.order_type} onChange={set("order_type")}>
                {ORDER_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="ord-desc" className="field-label">{tr("What is ordered")}</label>
              <input id="ord-desc" className="field-input" value={form.description} onChange={set("description")}
                list="ord-suggest" required maxLength={500} />
              <datalist id="ord-suggest">
                {suggestions.map((s) => <option key={s.drug_code} value={s.drug_generic_name} />)}
              </datalist>
            </div>
            <div>
              <label htmlFor="ord-qty" className="field-label">{tr("Quantity")}</label>
              <input id="ord-qty" type="number" min="1" className="field-input" value={form.quantity} onChange={set("quantity")} />
            </div>
            {form.order_type === "drug" && (
              <div>
                <label htmlFor="ord-dose" className="field-label">{tr("Dosage")}</label>
                <input id="ord-dose" className="field-input" value={form.dosage} onChange={set("dosage")} maxLength={64} />
              </div>
            )}
            <div className="sm:col-span-2">
              <label htmlFor="ord-notes" className="field-label">{tr("Notes")}</label>
              <input id="ord-notes" className="field-input" value={form.notes} onChange={set("notes")} maxLength={2000} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={form.is_stat} onChange={set("is_stat")} /> Urgent (STAT)
          </label>
          {formError && <p className="alert-error" role="alert">{formError}</p>}
          <div className="flex gap-2">
            <button type="submit" className="btn-primary" disabled={saving}>{saving ? "Placing..." : "Place order"}</button>
            <button type="button" className="btn-secondary" onClick={() => { setOpen(false); setFormError(""); }}>{tr("Cancel")}</button>
          </div>
        </form>
      )}
      {error && <p className="alert-error" role="alert">{error}</p>}
      {!error && orders === null && <p className="empty-state">{tr("Loading...")}</p>}
      {orders && orders.length === 0 && <p className="empty-state">{tr("No orders at this facility for this patient.")}</p>}
      {orders && orders.length > 0 && (
        <ul>
          {orders.map((o) => (
            <OrderRow
              key={o.id} order={o} onChanged={load}
              canCancel={user?.role === "admin" || o.ordered_by === user?.id}
              canComplete={user?.role === "admin" || (user?.role === "clinician" && o.order_type !== "drug")}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
