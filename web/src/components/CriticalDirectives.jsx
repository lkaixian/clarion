import { useCallback, useEffect, useState } from "react";
import { addPatientDirective, errorMessage, getMyDirectives, getPatientDirectives, putMyDirective } from "../api/client";
import { tr } from "../lib/i18n";

const KINDS = ["organ_donation", "blood_transfusion", "implanted_device", "advance_directive"];
const CHOICE = ["organ_donation", "blood_transfusion"];
const LABEL = {
  organ_donation: "Organ donation",
  blood_transfusion: "Blood transfusion",
  implanted_device: "Implanted device",
  advance_directive: "Advance directive",
};
const INPUT = "border border-slate-300 rounded-lg px-3 py-2 w-full text-sm";
const BTN = "bg-blue-800 hover:bg-blue-900 text-white text-sm font-semibold px-4 py-2 rounded-lg disabled:opacity-50";

export const NOT_LEGAL_PROOF = "This is information recorded in CLARION. It is not legal proof of consent or refusal.";

const valueText = (v) => (v === "yes" ? tr("Yes") : v === "no" ? tr("No") : v === "undecided" ? tr("Undecided") : v);
const sourceText = (source, ref) =>
  source === "patient" ? tr("patient-declared")
    : source === "guardian" ? tr("declared by a guardian")
    : `${tr("recorded by staff")}${ref ? ` (${tr("form")} ${ref})` : ""}`;

// Read-only list for the emergency pages: { kind, value, source, evidence_ref? , label } items from /emergency/scan.
export function DirectivesBlock({ items }) {
  if (!items || !items.length) return null;
  return (
    <section aria-labelledby="em-dir">
      <h2 id="em-dir" className="mb-2 text-xl font-bold">{tr("Critical personal directives")}</h2>
      <ul className="space-y-1 text-xl">
        {items.map((d) => (
          <li key={d.kind}>
            {tr(LABEL[d.kind] || d.kind)}: <strong>{valueText(d.value)}</strong>
            <span className="block text-sm text-slate-600">
              {d.source === "patient" ? tr("patient-declared") : tr(d.label)}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-sm text-slate-600">{tr(NOT_LEGAL_PROOF)}</p>
    </section>
  );
}

function Who({ d }) {
  return (
    <span className="block text-xs text-slate-500">
      {sourceText(d.source, d.evidence_ref)}
      {d.recorded_by_name ? ` - ${d.recorded_by_name}` : ""}{d.recorded_by_role ? ` (${d.recorded_by_role})` : ""}
      {d.recorded_by_facility ? `, ${d.recorded_by_facility}` : ""} - {String(d.recorded_at).slice(0, 16).replace("T", " ")}
    </span>
  );
}

const initial = (kind) => (CHOICE.includes(kind) ? "undecided" : "");

// mode="self": the signed-in patient (or the profile they act for) declares their own.
// mode="staff": record from a signed form for patientId; the form number is required.
export default function CriticalDirectives({ mode, patientId, readOnly = false }) {
  const staff = mode === "staff";
  const [data, setData] = useState({ current: [], history: [] });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [kind, setKind] = useState(KINDS[0]);
  const [value, setValue] = useState(initial(KINDS[0]));
  const [note, setNote] = useState("");
  const [evidence, setEvidence] = useState("");

  const load = useCallback(() => {
    (staff ? getPatientDirectives(patientId) : getMyDirectives())
      .then(setData)
      .catch((e) => setError(errorMessage(e, tr("Could not load critical information."))));
  }, [staff, patientId]);
  useEffect(() => { load(); }, [load]);

  const pickKind = (k) => { setKind(k); setValue(initial(k)); };

  async function submit(e) {
    e.preventDefault();
    setError("");
    if (staff && !evidence.trim()) return setError(tr("Enter the signed form number."));
    setBusy(true);
    try {
      const body = { value, note: note || null };
      if (staff) await addPatientDirective(patientId, { ...body, kind, evidence_ref: evidence });
      else await putMyDirective(kind, body);
      setNote(""); setEvidence(""); setValue(initial(kind));
      load();
    } catch (ex) {
      setError(errorMessage(ex, tr("Could not save.")));
    } finally {
      setBusy(false);
    }
  }

  const cur = Object.fromEntries(data.current.map((d) => [d.kind, d]));
  return (
    <div className="text-sm text-slate-700">
      {error && <p role="alert" className="mb-2 text-red-600">{error}</p>}
      <ul className="mb-3 space-y-2">
        {KINDS.map((k) => (
          <li key={k}>
            <strong>{tr(LABEL[k])}</strong>:{" "}
            {cur[k] && cur[k].value ? valueText(cur[k].value) : <span className="text-slate-500">{tr("Not recorded")}</span>}
            {cur[k] && cur[k].note && <span className="block text-xs">{cur[k].note}</span>}
            {cur[k] && cur[k].value && <Who d={cur[k]} />}
          </li>
        ))}
      </ul>
      {!readOnly && <form onSubmit={submit} className="space-y-2 border-t border-slate-200 pt-3">
        <label className="block">
          <span className="field-label">{tr("Item")}</span>
          <select className={INPUT} value={kind} onChange={(e) => pickKind(e.target.value)}>
            {KINDS.map((k) => <option key={k} value={k}>{tr(LABEL[k])}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="field-label">{tr("Value")}</span>
          {CHOICE.includes(kind) ? (
            <select className={INPUT} value={value} onChange={(e) => setValue(e.target.value)}>
              <option value="yes">{tr("Yes")}</option>
              <option value="no">{tr("No")}</option>
              <option value="undecided">{tr("Undecided")}</option>
            </select>
          ) : (
            <input className={INPUT} maxLength={300} value={value} onChange={(e) => setValue(e.target.value)}
              placeholder={tr("Leave empty to clear")} />
          )}
        </label>
        <label className="block">
          <span className="field-label">{tr("Note (optional, for example which organs)")}</span>
          <input className={INPUT} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        {staff && (
          <label className="block">
            <span className="field-label">{tr("Signed form number")}</span>
            <input className={INPUT} maxLength={120} value={evidence} onChange={(e) => setEvidence(e.target.value)} />
          </label>
        )}
        <button className={BTN} disabled={busy}>{tr("Save")}</button>
      </form>}
      <p className="mt-2 text-xs text-slate-500">
        {tr(NOT_LEGAL_PROOF)} {tr("Every change is kept as a new entry; earlier entries are never overwritten.")}
      </p>
      {staff && data.history.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer font-semibold">{tr("History")} ({data.history.length})</summary>
          <ul className="mt-2 space-y-2">
            {data.history.map((d) => (
              <li key={d.id}>
                {tr(LABEL[d.kind] || d.kind)}: <strong>{d.value ? valueText(d.value) : tr("Cleared")}</strong>
                {d.note ? ` - ${d.note}` : ""}<Who d={d} />
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
