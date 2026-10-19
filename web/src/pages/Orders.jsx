import { useCallback, useEffect, useState } from "react";
import Layout from "../components/Layout";
import { OrderRow, ORDER_TYPES } from "../components/PatientOrders";
import { listOrders, getCurrentUser, errorMessage } from "../api/client";
import { tr } from "../lib/i18n";

const STATUSES = [["ordered", "Open"], ["completed", "Completed"], ["cancelled", "Cancelled"]];

// The facility's worklist: pharmacists see drug orders to dispense, clinicians see everything.
export default function Orders() {
  const user = getCurrentUser();
  const [status, setStatus] = useState("ordered");
  const [type, setType] = useState("");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setRows(null);
    setError("");
    listOrders({ status, orderType: type }).then(setRows).catch((e) => setError(errorMessage(e, "Could not load orders.")));
  }, [status, type]);
  useEffect(load, [load]);

  return (
    <Layout>
      <div className="mx-auto max-w-4xl space-y-4">
        <h1 className="page-title">{tr("Orders")}</h1>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor="ow-status" className="field-label">{tr("Status")}</label>
            <select id="ow-status" className="field-input" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          {user?.role !== "pharmacist" && (
            <div>
              <label htmlFor="ow-type" className="field-label">{tr("Type")}</label>
              <select id="ow-type" className="field-input" value={type} onChange={(e) => setType(e.target.value)}>
                <option value="">{tr("All types")}</option>
                {ORDER_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
          )}
          <button type="button" className="btn-secondary" onClick={load}>{tr("Refresh")}</button>
        </div>
        <section className="card">
          {error && <p className="alert-error" role="alert">{error}</p>}
          {!error && rows === null && <p className="empty-state">{tr("Loading...")}</p>}
          {rows && rows.length === 0 && <p className="empty-state">{tr("Nothing here.")}</p>}
          {rows && rows.length > 0 && (
            <ul>
              {rows.map((o) => (
                <OrderRow
                  key={o.id} order={o} showPatient onChanged={load}
                  canCancel={user?.role === "admin" || o.ordered_by === user?.id}
                  canComplete={
                    user?.role === "admin" ? o.ordered_by !== user?.id || o.order_type !== "drug"
                      : user?.role === "pharmacist" ? o.order_type === "drug"
                      : o.order_type !== "drug"
                  }
                />
              ))}
            </ul>
          )}
        </section>
      </div>
    </Layout>
  );
}
