import { useCallback, useEffect, useState } from "react";
import Layout from "../components/Layout";
import {
  listSuppliers, createSupplier, listPurchaseOrders, createPurchaseOrder, placePurchaseOrder,
  cancelPurchaseOrder, receivePurchaseOrder, getPharmacyInventory, getCurrentUser, errorMessage,
} from "../api/client";
import { formatDateTime } from "../lib/format";
import { tr } from "../lib/i18n";

const STATUS_TONE = {
  draft: "bg-slate-100 text-slate-700", ordered: "bg-blue-50 text-blue-800",
  partially_received: "bg-amber-50 text-amber-800", received: "bg-green-50 text-green-800",
  cancelled: "bg-slate-100 text-slate-500",
};
const money = (n) => `RM ${Number(n || 0).toFixed(2)}`;

function Suppliers({ suppliers, isAdmin, onChanged }) {
  const [form, setForm] = useState({ code: "", name: "" });
  const [error, setError] = useState("");
  async function add(e) {
    e.preventDefault();
    setError("");
    try { await createSupplier({ code: form.code.trim(), name: form.name.trim() }); setForm({ code: "", name: "" }); onChanged(); }
    catch (err) { setError(errorMessage(err, "Could not add the supplier.")); }
  }
  return (
    <section className="card space-y-3">
      <h2 className="font-semibold text-slate-800">{tr("Suppliers")}</h2>
      {suppliers.length === 0 && <p className="empty-state">{tr("No suppliers yet.")}</p>}
      <ul>
        {suppliers.map((s) => (
          <li key={s.id} className="record-row">
            <span className="text-sm text-slate-900">{s.name} <span className="text-xs text-slate-400">{s.code}</span></span>
            {!s.active && <span className="text-xs text-slate-500">{tr("inactive")}</span>}
          </li>
        ))}
      </ul>
      {isAdmin && (
        <form onSubmit={add} className="flex flex-wrap items-end gap-2" aria-label={tr("Add supplier")}>
          <div>
            <label htmlFor="sup-code" className="field-label">{tr("Code")}</label>
            <input id="sup-code" className="field-input" value={form.code} required maxLength={32}
              onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))} />
          </div>
          <div>
            <label htmlFor="sup-name" className="field-label">{tr("Name")}</label>
            <input id="sup-name" className="field-input" value={form.name} required maxLength={255}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
          <button type="submit" className="btn-primary">{tr("Add supplier")}</button>
        </form>
      )}
      {error && <p className="alert-error" role="alert">{error}</p>}
    </section>
  );
}

function NewOrder({ suppliers, onCreated }) {
  const [items, setItems] = useState([]);
  const [supplierId, setSupplierId] = useState("");
  const [lines, setLines] = useState([{ item_id: "", quantity: "1", unit_cost: "" }]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => { getPharmacyInventory({}).then(setItems).catch(() => {}); }, []);

  const setLine = (i, k, v) => setLines((ls) => ls.map((l, n) => (n === i ? { ...l, [k]: v } : l)));

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await createPurchaseOrder({
        supplier_id: supplierId,
        lines: lines.map((l) => ({
          item_id: l.item_id, quantity: Number(l.quantity),
          unit_cost: l.unit_cost === "" ? null : Number(l.unit_cost),
        })),
      });
      setLines([{ item_id: "", quantity: "1", unit_cost: "" }]);
      onCreated();
    } catch (err) { setError(errorMessage(err, "Could not create the order.")); } finally { setSaving(false); }
  }

  return (
    <form onSubmit={submit} className="card space-y-3" aria-label={tr("New purchase order")}>
      <h2 className="font-semibold text-slate-800">{tr("New purchase order")}</h2>
      <div>
        <label htmlFor="po-supplier" className="field-label">{tr("Supplier")}</label>
        <select id="po-supplier" className="field-input max-w-sm" value={supplierId} required
          onChange={(e) => setSupplierId(e.target.value)}>
          <option value="">{tr("Choose a supplier")}</option>
          {suppliers.filter((s) => s.active).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>
      {lines.map((l, i) => (
        <div key={i} className="grid gap-2 sm:grid-cols-[2fr_1fr_1fr_auto] sm:items-end">
          <div>
            <label htmlFor={`po-item-${i}`} className="field-label">{tr("Item")}</label>
            <select id={`po-item-${i}`} className="field-input" value={l.item_id} required
              onChange={(e) => setLine(i, "item_id", e.target.value)}>
              <option value="">{tr("Choose an item")}</option>
              {items.map((it) => <option key={it.id} value={it.id}>{it.drug_name}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor={`po-qty-${i}`} className="field-label">{tr("Quantity")}</label>
            <input id={`po-qty-${i}`} type="number" min="1" className="field-input" value={l.quantity} required
              onChange={(e) => setLine(i, "quantity", e.target.value)} />
          </div>
          <div>
            <label htmlFor={`po-cost-${i}`} className="field-label">{tr("Unit cost (RM)")}</label>
            <input id={`po-cost-${i}`} type="number" min="0" step="0.01" className="field-input" value={l.unit_cost}
              onChange={(e) => setLine(i, "unit_cost", e.target.value)} />
          </div>
          {lines.length > 1 && (
            <button type="button" className="btn-chip" onClick={() => setLines((ls) => ls.filter((_, n) => n !== i))}>{tr("Remove")}</button>
          )}
        </div>
      ))}
      <div className="flex gap-2">
        <button type="button" className="btn-secondary"
          onClick={() => setLines((ls) => [...ls, { item_id: "", quantity: "1", unit_cost: "" }])}>{tr("Add line")}</button>
        <button type="submit" className="btn-primary" disabled={saving}>{saving ? "Saving..." : "Create draft"}</button>
      </div>
      {error && <p className="alert-error" role="alert">{error}</p>}
    </form>
  );
}

function OrderCard({ po, isAdmin, onChanged }) {
  const [receive, setReceive] = useState(null); // {line_id: {quantity, batch_number, expiry_date}}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(fn) {
    setBusy(true);
    setError("");
    try { await fn(); setReceive(null); onChanged(); } catch (e) { setError(errorMessage(e, "That did not work.")); } finally { setBusy(false); }
  }
  const canReceive = po.status === "ordered" || po.status === "partially_received";
  const setField = (id, k, v) => setReceive((r) => ({ ...r, [id]: { ...r[id], [k]: v } }));

  function submitReceive(e) {
    e.preventDefault();
    const lines = Object.entries(receive)
      .filter(([, v]) => Number(v.quantity) > 0)
      .map(([line_id, v]) => ({
        line_id, quantity: Number(v.quantity),
        batch_number: v.batch_number || null, expiry_date: v.expiry_date || null,
      }));
    if (!lines.length) { setError("Enter a quantity for at least one line."); return; }
    run(() => receivePurchaseOrder(po.id, lines));
  }

  return (
    <li className="card space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-slate-900">{po.po_number} · {po.supplier_name}</p>
          <p className="text-xs text-slate-500">Created {formatDateTime(po.created_at)} · {money(po.total_cost)}</p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_TONE[po.status] || ""}`}>
          {po.status.replace("_", " ")}
        </span>
      </div>
      <table className="w-full text-sm">
        <thead><tr className="text-left text-xs text-slate-500"><th>{tr("Item")}</th><th>{tr("Ordered")}</th><th>{tr("Received")}</th>{receive && <th>{tr("Receive now")}</th>}</tr></thead>
        <tbody>
          {po.lines.map((l) => (
            <tr key={l.id}>
              <td>{l.item_name}</td><td>{l.quantity}</td><td>{l.received_quantity}</td>
              {receive && (
                <td>
                  {l.quantity > l.received_quantity && (
                    <div className="flex flex-wrap gap-1">
                      <input aria-label={`Quantity received for ${l.item_name}`} type="number" min="0"
                        max={l.quantity - l.received_quantity} className="field-input w-20"
                        value={receive[l.id]?.quantity ?? ""} onChange={(e) => setField(l.id, "quantity", e.target.value)} />
                      <input aria-label={`Batch for ${l.item_name}`} placeholder={tr("Batch")} className="field-input w-24"
                        value={receive[l.id]?.batch_number ?? ""} onChange={(e) => setField(l.id, "batch_number", e.target.value)} />
                      <input aria-label={`Expiry for ${l.item_name}`} type="date" className="field-input w-36"
                        value={receive[l.id]?.expiry_date ?? ""} onChange={(e) => setField(l.id, "expiry_date", e.target.value)} />
                    </div>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {error && <p className="alert-error" role="alert">{error}</p>}
      <div className="flex flex-wrap gap-2">
        {po.status === "draft" && isAdmin && (
          <button type="button" className="btn-primary" disabled={busy} onClick={() => run(() => placePurchaseOrder(po.id))}>{tr("Place order")}</button>
        )}
        {po.status === "draft" && !isAdmin && <span className="text-xs text-slate-500">{tr("Waiting for an admin to place this order.")}</span>}
        {canReceive && !receive && (
          <button type="button" className="btn-secondary" onClick={() => setReceive({})}>{tr("Receive goods")}</button>
        )}
        {receive && (
          <>
            <button type="button" className="btn-primary" disabled={busy} onClick={submitReceive}>{tr("Book receipt")}</button>
            <button type="button" className="btn-secondary" onClick={() => { setReceive(null); setError(""); }}>{tr("Cancel")}</button>
          </>
        )}
        {isAdmin && (po.status === "draft" || po.status === "ordered") && !po.lines.some((l) => l.received_quantity > 0) && (
          <button type="button" className="btn-chip" disabled={busy} onClick={() => run(() => cancelPurchaseOrder(po.id))}>{tr("Cancel order")}</button>
        )}
      </div>
    </li>
  );
}

export default function Purchasing() {
  const isAdmin = getCurrentUser()?.role === "admin";
  const [suppliers, setSuppliers] = useState(null);
  const [orders, setOrders] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    Promise.all([listSuppliers(), listPurchaseOrders()])
      .then(([s, o]) => { setSuppliers(s); setOrders(o); setError(""); })
      .catch((e) => setError(errorMessage(e, "Could not load purchasing.")));
  }, []);
  useEffect(load, [load]);

  return (
    <Layout>
      <div className="mx-auto max-w-4xl space-y-5">
        <h1 className="page-title">{tr("Purchasing")}</h1>
        {error && <p className="alert-error" role="alert">{error}</p>}
        {!error && suppliers === null && <p className="empty-state">{tr("Loading...")}</p>}
        {suppliers && (
          <>
            <Suppliers suppliers={suppliers} isAdmin={isAdmin} onChanged={load} />
            <NewOrder suppliers={suppliers} onCreated={load} />
            <section className="space-y-3">
              <h2 className="font-semibold text-slate-800">{tr("Purchase orders")}</h2>
              {orders && orders.length === 0 && <p className="empty-state">{tr("No purchase orders yet.")}</p>}
              <ul className="space-y-3">
                {(orders || []).map((po) => <OrderCard key={po.id} po={po} isAdmin={isAdmin} onChanged={load} />)}
              </ul>
            </section>
          </>
        )}
      </div>
    </Layout>
  );
}
