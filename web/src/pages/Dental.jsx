// P3.2 Dental module UI -- FDI tooth chart + per-entry sign-off.
// Reachable by admin/records_officer/clinician only (server-side gated via
// require_page_access("dental") + CHART_ROLES in routers/dental.py) --
// receptionist/pharmacist get a 403 from the API calls below and never see a
// working UI here, matching the intent. Every role that CAN reach this page
// gets the full set of controls (no receptionist-restricted subset like
// Ancillary.jsx has), so there is no role-gating inside the component beyond
// pulling `user` for signature/attribution display.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Layout from "../components/Layout";
import SignaturePad from "../components/SignaturePad";
import {
  getCurrentUser,
  refreshCurrentUser,
  getDentalChartOptions,
  getDentalChart,
  createDentalChartEntry,
  listPatients,
  getMySignatureBlob,
} from "../api/client";
import { formatDateTime } from "../lib/format";

// Deliberately a plain, clearly-labeled grid grouped by FDI quadrant -- not
// an anatomically mirrored dentist's-eye-view layout. Labeling correctness
// matters far more than layout convention for this pass.
const QUADRANTS = [
  { prefix: "1", label: "Upper Right (11–18)" },
  { prefix: "2", label: "Upper Left (21–28)" },
  { prefix: "3", label: "Lower Left (31–38)" },
  { prefix: "4", label: "Lower Right (41–48)" },
];

export default function Dental() {
  // Held in state, not a plain const -- a dental visit is naturally a
  // multi-entry session (several teeth per patient), unlike PatientDetail's
  // one-shot annotation sign-off modal. Without refreshing after a
  // first-entry on-the-spot signature save, `hasSignature` would stay stale
  // (getCurrentUser() is a localStorage snapshot) and force a signature
  // redraw on every subsequent tooth in the same visit.
  const [user, setUser] = useState(getCurrentUser());
  const hasSignature = !!user?.has_signature;

  const [options, setOptions] = useState({ tooth_codes: [], findings: [], treatments: [] });
  const [optionsLoaded, setOptionsLoaded] = useState(false);

  const [patients, setPatients] = useState([]);
  const [patientsLoaded, setPatientsLoaded] = useState(false);
  const [patientSearch, setPatientSearch] = useState("");
  const [patientId, setPatientId] = useState("");

  const [chart, setChart] = useState([]);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState("");

  const [toothCode, setToothCode] = useState("");
  const [notice, setNotice] = useState(null);

  useEffect(() => {
    getDentalChartOptions()
      .then((data) => { setOptions(data); setOptionsLoaded(true); })
      .catch(() => {});
  }, []);

  // No receptionist role reaches this page at all, so (unlike Ancillary's
  // OrderForm) there is no plain-ID-input fallback here -- always the
  // searchable list.
  useEffect(() => {
    listPatients({ limit: 200 })
      .then((data) => { setPatients(data); setPatientsLoaded(true); })
      .catch(() => {});
  }, []);

  function loadChart() {
    if (!patientId) return;
    setChartLoading(true);
    getDentalChart(patientId)
      .then((data) => { setChart(data); setChartError(""); })
      .catch((err) => setChartError(err?.response?.data?.detail || "Failed to load dental chart."))
      .finally(() => setChartLoading(false));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(loadChart, [patientId]);

  function showMsg(type, text) {
    setNotice({ type, text });
    setTimeout(() => setNotice(null), 5000);
  }

  function handleChangePatient() {
    setPatientId("");
    setToothCode("");
    setChart([]);
    setChartError("");
  }

  const selectedPatient = patients.find((p) => p.id === patientId);
  const filteredPatients = patients.filter((p) =>
    p.full_name?.toLowerCase().includes(patientSearch.toLowerCase()) ||
    p.national_id?.toLowerCase().includes(patientSearch.toLowerCase())
  ).slice(0, 10);

  const toothCodesWithEntries = new Set(chart.map((entry) => entry.tooth_code));

  return (
    <Layout>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">Dental Chart</h1>
        <p className="text-sm text-slate-500">Record tooth-level findings and treatments, signed per entry.</p>
      </div>

      {notice && (
        <div className={`mb-4 text-sm rounded-lg px-3 py-2 flex items-start justify-between gap-3 ${
          notice.type === "success" ? "bg-green-50 border border-green-200 text-green-800" : "bg-red-50 border border-red-200 text-red-700"
        }`}>
          <span>{notice.text}</span>
          <button onClick={() => setNotice(null)} className="shrink-0 font-medium">✕</button>
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl p-5 mb-6">
        <h2 className="font-semibold text-slate-800 mb-3">Patient</h2>
        {patientId ? (
          <div className="flex items-center justify-between border border-blue-200 bg-blue-50 rounded-lg px-3 py-2 text-sm">
            <span>{selectedPatient?.full_name || patientId}</span>
            <button onClick={handleChangePatient} className="text-blue-700 hover:underline">Change</button>
          </div>
        ) : (
          <div>
            <input
              type="text"
              placeholder="Search by name or NRIC..."
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm mb-1"
              value={patientSearch}
              onChange={(e) => setPatientSearch(e.target.value)}
            />
            {!patientsLoaded ? (
              <p className="text-xs text-slate-400 mt-1">Loading patients…</p>
            ) : patientSearch && filteredPatients.length > 0 ? (
              <ul className="border border-slate-200 rounded-lg divide-y max-h-40 overflow-y-auto">
                {filteredPatients.map((p) => (
                  <li
                    key={p.id}
                    onClick={() => setPatientId(p.id)}
                    className="px-3 py-2 text-sm hover:bg-slate-50 cursor-pointer"
                  >
                    {p.full_name} <span className="text-xs text-slate-500 ml-1">{p.national_id}</span>
                  </li>
                ))}
              </ul>
            ) : patientSearch ? (
              <p className="text-xs text-slate-400 mt-1">No matching patients.</p>
            ) : null}
          </div>
        )}
      </div>

      {patientId && (
        <>
          <div className="bg-white border border-slate-200 rounded-xl p-5 mb-6">
            <div className="flex items-center justify-between mb-3 gap-3">
              <h2 className="font-semibold text-slate-800">Tooth Chart (FDI notation)</h2>
              <Link to="/ancillary" className="text-xs text-blue-700 hover:underline whitespace-nowrap">
                Need an X-ray? Refer via the Ancillary module
              </Link>
            </div>
            {!optionsLoaded ? (
              <p className="text-sm text-slate-400">Loading chart options…</p>
            ) : (
              <ToothChart
                toothCodes={options.tooth_codes}
                selected={toothCode}
                withEntries={toothCodesWithEntries}
                onSelect={setToothCode}
              />
            )}
          </div>

          {optionsLoaded && (
            <EntryForm
              patientId={patientId}
              toothCode={toothCode}
              onToothCodeChange={setToothCode}
              options={options}
              user={user}
              hasSignature={hasSignature}
              onSuccess={() => { showMsg("success", "Dental chart entry recorded."); setToothCode(""); loadChart(); }}
              onError={(msg) => showMsg("error", msg)}
              onSignatureSaved={() => refreshCurrentUser().then(setUser).catch(() => {})}
            />
          )}

          <div className="bg-white border border-slate-200 rounded-xl p-5 mb-6">
            <h2 className="font-semibold text-slate-800 mb-3">Chart History</h2>
            {chartLoading ? (
              <p className="text-sm text-slate-400">Loading history…</p>
            ) : chartError ? (
              <p className="text-sm text-red-600">{chartError}</p>
            ) : chart.length === 0 ? (
              <p className="text-sm text-slate-400">No dental chart entries recorded yet.</p>
            ) : (
              <div className="space-y-2">
                {chart.map((entry) => (
                  <ChartHistoryRow key={entry.id} entry={entry} />
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </Layout>
  );
}

function ToothChart({ toothCodes, selected, withEntries, onSelect }) {
  return (
    <div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {QUADRANTS.map((q) => (
          <div key={q.prefix} className="border border-slate-200 rounded-lg p-3">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">{q.label}</p>
            <div className="grid grid-cols-4 gap-2">
              {toothCodes.filter((code) => code.startsWith(q.prefix)).map((code) => {
                const isSelected = selected === code;
                const hasEntry = withEntries.has(code);
                return (
                  <button
                    key={code}
                    type="button"
                    onClick={() => onSelect(code)}
                    className={`text-sm font-medium rounded-lg py-2 text-center border ${
                      isSelected
                        ? "bg-blue-800 text-white border-blue-800"
                        : hasEntry
                        ? "bg-amber-100 text-amber-800 border-amber-300"
                        : "bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100"
                    }`}
                  >
                    {code}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-400 mt-3">Highlighted teeth have at least one recorded chart entry. Click a tooth to pre-fill it below.</p>
    </div>
  );
}

function EntryForm({
  patientId, toothCode, onToothCodeChange, options, user, hasSignature, onSuccess, onError, onSignatureSaved,
}) {
  const [finding, setFinding] = useState("");
  const [treatment, setTreatment] = useState("none");
  const [notes, setNotes] = useState("");
  const [encounterId, setEncounterId] = useState("");
  const [drawn, setDrawn] = useState(null); // pad data-URL, only used when no saved signature
  const [savedSigUrl, setSavedSigUrl] = useState(null);
  const [busy, setBusy] = useState(false);
  const sigUrlRef = useRef(null);

  useEffect(() => {
    if (!hasSignature) return undefined;
    let cancelled = false;
    getMySignatureBlob()
      .then((u) => {
        if (cancelled) { if (u) URL.revokeObjectURL(u); return; }
        sigUrlRef.current = u;
        setSavedSigUrl(u);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [hasSignature]);
  useEffect(() => () => { if (sigUrlRef.current) URL.revokeObjectURL(sigUrlRef.current); }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!toothCode || !finding) {
      onError("Select a tooth and a finding.");
      return;
    }
    if (!hasSignature && !drawn) {
      onError("Draw your signature to sign off this entry.");
      return;
    }
    setBusy(true);
    try {
      const body = {
        patient_id: patientId,
        tooth_code: toothCode,
        finding,
        treatment,
        notes: notes.trim() || undefined,
        encounter_id: encounterId.trim() || undefined,
      };
      // Only send signature_b64 when there's nothing saved -- otherwise the
      // backend uses the profile signature and ignores this anyway.
      const savingSignatureNow = !hasSignature && drawn;
      if (savingSignatureNow) body.signature_b64 = drawn;
      await createDentalChartEntry(body);
      // The backend just saved this drawing to the caller's profile
      // (save_signature_from_b64) -- refresh the cached user so
      // `hasSignature` flips true and the next tooth in this same visit
      // shows the saved-signature preview instead of asking for a redraw.
      if (savingSignatureNow) onSignatureSaved?.();
      onSuccess();
      setFinding("");
      setTreatment("none");
      setNotes("");
      setEncounterId("");
      setDrawn(null);
    } catch (err) {
      onError(err?.response?.data?.detail || "Failed to record entry.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white border border-slate-200 rounded-xl p-5 mb-6 grid gap-3">
      <h2 className="font-semibold text-slate-800">Record Entry</h2>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Tooth (FDI)</label>
          <select
            required
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            value={toothCode}
            onChange={(e) => onToothCodeChange(e.target.value)}
          >
            <option value="">-- select tooth --</option>
            {options.tooth_codes.map((code) => (
              <option key={code} value={code}>{code}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Finding</label>
          <select
            required
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            value={finding}
            onChange={(e) => setFinding(e.target.value)}
          >
            <option value="">-- select finding --</option>
            {options.findings.map((f) => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Treatment</label>
          <select
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
            value={treatment}
            onChange={(e) => setTreatment(e.target.value)}
          >
            {options.treatments.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">Notes (Optional)</label>
        <textarea
          rows={2}
          className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        ></textarea>
      </div>

      <div>
        <label className="block text-xs font-medium text-slate-600 mb-1">Encounter ID (Optional)</label>
        <input
          type="text"
          placeholder="Links this entry to a visit -- e.g. for an X-ray referral raised during it"
          className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
          value={encounterId}
          onChange={(e) => setEncounterId(e.target.value)}
        />
      </div>

      <div className="mt-1 pt-3 border-t border-slate-100">
        <p className="text-xs text-slate-500 mb-2">Signing as {user?.full_name}</p>
        {hasSignature ? (
          savedSigUrl ? (
            <img
              src={savedSigUrl}
              alt="Your signature"
              className="border border-slate-200 rounded-lg bg-white"
              style={{ width: 240, height: 94, objectFit: "contain" }}
            />
          ) : (
            <p className="text-xs text-slate-400">Loading your signature…</p>
          )
        ) : (
          <>
            <p className="text-xs text-amber-700 mb-1">
              You have no saved signature — draw one to sign off this entry (also saved to your profile).
            </p>
            <SignaturePad onChange={setDrawn} />
          </>
        )}
      </div>

      <div className="flex gap-2 mt-2">
        <button disabled={busy} className="text-sm bg-blue-800 text-white px-4 py-2 rounded-lg disabled:opacity-50">
          {busy ? "Saving…" : "Record & Sign"}
        </button>
      </div>
    </form>
  );
}

function ChartHistoryRow({ entry }) {
  return (
    <div className="border border-slate-200 rounded-lg p-3 bg-slate-50">
      <div className="flex items-center gap-2 mb-1 flex-wrap">
        <span className="text-xs font-mono bg-white border border-slate-300 px-1.5 py-0.5 rounded">{entry.tooth_code}</span>
        <span className="font-semibold text-slate-800">{entry.finding}</span>
        {entry.treatment && entry.treatment !== "none" && (
          <span className="text-xs bg-blue-100 text-blue-800 px-2 py-0.5 rounded-full uppercase font-medium">{entry.treatment}</span>
        )}
        {entry.facility_name && <span className="text-xs text-slate-500 bg-white border border-slate-200 px-1.5 py-0.5 rounded">{entry.facility_name}</span>}
      </div>
      {entry.notes && <p className="text-sm text-slate-600 mb-1 whitespace-pre-wrap">{entry.notes}</p>}
      {entry.encounter_id && (
        <p className="text-xs text-slate-400 mb-1">Linked to encounter {entry.encounter_id}</p>
      )}
      <p className="text-xs text-slate-500">
        Signed by {entry.signed_by_name || entry.recorded_by_name} at {formatDateTime(entry.created_at)}
      </p>
    </div>
  );
}
