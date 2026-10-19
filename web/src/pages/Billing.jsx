// P3.3 Billing module UI: charge master, bills, bill items, payments, claims.
// Facility-local only — server-side there is no cross-facility bill view at
// all (see routers/billing.py's module docstring), so this page never offers
// a cross-facility patient-history mode the way Ancillary.jsx does.
// Every BillItem's price is server-derived — this UI only ever sends a
// source reference + quantity, never a price.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Layout from "../components/Layout";
import SearchSelect from "../components/SearchSelect";
import {
  getCurrentUser,
  listPatients,
  listAncillaryRequests,
  getPharmacyInventory,
  getChargeMasterItems,
  createChargeMasterItem,
  updateChargeMasterItem,
  importChargeMasterFile,
  getChargeMasterTemplate,
  createBill,
  listBills,
  getBill,
  addBillItem,
  voidBillItem,
  finalizeBill,
  voidBill,
  recordPayment,
  voidPayment,
  requestRefund,
  createClaim,
  updateClaim,
  submitClaim,
  approveClaim,
  rejectClaim,
  voidClaim,
} from "../api/client";
import { formatDateTime } from "../lib/format";
import { toCents } from "../lib/money";
import { tr } from "../lib/i18n";

const BILL_STATUS_STYLE = {
  open: "bg-blue-100 text-blue-800",
  finalized: "bg-amber-100 text-amber-800",
  voided: "bg-slate-200 text-slate-600",
};
const CLAIM_STATUS_STYLE = {
  draft: "bg-slate-100 text-slate-700",
  submitted: "bg-amber-100 text-amber-800",
  approved: "bg-blue-100 text-blue-800",
  rejected: "bg-red-100 text-red-800",
  paid: "bg-green-100 text-green-800",
  void: "bg-slate-200 text-slate-500",
};

function rm(cents) {
  return `RM ${((cents || 0) / 100).toFixed(2)}`;
}

export default function Billing() {
  const user = getCurrentUser();
  // Same "front-desk role, not a clinical reader" split Ancillary.jsx draws
  // for receptionist — here it's inverted: clinician/pharmacist are the
  // READ-ONLY roles (the tender only ask that they can VIEW
  // fees/charges), admin/records_officer/receptionist do the actual
  // invoicing/payment work (the tender "frontdesk billing").
  const canWriteBills = ["admin", "records_officer", "receptionist"].includes(user?.role);
  const canManageChargeMaster = ["admin", "records_officer"].includes(user?.role);
  const canManageClaims = ["admin", "records_officer"].includes(user?.role);
  // Same receptionist-safe fallback as Ancillary.jsx::canBrowsePatients — GET
  // /patients 403s for that role by design.
  const canBrowsePatients = user?.role !== "receptionist";

  const [notice, setNotice] = useState(null);
  function showMsg(type, text) {
    setNotice({ type, text });
    setTimeout(() => setNotice(null), 5000);
  }

  const [patientId, setPatientId] = useState("");
  const [patientLabel, setPatientLabel] = useState("");

  const [bills, setBills] = useState([]);
  const [billsLoading, setBillsLoading] = useState(false);
  const [showNewBillForm, setShowNewBillForm] = useState(false);

  const [selectedBillId, setSelectedBillId] = useState(null);
  const [selectedBill, setSelectedBill] = useState(null);

  const [showChargeMaster, setShowChargeMaster] = useState(false);
  const [chargeMasterItems, setChargeMasterItems] = useState([]);

  function loadBills(pid) {
    if (!pid) return;
    setBillsLoading(true);
    listBills({ patientId: pid })
      .then(setBills)
      .catch((err) => showMsg("error", err?.response?.data?.detail || "Failed to load bills."))
      .finally(() => setBillsLoading(false));
  }

  useEffect(() => {
    if (patientId) loadBills(patientId);
    setSelectedBillId(null);
    setSelectedBill(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientId]);

  function refreshSelectedBill(billId) {
    getBill(billId)
      .then((bill) => {
        setSelectedBill(bill);
        setBills((prev) => prev.map((b) => (b.id === bill.id ? bill : b)));
      })
      .catch((err) => showMsg("error", err?.response?.data?.detail || "Failed to load bill."));
  }

  useEffect(() => {
    if (selectedBillId) refreshSelectedBill(selectedBillId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedBillId]);

  function loadChargeMaster() {
    getChargeMasterItems({ includeInactive: true }).then(setChargeMasterItems).catch(() => {});
  }

  useEffect(() => {
    if (showChargeMaster) loadChargeMaster();
  }, [showChargeMaster]);

  return (
    <Layout>
      <div className="mb-6">
        <h1 className="page-title">{tr("Billing")}</h1>
        <p className="text-sm text-slate-500">{tr("Charge master, invoices, payments, and insurance/panel claims.")}</p>
      </div>

      {notice && (
        <div
          className={`mb-4 text-sm rounded-lg px-3 py-2 flex items-start justify-between gap-3 ${
            notice.type === "success"
              ? "bg-green-50 border border-green-200 text-green-800"
              : "bg-red-50 border border-red-200 text-red-700"
          }`}
        >
          <span>{notice.text}</span>
          <button onClick={() => setNotice(null)} className="shrink-0 font-medium">✕</button>
        </div>
      )}

      <div className="card mb-6">
        <h2 className="font-semibold text-slate-800 mb-3">{tr("Patient")}</h2>
        {patientId ? (
          <div className="flex items-center justify-between border border-blue-200 bg-blue-50 rounded-lg px-3 py-2 text-sm">
            <span>{patientLabel || patientId}</span>
            <button
              type="button"
              onClick={() => {
                setPatientId("");
                setPatientLabel("");
              }}
              className="text-blue-700 hover:underline"
            >
              Change
            </button>
          </div>
        ) : (
          <PatientPicker canBrowsePatients={canBrowsePatients} onSelect={(id, label) => { setPatientId(id); setPatientLabel(label); }} />
        )}
      </div>

      {patientId && (
        <div className="card mb-6">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-slate-800">{tr("Bills")}</h2>
            {canWriteBills && (
              <button
                onClick={() => setShowNewBillForm(!showNewBillForm)}
                className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg whitespace-nowrap"
              >
                {showNewBillForm ? "Cancel" : "New bill"}
              </button>
            )}
          </div>

          {showNewBillForm && (
            <NewBillForm
              patientId={patientId}
              onCancel={() => setShowNewBillForm(false)}
              onSuccess={(bill) => {
                setShowNewBillForm(false);
                setBills((prev) => [bill, ...prev]);
                setSelectedBillId(bill.id);
                showMsg("success", "Bill created.");
              }}
              onError={(msg) => showMsg("error", msg)}
            />
          )}

          {billsLoading ? (
            <p className="text-sm text-slate-400">{tr("Loading bills…")}</p>
          ) : bills.length === 0 ? (
            <p className="text-sm text-slate-400">{tr("No bills for this patient yet.")}</p>
          ) : (
            <div className="space-y-2">
              {bills.map((bill) => (
                <button
                  key={bill.id}
                  onClick={() => setSelectedBillId(bill.id)}
                  className={`w-full text-left border rounded-lg px-3 py-2 flex items-center justify-between ${
                    selectedBillId === bill.id ? "border-blue-400 bg-blue-50" : "border-slate-200 bg-slate-50 hover:bg-slate-100"
                  }`}
                >
                  <div>
                    <span className={`text-xs px-2 py-0.5 rounded-full uppercase font-medium mr-2 ${BILL_STATUS_STYLE[bill.status] || "bg-slate-100 text-slate-800"}`}>
                      {bill.status}
                    </span>
                    <span className="text-xs text-slate-500">{formatDateTime(bill.created_at)}</span>
                  </div>
                  <div className="text-sm font-medium text-slate-800">
                    Total {rm(bill.total_cents)} · Due {rm(bill.patient_due_cents)}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {selectedBill && (
        <BillDetail
          bill={selectedBill}
          canWriteBills={canWriteBills}
          canManageClaims={canManageClaims}
          onChanged={(bill) => {
            setSelectedBill(bill);
            setBills((prev) => prev.map((b) => (b.id === bill.id ? bill : b)));
          }}
          showMsg={showMsg}
        />
      )}

      {canManageChargeMaster && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 mb-4">
          <button onClick={() => setShowChargeMaster(!showChargeMaster)} className="w-full flex items-center justify-between text-left">
            <span className="font-semibold text-slate-800">{tr("Charge Master")}</span>
            <span className="text-xs text-slate-400">{showChargeMaster ? "Hide" : "Show"}</span>
          </button>

          {showChargeMaster && (
            <div className="mt-4">
              <div className="space-y-2 mb-4">
                {chargeMasterItems.length === 0 ? (
                  <p className="text-sm text-slate-400">{tr("No charge master items yet.")}</p>
                ) : (
                  chargeMasterItems.map((item) => (
                    <div
                      key={item.id}
                      className={`flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2 ${
                        item.active ? "bg-slate-50" : "bg-slate-100 opacity-70"
                      }`}
                    >
                      <div>
                        <p className="text-sm font-medium text-slate-800">
                          {item.name}{" "}
                          {item.code && <span className="text-xs text-slate-500 font-normal">({item.code})</span>}
                          <span className="text-xs text-slate-400 font-normal ml-2">{item.category}</span>
                        </p>
                        <p className="text-xs text-slate-500">{rm(item.unit_price_cents)}</p>
                      </div>
                      <button
                        onClick={async () => {
                          try {
                            await updateChargeMasterItem(item.id, { active: !item.active });
                            loadChargeMaster();
                          } catch {
                            showMsg("error", "Failed to update charge master item.");
                          }
                        }}
                        className={`text-xs px-2 py-1 rounded border ${
                          item.active ? "border-slate-300 text-slate-600 hover:bg-slate-100" : "border-blue-300 text-blue-700 bg-blue-50"
                        }`}
                      >
                        {item.active ? "Deactivate" : "Reactivate"}
                      </button>
                    </div>
                  ))
                )}
              </div>
              <ChargeMasterImport onDone={(n) => { loadChargeMaster(); showMsg("success", `${n} charge master items imported.`); }} />
              <ChargeMasterAddForm onSuccess={() => { loadChargeMaster(); showMsg("success", "Charge master item added."); }} onError={(msg) => showMsg("error", msg)} />
            </div>
          )}
        </div>
      )}
    </Layout>
  );
}

function PatientPicker({ canBrowsePatients, onSelect }) {
  const [search, setSearch] = useState("");
  const [manualId, setManualId] = useState("");
  const [patients, setPatients] = useState([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (canBrowsePatients && !loaded) {
      listPatients({ limit: 200 }).then((data) => { setPatients(data); setLoaded(true); }).catch(() => {});
    }
  }, [canBrowsePatients, loaded]);

  if (!canBrowsePatients) {
    // Receptionist has no `patients` page access (GET /patients 403s for
    // that role by design) — same fallback as Ancillary.jsx's OrderForm.
    return (
      <div className="flex gap-2">
        <input
          type="text"
          placeholder={tr("Patient ID (from Reception check-in)")}
          className="flex-1 border border-slate-300 rounded-lg px-3 py-2 text-sm"
          value={manualId}
          onChange={(e) => setManualId(e.target.value.trim())}
        />
        <button
          type="button"
          disabled={!manualId}
          onClick={() => onSelect(manualId, manualId)}
          className="text-sm bg-blue-800 text-white px-3 py-2 rounded-lg disabled:opacity-50"
        >
          Select
        </button>
      </div>
    );
  }

  const filtered = patients
    .filter(
      (p) =>
        p.full_name?.toLowerCase().includes(search.toLowerCase()) ||
        p.national_id?.toLowerCase().includes(search.toLowerCase())
    )
    .slice(0, 10);

  return (
    <div>
      <input
        type="text"
        placeholder={tr("Search by name or NRIC…")}
        className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm mb-1"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      {search && filtered.length > 0 && (
        <ul className="border border-slate-200 rounded-lg divide-y max-h-40 overflow-y-auto">
          {filtered.map((p) => (
            <li key={p.id} onClick={() => onSelect(p.id, p.full_name)} className="px-3 py-2 text-sm hover:bg-slate-50 cursor-pointer">
              {p.full_name} <span className="text-xs text-slate-500 ml-1">{p.national_id}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function NewBillForm({ patientId, onCancel, onSuccess, onError }) {
  const [encounterId, setEncounterId] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const bill = await createBill({ patient_id: patientId, encounter_id: encounterId || undefined });
      onSuccess(bill);
    } catch (err) {
      onError(err?.response?.data?.detail || "Failed to create bill.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="border border-slate-200 rounded-lg p-4 mb-4 grid gap-3 bg-slate-50">
      <div>
        <label className="field-label">{tr("Encounter ID (optional)")}</label>
        <input
          type="text"
          className="field-input"
          value={encounterId}
          onChange={(e) => setEncounterId(e.target.value.trim())}
          placeholder={tr("Link this bill to a visit, if any")}
        />
      </div>
      <div className="flex gap-2">
        <button disabled={busy} className="btn-primary">{tr("Create Bill")}</button>
        <button type="button" onClick={onCancel} className="text-sm border border-slate-300 px-4 py-2 rounded-lg">{tr("Cancel")}</button>
      </div>
    </form>
  );
}

function BillDetail({ bill, canWriteBills, canManageClaims, onChanged, showMsg }) {
  const [showAddItem, setShowAddItem] = useState(false);
  const [showRecordPayment, setShowRecordPayment] = useState(false);
  const [showAddClaim, setShowAddClaim] = useState(false);

  async function handleVoidItem(itemId) {
    const reason = prompt("Reason for voiding this line item:");
    if (!reason) return;
    try {
      onChanged(await voidBillItem(bill.id, itemId, reason));
      showMsg("success", "Line item voided.");
    } catch (err) {
      showMsg("error", err?.response?.data?.detail || "Failed to void item.");
    }
  }

  async function handleRefund(payment) {
    const max = (payment.amount_cents / 100).toFixed(2);
    const amount = window.prompt(`Refund how much (RM)? Up to ${max} of this payment.`, max);
    if (amount === null) return;
    const cents = toCents(amount);
    if (cents === null) return showMsg("error", "Enter an amount in RM, for example 25.00.");
    const reason = window.prompt("Reason for the refund:");
    if (!reason || !reason.trim()) return;
    try {
      await requestRefund(payment.id, { amount_cents: cents, reason });
      showMsg("success", "Refund requested. An admin must approve it in Cashier > Refunds.");
    } catch (err) {
      showMsg("error", err?.response?.data?.detail || "Failed to request the refund.");
    }
  }

  async function handleVoidPayment(paymentId) {
    const reason = prompt("Reason for voiding this payment:");
    if (!reason) return;
    try {
      onChanged(await voidPayment(paymentId, reason));
      showMsg("success", "Payment voided.");
    } catch (err) {
      showMsg("error", err?.response?.data?.detail || "Failed to void payment.");
    }
  }

  async function handleFinalize() {
    try {
      onChanged(await finalizeBill(bill.id));
      showMsg("success", "Bill finalized.");
    } catch (err) {
      showMsg("error", err?.response?.data?.detail || "Failed to finalize bill.");
    }
  }

  async function handleVoidBill() {
    const reason = prompt("Reason for voiding this bill:");
    if (!reason) return;
    try {
      onChanged(await voidBill(bill.id, reason));
      showMsg("success", "Bill voided.");
    } catch (err) {
      showMsg("error", err?.response?.data?.detail || "Failed to void bill.");
    }
  }

  async function handleClaimAction(claimId, action, needsReason) {
    let reason;
    if (needsReason) {
      reason = prompt("Reason:");
      if (!reason) return;
    }
    try {
      const fn = { submit: submitClaim, approve: approveClaim, reject: rejectClaim, void: voidClaim }[action];
      await fn(claimId, needsReason ? reason : undefined);
      refreshBill(bill.id, onChanged, showMsg);
      showMsg("success", "Claim updated.");
    } catch (err) {
      showMsg("error", err?.response?.data?.detail || "Failed to update claim.");
    }
  }

  const activeItems = bill.items.filter((i) => !i.voided_at);
  const voidedItems = bill.items.filter((i) => i.voided_at);
  const activePayments = bill.payments.filter((p) => !p.voided_at);
  const voidedPayments = bill.payments.filter((p) => p.voided_at);

  return (
    <div className="card mb-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-semibold text-slate-800">
            Bill{" "}
            <span className={`text-xs px-2 py-0.5 rounded-full uppercase font-medium ml-1 ${BILL_STATUS_STYLE[bill.status] || "bg-slate-100 text-slate-800"}`}>
              {bill.status}
            </span>
          </h2>
          <p className="text-xs text-slate-500">
            {bill.patient_full_name || bill.patient_id}
            <Link to={`/patients/${bill.patient_id}`} className="ml-2 text-blue-700 hover:underline">{tr("View Record")}</Link>
            <span className="ml-2">· Opened {formatDateTime(bill.created_at)} by {bill.created_by_name}</span>
            {bill.encounter_id && <span className="ml-2">· Encounter {bill.encounter_id}</span>}
          </p>
        </div>
        {canWriteBills && bill.status === "open" && (
          <div className="flex gap-2">
            <button onClick={handleFinalize} className="text-xs bg-amber-700 hover:bg-amber-600 text-white px-3 py-1.5 rounded-lg">{tr("Finalize")}</button>
            <button onClick={handleVoidBill} className="text-xs border border-slate-300 hover:bg-slate-100 text-slate-700 px-3 py-1.5 rounded-lg">{tr("Void bill")}</button>
          </div>
        )}
        {canWriteBills && bill.status === "finalized" && (
          <button onClick={handleVoidBill} className="text-xs border border-slate-300 hover:bg-slate-100 text-slate-700 px-3 py-1.5 rounded-lg">{tr("Void bill")}</button>
        )}
      </div>

      {bill.voided_reason && (
        <p className="text-xs text-slate-500 mb-3 italic">Voided: {bill.voided_reason}</p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 mb-4 text-center">
        <TotalTile label={tr("Total")} value={rm(bill.total_cents)} />
        <TotalTile label={tr("Paid")} value={rm(bill.paid_cents)} tone="green" />
        <TotalTile label={tr("Claimed (pending)")} value={rm(bill.claimed_pending_cents)} tone="amber" />
        <TotalTile label={tr("Amount Due")} value={rm(bill.amount_due_cents)} />
        <TotalTile label={tr("Patient Due Now")} value={rm(bill.patient_due_cents)} tone="blue" />
      </div>

      <div className="mb-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-700">{tr("Line Items")}</h3>
          {canWriteBills && bill.status === "open" && (
            <button onClick={() => setShowAddItem(!showAddItem)} className="text-xs bg-blue-800 text-white px-3 py-1 rounded-lg">
              {showAddItem ? "Cancel" : "Add item"}
            </button>
          )}
        </div>
        {showAddItem && (
          <AddItemForm
            bill={bill}
            onCancel={() => setShowAddItem(false)}
            onSuccess={(updated) => { setShowAddItem(false); onChanged(updated); showMsg("success", "Line item added."); }}
            onError={(msg) => showMsg("error", msg)}
          />
        )}
        {activeItems.length === 0 && voidedItems.length === 0 ? (
          <p className="text-sm text-slate-400">{tr("No line items yet.")}</p>
        ) : (
          <div className="space-y-1">
            {[...activeItems, ...voidedItems].map((item) => (
              <div key={item.id} className={`flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2 text-sm ${item.voided_at ? "bg-slate-50 opacity-60" : "bg-white"}`}>
                <div>
                  <span className="font-medium text-slate-800">{item.description}</span>
                  <span className="text-xs text-slate-500 ml-2">x{item.quantity}</span>
                  {item.voided_at && <span className="text-xs text-red-600 ml-2">Voided: {item.voided_reason}</span>}
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-medium text-slate-800">{rm(item.amount_cents)}</span>
                  {canWriteBills && !item.voided_at && bill.status !== "voided" && (
                    <button onClick={() => handleVoidItem(item.id)} className="text-xs text-red-700 hover:underline">{tr("Void")}</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mb-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-700">{tr("Payments")}</h3>
          {canWriteBills && bill.status !== "voided" && (
            <button onClick={() => setShowRecordPayment(!showRecordPayment)} className="text-xs bg-blue-800 text-white px-3 py-1 rounded-lg">
              {showRecordPayment ? "Cancel" : "Record payment"}
            </button>
          )}
        </div>
        {showRecordPayment && (
          <RecordPaymentForm
            bill={bill}
            onCancel={() => setShowRecordPayment(false)}
            onSuccess={(updated) => { setShowRecordPayment(false); onChanged(updated); showMsg("success", "Payment recorded."); }}
            onError={(msg) => showMsg("error", msg)}
          />
        )}
        {activePayments.length === 0 && voidedPayments.length === 0 ? (
          <p className="text-sm text-slate-400">{tr("No payments recorded yet.")}</p>
        ) : (
          <div className="space-y-1">
            {[...activePayments, ...voidedPayments].map((p) => (
              <div key={p.id} className={`flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2 text-sm ${p.voided_at ? "bg-slate-50 opacity-60" : "bg-white"}`}>
                <div>
                  <span className="font-medium text-slate-800">{p.method}</span>
                  {p.reference_no && <span className="text-xs text-slate-500 ml-2">Ref: {p.reference_no}</span>}
                  <span className="text-xs text-slate-500 ml-2">{formatDateTime(p.received_at)} · {p.received_by_name}</span>
                  {p.voided_at && <span className="text-xs text-red-600 ml-2">Voided: {p.voided_reason}</span>}
                </div>
                <div className="flex items-center gap-3">
                  <span className="font-medium text-slate-800">{rm(p.amount_cents)}</span>
                  {canWriteBills && !p.voided_at && ["cash", "card", "online", "other"].includes(p.method) && (
                    <button onClick={() => handleRefund(p)} className="text-xs text-blue-800 hover:underline">{tr("Refund")}</button>
                  )}
                  {canWriteBills && !p.voided_at && p.method !== "online" && (
                    <button onClick={() => handleVoidPayment(p.id)} className="text-xs text-red-700 hover:underline">{tr("Void")}</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-700">{tr("Insurance / Panel Claims")}</h3>
          {canManageClaims && bill.status !== "voided" && (
            <button onClick={() => setShowAddClaim(!showAddClaim)} className="text-xs bg-blue-800 text-white px-3 py-1 rounded-lg">
              {showAddClaim ? "Cancel" : "New claim"}
            </button>
          )}
        </div>
        {showAddClaim && (
          <AddClaimForm
            bill={bill}
            onCancel={() => setShowAddClaim(false)}
            onSuccess={() => { setShowAddClaim(false); refreshBill(bill.id, onChanged, showMsg); showMsg("success", "Claim created."); }}
            onError={(msg) => showMsg("error", msg)}
          />
        )}
        {bill.claims.length === 0 ? (
          <p className="text-sm text-slate-400">{tr("No claims on this bill.")}</p>
        ) : (
          <div className="space-y-2">
            {bill.claims.map((claim) => (
              <ClaimRow
                key={claim.id}
                claim={claim}
                canManageClaims={canManageClaims}
                onAction={handleClaimAction}
                onUpdated={() => refreshBill(bill.id, onChanged, showMsg)}
                onError={(msg) => showMsg("error", msg)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function refreshBill(billId, onChanged, showMsg) {
  getBill(billId).then(onChanged).catch((err) => showMsg("error", err?.response?.data?.detail || "Failed to refresh bill."));
}

function TotalTile({ label, value, tone }) {
  const toneClass =
    tone === "green" ? "bg-green-50 border-green-200 text-green-800" :
    tone === "amber" ? "bg-amber-50 border-amber-200 text-amber-800" :
    tone === "blue" ? "bg-blue-50 border-blue-200 text-blue-800" :
    "bg-slate-50 border-slate-200 text-slate-800";
  return (
    <div className={`border rounded-lg p-2 ${toneClass}`}>
      <p className="text-sm font-bold">{value}</p>
      <p className="text-[10px] uppercase tracking-wide opacity-80">{label}</p>
    </div>
  );
}

function AddItemForm({ bill, onCancel, onSuccess, onError }) {
  const [sourceType, setSourceType] = useState("charge_master");
  const [chargeMasterItems, setChargeMasterItems] = useState([]);
  const [ancillaryRequests, setAncillaryRequests] = useState([]);
  const [pharmacyItems, setPharmacyItems] = useState([]);
  const [selectedId, setSelectedId] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getChargeMasterItems({ includeInactive: false }).then(setChargeMasterItems).catch(() => {});
    listAncillaryRequests({ patientId: bill.patient_id, status: "signed_off" }).then(setAncillaryRequests).catch(() => {});
    getPharmacyInventory().then(setPharmacyItems).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!selectedId) {
      onError("Select an item to bill.");
      return;
    }
    setBusy(true);
    try {
      const body = { source_type: sourceType, quantity: Number(quantity) || 1 };
      if (sourceType === "charge_master") body.charge_master_item_id = selectedId;
      if (sourceType === "service_request") body.service_request_id = selectedId;
      if (sourceType === "pharmacy_item") body.medicine_inventory_item_id = selectedId;
      const updated = await addBillItem(bill.id, body);
      onSuccess(updated);
    } catch (err) {
      onError(err?.response?.data?.detail || "Failed to add line item.");
      setBusy(false);
    }
  }

  const options =
    sourceType === "charge_master"
      ? chargeMasterItems.map((i) => ({ id: i.id, label: `${i.name} (${rm(i.unit_price_cents)})` }))
      : sourceType === "service_request"
      ? ancillaryRequests.map((r) => ({ id: r.id, label: `${r.catalog_item_name} — ${rm(r.unit_price_cents)}` }))
      : pharmacyItems.map((i) => ({ id: i.id, label: i.drug_name }));

  return (
    <form onSubmit={handleSubmit} className="border border-slate-200 rounded-lg p-4 mb-3 grid gap-3 bg-slate-50">
      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="field-label">{tr("Source")}</label>
          <select
            className="field-input"
            value={sourceType}
            onChange={(e) => { setSourceType(e.target.value); setSelectedId(""); }}
          >
            <option value="charge_master">{tr("Charge master item")}</option>
            <option value="service_request">{tr("Signed-off ancillary result")}</option>
            <option value="pharmacy_item">{tr("Pharmacy inventory item")}</option>
          </select>
        </div>
        <div>
          <label htmlFor="bill-item" className="field-label">{tr("Item")}</label>
          <SearchSelect
            id="bill-item" required options={options} value={selectedId} onChange={setSelectedId}
            placeholder={`Type to search ${options.length} item${options.length === 1 ? "" : "s"}`}
          />
        </div>
        <div>
          <label className="field-label">{tr("Quantity")}</label>
          <input type="number" min="1" step="1" className="field-input" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </div>
      </div>
      <div className="flex gap-2">
        <button disabled={busy} className="btn-primary">{tr("Add Item")}</button>
        <button type="button" onClick={onCancel} className="text-sm border border-slate-300 px-4 py-2 rounded-lg">{tr("Cancel")}</button>
      </div>
    </form>
  );
}

function RecordPaymentForm({ bill, onCancel, onSuccess, onError }) {
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");
  const [referenceNo, setReferenceNo] = useState("");
  const [claimId, setClaimId] = useState("");
  const [busy, setBusy] = useState(false);

  const settleableClaims = bill.claims.filter((c) => c.status === "submitted" || c.status === "approved");

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const body = {
        amount_cents: Math.round(parseFloat(amount || 0) * 100),
        method,
        reference_no: referenceNo || undefined,
        claim_id: claimId || undefined,
      };
      const updated = await recordPayment(bill.id, body);
      onSuccess(updated);
    } catch (err) {
      onError(err?.response?.data?.detail || "Failed to record payment.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="border border-slate-200 rounded-lg p-4 mb-3 grid gap-3 bg-slate-50">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="field-label">Amount (RM)</label>
          <input required type="number" step="0.01" min="0.01" className="field-input" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div>
          <label className="field-label">{tr("Method")}</label>
          <select className="field-input" value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="cash">{tr("Cash")}</option>
            <option value="card">{tr("Card")}</option>
            <option value="insurance">{tr("Insurance")}</option>
            <option value="panel">{tr("Panel")}</option>
            <option value="other">{tr("Other")}</option>
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="field-label">{tr("Reference No. (optional)")}</label>
          <input type="text" className="field-input" value={referenceNo} onChange={(e) => setReferenceNo(e.target.value)} />
        </div>
        {(method === "insurance" || method === "panel") && settleableClaims.length > 0 && (
          <div>
            <label className="field-label">{tr("Settles Claim (optional)")}</label>
            <select className="field-input" value={claimId} onChange={(e) => setClaimId(e.target.value)}>
              <option value="">{tr("-- none --")}</option>
              {settleableClaims.map((c) => (
                <option key={c.id} value={c.id}>{c.payer_name} ({rm(c.claim_amount_cents)})</option>
              ))}
            </select>
          </div>
        )}
      </div>
      <div className="flex gap-2">
        <button disabled={busy} className="btn-primary">{tr("Record Payment")}</button>
        <button type="button" onClick={onCancel} className="text-sm border border-slate-300 px-4 py-2 rounded-lg">{tr("Cancel")}</button>
      </div>
    </form>
  );
}

function AddClaimForm({ bill, onCancel, onSuccess, onError }) {
  const [payerName, setPayerName] = useState("");
  const [amount, setAmount] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await createClaim(bill.id, {
        payer_name: payerName,
        claim_amount_cents: Math.round(parseFloat(amount || 0) * 100),
        notes: notes || undefined,
      });
      onSuccess();
    } catch (err) {
      onError(err?.response?.data?.detail || "Failed to create claim.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="border border-slate-200 rounded-lg p-4 mb-3 grid gap-3 bg-slate-50">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="field-label">Payer (insurer/panel)</label>
          <input required type="text" className="field-input" value={payerName} onChange={(e) => setPayerName(e.target.value)} />
        </div>
        <div>
          <label className="field-label">{tr("Claim Amount (RM)")}</label>
          <input required type="number" step="0.01" min="0.01" className="field-input" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <p className="text-[10px] text-slate-400 mt-1">{tr("May cover part of the bill (copay) — the rest stays owed by the patient until this claim settles.")}</p>
        </div>
      </div>
      <div>
        <label className="field-label">Notes (optional)</label>
        <textarea rows={2} className="field-input" value={notes} onChange={(e) => setNotes(e.target.value)}></textarea>
      </div>
      <div className="flex gap-2">
        <button disabled={busy} className="btn-primary">{tr("Create Claim")}</button>
        <button type="button" onClick={onCancel} className="text-sm border border-slate-300 px-4 py-2 rounded-lg">{tr("Cancel")}</button>
      </div>
    </form>
  );
}

function ClaimRow({ claim, canManageClaims, onAction, onUpdated, onError }) {
  const [editing, setEditing] = useState(false);
  const [amount, setAmount] = useState((claim.claim_amount_cents / 100).toFixed(2));
  const [payerName, setPayerName] = useState(claim.payer_name);
  const [busy, setBusy] = useState(false);

  async function handleSaveEdit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await updateClaim(claim.id, { payer_name: payerName, claim_amount_cents: Math.round(parseFloat(amount || 0) * 100) });
      setEditing(false);
      onUpdated();
    } catch (err) {
      onError(err?.response?.data?.detail || "Failed to update claim.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border border-slate-200 rounded-lg p-3 bg-slate-50">
      <div className="flex items-center justify-between">
        <div>
          <span className="font-medium text-slate-800">{claim.payer_name}</span>
          <span className={`text-xs px-2 py-0.5 rounded-full uppercase font-medium ml-2 ${CLAIM_STATUS_STYLE[claim.status] || "bg-slate-100 text-slate-800"}`}>
            {claim.status}
          </span>
          <span className="text-xs text-slate-500 ml-2">{rm(claim.claim_amount_cents)}</span>
        </div>
        {canManageClaims && claim.status === "draft" && !editing && (
          <button onClick={() => setEditing(true)} className="text-xs text-blue-700 hover:underline">{tr("Edit")}</button>
        )}
      </div>
      {claim.notes && <p className="text-xs text-slate-600 mt-1 italic">{claim.notes}</p>}

      {editing ? (
        <form onSubmit={handleSaveEdit} className="mt-2 flex flex-wrap items-end gap-2">
          <input type="text" className="border border-slate-300 rounded px-2 py-1 text-sm" value={payerName} onChange={(e) => setPayerName(e.target.value)} />
          <input type="number" step="0.01" min="0.01" className="w-28 border border-slate-300 rounded px-2 py-1 text-sm" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <button disabled={busy} className="text-xs bg-blue-800 text-white px-3 py-1 rounded disabled:opacity-50">{tr("Save")}</button>
          <button type="button" onClick={() => setEditing(false)} className="text-xs border border-slate-300 px-3 py-1 rounded">{tr("Cancel")}</button>
        </form>
      ) : (
        canManageClaims && (
          <div className="flex gap-2 mt-2">
            {claim.status === "draft" && (
              <button onClick={() => onAction(claim.id, "submit", false)} className="text-xs bg-amber-700 hover:bg-amber-600 text-white px-2 py-1 rounded">{tr("Submit")}</button>
            )}
            {claim.status === "submitted" && (
              <>
                <button onClick={() => onAction(claim.id, "approve", false)} className="text-xs bg-blue-700 hover:bg-blue-600 text-white px-2 py-1 rounded">{tr("Approve")}</button>
                <button onClick={() => onAction(claim.id, "reject", true)} className="text-xs border border-red-300 text-red-700 hover:bg-red-50 px-2 py-1 rounded">{tr("Reject")}</button>
              </>
            )}
            {claim.status === "approved" && (
              <>
                {/* No standalone "mark paid" action -- a claim only moves to
                    "paid" via a linked Payment (record one below with method
                    insurance/panel and this claim selected as "Settles
                    Claim"), so "paid" always has a real amount behind it. */}
                <span className="text-xs text-slate-400 italic self-center">{tr("Record a settling payment below to mark this paid")}</span>
                <button onClick={() => onAction(claim.id, "reject", true)} className="text-xs border border-red-300 text-red-700 hover:bg-red-50 px-2 py-1 rounded">{tr("Reject")}</button>
              </>
            )}
            {["draft", "submitted", "approved", "rejected"].includes(claim.status) && (
              <button onClick={() => onAction(claim.id, "void", true)} className="text-xs border border-slate-300 text-slate-600 hover:bg-slate-100 px-2 py-1 rounded">{tr("Void")}</button>
            )}
          </div>
        )
      )}
    </div>
  );
}

export function ChargeMasterImport({ onDone }) {
  const [file, setFile] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(f, dryRun) {
    setBusy(true);
    setError("");
    try {
      const r = await importChargeMasterFile(f, dryRun);
      if (dryRun) {
        setResult(r);
      } else {
        setFile(null);
        setResult(null);
        onDone(r.added);
      }
    } catch (err) {
      setResult(null);
      setError(err?.response?.data?.detail || "The file could not be checked.");
    } finally {
      setBusy(false);
    }
  }

  async function downloadTemplate() {
    try {
      const url = URL.createObjectURL(await getChargeMasterTemplate());
      const a = document.createElement("a");
      a.href = url;
      a.download = "charge-master-template.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Could not download the template.");
    }
  }

  return (
    <div className="mt-2 pt-4 border-t border-slate-200 mb-4">
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="cm-import-file" className="text-sm font-medium text-slate-800">{tr("Import from Excel")}</label>
        <input
          id="cm-import-file"
          type="file"
          accept=".xlsx"
          disabled={busy}
          className="text-sm"
          onChange={(e) => {
            const f = e.target.files?.[0] || null;
            setFile(f);
            setResult(null);
            setError("");
            if (f) run(f, true);
          }}
        />
        <button type="button" onClick={downloadTemplate} className="text-sm text-blue-700 underline">
          Download template
        </button>
      </div>

      <details className="mt-2 text-sm text-slate-600">
        <summary className="cursor-pointer text-blue-700">{tr("What the file must look like")}</summary>
        <div className="mt-2 space-y-1">
          <p>{tr("First row holds the column names. Order does not matter.")}</p>
          <ul className="list-disc ml-5">
            <li><b>{tr("category")}</b> {tr("(required): consultation or misc")}</li>
            <li><b>{tr("name")}</b> (required): up to 255 characters</li>
            <li><b>{tr("price")}</b> (required): RM, up to 2 decimals</li>
            <li><b>{tr("code")}</b>{tr(": optional, up to 64 characters")}</li>
            <li><b>{tr("active")}</b>{tr(": yes or no, blank means yes")}</li>
          </ul>
          <p>
            Rows are only added to your facility. A row with the same category and code (or the same
            category and name when a code is missing) is skipped, never overwritten. If any row has an
            error, nothing is added.
          </p>
        </div>
      </details>

      {busy && <p className="mt-2 text-sm text-slate-500" role="status">Checking {file?.name}...</p>}
      {error && <p className="mt-2 text-sm text-red-700" role="alert">{error}</p>}

      {result && !busy && (
        <div className="mt-3 text-sm" role="status">
          {result.error_count > 0 ? (
            <>
              <p className="text-red-700 font-medium">
                {result.error_count} row(s) have problems. Nothing was added. Fix the file and choose it again.
              </p>
              <ul className="mt-1 list-disc ml-5 text-slate-700">
                {result.errors.map((e) => (
                  <li key={e.row}>Row {e.row}: {e.message}</li>
                ))}
              </ul>
            </>
          ) : (
            <>
              <p className="text-slate-800">
                {result.would_add} new item(s), {result.skipped_duplicates} duplicate(s) will be skipped.
              </p>
              {result.preview.length > 0 && (
                <ul className="mt-1 text-slate-600">
                  {result.preview.map((r) => (
                    <li key={r.row}>{r.name} ({r.category}) {rm(r.unit_price_cents)}</li>
                  ))}
                  {result.would_add > result.preview.length && <li>and {result.would_add - result.preview.length} more</li>}
                </ul>
              )}
              <button
                type="button"
                disabled={busy || result.would_add === 0}
                onClick={() => run(file, false)}
                className="mt-2 bg-slate-800 text-white text-sm px-3 py-1 rounded disabled:opacity-50"
              >
                {result.would_add === 0 ? "Nothing new to add" : `Add ${result.would_add} items`}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ChargeMasterAddForm({ onSuccess, onError }) {
  const [category, setCategory] = useState("consultation");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await createChargeMasterItem({ category, name, code, unit_price_cents: Math.round(parseFloat(price || 0) * 100) });
      onSuccess();
      setName("");
      setCode("");
      setPrice("");
    } catch (err) {
      onError(err?.response?.data?.detail || "Failed to add charge master item.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 pt-4 border-t border-slate-200 flex flex-wrap items-end gap-3">
      <div>
        <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">{tr("Category")}</label>
        <select className="w-36 border border-slate-300 rounded px-2 py-1 text-sm" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="consultation">{tr("Consultation")}</option>
          <option value="misc">{tr("Misc / Admin")}</option>
        </select>
      </div>
      <div>
        <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">{tr("Item Name")}</label>
        <input required type="text" className="w-48 border border-slate-300 rounded px-2 py-1 text-sm" value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div>
        <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">Code (Opt)</label>
        <input type="text" className="w-24 border border-slate-300 rounded px-2 py-1 text-sm" value={code} onChange={(e) => setCode(e.target.value)} />
      </div>
      <div>
        <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">Price (RM)</label>
        <input required type="number" step="0.01" min="0" className="w-24 border border-slate-300 rounded px-2 py-1 text-sm" value={price} onChange={(e) => setPrice(e.target.value)} />
      </div>
      <button disabled={busy} className="bg-slate-800 text-white text-sm px-3 py-1 rounded disabled:opacity-50 h-[30px]">{tr("Add Item")}</button>
    </form>
  );
}
