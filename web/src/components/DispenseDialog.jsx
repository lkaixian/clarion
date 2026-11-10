import { useEffect, useState } from "react";
import { getPharmacyInventory, dispenseMedicine, errorMessage } from "../api/client";
import { sigQuantity } from "../lib/sig";
import { tr } from "../lib/i18n";

const money = (cents) => `RM ${(cents / 100).toFixed(2)}`;
// Billed at the item's procurement unit_cost (no sale-price column yet), same as billing add-item.
const unitCents = (item) => Math.round(Number(item.unit_cost) * 100);

export default function DispenseDialog({ patientId, medication, onClose }) {
  const [items, setItems] = useState(null);
  const [itemId, setItemId] = useState("");
  const [qty, setQty] = useState(sigQuantity(medication.dosage, medication.frequency)?.qty || 1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(null);

  useEffect(() => {
    getPharmacyInventory({ q: medication.drug_name })
      .then((r) => { setItems(r); setItemId(r[0]?.id || ""); })
      .catch((e) => { setItems([]); setError(errorMessage(e)); });
  }, [medication.drug_name]);

  const item = (items || []).find((i) => i.id === itemId);
  const priced = item && item.unit_cost != null;
  const n = Number(qty);
  const valid = Number.isInteger(n) && n >= 1 && n <= 10000;

  const confirm = async () => {
    setBusy(true);
    setError("");
    try {
      setDone(await dispenseMedicine({
        patient_id: patientId, medicine_inventory_item_id: itemId, quantity: n,
        medication_statement_id: medication.id,
      }));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="bg-white rounded-xl p-6 max-w-md w-full" role="dialog" aria-modal="true" aria-label={tr("Dispense")}>
        <h3 className="font-semibold text-slate-800 mb-3">{tr("Dispense")}: {medication.drug_name}</h3>
        {done ? (
          <>
            <p className="text-sm text-green-700">{tr("Dispensed and added to the patient's bill")}: {money(done.amount_cents)}</p>
            <p className="text-xs text-slate-500">{tr("Stock on hand")}: {done.quantity_on_hand}</p>
            <button onClick={onClose} className="btn-primary mt-4">{tr("Close")}</button>
          </>
        ) : (
          <>
            {items === null && <p className="text-sm text-slate-500">{tr("Loading...")}</p>}
            {items && items.length === 0 && <p className="text-sm text-slate-500">{tr("No matching item in the pharmacy inventory.")}</p>}
            {items && items.length > 0 && (
              <div className="space-y-3">
                <div>
                  <label className="field-label" htmlFor="dispense-item">{tr("Inventory item")}</label>
                  <select id="dispense-item" className="field-input" value={itemId} onChange={(e) => setItemId(e.target.value)}>
                    {items.map((i) => <option key={i.id} value={i.id}>{i.drug_name} ({i.quantity_on_hand} {i.unit})</option>)}
                  </select>
                </div>
                <div>
                  <label className="field-label" htmlFor="dispense-qty">{tr("Quantity")}</label>
                  <input id="dispense-qty" type="number" min="1" max="10000" className="field-input" value={qty} onChange={(e) => setQty(e.target.value)} />
                </div>
                {priced
                  ? <p className="text-sm">{tr("Price")}: {money(unitCents(item))} × {valid ? n : "?"} = <b>{valid ? money(n * unitCents(item)) : "-"}</b></p>
                  : <p className="text-sm text-red-600">{tr("This inventory item has no price set")}</p>}
              </div>
            )}
            {error && <div role="alert" className="alert-error mt-3">{error}</div>}
            <div className="flex gap-2 justify-end mt-4">
              <button onClick={onClose} className="btn-chip" disabled={busy}>{tr("Cancel")}</button>
              <button onClick={confirm} className="btn-primary" disabled={busy || !item || !priced || !valid}>
                {busy ? tr("Dispensing...") : tr("Confirm dispense")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
