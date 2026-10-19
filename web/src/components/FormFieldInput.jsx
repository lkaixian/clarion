import { tr } from "../lib/i18n";
// One input for one field of a clinical form. Shared by the patient form screen and the form
// builder's live preview, so what an admin sees while building is what a clinician gets.
export default function FormFieldInput({ field, value, onChange, idPrefix = "ff", readOnly = false }) {
  const id = `${idPrefix}-${field.key || "new"}`;
  if (field.type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" id={id} checked={value === true} disabled={readOnly}
          onChange={(e) => onChange?.(e.target.checked)} />
        {field.label || "Untitled field"}
      </label>
    );
  }
  return (
    <div>
      <label htmlFor={id} className="field-label">
        {field.label || "Untitled field"}{field.required ? " *" : ""}
      </label>
      {field.type === "select" ? (
        <select id={id} className="field-input" value={value ?? ""} disabled={readOnly}
          onChange={(e) => onChange?.(e.target.value)}>
          <option value="">{tr("Select")}</option>
          {(field.options || []).map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : (
        <input
          id={id} className="field-input" value={value ?? ""} disabled={readOnly}
          onChange={(e) => onChange?.(e.target.value)}
          type={field.type === "number" ? "number" : field.type === "date" ? "date" : "text"}
          step={field.type === "number" ? "any" : undefined}
        />
      )}
    </div>
  );
}
