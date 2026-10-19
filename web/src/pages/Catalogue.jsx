import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import {
  listDrugs, getDrug, listProducts, getProduct,
  listFeeSchedules, listReferenceKinds, getReferenceList, errorMessage,
} from "../api/client";
import { tr } from "../lib/i18n";

const PAGE = 25;
const TABS = [["drugs", "Drugs"], ["products", "Products"], ["fees", "Fee schedule"], ["lists", "Code lists"]];

const label = (kind) => kind.replace(/_/g, " ");
const money = (n) => (n == null ? "-" : Number(n).toFixed(2));

function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function Field({ name, children }) {
  if (children == null || children === "") return null;
  return (
    <div>
      <dt className="text-xs font-medium text-slate-500">{name}</dt>
      <dd className="text-sm text-slate-900">{children}</dd>
    </div>
  );
}

function DrugDetail({ code }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let off = false;
    getDrug(code).then((x) => !off && setD(x)).catch((e) => !off && setErr(errorMessage(e, "Could not load this drug.")));
    return () => { off = true; };
  }, [code]);
  if (err) return <p className="alert-error">{err}</p>;
  if (!d) return <p className="empty-state">{tr("Loading...")}</p>;
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
        <Field name="Code">{d.drug_code}</Field>
        <Field name="Active ingredient">{d.active_ingredient}</Field>
        <Field name="Trade name">{d.trade_name}</Field>
        <Field name="Therapeutic class">{d.category_name}</Field>
        <Field name="Schedule">{d.drug_schedule}</Field>
        <Field name="Formulary">{d.drug_formulary === "Y" ? "In formulary" : d.drug_formulary === "N" ? "Not in formulary" : d.drug_formulary}</Field>
        <Field name="Dosage form">{d.dosage_form}</Field>
        <Field name="Strength">{d.strength && d.uom_strength ? `${d.strength} ${d.uom_strength}` : d.strength}</Field>
        <Field name="Dispensed as">{d.sku_uom}</Field>
        <Field name="Instruction">{d.instruction}</Field>
        <Field name="Special instruction">{d.special_instruction}</Field>
        <Field name="Caution">{d.caution}</Field>
      </dl>
      {d.indications.length > 0 && (
        <div>
          <h3 className="field-label">{tr("Indications")}</h3>
          <p className="text-sm text-slate-900">{d.indications.join("; ")}</p>
        </div>
      )}
      <div>
        <h3 className="field-label">{tr("Default prescribing lines")}</h3>
        {d.prescriptions.length === 0 ? (
          <p className="empty-state">{tr("No default lines recorded for this drug.")}</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500">
                  <th className="py-1 pr-4 font-medium">{tr("Dose")}</th><th className="py-1 pr-4 font-medium">{tr("Frequency")}</th>
                  <th className="py-1 pr-4 font-medium">{tr("Route")}</th><th className="py-1 pr-4 font-medium">{tr("Duration")}</th>
                  <th className="py-1 font-medium">{tr("Instruction")}</th>
                </tr>
              </thead>
              <tbody>
                {d.prescriptions.map((p, i) => (
                  <tr key={i} className="border-t border-slate-100">
                    <td className="py-1.5 pr-4">{[p.drug_dosage, p.dosage].filter((x) => x != null).join(" ") || "-"}</td>
                    <td className="py-1.5 pr-4">{p.frequency || "-"}</td>
                    <td className="py-1.5 pr-4">{p.route || "-"}</td>
                    <td className="py-1.5 pr-4">{p.drug_duration != null ? `${p.drug_duration} ${p.period || ""}` : "-"}</td>
                    <td className="py-1.5">{p.instruction || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function ProductDetail({ code }) {
  const [p, setP] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    let off = false;
    getProduct(code).then((x) => !off && setP(x)).catch((e) => !off && setErr(errorMessage(e, "Could not load this product.")));
    return () => { off = true; };
  }, [code]);
  if (err) return <p className="alert-error">{err}</p>;
  if (!p) return <p className="empty-state">{tr("Loading...")}</p>;
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
        <Field name="Code">{p.product_code}</Field>
        <Field name="Category">{p.category_name || p.category_code}</Field>
        <Field name="Status">{p.status_code}</Field>
        <Field name="Unit charge">{money(p.product_unit_charge)}</Field>
        <Field name="Average cost">{money(p.product_average_cost)}</Field>
        <Field name="On hand">{p.product_stocked ? p.product_on_hand : "Not stocked"}</Field>
      </dl>
      <div>
        <h3 className="field-label">{tr("Units of measure")}</h3>
        {p.uoms.length === 0 ? (
          <p className="empty-state">{tr("No units recorded.")}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-1 pr-4 font-medium">{tr("Unit")}</th><th className="py-1 pr-4 font-medium">{tr("Rate")}</th>
                <th className="py-1 pr-4 font-medium">{tr("Price")}</th><th className="py-1 font-medium">{tr("Cost")}</th>
              </tr>
            </thead>
            <tbody>
              {p.uoms.map((u, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="py-1.5 pr-4">{u.unit_code}{u.uom_default_price ? " (default)" : ""}</td>
                  <td className="py-1.5 pr-4">{u.uom_rate ?? "-"}</td>
                  <td className="py-1.5 pr-4">{money(u.uom_price)}</td>
                  <td className="py-1.5">{money(u.uom_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// The fee schedule has no per-row endpoint: the list row already carries everything.
function FeeDetail({ row }) {
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
      <Field name="Code">{row.fee_code}</Field>
      <Field name="Part">{row.part}</Field>
      <Field name="Group">{row.header}</Field>
      <Field name="Item">{row.sub_header}</Field>
      <Field name="Fee">{row.value}</Field>
      <Field name="Second value">{row.value2}</Field>
    </dl>
  );
}

// Paged, searchable list with one expandable row at a time. `fetchPage` returns an
// array; we ask for PAGE+1 rows so "Next" is only enabled when another page exists.
function Browser({ noun, fetchPage, idKey, nameKey, sub, Detail }) {
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim());
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(null);

  useEffect(() => setOffset(0), [dq]);
  useEffect(() => {
    let off = false;
    setRows(null);
    setError("");
    fetchPage({ q: dq, limit: PAGE + 1, offset })
      .then((r) => !off && setRows(r))
      .catch((e) => !off && setError(errorMessage(e, `Could not load ${noun}.`)));
    return () => { off = true; };
  }, [dq, offset, fetchPage, noun]);

  const more = rows && rows.length > PAGE;
  const shown = rows ? rows.slice(0, PAGE) : [];
  return (
    <div className="space-y-3">
      <div>
        <label htmlFor={`q-${noun}`} className="field-label">Search {noun}</label>
        <input id={`q-${noun}`} className="field-input" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={tr("Name, code, class or category")} autoComplete="off" />
      </div>
      {error && <p className="alert-error" role="alert">{error}</p>}
      {!error && rows === null && <p className="empty-state">{tr("Loading...")}</p>}
      {rows && shown.length === 0 && <p className="empty-state">No {noun} match{dq ? ` "${dq}"` : ""}.</p>}
      <ul className="card divide-y divide-slate-100 p-0">
        {shown.map((r) => {
          const id = r[idKey];
          const isOpen = open === id;
          return (
            <li key={id} className="px-4 py-3">
              <button type="button" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : id)}
                      className="flex w-full items-start justify-between gap-3 text-left">
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-slate-900">{r[nameKey]}</span>
                  <span className="block truncate text-xs text-slate-500">{sub(r)}</span>
                </span>
                <span className="shrink-0 text-xs text-slate-500">{isOpen ? "Hide" : "Details"}</span>
              </button>
              {isOpen && <div className="mt-3 border-t border-slate-100 pt-3"><Detail code={id} row={r} /></div>}
            </li>
          );
        })}
      </ul>
      <div className="flex items-center justify-between">
        <button type="button" className="btn-secondary" disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}>{tr("Previous")}</button>
        <span className="text-xs text-slate-500">
          {shown.length ? `${offset + 1} to ${offset + shown.length}` : ""}
        </span>
        <button type="button" className="btn-secondary" disabled={!more}
                onClick={() => setOffset(offset + PAGE)}>{tr("Next")}</button>
      </div>
    </div>
  );
}

const fetchDrugs = (p) => listDrugs(p);
const fetchProducts = (p) => listProducts(p);
const fetchFees = (p) => listFeeSchedules(p);

function CodeLists() {
  const [kinds, setKinds] = useState(null);
  const [kind, setKind] = useState("");
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim());
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    listReferenceKinds().then(setKinds).catch((e) => setError(errorMessage(e, "Could not load the code lists.")));
  }, []);
  useEffect(() => {
    if (!kind) return undefined;
    let off = false;
    setRows(null);
    setError("");
    getReferenceList(kind, { q: dq })
      .then((r) => !off && setRows(r))
      .catch((e) => !off && setError(errorMessage(e, "Could not load this list.")));
    return () => { off = true; };
  }, [kind, dq]);

  if (error && !kinds) return <p className="alert-error" role="alert">{error}</p>;
  if (!kinds) return <p className="empty-state">{tr("Loading...")}</p>;
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="kind" className="field-label">{tr("List")}</label>
          <select id="kind" className="field-input" value={kind} onChange={(e) => { setKind(e.target.value); setQ(""); }}>
            <option value="">{tr("Choose a list...")}</option>
            {Object.entries(kinds).map(([k, n]) => <option key={k} value={k}>{label(k)} ({n})</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="kq" className="field-label">{tr("Filter")}</label>
          <input id="kq" className="field-input" value={q} disabled={!kind}
                 onChange={(e) => setQ(e.target.value)} placeholder={tr("Name, code or parent (for example a city or state)")} autoComplete="off" />
        </div>
      </div>
      {error && <p className="alert-error" role="alert">{error}</p>}
      {!kind && <p className="empty-state">{tr("Choose a list to see its codes.")}</p>}
      {kind && !error && rows === null && <p className="empty-state">{tr("Loading...")}</p>}
      {rows && rows.length === 0 && <p className="empty-state">{tr("Nothing matches.")}</p>}
      {rows && rows.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="px-4 py-2 font-medium">{tr("Code")}</th>
                <th className="px-4 py-2 font-medium">{tr("Name")}</th>
                <th className="px-4 py-2 font-medium">{tr("Parent")}</th>
                <th className="px-4 py-2 font-medium">{tr("State")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.code}-${i}`} className="border-t border-slate-100">
                  <td className="px-4 py-1.5 font-mono text-xs">{r.code}</td>
                  <td className="px-4 py-1.5">{r.name}</td>
                  <td className="px-4 py-1.5 text-slate-500">
                    {r.parent_name ? `${r.parent_name} (${r.parent})` : r.parent || ""}
                  </td>
                  <td className="px-4 py-1.5 text-slate-500">{r.state_name || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// Read-only browser for the HIS drug master, product catalogue and code lists
// (backend routers/catalogue.py + reference.py). Staff accounts only.
export default function Catalogue() {
  const [tab, setTab] = useState("drugs");
  return (
    <Layout>
      <div className="mx-auto max-w-4xl space-y-4">
        <h1 className="page-title">{tr("Catalogue")}</h1>
        <div role="tablist" aria-label={tr("Catalogue sections")} className="flex gap-2">
          {TABS.map(([key, text]) => (
            <button key={key} type="button" role="tab" id={`tab-${key}`} aria-selected={tab === key}
                    aria-controls="catalogue-panel" onClick={() => setTab(key)}
                    className={tab === key ? "btn-primary" : "btn-secondary"}>
              {text}
            </button>
          ))}
        </div>
        <div role="tabpanel" id="catalogue-panel" aria-labelledby={`tab-${tab}`}>
          {tab === "drugs" && (
            <Browser noun="drugs" fetchPage={fetchDrugs} idKey="drug_code" nameKey="drug_generic_name"
                     sub={(d) => [d.trade_name, d.dosage_form, d.drug_schedule].filter(Boolean).join(" · ")}
                     Detail={DrugDetail} />
          )}
          {tab === "products" && (
            <Browser noun="products" fetchPage={fetchProducts} idKey="product_code" nameKey="product_name"
                     sub={(p) => [p.product_code, p.category_code, p.product_unit_charge != null ? money(p.product_unit_charge) : null].filter(Boolean).join(" · ")}
                     Detail={ProductDetail} />
          )}
          {tab === "fees" && (
            <Browser noun="fees" fetchPage={fetchFees} idKey="fee_code" nameKey="description"
                     sub={(f) => [f.header, f.sub_header, f.value].filter(Boolean).join(" · ")}
                     Detail={FeeDetail} />
          )}
          {tab === "lists" && <CodeLists />}
        </div>
      </div>
    </Layout>
  );
}

