import { useCallback, useEffect, useState } from "react";
import Layout from "../components/Layout";
import FormFieldInput from "../components/FormFieldInput";
import { listForms, createForm, deactivateForm, errorMessage } from "../api/client";
import { tr } from "../lib/i18n";

const TYPES = [["text", "Text"], ["number", "Number"], ["select", "Choice"], ["boolean", "Yes / no"], ["date", "Date"]];
const blank = (type = "text") => ({ key: "", label: "", type, required: false, options: "", id: Math.random().toString(36).slice(2) });

// Builds the field list the API wants from the rows on screen.
export function toFields(rows) {
  return rows.map((r) => ({
    key: r.key.trim(),
    label: r.label.trim(),
    type: r.type,
    required: r.required,
    options: r.type === "select" ? r.options.split(",").map((o) => o.trim()).filter(Boolean) : null,
  }));
}

// A label becomes a valid field key: "Pain score" -> "pain_score".
export const keyFromLabel = (label) =>
  label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^[0-9]/, "f_$&").slice(0, 32);

// Same label twice would give the same key; number the later ones so the form still saves.
function withUniqueKeys(rows) {
  const used = new Set();
  return rows.map((r) => {
    let key = r.key || keyFromLabel(r.label) || "field";
    let n = 2;
    while (used.has(key)) key = `${key.replace(/_\d+$/, "")}_${n++}`;
    used.add(key);
    return { ...r, key };
  });
}

function FieldCard({ row, index, count, onChange, onMove, onRemove }) {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-3" data-testid="builder-field">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{index + 1}</span>
        <div className="min-w-[10rem] flex-1">
          <label htmlFor={`fb-label-${row.id}`} className="sr-only">{tr("Field label")}</label>
          <input id={`fb-label-${row.id}`} className="field-input" placeholder={tr("Field label, for example Pain score")}
            value={row.label} maxLength={200} onChange={(e) => onChange({ label: e.target.value })} />
        </div>
        <div>
          <label htmlFor={`fb-type-${row.id}`} className="sr-only">{tr("Type")}</label>
          <select id={`fb-type-${row.id}`} className="field-input" value={row.type}
            onChange={(e) => onChange({ type: e.target.value })}>
            {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <label className="flex items-center gap-1.5 text-sm text-slate-700">
          <input type="checkbox" checked={row.required} onChange={(e) => onChange({ required: e.target.checked })} />
          Required
        </label>
        <div className="flex gap-1">
          <button type="button" className="btn-chip" disabled={index === 0} onClick={() => onMove(-1)}
            aria-label={`Move field ${index + 1} up`}>{tr("Up")}</button>
          <button type="button" className="btn-chip" disabled={index === count - 1} onClick={() => onMove(1)}
            aria-label={`Move field ${index + 1} down`}>{tr("Down")}</button>
          <button type="button" className="btn-chip" disabled={count === 1} onClick={onRemove}
            aria-label={`Remove field ${index + 1}`}>{tr("Remove")}</button>
        </div>
      </div>
      {row.type === "select" && (
        <div className="mt-2">
          <label htmlFor={`fb-opts-${row.id}`} className="field-label">{tr("Choices, separated by commas")}</label>
          <input id={`fb-opts-${row.id}`} className="field-input" placeholder={tr("head, chest, limb")} value={row.options}
            onChange={(e) => onChange({ options: e.target.value })} />
        </div>
      )}
    </li>
  );
}

export default function FormsAdmin() {
  const [forms, setForms] = useState(null);
  const [error, setError] = useState("");
  const [code, setCode] = useState("");
  const [codeTouched, setCodeTouched] = useState(false);
  const [name, setName] = useState("");
  const [rows, setRows] = useState([blank()]);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [saved, setSaved] = useState("");

  const load = useCallback(() => {
    listForms().then(setForms).catch((e) => setError(errorMessage(e, "Could not load forms.")));
  }, []);
  useEffect(load, [load]);

  const setRow = (i, patch) => setRows((rs) => rs.map((r, n) => (n === i ? { ...r, ...patch } : r)));
  const move = (i, d) => setRows((rs) => {
    const next = [...rs];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    return next;
  });

  // What the preview shows is built from the same rows the save sends.
  const keyed = withUniqueKeys(rows);
  const previewFields = toFields(keyed).map((f) => ({ ...f, label: f.label }));

  function editExisting(f) {
    setName(f.name);
    setCode(f.code);
    setCodeTouched(true);
    setRows(f.fields.map((x) => ({ ...blank(x.type), key: x.key, label: x.label, required: !!x.required, options: (x.options || []).join(", ") })));
    setSaved("");
    setFormError("");
    window.scrollTo?.({ top: document.body.scrollHeight, behavior: "smooth" });
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setFormError("");
    setSaved("");
    try {
      await createForm({ code: code.trim(), name: name.trim(), fields: toFields(keyed) });
      setSaved(`"${name.trim()}" saved. Clinicians see it under Orders & forms on a patient.`);
      setCode(""); setCodeTouched(false); setName(""); setRows([blank()]);
      load();
    } catch (err) { setFormError(errorMessage(err, "Could not save the form.")); } finally { setSaving(false); }
  }

  return (
    <Layout>
      <div className="mx-auto max-w-5xl space-y-5">
        <h1 className="page-title">{tr("Forms")}</h1>
        <section className="card space-y-2">
          <h2 className="font-semibold text-slate-800">{tr("Active forms")}</h2>
          {error && <p className="alert-error" role="alert">{error}</p>}
          {!error && forms === null && <p className="empty-state">{tr("Loading...")}</p>}
          {forms && forms.length === 0 && <p className="empty-state">{tr("No forms yet. Build one below.")}</p>}
          <ul>
            {(forms || []).map((f) => (
              <li key={f.id} className="record-row">
                <div>
                  <p className="text-sm font-medium text-slate-900">{f.name} <span className="text-xs text-slate-400">{f.code} v{f.version}</span></p>
                  <p className="text-xs text-slate-500">{f.fields.map((x) => x.label).join(", ")}</p>
                </div>
                <div className="flex gap-1">
                  <button type="button" className="btn-chip" onClick={() => editExisting(f)}>{tr("Edit as new version")}</button>
                  <button type="button" className="btn-chip"
                    onClick={() => deactivateForm(f.id).then(load).catch((e) => setError(errorMessage(e, "Could not retire the form.")))}>
                    Retire
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>

        <form onSubmit={submit} aria-label={tr("Build a form")} className="space-y-3">
          <div className="grid gap-5 lg:grid-cols-2">
            <section className="card space-y-3">
              <h2 className="font-semibold text-slate-800">{tr("1. Build")}</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label htmlFor="fb-name" className="field-label">{tr("Form name")}</label>
                  <input id="fb-name" className="field-input" value={name} required maxLength={255}
                    onChange={(e) => {
                      setName(e.target.value);
                      if (!codeTouched) setCode(keyFromLabel(e.target.value).replace(/_/g, "-"));
                    }} />
                </div>
                <div>
                  <label htmlFor="fb-code" className="field-label">{tr("Code")}</label>
                  <input id="fb-code" className="field-input" value={code} required maxLength={64}
                    onChange={(e) => { setCode(e.target.value); setCodeTouched(true); }} />
                </div>
              </div>
              <ol className="space-y-2">
                {rows.map((r, i) => (
                  <FieldCard key={r.id} row={r} index={i} count={rows.length}
                    onChange={(p) => setRow(i, p)} onMove={(d) => move(i, d)}
                    onRemove={() => setRows((rs) => rs.filter((_, n) => n !== i))} />
                ))}
              </ol>
              <div className="flex flex-wrap gap-2" role="group" aria-label={tr("Add a field")}>
                {TYPES.map(([v, l]) => (
                  <button key={v} type="button" className="btn-add" onClick={() => setRows((rs) => [...rs, blank(v)])}>
                    + {l}
                  </button>
                ))}
              </div>
              <p className="text-xs text-slate-500">
                Saving a code that already exists makes a new version and retires the old one. Responses already
                filled in keep the version they were filled in on.
              </p>
            </section>

            <section className="card space-y-3" aria-label={tr("Preview")}>
              <h2 className="font-semibold text-slate-800">{tr("2. Preview")}</h2>
              <div className="rounded-lg border border-dashed border-slate-300 p-4">
                <p className="mb-3 text-sm font-semibold text-slate-900">{name || "Untitled form"}</p>
                <div className="grid gap-3 sm:grid-cols-2">
                  {previewFields.map((f, i) => (
                    <FormFieldInput key={rows[i].id} field={f} idPrefix="pv" readOnly />
                  ))}
                </div>
              </div>
              <p className="text-xs text-slate-500">{tr("This is how clinicians will see the form. Fields appear in this order.")}</p>
            </section>
          </div>
          {formError && <p className="alert-error" role="alert">{formError}</p>}
          {saved && <p className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800" role="status">{saved}</p>}
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? "Saving..." : "Save form"}</button>
        </form>
      </div>
    </Layout>
  );
}
