import { useEffect, useState } from "react";
import { listDrugs } from "../api/client";

// Drug-master suggestions for a free-text drug name. Free text stays valid (external or
// unlisted drugs are common); the server links an exact name match to the catalogue.
// Point an input's `list` at `id`.
export default function DrugHints({ id, query }) {
  const [rows, setRows] = useState([]);
  useEffect(() => {
    const q = String(query || "").trim();
    if (q.length < 3) { setRows([]); return undefined; }
    let off = false;
    const t = setTimeout(() => {
      listDrugs({ q, limit: 8 }).then((r) => !off && setRows(r)).catch(() => !off && setRows([]));
    }, 250);
    return () => { off = true; clearTimeout(t); };
  }, [query]);
  return (
    <datalist id={id}>
      {rows.map((d) => (
        <option key={d.drug_code} value={d.drug_generic_name}>
          {[d.trade_name, d.dosage_form].filter(Boolean).join(", ")}
        </option>
      ))}
    </datalist>
  );
}

// Small marker next to a drug name that is linked to the catalogue.
export function CatalogueTag({ code }) {
  return code ? <span className="ml-2 text-xs text-slate-500">Catalogue {code}</span> : null;
}
