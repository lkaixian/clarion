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
  getReportDatasets, runReport, exportReport,
  listReportTemplates, createReportTemplate, deleteReportTemplate,
} from "../api/client";

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
        <span className="text-xs text-slate-400 self-center">to</span>
        <input type="date" value={value?.to || ""} onChange={(e) => onChange({ ...value, to: e.target.value })}
          className="border border-slate-300 rounded px-2 py-1 text-xs" />
      </div>
    );
  }
  if (spec.type === "number") {
    return (
      <div className="flex gap-2">
        <input type="number" placeholder="min" value={value?.min ?? ""} onChange={(e) => onChange({ ...value, min: e.target.value })}
          className="w-20 border border-slate-300 rounded px-2 py-1 text-xs" />
        <input type="number" placeholder="max" value={value?.max ?? ""} onChange={(e) => onChange({ ...value, max: e.target.value })}
          className="w-20 border border-slate-300 rounded px-2 py-1 text-xs" />
      </div>
    );
  }
  if (spec.type === "bool") {
    return (
      <select value={value} onChange={(e) => onChange(e.target.value)} className="border border-slate-300 rounded px-2 py-1 text-xs">
        <option value="">Any</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </select>
    );
  }
  return (
    <input type="text" value={value} onChange={(e) => onChange(e.target.value)} placeholder="contains..."
      className="border border-slate-300 rounded px-2 py-1 text-xs w-full" />
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

  const [result, setResult] = useState(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

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
    };
  }

  function run() {
    setRunning(true);
    setError("");
    runReport(buildPayload())
      .then(setResult)
      .catch((e) => setError(e?.response?.data?.detail || "Failed to run report."))
      .finally(() => setRunning(false));
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
        <h1 className="text-2xl font-bold text-slate-800">Reporting</h1>
        <p className="text-sm text-slate-500">Canned operational reports and a custom report builder, scoped to your facility.</p>
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
            <label className="block text-xs font-semibold text-slate-500 mb-1">Dataset</label>
            <select value={datasetKey} onChange={(e) => setDatasetKey(e.target.value)}
              className="w-full border border-slate-300 rounded px-2 py-1.5 text-sm">
              {datasets.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
            </select>

            <div className="mt-4">
              <div className="text-xs font-semibold text-slate-500 mb-1">Fields</div>
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
                <div className="text-xs font-semibold text-slate-500 mb-1">Group by</div>
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
              <div className="text-xs font-semibold text-slate-500 mb-1">Sort</div>
              <div className="flex gap-2">
                <select value={sortField} onChange={(e) => setSortField(e.target.value)}
                  className="flex-1 border border-slate-300 rounded px-2 py-1 text-xs">
                  <option value="">None</option>
                  {sortOptions.map((k) => <option key={k} value={k}>{fieldSpecs[k]?.label || k}</option>)}
                </select>
                <select value={sortDir} onChange={(e) => setSortDir(e.target.value)}
                  className="border border-slate-300 rounded px-2 py-1 text-xs">
                  <option value="asc">Asc</option>
                  <option value="desc">Desc</option>
                </select>
              </div>
            </div>

            <button onClick={run} disabled={running || !fields.length}
              className="mt-4 w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg">
              {running ? "Running..." : "Run report"}
            </button>
          </div>

          {filterableFields.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="text-xs font-semibold text-slate-500 mb-2">Filters</div>
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
            <div className="text-xs font-semibold text-slate-500 mb-2">Saved templates</div>
            <div className="space-y-1 mb-3 max-h-40 overflow-y-auto">
              {templates.length === 0 && <p className="text-xs text-slate-400">None saved for this dataset yet.</p>}
              {templates.map((t) => (
                <div key={t.id} className="flex items-center justify-between text-sm gap-2">
                  <button onClick={() => loadTemplate(t)} className="text-blue-700 hover:underline truncate text-left">
                    {t.name}{t.is_shared && <span className="text-xs text-slate-400"> (shared)</span>}
                  </button>
                  {t.editable && (
                    <button onClick={() => removeTemplate(t)} className="text-xs text-red-500 hover:underline shrink-0">Delete</button>
                  )}
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <input type="text" value={templateName} onChange={(e) => setTemplateName(e.target.value)}
                placeholder="Template name" className="flex-1 border border-slate-300 rounded px-2 py-1 text-xs" />
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
            {!result && <p className="text-sm text-slate-400">Pick fields and run the report to see results here.</p>}
            {result && (
              <>
                <div className="flex items-center justify-between mb-3">
                  <p className="text-sm text-slate-500">{result.row_count} row(s){result.truncated && " (capped -- narrow your filters for a complete export)"}</p>
                  <div className="flex gap-2">
                    <button onClick={() => doExport("pdf")} className="text-xs bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded">Export PDF</button>
                    <button onClick={() => doExport("excel")} className="text-xs bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded">Export Excel</button>
                  </div>
                </div>
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
                  {result.rows.length === 0 && <p className="text-sm text-slate-400 py-4">No rows matched.</p>}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}
