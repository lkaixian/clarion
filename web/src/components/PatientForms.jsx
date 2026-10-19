import { useCallback, useEffect, useState } from "react";
import { listForms, listFormResponses, submitFormResponse, errorMessage } from "../api/client";
import { formatDateTime } from "../lib/format";
import FormFieldInput from "./FormFieldInput";
import { tr } from "../lib/i18n";

// Turns the text a user typed into the value the backend expects for that field type.
export function toFieldValue(field, raw) {
  if (field.type === "boolean") return raw === true;
  if (raw === "" || raw == null) return null;
  if (field.type === "number") return Number(raw);
  return raw;
}

function ResponseCard({ r }) {
  return (
    <li className="record-row">
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-900">{r.form_name} <span className="text-xs text-slate-400">v{r.form_version}</span></p>
        <dl className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
          {r.fields.filter((f) => r.values[f.key] !== undefined).map((f) => (
            <div key={f.key}>
              <dt className="text-slate-500">{f.label}</dt>
              <dd className="text-slate-900">{typeof r.values[f.key] === "boolean" ? (r.values[f.key] ? "Yes" : "No") : String(r.values[f.key])}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-1 text-xs text-slate-500">{r.submitted_by_name} · {formatDateTime(r.created_at)}</p>
      </div>
    </li>
  );
}

// Fill in a facility form for this patient, and see what was filled in before.
export default function PatientForms({ patientId }) {
  const [forms, setForms] = useState(null);
  const [responses, setResponses] = useState(null);
  const [error, setError] = useState("");
  const [formId, setFormId] = useState("");
  const [values, setValues] = useState({});
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const load = useCallback(() => {
    Promise.all([listForms(), listFormResponses(patientId)])
      .then(([f, r]) => { setForms(f); setResponses(r); })
      .catch((e) => setError(errorMessage(e, "Could not load forms.")));
  }, [patientId]);
  useEffect(load, [load]);

  const form = forms?.find((f) => f.id === formId) || null;

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setFormError("");
    try {
      const body = {};
      for (const f of form.fields) {
        const v = toFieldValue(f, values[f.key]);
        if (v !== null && !(f.type === "boolean" && v === false && values[f.key] === undefined)) body[f.key] = v;
      }
      await submitFormResponse(patientId, form.id, body);
      setValues({});
      setFormId("");
      load();
    } catch (err) { setFormError(errorMessage(err, "Could not save the form.")); } finally { setSaving(false); }
  }

  if (error) return <p className="alert-error" role="alert">{error}</p>;
  if (forms === null) return <p className="empty-state">{tr("Loading...")}</p>;
  return (
    <div className="space-y-3">
      {forms.length === 0 ? (
        <p className="empty-state">{tr("No forms are set up at this facility. An admin can add them under Forms.")}</p>
      ) : (
        <div>
          <label htmlFor="pf-form" className="field-label">{tr("Fill in a form")}</label>
          <select id="pf-form" className="field-input max-w-sm" value={formId}
            onChange={(e) => { setFormId(e.target.value); setValues({}); setFormError(""); }}>
            <option value="">{tr("Choose a form")}</option>
            {forms.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        </div>
      )}
      {form && (
        <form onSubmit={submit} className="space-y-3 rounded-lg border border-slate-200 p-4" aria-label={form.name}>
          <div className="grid gap-3 sm:grid-cols-2">
            {form.fields.map((f) => (
              <FormFieldInput key={f.key} field={f} value={values[f.key]} onChange={(v) => setValues((s) => ({ ...s, [f.key]: v }))} />
            ))}
          </div>
          {formError && <p className="alert-error" role="alert">{formError}</p>}
          <button type="submit" className="btn-primary" disabled={saving}>{saving ? "Saving..." : "Save form"}</button>
        </form>
      )}
      {responses && responses.length === 0 && <p className="empty-state">{tr("No forms filled in for this patient yet.")}</p>}
      {responses && responses.length > 0 && <ul>{responses.map((r) => <ResponseCard key={r.id} r={r} />)}</ul>}
    </div>
  );
}
