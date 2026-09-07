import { useEffect, useRef, useState } from "react";
import Layout from "../components/Layout";
import {
  getPharmacyInventory,
  getLowStockInventory,
  getPharmacySummary,
  adjustStock,
  requestInventoryDeletion,
  getPharmacyProposals,
  createPurchaseProposal,
  uploadMedicineImage,
  getMedicineImageBlob,
} from "../api/client";

// No date library in this codebase (see AdminConsole.jsx's identical note) —
// a plain toLocaleString() matches every other timestamp rendered in the
// console.
function formatDateTime(iso) {
  return iso ? new Date(iso).toLocaleString() : "—";
}

// Client-side gate before we even attempt an upload — the backend also
// re-checks content-type + extension + magic bytes and 422s on mismatch,
// but rejecting the obvious cases here saves a round-trip and gives an
// instant inline message. Returns an error string, or "" when acceptable.
const MAX_IMAGE_BYTES = 2 * 1024 * 1024;
function validateImageFile(file) {
  if (!file) return "";
  if (!file.type.startsWith("image/")) return "That file isn't an image.";
  if (file.size > MAX_IMAGE_BYTES) return "Image must be 2MB or smaller.";
  return "";
}

// pending=amber, approved=green, rejected=slate — reuses the same
// "amber = needs attention / green = good / slate = closed" vocabulary the
// rest of the console uses, rather than a new palette.
const PROPOSAL_STATUS_STYLE = {
  pending: "bg-amber-100 text-amber-800",
  approved: "bg-green-100 text-green-800",
  rejected: "bg-slate-200 text-slate-600",
};
const PROPOSAL_STATUS_ORDER = ["pending", "approved", "rejected"];

// Pharmacist-facing stock console. Deliberately has NO catalogue
// create/edit/delete — a pharmacist adjusts stock VOLUME (restock / dispense),
// can REQUEST a catalogue deletion, and can PROPOSE a purchase (restock of a
// non-auto-approved item, or a brand-new medicine) for an admin to approve;
// everything else stays in the admin console (routers/admin.py). Route access
// is gated by App.jsx's <RequirePage page="pharmacy"> guard; nothing here
// re-checks the role.
export default function Pharmacy() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // Per-row id mid-request — disables that row's steppers / actions so a
  // double click can't fire two overlapping adjustments against one item.
  const [busyId, setBusyId] = useState(null);
  // Which row's "Add stock…" inline form is open, if any.
  const [addStockId, setAddStockId] = useState(null);
  // Transient inline banner for outcomes that aren't row-level errors
  // (proposal filed, duplicate pending, etc.).
  const [notice, setNotice] = useState(null); // { type: "success" | "error", text }

  // Search — the raw input value plus its debounced copy. A hardware barcode
  // scanner types the code then sends Enter, so the input is also wired to
  // scroll to / highlight the row when Enter lands on exactly one result.
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [highlightId, setHighlightId] = useState(null);
  // Set when Enter is pressed in the search box (barcode scan): the next
  // results render, if it's a single row, scrolls to / highlights it.
  const [scanJump, setScanJump] = useState(false);
  const rowRefs = useRef({});

  // Low-stock: summary counter drives the sticky banner; clicking it toggles
  // a filter down to just the low-stock rows.
  const [summary, setSummary] = useState(null);
  const [lowStockOnly, setLowStockOnly] = useState(false);

  const [showProposeForm, setShowProposeForm] = useState(false);

  const [proposalsOpen, setProposalsOpen] = useState(false);
  const [proposals, setProposals] = useState([]);
  const [proposalsLoading, setProposalsLoading] = useState(false);

  function loadSummary() {
    getPharmacySummary().then(setSummary).catch(() => setSummary(null));
  }

  function refresh() {
    setLoading(true);
    const q = debouncedQuery.trim();
    const load = lowStockOnly ? getLowStockInventory() : getPharmacyInventory({ q: q || undefined });
    load
      .then((rows) => {
        // The low-stock endpoint has no ?q= — apply the same name/barcode
        // filter client-side so the search box still narrows that view.
        if (lowStockOnly && q) {
          const needle = q.toLowerCase();
          rows = rows.filter(
            (r) =>
              r.drug_name.toLowerCase().includes(needle) ||
              (r.barcode || "").toLowerCase().includes(needle)
          );
        }
        setItems(rows);
        setError("");
      })
      .catch((err) => setError(err?.response?.data?.detail || "Failed to load inventory."))
      .finally(() => setLoading(false));
  }

  useEffect(loadSummary, []);

  // Debounce the search input ~300ms before re-querying.
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(t);
  }, [query]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(refresh, [debouncedQuery, lowStockOnly]);

  function loadProposals() {
    setProposalsLoading(true);
    getPharmacyProposals("all")
      .then(setProposals)
      .catch(() => setProposals([]))
      .finally(() => setProposalsLoading(false));
  }

  function toggleProposals() {
    const next = !proposalsOpen;
    setProposalsOpen(next);
    if (next) loadProposals();
  }

  function replaceRow(updated) {
    setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
  }

  function onSearchKeyDown(e) {
    if (e.key !== "Enter") return;
    e.preventDefault();
    // A hardware scanner types the code then sends Enter faster than the
    // 300ms debounce — flush the query now and let the effect below jump to
    // the row once the (possibly single) result lands.
    setDebouncedQuery(query);
    setScanJump(true);
  }

  // Barcode-scanner friendly: a scan that resolves to exactly one item jumps
  // straight to it instead of making the pharmacist hunt the list.
  useEffect(() => {
    if (!scanJump || loading) return;
    setScanJump(false);
    if (items.length === 1) {
      const el = rowRefs.current[items[0].id];
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
      setHighlightId(items[0].id);
      setTimeout(() => setHighlightId(null), 2000);
    }
  }, [scanJump, loading, items]);

  async function step(item, delta) {
    // delta is only ever -1 here — the "+" stepper is disabled on
    // non-auto-approved rows (see the button below), and on auto-approved
    // rows a +1 restock just applies immediately (200).
    if (item.quantity_on_hand + delta < 0) return;
    setBusyId(item.id);
    try {
      const res = await adjustStock(item.id, { delta });
      replaceRow(res.data);
    } catch (err) {
      setNotice({ type: "error", text: err?.response?.data?.detail || "Failed to adjust stock." });
    } finally {
      setBusyId(null);
    }
  }

  async function submitAddStock(item, qty, unitCost) {
    const delta = Number(qty);
    if (!Number.isInteger(delta) || delta <= 0) {
      setNotice({ type: "error", text: "Enter a whole number of units greater than 0." });
      return;
    }
    const payload = { delta };
    if (unitCost !== "" && unitCost != null) payload.unit_cost = Number(unitCost);
    setBusyId(item.id);
    try {
      const res = await adjustStock(item.id, payload);
      if (res.status === 202) {
        // Non-auto-approved item: a purchase proposal was filed and stock /
        // budget were left untouched — do NOT optimistically bump the row.
        setNotice({ type: "success", text: "Purchase proposal sent to admin for approval." });
        loadSummary();
        if (proposalsOpen) loadProposals();
      } else {
        replaceRow(res.data);
        setNotice({ type: "success", text: `Added ${delta} ${item.unit} of ${item.drug_name}.` });
      }
      setAddStockId(null);
    } catch (err) {
      if (err?.response?.status === 409) {
        setNotice({ type: "error", text: "A matching request is already pending." });
      } else {
        setNotice({ type: "error", text: err?.response?.data?.detail || "Failed to add stock." });
      }
    } finally {
      setBusyId(null);
    }
  }

  async function onImageUploaded(item, file, setLocalErr) {
    const localErr = validateImageFile(file);
    if (localErr) {
      setLocalErr(localErr);
      return;
    }
    setLocalErr("");
    setBusyId(item.id);
    try {
      const updated = await uploadMedicineImage(item.id, file);
      replaceRow(updated);
    } catch (err) {
      setLocalErr(err?.response?.data?.detail || "Upload failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function requestDeletion(item) {
    const reason = prompt(`Request removal of "${item.drug_name}" from the catalogue?\nOptional reason for the admin:`);
    if (reason === null) return; // cancelled
    setBusyId(item.id);
    try {
      await requestInventoryDeletion(item.id, { reason: reason.trim() || null });
      refresh();
    } catch (err) {
      setNotice({ type: "error", text: err?.response?.data?.detail || "Failed to file deletion request." });
    } finally {
      setBusyId(null);
    }
  }

  async function submitProposal(body) {
    try {
      await createPurchaseProposal(body);
      setNotice({ type: "success", text: "Purchase proposal sent to admin for approval." });
      setShowProposeForm(false);
      loadSummary();
      if (proposalsOpen) loadProposals();
      return true;
    } catch (err) {
      if (err?.response?.status === 409) {
        setNotice({ type: "error", text: "You already have a pending proposal for that medicine." });
      } else {
        setNotice({ type: "error", text: err?.response?.data?.detail || "Failed to send proposal." });
      }
      return false;
    }
  }

  const lowStockCount = summary?.low_stock_count ?? 0;

  return (
    <Layout>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Pharmacy</h1>
        <p className="text-sm text-slate-500">
          Stock levels for your facility. Restocking accrues against the procurement budget; the
          catalogue itself is managed by an admin.
        </p>
      </div>

      {/* Search stays pinned above the list — scanner-friendly (type/scan a
          barcode then Enter jumps to the row). */}
      <div className="sticky top-0 z-20 bg-slate-50 pb-2">
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="Search by drug name or scan a barcode…"
            className="border rounded-lg px-3 py-2 text-sm flex-1"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onSearchKeyDown}
          />
          {query && (
            <button
              onClick={() => setQuery("")}
              className="text-sm border border-slate-300 px-3 py-2 rounded-lg whitespace-nowrap"
            >
              Clear
            </button>
          )}
          <button
            onClick={() => setShowProposeForm((s) => !s)}
            className="text-sm bg-blue-800 text-white px-3 py-2 rounded-lg whitespace-nowrap"
          >
            {showProposeForm ? "Cancel" : "Propose new medicine"}
          </button>
        </div>

        {lowStockCount > 0 && (
          <button
            onClick={() => setLowStockOnly((v) => !v)}
            className={`mt-2 w-full text-left text-sm rounded-lg px-3 py-2 border ${
              lowStockOnly
                ? "bg-amber-100 border-amber-300 text-amber-900"
                : "bg-amber-50 border-amber-200 text-amber-800"
            }`}
          >
            ⚠ {lowStockCount} item{lowStockCount === 1 ? "" : "s"} low on stock — reorder soon
            <span className="ml-2 font-medium underline">
              {lowStockOnly ? "show all" : "show only these"}
            </span>
          </button>
        )}
      </div>

      {notice && (
        <div
          className={`mb-3 text-sm rounded-lg px-3 py-2 flex items-start justify-between gap-3 ${
            notice.type === "success"
              ? "bg-green-50 border border-green-200 text-green-800"
              : "bg-red-50 border border-red-200 text-red-700"
          }`}
        >
          <span>{notice.text}</span>
          <button onClick={() => setNotice(null)} className="shrink-0 font-medium">✕</button>
        </div>
      )}

      {showProposeForm && (
        <div className="bg-white border border-slate-200 rounded-xl p-5 mb-4">
          <h2 className="font-semibold text-slate-800 mb-3">Propose a new medicine</h2>
          <ProposeNewMedicineForm onSubmit={submitProposal} onCancel={() => setShowProposeForm(false)} />
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl p-5">
        {loading ? (
          <p className="text-sm text-slate-400">Loading…</p>
        ) : error ? (
          <p className="text-sm text-red-600">{error}</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-slate-400">
            {debouncedQuery.trim() || lowStockOnly
              ? "No inventory items match."
              : "No inventory items for this facility yet."}
          </p>
        ) : (
          <div className="space-y-2">
            {items.map((item) => (
              <div
                key={item.id}
                ref={(el) => (rowRefs.current[item.id] = el)}
                className={`rounded-lg px-3 py-2 border ${
                  item.is_low_stock ? "bg-amber-50 border-amber-200" : "bg-slate-50 border-slate-200"
                } ${highlightId === item.id ? "ring-2 ring-blue-500" : ""}`}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <MedicineThumb item={item} onUpload={onImageUploaded} disabled={busyId === item.id} />
                    <div className="text-sm text-slate-700 min-w-0">
                      <p className="font-medium">
                        {item.drug_name}
                        {item.auto_approved && (
                          <span className="ml-2 text-xs font-semibold text-green-700 bg-green-100 rounded px-1.5 py-0.5">
                            Auto-approved
                          </span>
                        )}
                        {item.is_low_stock && (
                          <span className="ml-2 text-xs font-semibold text-amber-700 uppercase">⚠ Low stock</span>
                        )}
                      </p>
                      <p className="text-xs text-slate-400">
                        {item.quantity_on_hand} {item.unit}
                        {item.reorder_threshold != null && ` · reorder at ${item.reorder_threshold}`}
                        {item.unit_cost != null && ` · RM ${Number(item.unit_cost).toFixed(2)}/${item.unit}`}
                        {item.barcode && ` · barcode ${item.barcode}`}
                        {" · last restocked "}
                        {item.last_restocked_at ? formatDateTime(item.last_restocked_at) : "never"}
                      </p>
                      {item.notes && <p className="text-xs text-slate-500 mt-0.5">{item.notes}</p>}
                    </div>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => step(item, -1)}
                        disabled={busyId === item.id || item.quantity_on_hand <= 0}
                        className="w-6 h-6 text-sm border border-slate-300 rounded disabled:opacity-30"
                        title="Dispense 1"
                      >
                        −
                      </button>
                      <span className="text-xs text-slate-500 w-8 text-center">{item.quantity_on_hand}</span>
                      {/* "+" is only a live one-tap restock for auto-approved
                          items. For everything else a restock has to go
                          through admin approval with a real quantity and
                          (optionally) a cost, so a bare "+1" would be
                          misleading — disable it and point at "Add stock…"
                          / "Propose" instead. Repeated "+1" taps would also
                          just pile up duplicate-pending 409s. */}
                      <button
                        onClick={() => step(item, 1)}
                        disabled={busyId === item.id || !item.auto_approved}
                        className="w-6 h-6 text-sm border border-slate-300 rounded disabled:opacity-30"
                        title={
                          item.auto_approved
                            ? "Restock 1"
                            : "Restocking needs admin approval — use “Add stock…”"
                        }
                      >
                        +
                      </button>
                    </div>
                    <button
                      onClick={() => setAddStockId(addStockId === item.id ? null : item.id)}
                      disabled={busyId === item.id}
                      className="text-xs text-blue-700 whitespace-nowrap disabled:opacity-40"
                    >
                      Add stock…
                    </button>
                    {item.pending_delete_request ? (
                      <span className="text-xs text-slate-400 whitespace-nowrap">Deletion requested</span>
                    ) : (
                      <button
                        onClick={() => requestDeletion(item)}
                        disabled={busyId === item.id}
                        className="text-xs text-red-700 whitespace-nowrap disabled:opacity-40"
                      >
                        Request deletion
                      </button>
                    )}
                  </div>
                </div>

                {addStockId === item.id && (
                  <AddStockForm
                    item={item}
                    busy={busyId === item.id}
                    onCancel={() => setAddStockId(null)}
                    onSubmit={submitAddStock}
                  />
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* My proposals — collapsible; the pharmacist's own restock / new-item
          proposals grouped by status. */}
      <div className="bg-white border border-slate-200 rounded-xl p-5 mt-4">
        <button
          onClick={toggleProposals}
          className="w-full flex items-center justify-between text-left"
        >
          <span className="font-semibold text-slate-800">My proposals</span>
          <span className="text-xs text-slate-400">{proposalsOpen ? "Hide" : "Show"}</span>
        </button>

        {proposalsOpen && (
          <div className="mt-3">
            {proposalsLoading ? (
              <p className="text-sm text-slate-400">Loading…</p>
            ) : proposals.length === 0 ? (
              <p className="text-sm text-slate-400">You haven't sent any proposals yet.</p>
            ) : (
              <div className="space-y-4">
                {PROPOSAL_STATUS_ORDER.filter((s) => proposals.some((p) => p.status === s)).map((status) => (
                  <div key={status}>
                    <p className="text-xs font-semibold uppercase text-slate-400 mb-1">{status}</p>
                    <div className="space-y-2">
                      {proposals
                        .filter((p) => p.status === status)
                        .map((p) => (
                          <div key={p.id} className="bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
                            <div className="flex items-start justify-between gap-3">
                              <div className="text-sm text-slate-700 min-w-0">
                                <p className="font-medium">
                                  {p.proposed_drug_name}
                                  {p.is_new_item && (
                                    <span className="ml-2 text-xs font-normal text-slate-400">(new medicine)</span>
                                  )}
                                </p>
                                <p className="text-xs text-slate-400">
                                  {p.quantity} {p.proposed_unit}
                                  {p.unit_cost != null && ` · RM ${Number(p.unit_cost).toFixed(2)}/unit`}
                                  {" · sent "}
                                  {formatDateTime(p.created_at)}
                                </p>
                                {p.reason && <p className="text-xs text-slate-500 mt-0.5">Reason: {p.reason}</p>}
                                {p.admin_note && (
                                  <p className="text-xs text-slate-500 mt-0.5">Admin note: {p.admin_note}</p>
                                )}
                                {p.reviewed_at && (
                                  <p className="text-xs text-slate-400 mt-0.5">
                                    Reviewed {formatDateTime(p.reviewed_at)}
                                  </p>
                                )}
                              </div>
                              <span
                                className={`text-xs font-semibold rounded px-1.5 py-0.5 whitespace-nowrap ${
                                  PROPOSAL_STATUS_STYLE[p.status] || "bg-slate-200 text-slate-600"
                                }`}
                              >
                                {p.status}
                              </span>
                            </div>
                          </div>
                        ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </Layout>
  );
}

// 40px thumbnail. Loads the photo as an auth blob (object URL, revoked on
// unmount / when the row's image changes) or shows a pill placeholder.
// "Add photo" / "Replace photo" opens a file picker; the parent does the
// actual upload + row refresh and this just surfaces the inline guard error.
function MedicineThumb({ item, onUpload, disabled }) {
  const [url, setUrl] = useState(null);
  const [err, setErr] = useState("");
  const fileRef = useRef(null);

  useEffect(() => {
    let revoked = false;
    let objectUrl = null;
    if (item.has_image && item.image_url) {
      getMedicineImageBlob(item.image_url)
        .then((u) => {
          if (revoked) {
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
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // image_url changes (new path fragment or null) whenever the photo is
    // added / replaced / not present, so it's the right dependency.
  }, [item.has_image, item.image_url]);

  return (
    <div className="shrink-0">
      <button
        type="button"
        onClick={() => !disabled && fileRef.current?.click()}
        className="block w-10 h-10 rounded-lg border border-slate-200 overflow-hidden bg-white disabled:opacity-50"
        disabled={disabled}
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
        onClick={() => !disabled && fileRef.current?.click()}
        disabled={disabled}
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
          e.target.value = ""; // allow re-picking the same file
          if (file) onUpload(item, file, setErr);
        }}
      />
    </div>
  );
}

function AddStockForm({ item, busy, onCancel, onSubmit }) {
  const [qty, setQty] = useState("");
  // Prefill with the item's known unit cost so the common "same price as
  // last time" restock is one field less to fill in.
  const [unitCost, setUnitCost] = useState(item.unit_cost != null ? String(item.unit_cost) : "");

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(item, qty, unitCost);
      }}
      className="mt-2 pt-2 border-t border-slate-200 flex flex-wrap items-end gap-3"
    >
      {!item.auto_approved && (
        <p className="w-full text-xs text-amber-700">
          This medicine isn't auto-approved — submitting sends a purchase proposal to an admin;
          stock won't change until they approve it.
        </p>
      )}
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">Quantity to add</label>
        <input
          className="w-28 border border-slate-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          type="number"
          min="1"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">Unit cost (RM)</label>
        <input
          className="w-28 border border-slate-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          type="number"
          min="0"
          step="0.01"
          value={unitCost}
          onChange={(e) => setUnitCost(e.target.value)}
        />
      </div>
      <button
        disabled={busy}
        className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50"
      >
        {busy ? "Saving…" : item.auto_approved ? "Add" : "Send proposal"}
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="text-sm border border-slate-300 px-3 py-1.5 rounded-lg"
      >
        Cancel
      </button>
    </form>
  );
}

function ProposeNewMedicineForm({ onSubmit, onCancel }) {
  const [values, setValues] = useState({
    proposed_drug_name: "",
    proposed_unit: "units",
    proposed_barcode: "",
    quantity: "",
    unit_cost: "",
    reason: "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function set(key, v) {
    setValues((prev) => ({ ...prev, [key]: v }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!values.proposed_drug_name.trim()) {
      setErr("Drug name is required.");
      return;
    }
    const quantity = Number(values.quantity);
    if (!Number.isInteger(quantity) || quantity <= 0) {
      setErr("Quantity must be a whole number greater than 0.");
      return;
    }
    setErr("");
    const body = {
      proposed_drug_name: values.proposed_drug_name.trim(),
      proposed_unit: values.proposed_unit.trim() || "units",
      quantity,
    };
    if (values.proposed_barcode.trim()) body.proposed_barcode = values.proposed_barcode.trim();
    if (values.unit_cost !== "") body.unit_cost = Number(values.unit_cost);
    if (values.reason.trim()) body.reason = values.reason.trim();

    setBusy(true);
    const ok = await onSubmit(body);
    setBusy(false);
    if (ok) {
      setValues({
        proposed_drug_name: "",
        proposed_unit: "units",
        proposed_barcode: "",
        quantity: "",
        unit_cost: "",
        reason: "",
      });
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {err && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{err}</div>}
      <div className="flex flex-wrap gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Drug name<span className="text-red-600"> *</span></label>
          <input
            className="w-52 border border-slate-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={values.proposed_drug_name}
            onChange={(e) => set("proposed_drug_name", e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Unit</label>
          <input
            className="w-28 border border-slate-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. tablets"
            value={values.proposed_unit}
            onChange={(e) => set("proposed_unit", e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Barcode</label>
          <input
            className="w-40 border border-slate-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={values.proposed_barcode}
            onChange={(e) => set("proposed_barcode", e.target.value)}
          />
        </div>
      </div>
      <div className="flex flex-wrap gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Quantity<span className="text-red-600"> *</span></label>
          <input
            className="w-28 border border-slate-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            type="number"
            min="1"
            value={values.quantity}
            onChange={(e) => set("quantity", e.target.value)}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Unit cost (RM)</label>
          <input
            className="w-28 border border-slate-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            type="number"
            min="0"
            step="0.01"
            value={values.unit_cost}
            onChange={(e) => set("unit_cost", e.target.value)}
          />
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">Reason</label>
        <textarea
          className="w-full border border-slate-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          rows={2}
          value={values.reason}
          onChange={(e) => set("reason", e.target.value)}
        />
      </div>
      <div className="flex gap-2">
        <button disabled={busy} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50">
          {busy ? "Sending…" : "Send proposal"}
        </button>
        <button type="button" onClick={onCancel} className="text-sm border border-slate-300 px-3 py-1.5 rounded-lg">
          Cancel
        </button>
      </div>
    </form>
  );
}
