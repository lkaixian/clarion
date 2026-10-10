// P3.3 Billing module UI: charge master, bills, bill items, payments, claims.
// Facility-local only — server-side there is no cross-facility bill view at
// all (see routers/billing.py's module docstring), so this page never offers
// a cross-facility patient-history mode the way Ancillary.jsx does.
// Every BillItem's price is server-derived — this UI only ever sends a
// source reference + quantity, never a price.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Layout from "../components/Layout";
import {
  getCurrentUser,
  listPatients,
  listAncillaryRequests,
  getPharmacyInventory,
  getChargeMasterItems,
  createChargeMasterItem,
  updateChargeMasterItem,
  createBill,
  listBills,
  getBill,
  addBillItem,
  voidBillItem,
  finalizeBill,
  voidBill,
  recordPayment,
  voidPayment,
  createClaim,
  updateClaim,
  submitClaim,
  approveClaim,
  rejectClaim,
  voidClaim,
} from "../api/client";
import { formatDateTime } from "../lib/format";

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
        <h1 className="page-title">Billing</h1>
        <p className="text-sm text-slate-500">Charge master, invoices, payments, and insurance/panel claims.</p>
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
        <h2 className="font-semibold text-slate-800 mb-3">Patient</h2>
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
            <h2 className="font-semibold text-slate-800">Bills</h2>
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
            <p className="text-sm text-slate-400">Loading bills…</p>
          ) : bills.length === 0 ? (
            <p className="text-sm text-slate-400">No bills for this patient yet.</p>
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
            <span className="font-semibold text-slate-800">Charge Master</span>
            <span className="text-xs text-slate-400">{showChargeMaster ? "Hide" : "Show"}</span>
          </button>

          {showChargeMaster && (
            <div className="mt-4">
              <div className="space-y-2 mb-4">
                {chargeMasterItems.length === 0 ? (
                  <p className="text-sm text-slate-400">No charge master items yet.</p>
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
          placeholder="Patient ID (from Reception check-in)"
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
        placeholder="Search by name or NRIC…"
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
        <label className="field-label">Encounter ID (optional)</label>
        <input
          type="text"
          className="field-input"
          value={encounterId}
          onChange={(e) => setEncounterId(e.target.value.trim())}
          placeholder="Link this bill to a visit, if any"
        />
      </div>
      <div className="flex gap-2">
        <button disabled={busy} className="btn-primary">Create Bill</button>
        <button type="button" onClick={onCancel} className="text-sm border border-slate-300 px-4 py-2 rounded-lg">Cancel</button>
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
            <Link to={`/patients/${bill.patient_id}`} className="ml-2 text-blue-700 hover:underline">View Record</Link>
            <span className="ml-2">· Opened {formatDateTime(bill.created_at)} by {bill.created_by_name}</span>
            {bill.encounter_id && <span className="ml-2">· Encounter {bill.encounter_id}</span>}
          </p>
        </div>
        {canWriteBills && bill.status === "open" && (
          <div className="flex gap-2">
            <button onClick={handleFinalize} className="text-xs bg-amber-700 hover:bg-amber-600 text-white px-3 py-1.5 rounded-lg">Finalize</button>
            <button onClick={handleVoidBill} className="text-xs border border-slate-300 hover:bg-slate-100 text-slate-700 px-3 py-1.5 rounded-lg">Void bill</button>
          </div>
        )}
        {canWriteBills && bill.status === "finalized" && (
          <button onClick={handleVoidBill} className="text-xs border border-slate-300 hover:bg-slate-100 text-slate-700 px-3 py-1.5 rounded-lg">Void bill</button>
        )}
      </div>

      {bill.voided_reason && (
        <p className="text-xs text-slate-500 mb-3 italic">Voided: {bill.voided_reason}</p>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 mb-4 text-center">
        <TotalTile label="Total" value={rm(bill.total_cents)} />
        <TotalTile label="Paid" value={rm(bill.paid_cents)} tone="green" />
        <TotalTile label="Claimed (pending)" value={rm(bill.claimed_pending_cents)} tone="amber" />
        <TotalTile label="Amount Due" value={rm(bill.amount_due_cents)} />
        <TotalTile label="Patient Due Now" value={rm(bill.patient_due_cents)} tone="blue" />
      </div>

      <div className="mb-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-700">Line Items</h3>
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
          <p className="text-sm text-slate-400">No line items yet.</p>
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
                    <button onClick={() => handleVoidItem(item.id)} className="text-xs text-red-700 hover:underline">Void</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mb-5">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-700">Payments</h3>
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
          <p className="text-sm text-slate-400">No payments recorded yet.</p>
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
                  {canWriteBills && !p.voided_at && (
                    <button onClick={() => handleVoidPayment(p.id)} className="text-xs text-red-700 hover:underline">Void</button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold text-slate-700">Insurance / Panel Claims</h3>
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
          <p className="text-sm text-slate-400">No claims on this bill.</p>
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
          <label className="field-label">Source</label>
          <select
            className="field-input"
            value={sourceType}
            onChange={(e) => { setSourceType(e.target.value); setSelectedId(""); }}
          >
            <option value="charge_master">Charge master item</option>
            <option value="service_request">Signed-off ancillary result</option>
            <option value="pharmacy_item">Pharmacy inventory item</option>
          </select>
        </div>
        <div>
          <label className="field-label">Item</label>
          <select required className="field-input" value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
            <option value="">-- select --</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>{o.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="field-label">Quantity</label>
          <input type="number" min="1" step="1" className="field-input" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </div>
      </div>
      <div className="flex gap-2">
        <button disabled={busy} className="btn-primary">Add Item</button>
        <button type="button" onClick={onCancel} className="text-sm border border-slate-300 px-4 py-2 rounded-lg">Cancel</button>
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
          <label className="field-label">Method</label>
          <select className="field-input" value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="cash">Cash</option>
            <option value="card">Card</option>
            <option value="insurance">Insurance</option>
            <option value="panel">Panel</option>
            <option value="other">Other</option>
          </select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="field-label">Reference No. (optional)</label>
          <input type="text" className="field-input" value={referenceNo} onChange={(e) => setReferenceNo(e.target.value)} />
        </div>
        {(method === "insurance" || method === "panel") && settleableClaims.length > 0 && (
          <div>
            <label className="field-label">Settles Claim (optional)</label>
            <select className="field-input" value={claimId} onChange={(e) => setClaimId(e.target.value)}>
              <option value="">-- none --</option>
              {settleableClaims.map((c) => (
                <option key={c.id} value={c.id}>{c.payer_name} ({rm(c.claim_amount_cents)})</option>
              ))}
            </select>
          </div>
        )}
      </div>
      <div className="flex gap-2">
        <button disabled={busy} className="btn-primary">Record Payment</button>
        <button type="button" onClick={onCancel} className="text-sm border border-slate-300 px-4 py-2 rounded-lg">Cancel</button>
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
          <label className="field-label">Claim Amount (RM)</label>
          <input required type="number" step="0.01" min="0.01" className="field-input" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <p className="text-[10px] text-slate-400 mt-1">May cover part of the bill (copay) — the rest stays owed by the patient until this claim settles.</p>
        </div>
      </div>
      <div>
        <label className="field-label">Notes (optional)</label>
        <textarea rows={2} className="field-input" value={notes} onChange={(e) => setNotes(e.target.value)}></textarea>
      </div>
      <div className="flex gap-2">
        <button disabled={busy} className="btn-primary">Create Claim</button>
        <button type="button" onClick={onCancel} className="text-sm border border-slate-300 px-4 py-2 rounded-lg">Cancel</button>
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
          <button onClick={() => setEditing(true)} className="text-xs text-blue-700 hover:underline">Edit</button>
        )}
      </div>
      {claim.notes && <p className="text-xs text-slate-600 mt-1 italic">{claim.notes}</p>}

      {editing ? (
        <form onSubmit={handleSaveEdit} className="mt-2 flex flex-wrap items-end gap-2">
          <input type="text" className="border border-slate-300 rounded px-2 py-1 text-sm" value={payerName} onChange={(e) => setPayerName(e.target.value)} />
          <input type="number" step="0.01" min="0.01" className="w-28 border border-slate-300 rounded px-2 py-1 text-sm" value={amount} onChange={(e) => setAmount(e.target.value)} />
          <button disabled={busy} className="text-xs bg-blue-800 text-white px-3 py-1 rounded disabled:opacity-50">Save</button>
          <button type="button" onClick={() => setEditing(false)} className="text-xs border border-slate-300 px-3 py-1 rounded">Cancel</button>
        </form>
      ) : (
        canManageClaims && (
          <div className="flex gap-2 mt-2">
            {claim.status === "draft" && (
              <button onClick={() => onAction(claim.id, "submit", false)} className="text-xs bg-amber-700 hover:bg-amber-600 text-white px-2 py-1 rounded">Submit</button>
            )}
            {claim.status === "submitted" && (
              <>
                <button onClick={() => onAction(claim.id, "approve", false)} className="text-xs bg-blue-700 hover:bg-blue-600 text-white px-2 py-1 rounded">Approve</button>
                <button onClick={() => onAction(claim.id, "reject", true)} className="text-xs border border-red-300 text-red-700 hover:bg-red-50 px-2 py-1 rounded">Reject</button>
              </>
            )}
            {claim.status === "approved" && (
              <>
                {/* No standalone "mark paid" action -- a claim only moves to
                    "paid" via a linked Payment (record one below with method
                    insurance/panel and this claim selected as "Settles
                    Claim"), so "paid" always has a real amount behind it. */}
                <span className="text-xs text-slate-400 italic self-center">Record a settling payment below to mark this paid</span>
                <button onClick={() => onAction(claim.id, "reject", true)} className="text-xs border border-red-300 text-red-700 hover:bg-red-50 px-2 py-1 rounded">Reject</button>
              </>
            )}
            {["draft", "submitted", "approved", "rejected"].includes(claim.status) && (
              <button onClick={() => onAction(claim.id, "void", true)} className="text-xs border border-slate-300 text-slate-600 hover:bg-slate-100 px-2 py-1 rounded">Void</button>
            )}
          </div>
        )
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
        <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">Category</label>
        <select className="w-36 border border-slate-300 rounded px-2 py-1 text-sm" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="consultation">Consultation</option>
          <option value="misc">Misc / Admin</option>
        </select>
      </div>
      <div>
        <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">Item Name</label>
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
      <button disabled={busy} className="bg-slate-800 text-white text-sm px-3 py-1 rounded disabled:opacity-50 h-[30px]">Add Item</button>
    </form>
  );
}
