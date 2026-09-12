// P3.1 Shared Ancillary Engine UI (Procedure / Laboratory / X-ray / Physiotherapy).
// Combines ordering (available to receptionists and clinical staff) with 
// result sign-off and catalog management (restricted to clinical roles/admins).
// Facilities are inherently scoped server-side.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Layout from "../components/Layout";
import {
  getCurrentUser,
  getAncillaryCatalog,
  createAncillaryCatalogItem,
  updateAncillaryCatalogItem,
  listAncillaryRequests,
  createAncillaryRequest,
  cancelAncillaryRequest,
  signOffAncillaryResult,
  uploadAncillaryResultDocument,
  getAncillaryResultDocumentBlob,
  getAncillaryStats,
  listPatients,
} from "../api/client";
import { formatDateTime } from "../lib/format";

const TABS = [
  { key: "procedure", label: "Procedure" },
  { key: "laboratory", label: "Laboratory" },
  { key: "xray", label: "X-ray" },
  { key: "physiotherapy", label: "Physiotherapy" },
];

const PRIORITY_STYLE = {
  routine: "bg-slate-100 text-slate-800",
  urgent: "bg-amber-100 text-amber-800",
  stat: "bg-red-100 text-red-800",
};

export default function Ancillary() {
  const user = getCurrentUser();
  const canSignOff = ["admin", "records_officer", "clinician"].includes(user?.role);
  const canManageCatalog = ["admin", "records_officer"].includes(user?.role);

  const [module, setModule] = useState("procedure");
  const [viewStatus, setViewStatus] = useState("ordered"); // "ordered" | "signed_off" | "cancelled" | "all"

  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(null);

  const [stats, setStats] = useState(null);
  
  const [showOrderForm, setShowOrderForm] = useState(false);
  const [showCatalog, setShowCatalog] = useState(false);
  // Catalog Management (below) always wants includeInactive: true; the New
  // order form only ever offers active items. Kept as two separate pieces
  // of state (rather than one shared `catalogItems`) so opening the order
  // form's active-only fetch can never clobber the management list's
  // inactive rows out from under it.
  const [catalogItems, setCatalogItems] = useState([]);
  const [orderCatalogItems, setOrderCatalogItems] = useState([]);
  const [patients, setPatients] = useState([]); // Cached for order form
  const [patientsLoaded, setPatientsLoaded] = useState(false);

  function loadWorklist() {
    setLoading(true);
    listAncillaryRequests({ module, status: viewStatus === "all" ? undefined : viewStatus })
      .then((data) => {
        setRequests(data);
        setError("");
      })
      .catch((err) => setError(err?.response?.data?.detail || "Failed to load requests."))
      .finally(() => setLoading(false));
  }

  function loadStats() {
    if (!canSignOff) return;
    getAncillaryStats().then(setStats).catch(() => {});
  }

  function refresh() {
    loadWorklist();
    loadStats();
    if (canSignOff) {
      getAncillaryCatalog({ module, includeInactive: true })
        .then(setCatalogItems)
        .catch(() => {});
    }
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(refresh, [module, viewStatus]);

  // GET /patients (behind listPatients) is gated to
  // admin/records_officer/clinician -- receptionist deliberately does NOT
  // have the `patients` page (see app/permissions.py::DEFAULT_ROLE_PAGES),
  // so it always 403s for them. A receptionist places an order by typing
  // the patient id directly instead (see OrderForm's `canBrowsePatients`).
  const canBrowsePatients = user?.role !== "receptionist";

  useEffect(() => {
    if (!showOrderForm) return;
    if (canBrowsePatients && !patientsLoaded) {
      listPatients({ limit: 200 })
        .then((data) => {
          setPatients(data);
          setPatientsLoaded(true);
        })
        .catch(() => {});
    }
    // Active-only items for the order form's <select> -- kept separate from
    // catalogItems (Catalog Management's includeInactive:true list) above.
    getAncillaryCatalog({ module, includeInactive: false })
      .then(setOrderCatalogItems)
      .catch(() => {});
  }, [showOrderForm, module, patientsLoaded, canBrowsePatients]);

  function showMsg(type, text) {
    setNotice({ type, text });
    setTimeout(() => setNotice(null), 5000);
  }

  async function handleCancelRequest(id) {
    const reason = prompt("Optional reason for cancelling:");
    if (reason === null) return;
    try {
      await cancelAncillaryRequest(id, reason);
      showMsg("success", "Request cancelled.");
      loadWorklist();
    } catch (err) {
      showMsg("error", err?.response?.data?.detail || "Failed to cancel request.");
    }
  }

  async function handleDownloadBlob(id) {
    try {
      const blob = await getAncillaryResultDocumentBlob(id);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `result_${id}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      showMsg("error", err?.response?.data?.detail || "Failed to download document.");
    }
  }

  const statOpen = stats?.open_by_module?.[module] ?? 0;
  const statSignedOff = stats?.signed_off_last_30d_by_module?.[module] ?? 0;

  return (
    <Layout>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Ancillary Services</h1>
        <p className="text-sm text-slate-500">Manage orders, results, and catalogs for ancillary departments.</p>
      </div>

      <div className="flex gap-1 border-b border-slate-200 mb-4 overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => { setModule(t.key); setShowOrderForm(false); }}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap ${
              module === t.key ? "border-blue-800 text-blue-800" : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {notice && (
        <div className={`mb-4 text-sm rounded-lg px-3 py-2 flex items-start justify-between gap-3 ${
          notice.type === "success" ? "bg-green-50 border border-green-200 text-green-800" : "bg-red-50 border border-red-200 text-red-700"
        }`}>
          <span>{notice.text}</span>
          <button onClick={() => setNotice(null)} className="shrink-0 font-medium">✕</button>
        </div>
      )}

      {canSignOff && stats && (
        <div className="flex gap-4 mb-4">
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 w-40 text-center">
            <p className="text-2xl font-bold text-amber-800">{statOpen}</p>
            <p className="text-xs text-amber-700 uppercase tracking-wide">Open Orders</p>
          </div>
          <div className="bg-green-50 border border-green-200 rounded-lg p-3 w-40 text-center">
            <p className="text-2xl font-bold text-green-800">{statSignedOff}</p>
            <p className="text-xs text-green-700 uppercase tracking-wide">Signed Off (30d)</p>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between mb-4">
        <div className="flex gap-2 items-center">
          <label className="text-sm font-medium text-slate-600">View status:</label>
          <select 
            className="border border-slate-300 rounded-lg px-2 py-1 text-sm"
            value={viewStatus} onChange={(e) => setViewStatus(e.target.value)}
          >
            <option value="ordered">Ordered</option>
            <option value="signed_off">Signed off</option>
            <option value="cancelled">Cancelled</option>
            <option value="all">All</option>
          </select>
        </div>
        <button
          onClick={() => setShowOrderForm(!showOrderForm)}
          className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg whitespace-nowrap"
        >
          {showOrderForm ? "Cancel" : "New order"}
        </button>
      </div>

      {showOrderForm && (
        <OrderForm
          module={module}
          catalogItems={orderCatalogItems}
          patients={patients}
          canBrowsePatients={canBrowsePatients}
          onCancel={() => setShowOrderForm(false)}
          onSuccess={() => { setShowOrderForm(false); loadWorklist(); showMsg("success", "Order created."); }}
          onError={(msg) => showMsg("error", msg)}
        />
      )}

      <div className="bg-white border border-slate-200 rounded-xl p-5 mb-6">
        {loading ? (
          <p className="text-sm text-slate-400">Loading worklist…</p>
        ) : error ? (
          <p className="text-sm text-red-600">{error}</p>
        ) : requests.length === 0 ? (
          <p className="text-sm text-slate-400">No requests found.</p>
        ) : (
          <div className="space-y-3">
            {requests.map(req => (
              <RequestRow
                key={req.id}
                req={req}
                canSignOff={canSignOff}
                hasSignature={user?.has_signature}
                onCancel={() => handleCancelRequest(req.id)}
                onDownload={() => handleDownloadBlob(req.id)}
                onRefresh={loadWorklist}
                showMsg={showMsg}
              />
            ))}
          </div>
        )}
      </div>

      {canSignOff && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 mb-4">
          <button onClick={() => setShowCatalog(!showCatalog)} className="w-full flex items-center justify-between text-left">
            <span className="font-semibold text-slate-800">Catalog Management</span>
            <span className="text-xs text-slate-400">{showCatalog ? "Hide" : "Show"}</span>
          </button>
          
          {showCatalog && (
            <div className="mt-4">
              <div className="space-y-2 mb-4">
                {catalogItems.length === 0 ? (
                  <p className="text-sm text-slate-400">No items in this module's catalog.</p>
                ) : (
                  catalogItems.map(item => (
                    <div key={item.id} className={`flex items-center justify-between border border-slate-200 rounded-lg px-3 py-2 ${item.active ? "bg-slate-50" : "bg-slate-100 opacity-70"}`}>
                      <div>
                        <p className="text-sm font-medium text-slate-800">{item.name} {item.code && <span className="text-xs text-slate-500 font-normal">({item.code})</span>}</p>
                        <p className="text-xs text-slate-500">RM {(item.unit_price_cents / 100).toFixed(2)}</p>
                      </div>
                      {canManageCatalog && (
                        <button 
                          onClick={async () => {
                            try {
                              await updateAncillaryCatalogItem(item.id, { active: !item.active });
                              getAncillaryCatalog({ module, includeInactive: true }).then(setCatalogItems);
                            } catch {
                              showMsg("error", "Failed to update catalog item.");
                            }
                          }}
                          className={`text-xs px-2 py-1 rounded border ${item.active ? "border-slate-300 text-slate-600 hover:bg-slate-100" : "border-blue-300 text-blue-700 bg-blue-50"}`}
                        >
                          {item.active ? "Deactivate" : "Reactivate"}
                        </button>
                      )}
                    </div>
                  ))
                )}
              </div>
              {canManageCatalog && (
                <CatalogAddForm module={module} onSuccess={(items) => { setCatalogItems(items); showMsg("success", "Item added to catalog."); }} onError={(msg) => showMsg("error", msg)} />
              )}
            </div>
          )}
        </div>
      )}
    </Layout>
  );
}

function OrderForm({ module, catalogItems, patients, canBrowsePatients, onCancel, onSuccess, onError }) {
  const [patientSearch, setPatientSearch] = useState("");
  const [patientId, setPatientId] = useState("");
  const [catalogId, setCatalogId] = useState("");
  const [source, setSource] = useState("frontdesk");
  const [encounterId, setEncounterId] = useState("");
  const [indication, setIndication] = useState("");
  const [priority, setPriority] = useState("routine");
  const [busy, setBusy] = useState(false);

  const filteredPatients = patients.filter(p => 
    p.full_name?.toLowerCase().includes(patientSearch.toLowerCase()) || 
    p.national_id?.toLowerCase().includes(patientSearch.toLowerCase())
  ).slice(0, 10);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!patientId || !catalogId) {
      onError("Select a patient and catalog item.");
      return;
    }
    setBusy(true);
    try {
      await createAncillaryRequest({
        patient_id: patientId,
        module,
        catalog_item_id: catalogId,
        source,
        source_encounter_id: source === "physician_order" ? encounterId : undefined,
        clinical_indication: indication,
        priority
      });
      onSuccess();
    } catch (err) {
      onError(err?.response?.data?.detail || "Failed to create order.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-xl p-5 mb-4 grid gap-3">
      <h2 className="font-semibold text-slate-800">New Order</h2>
      
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">Patient</label>
        {!canBrowsePatients ? (
          // Receptionist has no `patients` page access (GET /patients 403s
          // for that role by design -- see app/permissions.py), so there's
          // no searchable list to offer here. They already have the
          // patient's id from Reception check-in; paste it directly.
          <input
            type="text" placeholder="Patient ID (from Reception check-in)"
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            value={patientId} onChange={e => setPatientId(e.target.value.trim())}
          />
        ) : patientId ? (
          <div className="flex items-center justify-between border border-blue-200 bg-blue-50 rounded-lg px-3 py-2 text-sm">
            <span>{patients.find(p => p.id === patientId)?.full_name || patientId}</span>
            <button type="button" onClick={() => setPatientId("")} className="text-blue-700 hover:underline">Change</button>
          </div>
        ) : (
          <div>
            <input type="text" placeholder="Search by name or NRIC..." className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm mb-1" value={patientSearch} onChange={e => setPatientSearch(e.target.value)} />
            {patientSearch && filteredPatients.length > 0 && (
              <ul className="border border-slate-200 rounded-lg divide-y max-h-40 overflow-y-auto">
                {filteredPatients.map(p => (
                  <li key={p.id} onClick={() => setPatientId(p.id)} className="px-3 py-2 text-sm hover:bg-slate-50 cursor-pointer">
                    {p.full_name} <span className="text-xs text-slate-500 ml-1">{p.national_id}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Catalog Item</label>
          <select required className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" value={catalogId} onChange={e => setCatalogId(e.target.value)}>
            <option value="">-- select item --</option>
            {catalogItems.map(item => (
              <option key={item.id} value={item.id}>{item.name} (RM {(item.unit_price_cents / 100).toFixed(2)})</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Priority</label>
          <select className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" value={priority} onChange={e => setPriority(e.target.value)}>
            <option value="routine">Routine</option>
            <option value="urgent">Urgent</option>
            <option value="stat">Stat</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Source</label>
          <select className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" value={source} onChange={e => setSource(e.target.value)}>
            <option value="frontdesk">Frontdesk</option>
            <option value="physician_order">Physician Order</option>
          </select>
        </div>
        {source === "physician_order" && (
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Encounter ID</label>
            <input required type="text" className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" value={encounterId} onChange={e => setEncounterId(e.target.value)} />
          </div>
        )}
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">Clinical Indication</label>
        <textarea rows={2} className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" value={indication} onChange={e => setIndication(e.target.value)}></textarea>
      </div>

      <div className="flex gap-2 mt-2">
        <button disabled={busy} className="text-sm bg-blue-800 text-white px-4 py-2 rounded-lg disabled:opacity-50">Create Order</button>
        <button type="button" onClick={onCancel} className="text-sm border border-slate-300 px-4 py-2 rounded-lg">Cancel</button>
      </div>
    </form>
  );
}

function RequestRow({ req, canSignOff, hasSignature, onCancel, onDownload, onRefresh, showMsg }) {
  const [showSignOff, setShowSignOff] = useState(false);
  
  return (
    <div className="border border-slate-200 rounded-lg p-3 bg-slate-50">
      <div className="flex justify-between items-start">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-semibold text-slate-800">{req.catalog_item_name}</span>
            <span className={`text-xs px-2 py-0.5 rounded-full uppercase font-medium ${PRIORITY_STYLE[req.priority] || "bg-slate-100 text-slate-800"}`}>{req.priority}</span>
            <span className="text-xs text-slate-500 bg-white border border-slate-200 px-1.5 py-0.5 rounded">{req.status}</span>
          </div>
          <p className="text-xs text-slate-600 mb-1">
            Patient: {req.patient_full_name || req.patient_id}
            <Link to={`/patients/${req.patient_id}`} className="ml-2 text-blue-700 hover:underline">View Record</Link>
          </p>
          <p className="text-xs text-slate-500">Ordered {formatDateTime(req.created_at)} · {req.source}</p>
          {req.clinical_indication && <p className="text-xs text-slate-600 mt-1 italic truncate max-w-lg">Indication: {req.clinical_indication}</p>}
        </div>
        
        <div className="flex gap-2">
          {req.status === "ordered" && canSignOff && (
            <button onClick={() => setShowSignOff(!showSignOff)} className="text-xs bg-green-700 hover:bg-green-600 text-white px-3 py-1.5 rounded-lg">
              {showSignOff ? "Cancel Sign-off" : "Sign off"}
            </button>
          )}
          {req.status === "ordered" && (
            <button onClick={onCancel} className="text-xs border border-slate-300 hover:bg-slate-100 text-slate-700 px-3 py-1.5 rounded-lg">
              Cancel
            </button>
          )}
        </div>
      </div>

      {showSignOff && (
        <SignOffForm 
          req={req} 
          hasSignature={hasSignature} 
          onSuccess={() => { setShowSignOff(false); onRefresh(); showMsg("success", "Result signed off."); }} 
          onError={(msg) => showMsg("error", msg)} 
        />
      )}

      {req.result && (
        <div className="mt-3 pt-3 border-t border-slate-200">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold text-slate-700">Result</span>
            {req.result.flag_abnormal && <span className="text-[10px] bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded uppercase">Abnormal</span>}
            {req.result.flag_critical && <span className="text-[10px] bg-red-100 text-red-800 px-1.5 py-0.5 rounded uppercase">Critical</span>}
            <span className="text-xs text-slate-500 ml-auto">Signed by {req.result.signed_by_name} at {formatDateTime(req.result.performed_at)}</span>
          </div>
          {req.result.result_text && <p className="text-sm text-slate-700 mb-2 whitespace-pre-wrap">{req.result.result_text}</p>}
          {req.result.has_document && (
            <button onClick={onDownload} className="text-xs text-blue-700 hover:underline inline-flex items-center gap-1">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg>
              Download attachment
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function SignOffForm({ req, hasSignature, onSuccess, onError }) {
  const [resultText, setResultText] = useState("");
  const [abnormal, setAbnormal] = useState(false);
  const [critical, setCritical] = useState(false);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);

  if (!hasSignature) {
    return (
      <div className="mt-3 bg-white p-4 border border-slate-200 rounded-lg text-sm text-center">
        <p className="text-amber-700 mb-2">You need a digital signature to sign off results.</p>
        <Link to="/profile" className="text-blue-700 underline font-medium">Save your signature in your profile first.</Link>
      </div>
    );
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await signOffAncillaryResult(req.id, {
        result_text: resultText,
        flag_abnormal: abnormal,
        flag_critical: critical
      });
      if (file) {
        await uploadAncillaryResultDocument(req.id, file);
      }
      onSuccess();
    } catch (err) {
      onError(err?.response?.data?.detail || "Failed to sign off.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 bg-white p-4 border border-slate-200 rounded-lg grid gap-3">
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">Result Text</label>
        <textarea rows={3} className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" value={resultText} onChange={e => setResultText(e.target.value)}></textarea>
      </div>
      <div className="flex gap-4">
        <label className="flex items-center gap-1 text-sm text-amber-800 bg-amber-50 px-2 py-1 rounded">
          <input type="checkbox" checked={abnormal} onChange={e => setAbnormal(e.target.checked)} /> Flag Abnormal
        </label>
        <label className="flex items-center gap-1 text-sm text-red-800 bg-red-50 px-2 py-1 rounded">
          <input type="checkbox" checked={critical} onChange={e => setCritical(e.target.checked)} /> Flag Critical
        </label>
      </div>
      <div className="mt-1 pt-3 border-t border-slate-100">
        <label className="block text-xs font-medium text-slate-600 mb-1">Attachment (Optional document/scan)</label>
        <input type="file" accept="image/*,application/pdf" className="text-sm" onChange={e => setFile(e.target.files?.[0])} />
      </div>
      <div className="mt-2 text-right">
        <button disabled={busy} className="bg-green-700 text-white text-sm px-4 py-2 rounded-lg disabled:opacity-50">Confirm Sign-off</button>
      </div>
    </form>
  );
}

function CatalogAddForm({ module, onSuccess, onError }) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [price, setPrice] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await createAncillaryCatalogItem({
        module,
        name,
        code,
        unit_price_cents: Math.round(parseFloat(price || 0) * 100)
      });
      const items = await getAncillaryCatalog({ module, includeInactive: true });
      onSuccess(items);
      setName(""); setCode(""); setPrice("");
    } catch (err) {
      onError(err?.response?.data?.detail || "Failed to add item.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-2 pt-4 border-t border-slate-200 flex flex-wrap items-end gap-3">
      <div>
        <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">Item Name</label>
        <input required type="text" className="w-48 border border-slate-300 rounded px-2 py-1 text-sm" value={name} onChange={e => setName(e.target.value)} />
      </div>
      <div>
        <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">Code (Opt)</label>
        <input type="text" className="w-24 border border-slate-300 rounded px-2 py-1 text-sm" value={code} onChange={e => setCode(e.target.value)} />
      </div>
      <div>
        <label className="block text-[10px] uppercase font-bold text-slate-500 mb-1">Price (RM)</label>
        <input required type="number" step="0.01" min="0" className="w-24 border border-slate-300 rounded px-2 py-1 text-sm" value={price} onChange={e => setPrice(e.target.value)} />
      </div>
      <button disabled={busy} className="bg-slate-800 text-white text-sm px-3 py-1 rounded disabled:opacity-50 h-[30px]">Add Item</button>
    </form>
  );
}
