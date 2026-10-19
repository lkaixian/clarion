// P3.6 Reporting -- canned operational reports + Custom Report
// Builder. Reachable by admin/records_officer/clinician only
// (require_page_access("reporting") + REPORTING_ROLES in
// routers/reporting.py). One page: pick a dataset, pick fields/filters/
// group-by/sort, run, export PDF/Excel, optionally save the selection as a
// template (private or shared with the facility).
//
// The field picker/filters/group-by are rendered GENERICALLY off
// GET /reports/datasets' field catalogue -- never a hardcoded field list
// here, matching app/reporting_engine.py's "no raw column name reaches the
// server" design (see that module's docstring).
import { useEffect, useMemo, useState } from "react";
import Layout from "../components/Layout";
import {
  getReportDatasets, runReport, exportReport, narrateReport,
  listReportTemplates, createReportTemplate, deleteReportTemplate,
  listNotifiableDiseaseCandidates, listNotifiableDiseaseReports,
  createNotifiableDiseaseReport, markNotifiableDiseaseSubmitted, getNotifiableDiseaseDocumentBlob,
} from "../api/client";
import { tr } from "../lib/i18n";

function emptyFilterValue(type) {
  if (type === "enum") return [];
  if (type === "date") return { from: "", to: "" };
  if (type === "number") return { min: "", max: "" };
  if (type === "bool") return "";
  return "";
}

function isFilterEmpty(type, v) {
  if (type === "enum") return !v || v.length === 0;
  if (type === "date") return !v?.from && !v?.to;
  if (type === "number") return v?.min === "" && v?.max === "";
  if (type === "bool") return v === "";
  return !v;
}

// Strips empty filter values and coerces number-typed inputs before the
// request leaves the browser -- the server only sees filters the user
// actually set.
function cleanFilters(filterState, fieldSpecs) {
  const out = {};
  for (const [key, value] of Object.entries(filterState)) {
    const spec = fieldSpecs[key];
    if (!spec || isFilterEmpty(spec.type, value)) continue;
    if (spec.type === "number") {
      out[key] = {
        ...(value.min !== "" ? { min: Number(value.min) } : {}),
        ...(value.max !== "" ? { max: Number(value.max) } : {}),
      };
    } else if (spec.type === "bool") {
      out[key] = value === "true";
    } else {
      out[key] = value;
    }
  }
  return out;
}

function FilterInput({ spec, value, onChange }) {
  if (spec.type === "enum") {
    const selected = new Set(value || []);
    return (
      <div className="flex flex-wrap gap-1">
        {(spec.options || []).map((opt) => (
          <button
            key={opt}
            type="button"
            onClick={() => {
              const next = new Set(selected);
              if (next.has(opt)) next.delete(opt); else next.add(opt);
              onChange([...next]);
            }}
            className={`text-xs px-2 py-1 rounded-full border ${
              selected.has(opt) ? "bg-blue-600 text-white border-blue-600" : "bg-white text-slate-600 border-slate-300"
            }`}
          >
            {opt}
          </button>
        ))}
      </div>
    );
  }
  if (spec.type === "date") {
    return (
      <div className="flex gap-2">
        <input type="date" value={value?.from || ""} onChange={(e) => onChange({ ...value, from: e.target.value })}
          className="border border-slate-300 rounded px-2 py-1 text-xs" />
        <span className="text-xs text-slate-400 self-center">{tr("to")}</span>
        <input type="date" value={value?.to || ""} onChange={(e) => onChange({ ...value, to: e.target.value })}
          className="border border-slate-300 rounded px-2 py-1 text-xs" />
      </div>
    );
  }
  if (spec.type === "number") {
    return (
      <div className="flex gap-2">
        <input type="number" placeholder={tr("min")} value={value?.min ?? ""} onChange={(e) => onChange({ ...value, min: e.target.value })}
          className="w-20 border border-slate-300 rounded px-2 py-1 text-xs" />
        <input type="number" placeholder={tr("max")} value={value?.max ?? ""} onChange={(e) => onChange({ ...value, max: e.target.value })}
          className="w-20 border border-slate-300 rounded px-2 py-1 text-xs" />
      </div>
    );
  }
  if (spec.type === "bool") {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)} className="border border-slate-300 rounded px-2 py-1 text-xs">
        <option value="">{tr("Any")}</option>
        <option value="true">{tr("Yes")}</option>
        <option value="false">{tr("No")}</option>
      </select>
    );
  }
  return (
    <input type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder={tr("contains...")}
      className="border border-slate-300 rounded px-2 py-1 text-xs w-full" />
  );
}

// P3.7 ("notifiable disease reports"). No public e-Notifikasi
// API exists, so this is deliberately a checklist + PDF generator, not a
// live submission -- "File" records the notification and lets staff mark
// it submitted once they've filed it at enotifikasi.moh.gov.my by hand.
function NotifiableDiseasePanel() {
  const [candidates, setCandidates] = useState([]);
  const [reports, setReports] = useState([]);
  const [filingCondition, setFilingCondition] = useState(null); // candidate being filed, or null
  const [onsetDate, setOnsetDate] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");

  function refresh() {
    listNotifiableDiseaseCandidates().then(setCandidates).catch(() => {});
    listNotifiableDiseaseReports().then(setReports).catch(() => {});
  }
  useEffect(refresh, []);

  function startFiling(candidate) {
    setFilingCondition(candidate);
    setOnsetDate(candidate.diagnosed_at || "");
    setNotes("");
  }

  function confirmFiling() {
    createNotifiableDiseaseReport({
      patient_id: filingCondition.patient_id,
      condition_id: filingCondition.condition_id,
      disease_name: filingCondition.matched_disease,
      onset_date: onsetDate || undefined,
      notes: notes || undefined,
    })
      .then(() => { setFilingCondition(null); refresh(); })
      .catch((e) => setError(e?.response?.data?.detail || "Failed to file notification."));
  }

  function markSubmitted(reportId) {
    markNotifiableDiseaseSubmitted(reportId).then(refresh)
      .catch((e) => setError(e?.response?.data?.detail || "Failed to update."));
  }

  function openDocument(reportId) {
    getNotifiableDiseaseDocumentBlob(reportId).then((blob) => {
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    }).catch((e) => setError(e?.response?.data?.detail || "Failed to open document."));
  }

  return (
    <div className="mt-6 bg-white rounded-xl border border-slate-200 p-4">
      <h2 className="text-sm font-semibold text-slate-700 mb-1">{tr("Notifiable disease reports")}</h2>
      <p className="text-xs text-slate-400 mb-3">
        Suggested from diagnoses matching MOH's notifiable disease list -- file, then submit at{" "}
        <a href="https://enotifikasi.moh.gov.my" target="_blank" rel="noreferrer" className="text-blue-700 hover:underline">{tr("enotifikasi.moh.gov.my")}</a>{" "}
        (no public API exists to do this automatically) and mark it done here.
      </p>
      {error && (
        <div className="mb-3 text-sm rounded-lg px-3 py-2 bg-red-50 border border-red-200 text-red-700 flex items-start justify-between gap-3">
          <span>{error}</span>
          <button onClick={() => setError("")} className="shrink-0 font-medium">✕</button>
        </div>
      )}

      {candidates.length > 0 && (
        <div className="mb-4">
          <div className="text-xs font-semibold text-slate-500 mb-1">{tr("Candidates")}</div>
          <div className="space-y-2">
            {candidates.map((c) => (
              <div key={c.condition_id} className="text-sm border border-slate-100 rounded-lg p-2">
                <div className="flex items-center justify-between gap-2">
                  <span>{c.patient_name} -- {c.matched_disease} <span className="text-xs text-slate-400">({c.condition_name})</span></span>
                  <button onClick={() => startFiling(c)} className="text-xs bg-blue-600 hover:bg-blue-700 text-white px-2 py-1 rounded shrink-0">{tr("File")}</button>
                </div>
                {filingCondition?.condition_id === c.condition_id && (
                  <div className="mt-2 flex flex-wrap items-end gap-2">
                    <div>
                      <div className="text-xs text-slate-500">{tr("Onset date")}</div>
                      <input type="text" value={onsetDate} onChange={(e) => setOnsetDate(e.target.value)}
                        placeholder={tr("YYYY-MM-DD")} className="border border-slate-300 rounded px-2 py-1 text-xs w-32" />
                    </div>
                    <div className="flex-1 min-w-[120px]">
                      <div className="text-xs text-slate-500">{tr("Notes")}</div>
                      <input type="text" value={notes} onChange={(e) => setNotes(e.target.value)}
                        className="border border-slate-300 rounded px-2 py-1 text-xs w-full" />
                    </div>
                    <button onClick={confirmFiling} className="text-xs bg-slate-800 hover:bg-slate-900 text-white px-2 py-1 rounded">{tr("Confirm")}</button>
                    <button onClick={() => setFilingCondition(null)} className="text-xs text-slate-500 hover:underline">{tr("Cancel")}</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="text-xs font-semibold text-slate-500 mb-1">{tr("Filed")}</div>
      {reports.length === 0 && <p className="text-xs text-slate-400">{tr("None filed yet.")}</p>}
      <div className="space-y-1">
        {reports.map((r) => (
          <div key={r.id} className="flex items-center justify-between gap-2 text-sm border-b border-slate-100 py-1">
            <span>
              {r.patient_name} -- {r.disease_name}{" "}
              <span className={`text-xs ${r.status === "submitted" ? "text-green-600" : "text-amber-600"}`}>({r.status})</span>
            </span>
            <div className="flex gap-2 shrink-0">
              <button onClick={() => openDocument(r.id)} className="text-xs text-blue-700 hover:underline">{tr("PDF")}</button>
              {r.status !== "submitted" && (
                <button onClick={() => markSubmitted(r.id)} className="text-xs text-slate-500 hover:underline">{tr("Mark submitted")}</button>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Reporting() {
  const [datasets, setDatasets] = useState([]);
  const [datasetKey, setDatasetKey] = useState("");
  const [fields, setFields] = useState([]); // selected field keys, in order
  const [filterState, setFilterState] = useState({}); // field -> raw UI value
  const [groupBy, setGroupBy] = useState([]);
  const [sortField, setSortField] = useState("");
  const [sortDir, setSortDir] = useState("asc");
  const [anonymize, setAnonymize] = useState(false);

  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [narrative, setNarrative] = useState(null); // { narrative, disclaimer } | null
  const [narrating, setNarrating] = useState(false);

  const [templates, setTemplates] = useState([]);
  const [templateName, setTemplateName] = useState("");
  const [templateShared, setTemplateShared] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getReportDatasets().then((data) => {
      setDatasets(data);
      if (data.length) setDatasetKey(data[0].key);
    }).catch(() => setError("Failed to load report datasets."));
  }, []);

  const dataset = datasets.find((d) => d.key === datasetKey);
  // Memoized so useMemo hooks below that depend on it (groupableFields/
  // filterableFields) don't recompute every render off a fresh {} literal.
  const fieldSpecs = useMemo(() => dataset?.fields || {}, [dataset]);

  // Reset the builder to the dataset's defaults whenever the dataset changes.
  useEffect(() => {
    if (!dataset) return;
    setFields(dataset.default_fields || []);
    setFilterState({});
    setGroupBy([]);
    setSortField("");
    setResult(null);
  }, [datasetKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!datasetKey) return;
    listReportTemplates(datasetKey).then(setTemplates).catch(() => {});
  }, [datasetKey]);

  const groupableFields = useMemo(
    () => Object.entries(fieldSpecs).filter(([, s]) => s.groupable),
    [fieldSpecs]
  );
  const filterableFields = useMemo(
    () => Object.entries(fieldSpecs).filter(([, s]) => s.filterable),
    [fieldSpecs]
  );
  const sortOptions = groupBy.length
    ? [...groupBy, "count"]
    : fields;

  function toggleField(key) {
    setFields((prev) => (prev.includes(key) ? prev.filter((f) => f !== key) : [...prev, key]));
  }
  function toggleGroupBy(key) {
    setGroupBy((prev) => (prev.includes(key) ? prev.filter((f) => f !== key) : [...prev, key]));
  }

  function buildPayload() {
    return {
      dataset: datasetKey,
      fields,
      filters: cleanFilters(filterState, fieldSpecs),
      group_by: groupBy.length ? groupBy : undefined,
      sort: sortField ? { field: sortField, dir: sortDir } : undefined,
      anonymize,
    };
  }

  const hasPiiField = fields.some((k) => fieldSpecs[k]?.pii);

  function run() {
    setRunning(true);
    setError("");
    setNarrative(null); // stale narrative belongs to the previous result, not this one
    runReport(buildPayload())
      .then(setResult)
      .catch((e) => setError(e?.response?.data?.detail || "Failed to run report."))
      .finally(() => setRunning(false));
  }

  function doNarrate() {
    setNarrating(true);
    setError("");
    narrateReport(buildPayload())
      .then(setNarrative)
      .catch((e) => setError(e?.response?.data?.detail || "Failed to generate narrative."))
      .finally(() => setNarrating(false));
  }

  function doExport(format) {
    setError("");
    exportReport({ ...buildPayload(), format })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        window.open(url, "_blank");
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      })
      .catch((e) => setError(e?.response?.data?.detail || "Export failed."));
  }

  function saveTemplate() {
    if (!templateName.trim()) return;
    setSaving(true);
    createReportTemplate({
      name: templateName.trim(), dataset: datasetKey, fields,
      filters: cleanFilters(filterState, fieldSpecs),
      group_by: groupBy.length ? groupBy : undefined,
      sort: sortField ? { field: sortField, dir: sortDir } : undefined,
      is_shared: templateShared,
    })
      .then((row) => { setTemplates((prev) => [row, ...prev]); setTemplateName(""); setTemplateShared(false); })
      .catch((e) => setError(e?.response?.data?.detail || "Failed to save template."))
      .finally(() => setSaving(false));
  }

  function loadTemplate(t) {
    setFields(t.fields);
    const restored = {};
    for (const [k, v] of Object.entries(t.filters || {})) restored[k] = v;
    setFilterState(restored);
    setGroupBy(t.group_by || []);
    setSortField(t.sort?.field || "");
    setSortDir(t.sort?.dir || "asc");
  }

  function removeTemplate(t) {
    deleteReportTemplate(t.id)
      .then(() => setTemplates((prev) => prev.filter((x) => x.id !== t.id)))
      .catch((e) => setError(e?.response?.data?.detail || "Failed to delete template."));
  }

  return (
    <Layout>
      <div className="mb-6">
        <h1 className="page-title">{tr("Reporting")}</h1>
        <p className="text-sm text-slate-500">{tr("Canned operational reports and a custom report builder, scoped to your facility.")}</p>
      </div>

      {error && (
        <div className="mb-4 text-sm rounded-lg px-3 py-2 bg-red-50 border border-red-200 text-red-700 flex items-start justify-between gap-3">
          <span>{error}</span>
          <button onClick={() => setError("")} className="shrink-0 font-medium">✕</button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-1 space-y-4">
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <label className="block text-xs font-semibold text-slate-500 mb-1">{tr("Dataset")}</label>
            <select value={datasetKey} onChange={(e) => setDatasetKey(e.target.value)}
              className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm">
              {datasets.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
            </select>

            <div className="mt-4">
              <div className="text-xs font-semibold text-slate-500 mb-1">{tr("Fields")}</div>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {Object.entries(fieldSpecs).map(([key, spec]) => (
                  <label key={key} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={fields.includes(key)} onChange={() => toggleField(key)} />
                    {spec.label}
                  </label>
                ))}
              </div>
            </div>

            {groupableFields.length > 0 && (
              <div className="mt-4">
                <div className="text-xs font-semibold text-slate-500 mb-1">{tr("Group by")}</div>
                <div className="space-y-1">
                  {groupableFields.map(([key, spec]) => (
                    <label key={key} className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={groupBy.includes(key)} onChange={() => toggleGroupBy(key)} />
                      {spec.label}
                    </label>
                  ))}
                </div>
                {groupBy.length > 0 && (
                  <p className="text-xs text-slate-400 mt-1">
                    Rows collapse to one per {groupBy.length > 1 ? "combination" : "value"}, with a count and the average of any numeric field also selected.
                  </p>
                )}
              </div>
            )}

            <div className="mt-4">
              <div className="text-xs font-semibold text-slate-500 mb-1">{tr("Sort")}</div>
              <div className="flex gap-2">
                <select value={sortField} onChange={(e) => setSortField(e.target.value)}
                  className="flex-1 border border-slate-300 rounded px-2 py-1 text-xs">
                  <option value="">{tr("None")}</option>
                  {sortOptions.map((k) => <option key={k} value={k}>{fieldSpecs[k]?.label || k}</option>)}
                </select>
                <select value={sortDir} onChange={(e) => setSortDir(e.target.value)}
                  className="border border-slate-300 rounded px-2 py-1 text-xs">
                  <option value="asc">{tr("Asc")}</option>
                  <option value="desc">{tr("Desc")}</option>
                </select>
              </div>
            </div>

            {hasPiiField && (
              <label className="flex items-center gap-2 text-xs text-slate-500 mt-4">
                <input type="checkbox" checked={anonymize} onChange={(e) => setAnonymize(e.target.checked)} />
                Anonymize patient name / NRIC
              </label>
            )}

            <button onClick={run} disabled={running || !fields.length}
              className="mt-4 w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg">
              {running ? "Running..." : "Run report"}
            </button>
          </div>

          {filterableFields.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-xs font-semibold text-slate-500 mb-2">{tr("Filters")}</div>
              <div className="space-y-3">
                {filterableFields.map(([key, spec]) => (
                  <div key={key}>
                    <div className="text-xs text-slate-600 mb-1">{spec.label}</div>
                    <FilterInput
                      spec={spec}
                      value={filterState[key] ?? emptyFilterValue(spec.type)}
                      onChange={(v) => setFilterState((prev) => ({ ...prev, [key]: v }))}
                    />
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="text-xs font-semibold text-slate-500 mb-2">{tr("Saved templates")}</div>
            <div className="space-y-1 mb-3 max-h-40 overflow-y-auto">
              {templates.length === 0 && <p className="text-xs text-slate-400">{tr("None saved for this dataset yet.")}</p>}
              {templates.map((t) => (
                <div key={t.id} className="flex items-center justify-between text-sm gap-2">
                  <button onClick={() => loadTemplate(t)} className="text-blue-700 hover:underline truncate text-left">
                    {t.name}{t.is_shared && <span className="text-xs text-slate-400"> (shared)</span>}
                  </button>
                  {t.editable && (
                    <button onClick={() => removeTemplate(t)} className="text-xs text-red-500 hover:underline shrink-0">{tr("Delete")}</button>
                  )}
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <input type="text" value={templateName} onChange={(e) => setTemplateName(e.target.value)}
                placeholder={tr("Template name")} className="flex-1 border border-slate-300 rounded px-2 py-1 text-xs" />
              <button onClick={saveTemplate} disabled={saving || !templateName.trim() || !fields.length}
                className="text-xs bg-slate-100 hover:bg-slate-200 disabled:opacity-50 px-2 py-1 rounded">
                Save
              </button>
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-500 mt-2">
              <input type="checkbox" checked={templateShared} onChange={(e) => setTemplateShared(e.target.checked)} />
              Share with everyone at my facility
            </label>
          </div>
        </div>

        <div className="lg:col-span-2">
          <div className="bg-white rounded-xl border border-slate-200 p-4 min-h-[200px]">
            {!result && <p className="text-sm text-slate-400">{tr("Pick fields and run the report to see results here.")}</p>}
            {result && (
              <>
                <div className="flex items-center justify-between mb-3">
                  <p className="text-sm text-slate-500">{result.row_count} row(s){result.truncated && " (capped -- narrow your filters for a complete export)"}</p>
                  <div className="flex gap-2">
                    <button onClick={doNarrate} disabled={narrating || !result.rows.length}
                      className="text-xs bg-slate-100 hover:bg-slate-200 disabled:opacity-50 px-3 py-1.5 rounded">
                      {narrating ? "Narrating..." : "✨ Narrate"}
                    </button>
                    <button onClick={() => doExport("pdf")} className="text-xs bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded">{tr("Export PDF")}</button>
                    <button onClick={() => doExport("excel")} className="text-xs bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded">{tr("Export Excel")}</button>
                  </div>
                </div>
                {narrative && (
                  <div className="mb-3 text-sm rounded-lg px-3 py-2 bg-blue-50 border border-blue-100 text-slate-700">
                    {narrative.narrative || (
                      <span className="text-slate-400 italic">
                        No narrative available -- the local AI engine isn't running (the table above is unaffected).
                      </span>
                    )}
                    <p className="text-xs text-slate-400 mt-1">{narrative.disclaimer}</p>
                  </div>
                )}
                <div className="overflow-x-auto">
                  <table className="min-w-full text-sm">
                    <thead>
                      <tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                        {result.columns.map((c) => <th key={c.key} className="py-1.5 pr-4 font-semibold">{c.label}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.map((row, i) => (
                        <tr key={i} className="border-b border-slate-100">
                          {row.map((v, j) => <td key={j} className="py-1.5 pr-4 whitespace-nowrap">{v === null || v === undefined ? "-" : String(v)}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {result.rows.length === 0 && <p className="text-sm text-slate-400 py-4">{tr("No rows matched.")}</p>}
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      <NotifiableDiseasePanel />
    </Layout>
  );
}
