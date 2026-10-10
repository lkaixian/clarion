import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import Layout from "../components/Layout";
import SignaturePad from "../components/SignaturePad";
import {
  getPatient, getSummary, getInteractionCheck, issueEmergencyCard,
  revokeEmergencyCard, getCurrentCardStatus,
  addCondition, addMedication, addAllergy, addEncounter, getAuditLog, screenPrescription,
  updateCondition, updateMedication, updateAllergy, updateEncounter,
  listNfcCards, registerNfcCard, revokeNfcCard, getCurrentUser,
  issuePatientAccount, updateOwnProfile, refreshCurrentUser,
  digitiseDocument, getDocumentDetail, getDocumentFileBlob, generateDocument,
  getAppointments, createAppointment, updateAppointment,
  rescheduleAppointment, acceptRescheduleRequest, rejectRescheduleRequest,
  addPatientAnnotation,
  getMySignatureBlob,
} from "../api/client";

const PROFILE_FIELD_LABELS = {
  email: "Contact email",
  phone: "Phone number",
  emergency_contact_name: "Emergency contact name",
  emergency_contact_phone: "Emergency contact phone",
};

// Field configs for the add/edit modal, one per record kind. Drives both
// what inputs are rendered and what gets sent to the POST (add) / PATCH
// (edit) endpoint — kept in lockstep with schemas.py's *Create / *Update
// models so the modal never offers a field the backend would reject.
const RECORD_FIELD_CONFIG = {
  condition: {
    label: "Condition",
    addFn: addCondition, updateFn: updateCondition,
    fields: [
      { key: "name", label: "Condition name", type: "text", required: true },
      { key: "status", label: "Status", type: "select", options: ["active", "resolved"], default: "active" },
      { key: "diagnosed_at", label: "Diagnosed on", type: "date" },
      { key: "is_chronic", label: "Chronic", type: "checkbox" },
      { key: "critical_for_emergency", label: "Show on emergency card", type: "checkbox" },
    ],
  },
  medication: {
    label: "Medication",
    addFn: addMedication, updateFn: updateMedication,
    fields: [
      { key: "drug_name", label: "Drug name", type: "text", required: true },
      { key: "dosage", label: "Dosage", type: "text", placeholder: "e.g. 500mg" },
      { key: "frequency", label: "Frequency", type: "text", placeholder: "e.g. twice daily" },
      // The prescriber — often an external clinic. Informational and editable;
      // it is NOT what governs who can edit this record (the recording facility
      // is, tracked server-side).
      { key: "prescribed_by_facility", label: "Prescribing facility", type: "text" },
      { key: "start_date", label: "Start date", type: "date" },
      { key: "active", label: "Currently active", type: "checkbox", default: true },
      { key: "critical_for_emergency", label: "Show on emergency card", type: "checkbox", default: true },
    ],
  },
  allergy: {
    label: "Allergy",
    addFn: addAllergy, updateFn: updateAllergy,
    fields: [
      { key: "substance", label: "Allergen", type: "text", required: true },
      { key: "reaction", label: "Reaction", type: "text", placeholder: "e.g. rash, anaphylaxis" },
      { key: "severity", label: "Severity", type: "select", options: ["mild", "moderate", "severe", "unknown"], default: "unknown" },
      { key: "critical_for_emergency", label: "Show on emergency card", type: "checkbox", default: true },
    ],
  },
  encounter: {
    label: "Visit / Transfer",
    addFn: addEncounter, updateFn: updateEncounter,
    fields: [
      // Authoring facility for the immutability guard — set at creation, not
      // editable afterwards (backend rejects it on PATCH). Read-only on edit.
      { key: "facility_name", label: "Facility name", type: "text", required: true, addOnly: true },
      { key: "encounter_type", label: "Type", type: "select", options: ["outpatient", "inpatient", "emergency", "transfer"], default: "outpatient" },
      { key: "reason", label: "Reason for visit", type: "textarea" },
      { key: "notes", label: "Notes", type: "textarea" },
    ],
  },
};

const DOC_TYPE_OPTIONS = ["prescription", "discharge_summary", "lab_report", "imaging"];
const DOC_TYPE_LABELS = {
  prescription: "Prescription", discharge_summary: "Discharge summary",
  lab_report: "Lab report", imaging: "Imaging (X-ray/scan)",
};

// P3.5: generated document kinds. Fields per kind mirror
// schemas.GenerateDocumentRequest's per-doc_type required set exactly, so
// the form never offers something the backend would 422 on submit.
const GENERATED_DOC_TYPE_OPTIONS = ["medical_certificate", "referral_letter", "timeslip"];
const GENERATED_DOC_TYPE_LABELS = {
  medical_certificate: "Digital Medical Certificate",
  referral_letter: "Referral Letter",
  timeslip: "Timeslip",
};
const GENERATED_DOC_FIELDS = {
  medical_certificate: [
    ["diagnosis", "Diagnosis / reason", "text"],
    ["rest_from", "Rest from", "date"],
    ["rest_to", "Rest to", "date"],
    ["remarks", "Remarks (optional)", "text"],
  ],
  referral_letter: [
    ["referred_to", "Referred to", "text"],
    ["reason_for_referral", "Reason for referral", "text"],
    ["clinical_summary", "Clinical summary (optional)", "text"],
  ],
  timeslip: [
    ["visit_date", "Visit date", "date"],
    ["time_in", "Time in", "time"],
    ["time_out", "Time out", "time"],
    ["purpose", "Purpose (optional)", "text"],
  ],
};

// Staff-side reschedule reason codes (see routers/appointments.py's
// POST .../reschedule) — "other" requires reschedule_reason_other to be a
// non-empty string, both here (client-side) and on the backend (422
// otherwise).
const STAFF_RESCHEDULE_REASON_OPTIONS = [
  { value: "doctor_unavailable", label: "Doctor unavailable" },
  { value: "facility_or_equipment_issue", label: "Facility or equipment issue" },
  { value: "emergency_prioritization", label: "Emergency prioritization" },
  { value: "patient_requested", label: "Patient requested" },
  { value: "other", label: "Other" },
];
const STAFF_RESCHEDULE_REASON_LABELS = Object.fromEntries(
  STAFF_RESCHEDULE_REASON_OPTIONS.map((o) => [o.value, o.label])
);

// Patient-side reason codes for their own reschedule *requests* (filed from
// the mobile app, not from web) — web only ever displays these, it never
// lets staff pick one.
const PATIENT_RESCHEDULE_REASON_LABELS = {
  schedule_conflict: "Schedule conflict",
  unwell_or_cannot_travel: "Unwell or cannot travel",
  transport_issue: "Transport issue",
  other: "Other",
};

const RESCHEDULE_REQUEST_STATUS_BADGE_CLASSES = {
  pending: "bg-amber-100 text-amber-700",
  accepted: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-600",
};

// Generic add/edit form for conditions/medications/allergies/encounters —
// replaces the old window.prompt() chain (quickAdd) with real inputs,
// select dropdowns constrained to the backend's actual enums, and proper
// edit-in-place instead of "create a new one, never touch the old one".
function RecordModal({ kind, mode, initial, onClose, onSaved }) {
  const config = RECORD_FIELD_CONFIG[kind];
  const [values, setValues] = useState(() => {
    const seed = {};
    for (const f of config.fields) {
      seed[f.key] = initial ? (initial[f.key] ?? "") : (f.default ?? (f.type === "checkbox" ? false : ""));
    }
    return seed;
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // P4.4: real-time safety alert before a NEW medication is
  // confirmed. `screenResult` holds the last check's findings; `screening`
  // is a resubmit-to-confirm gate -- once findings are shown, the clinician
  // must hit "Add Medication" again to actually save. Reset whenever the
  // drug name changes so a stale acknowledgement can't cover a new drug.
  const isNewMedication = kind === "medication" && mode === "add";
  const [screenResult, setScreenResult] = useState(null);
  const [screening, setScreening] = useState(false);
  const [screenAcknowledged, setScreenAcknowledged] = useState(false);
  useEffect(() => {
    setScreenResult(null);
    setScreenAcknowledged(false);
  }, [values.drug_name]);

  async function handleSubmit(e) {
    e.preventDefault();
    const missing = config.fields.find(
      (f) => f.required && !(mode !== "add" && f.addOnly) && !String(values[f.key] || "").trim(),
    );
    if (missing) {
      setError(`${missing.label} is required.`);
      return;
    }

    if (isNewMedication && !screenAcknowledged) {
      setScreening(true);
      setError("");
      try {
        const result = await screenPrescription(initial.patientId, values.drug_name);
        const hasFindings = (result.drug_interactions?.length || 0) + (result.allergy_conflicts?.length || 0) > 0;
        if (hasFindings) {
          setScreenResult(result);
          setScreenAcknowledged(true); // next submit proceeds to save
          return;
        }
      } catch {
        // Safety-check service unreachable -- fail open (never block care
        // over an optional check being down), same discipline as the
        // Medication Interaction Check panel already has.
      } finally {
        setScreening(false);
      }
    }

    setSaving(true);
    setError("");
    try {
      if (mode === "add") {
        await config.addFn(initial.patientId, values);
      } else {
        // Drop addOnly fields (authoring-facility keys) — the backend rejects
        // them on PATCH now that they gate cross-hospital immutability.
        const payload = Object.fromEntries(
          config.fields.filter((f) => !f.addOnly).map((f) => [f.key, values[f.key]]),
        );
        await config.updateFn(initial.patientId, initial.id, payload);
      }
      onSaved();
    } catch (err) {
      // A PATCH can still 403 even though the row rendered an Edit control
      // (e.g. the patient was discharged between page load and save) — the
      // backend's `detail` explains to add a new entry instead, so surface
      // it verbatim in this same error slot rather than a generic message.
      setError(err?.response?.data?.detail || "Failed to save. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-panel">
        <h3 className="font-semibold text-slate-800 mb-4">
          {mode === "add" ? `Add ${config.label}` : `Edit ${config.label}`}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="alert-error">{error}</div>}
          {config.fields.map((f) => (
            <div key={f.key}>
              {mode !== "add" && f.addOnly ? (
                <>
                  <label className="field-label">{f.label}</label>
                  <p className="text-sm text-slate-500 border border-slate-200 bg-slate-50 rounded-lg px-3 py-1.5">
                    {String(values[f.key] || "—")}
                    <span className="block text-xs text-slate-400">Set when the record was created — not editable here.</span>
                  </p>
                </>
              ) : f.type === "checkbox" ? (
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={!!values[f.key]}
                    onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.checked }))}
                  />
                  {f.label}
                </label>
              ) : (
                <>
                  <label className="field-label">
                    {f.label}{f.required && <span className="text-red-600"> *</span>}
                  </label>
                  {f.type === "select" ? (
                    <select
                      className="field-input"
                      value={values[f.key]}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                    >
                      {f.options.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
                    </select>
                  ) : f.type === "textarea" ? (
                    <textarea
                      className="field-input"
                      rows={3}
                      value={values[f.key]}
                      placeholder={f.placeholder}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                    />
                  ) : (
                    <input
                      className="field-input"
                      type={f.type}
                      placeholder={f.placeholder}
                      value={values[f.key]}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                    />
                  )}
                </>
              )}
            </div>
          ))}
          {screenResult && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800 space-y-1">
              <p className="font-semibold">Safety check found possible issues:</p>
              {screenResult.allergy_conflicts.map((c, idx) => <p key={`a${idx}`}>⚠ {c}</p>)}
              {screenResult.drug_interactions.map((d, idx) => (
                <p key={`d${idx}`}>⚠ {d.drug_a} + {d.drug_b}: {d.explanation}</p>
              ))}
              <p className="text-xs text-red-600">Review before proceeding — click Add Medication again to confirm and save anyway.</p>
            </div>
          )}
          <div className="flex gap-2 pt-2">
            <button disabled={saving || screening} className="btn-primary">
              {screening ? "Checking safety..." : saving ? "Saving..." : screenAcknowledged ? "Add anyway" : "Save"}
            </button>
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// How often to re-check "is there still a live QR card, and is it the one
// we're displaying?" — this is what makes a revoke/reissue done *elsewhere*
// (e.g. from the patient's phone) show up here without a manual browser
// refresh. Short enough to feel responsive in a demo, long enough not to
// hammer the backend.
const CARD_STATUS_POLL_MS = 4000;

// Viewer for a single document: fetches the full detail (OCR text + AI
// summary — deliberately not part of the patient record's lightweight
// documents list) on open, and lazily fetches the original file as a blob
// (never a bare <img src>/<a href>, since the endpoint needs the same
// Bearer auth as everything else) only if file_available says one exists.
function DocumentModal({ patientId, documentId, onClose }) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState("");
  const [fileUrl, setFileUrl] = useState(null);
  const [fileError, setFileError] = useState("");

  useEffect(() => {
    getDocumentDetail(patientId, documentId)
      .then(setDetail)
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load document."));
  }, [patientId, documentId]);

  useEffect(() => {
    if (!detail?.file_available) return;
    let objectUrl;
    getDocumentFileBlob(patientId, documentId)
      .then((blob) => {
        objectUrl = URL.createObjectURL(blob);
        setFileUrl(objectUrl);
      })
      .catch(() => setFileError("The original file could not be loaded."));
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [detail, patientId, documentId]);

  return (
    <div className="modal-backdrop">
      <div className="bg-white rounded-xl p-6 max-w-lg w-full max-h-[90vh] overflow-y-auto">
        {error && <div className="alert-error mb-3">{error}</div>}
        {!detail && !error && <p className="text-sm text-slate-400">Loading...</p>}
        {detail && (
          <>
            <h3 className="font-semibold text-slate-800 mb-1">
              {DOC_TYPE_LABELS[detail.doc_type] || GENERATED_DOC_TYPE_LABELS[detail.doc_type] || detail.doc_type}
            </h3>
            <p className="text-xs text-slate-400 mb-4">
              {detail.original_filename || "unnamed file"} · {detail.uploaded_by_facility || "unknown facility"} · {detail.uploaded_at}
              {detail.signed_by_name && <> · Signed by {detail.signed_by_name} at {detail.signed_at}</>}
            </p>

            {detail.file_available ? (
              fileUrl ? (
                <div className="mb-4">
                  {/* Not every doc_type is an image (a scanned lab PDF isn't) —
                      fall back to a plain link if the browser can't render it inline. */}
                  <img
                    src={fileUrl}
                    alt={detail.original_filename || "document"}
                    className="max-w-full max-h-64 border border-slate-200 rounded-lg mb-2"
                    onError={(e) => { e.target.style.display = "none"; }}
                  />
                  <a href={fileUrl} target="_blank" rel="noreferrer" className="text-sm text-blue-700 hover:underline">
                    Open original file in a new tab
                  </a>
                </div>
              ) : fileError ? (
                <p className="text-sm text-red-600 mb-4">{fileError}</p>
              ) : (
                <p className="text-sm text-slate-400 mb-4">Loading original file...</p>
              )
            ) : (
              <p className="text-xs text-slate-400 mb-4">
                Original file not available for this document (only the extracted text below was kept).
              </p>
            )}

            {detail.ai_summary && (
              <div className="mb-3">
                <h4 className="text-xs font-semibold text-slate-600 uppercase mb-1">AI Summary</h4>
                <p className="text-sm text-slate-700 whitespace-pre-wrap">{detail.ai_summary}</p>
              </div>
            )}
            {detail.raw_text && (
              <div className="mb-3">
                <h4 className="text-xs font-semibold text-slate-600 uppercase mb-1">
                  {detail.signed_by_name ? "Document content" : "Extracted Text (OCR)"}
                </h4>
                <pre className="text-xs text-slate-600 whitespace-pre-wrap bg-slate-50 border border-slate-200 rounded-lg p-3 max-h-40 overflow-y-auto font-sans">
                  {detail.raw_text}
                </pre>
              </div>
            )}
          </>
        )}
        <button onClick={onClose} className="w-full text-sm bg-blue-800 text-white px-3 py-2 rounded-lg mt-2">
          Close
        </button>
      </div>
    </div>
  );
}

// Upload + list for scanned/digitised documents (prescriptions, discharge
// summaries, lab reports, X-rays). Staff-only end to end — a patient
// viewing their own record only sees that a document exists via the
// summary embedded in GET /patients/{id} (below), not its content; see
// DocumentModal's staff-only detail/file fetches.
// Issue a signed Digital Medical Certificate / Referral Letter / Timeslip
// (P3.5). Same "saved signature, or draw one on the spot" convention as
// CompleteConsultationModal/SignOffModal — no preview of a saved signature
// here either, matching the consultation modal's (simpler) version of that
// pattern rather than SignOffModal's.
function GenerateDocumentForm({ patientId, onGenerated }) {
  const user = getCurrentUser();
  const hasSignature = !!user?.has_signature;
  const [open, setOpen] = useState(false);
  const [docType, setDocType] = useState(GENERATED_DOC_TYPE_OPTIONS[0]);
  const [fields, setFields] = useState({});
  const [sigDataUrl, setSigDataUrl] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function changeDocType(next) {
    setDocType(next);
    setFields({});
  }

  async function submit(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await generateDocument(patientId, {
        doc_type: docType,
        ...fields,
        signature_b64: sigDataUrl ? sigDataUrl.split(",").pop() : undefined,
      });
      setFields({});
      setSigDataUrl(null);
      setOpen(false);
      onGenerated();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to generate the document.");
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-sm border border-slate-300 px-3 py-1.5 rounded-lg mb-4"
      >
        + Generate MC / Referral / Timeslip
      </button>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-3 mb-4 pb-4 border-b border-slate-100">
      {error && <div className="alert-error">{error}</div>}
      <div>
        <label className="field-label">Document type</label>
        <select
          className="border border-slate-300 rounded-lg px-3 py-1.5 text-sm"
          value={docType}
          onChange={(e) => changeDocType(e.target.value)}
        >
          {GENERATED_DOC_TYPE_OPTIONS.map((t) => (
            <option key={t} value={t}>{GENERATED_DOC_TYPE_LABELS[t]}</option>
          ))}
        </select>
      </div>
      <div className="grid gap-2">
        {GENERATED_DOC_FIELDS[docType].map(([key, label, type]) => (
          <label key={key} className="block text-xs font-medium text-slate-600">
            {label}
            <input
              type={type}
              className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={fields[key] || ""}
              onChange={(e) => setFields((current) => ({ ...current, [key]: e.target.value }))}
            />
          </label>
        ))}
      </div>
      {!hasSignature && (
        <div>
          <SignaturePad onChange={setSigDataUrl} />
          <p className="text-xs text-slate-400 mt-1">
            You have no saved signature — draw one (also saved to your profile).
          </p>
        </div>
      )}
      <div className="flex gap-2">
        <button disabled={saving} className="btn-primary">
          {saving ? "Generating..." : "Generate & sign"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="btn-secondary">
          Cancel
        </button>
      </div>
    </form>
  );
}

function DocumentsSection({ patientId, documents, isStaff, onUploaded }) {
  const [docType, setDocType] = useState(DOC_TYPE_OPTIONS[0]);
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [viewingId, setViewingId] = useState(null);
  const fileInputRef = useRef(null);

  async function handleUpload(e) {
    e.preventDefault();
    if (!file) {
      setError("Choose a file first.");
      return;
    }
    setUploading(true);
    setError("");
    try {
      await digitiseDocument(patientId, docType, file);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      onUploaded();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to upload/digitise this document.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <Section title="Documents (scans, prescriptions, lab reports, X-rays)">
      {isStaff && <GenerateDocumentForm patientId={patientId} onGenerated={onUploaded} />}
      {isStaff && (
        <form onSubmit={handleUpload} className="flex flex-wrap items-end gap-2 mb-4 pb-4 border-b border-slate-100">
          <div>
            <label className="field-label">Document type</label>
            <select
              className="border border-slate-300 rounded-lg px-3 py-1.5 text-sm"
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
            >
              {DOC_TYPE_OPTIONS.map((t) => <option key={t} value={t}>{DOC_TYPE_LABELS[t]}</option>)}
            </select>
          </div>
          <div>
            <label className="field-label">File</label>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*,.pdf"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="text-sm"
            />
          </div>
          <button disabled={uploading} className="btn-primary">
            {uploading ? "Uploading & digitising..." : "Upload & Digitise"}
          </button>
        </form>
      )}
      {error && <div className="alert-error mb-3">{error}</div>}

      {documents.length === 0 ? (
        <p className="text-sm text-slate-400">No documents on file yet.</p>
      ) : (
        <div className="space-y-2">
          {documents.map((d) => (
            <button
              key={d.id}
              onClick={() => isStaff && setViewingId(d.id)}
              disabled={!isStaff}
              className={`w-full flex items-center justify-between bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-left ${isStaff ? "hover:bg-slate-100" : "cursor-default"}`}
            >
              <div>
                <p className="text-sm text-slate-700">
                  {DOC_TYPE_LABELS[d.doc_type] || GENERATED_DOC_TYPE_LABELS[d.doc_type] || d.doc_type}
                </p>
                <p className="text-xs text-slate-400">{d.original_filename || "unnamed"} · {d.uploaded_by_facility || "unknown facility"} · {d.uploaded_at}</p>
              </div>
              {isStaff && <span className="text-xs text-blue-700 whitespace-nowrap">View →</span>}
            </button>
          ))}
        </div>
      )}
      {!isStaff && documents.length > 0 && (
        <p className="text-xs text-slate-400 mt-2">Ask your clinic to review document contents with you.</p>
      )}

      {viewingId && (
        <DocumentModal patientId={patientId} documentId={viewingId} onClose={() => setViewingId(null)} />
      )}
    </Section>
  );
}

// Staff-only "book an appointment" form. Deliberately NOT plugged into the
// generic RecordModal/RECORD_FIELD_CONFIG machinery above (conditions/
// medications/allergies/encounters): this form needs a conditional field
// (fasting hours only when "fasting required" is checked), a datetime-local
// <-> ISO conversion, and a variable-length list field (extra reminder
// offsets) — none of which RecordModal's flat, one-input-per-field config
// supports. Bolting those onto RecordModal would complicate it for its four
// existing, much simpler callers, so this is a dedicated component instead.
// It still mirrors RecordModal's shell/classes so it doesn't look like a
// different app bolted on.
function AppointmentModal({ patientId, onClose, onSaved }) {
  const [facilityName, setFacilityName] = useState("");
  const [venue, setVenue] = useState("");
  const [scheduledAt, setScheduledAt] = useState(""); // raw <input type="datetime-local"> value
  const [reason, setReason] = useState("");
  const [fastingRequired, setFastingRequired] = useState(false);
  const [fastingHours, setFastingHours] = useState("");
  const [precautionNotes, setPrecautionNotes] = useState("");
  // Extra reminders beyond the backend's auto-computed default set — an
  // edge-case field, kept collapsed behind a toggle so it doesn't clutter
  // the primary "book an appointment" flow.
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [extraReminders, setExtraReminders] = useState([]); // array of string hour values
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function addReminderField() {
    setExtraReminders((r) => [...r, ""]);
  }
  function updateReminderField(idx, value) {
    setExtraReminders((r) => r.map((v, i) => (i === idx ? value : v)));
  }
  function removeReminderField(idx) {
    setExtraReminders((r) => r.filter((_, i) => i !== idx));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!facilityName.trim()) {
      setError("Facility name is required.");
      return;
    }
    if (!scheduledAt) {
      setError("Date & time is required.");
      return;
    }
    setSaving(true);
    setError("");
    const payload = {
      facility_name: facilityName.trim(),
      venue: venue.trim() || undefined,
      // datetime-local carries no timezone suffix, so both the browser and
      // this Date constructor treat it as local time — toISOString() then
      // hands the backend the correct absolute instant regardless of what
      // timezone the server itself runs in.
      scheduled_at: new Date(scheduledAt).toISOString(),
      reason: reason.trim() || undefined,
      fasting_required: fastingRequired,
      precaution_notes: precautionNotes.trim() || undefined,
    };
    // Only send fasting_hours when fasting is actually required — the
    // backend 422s on fasting_hours being set without fasting_required.
    if (fastingRequired && fastingHours) {
      payload.fasting_hours = Number(fastingHours);
    }
    const reminderHours = extraReminders
      .map((v) => Number(v))
      .filter((n) => Number.isFinite(n) && n > 0);
    if (reminderHours.length > 0) {
      payload.extra_reminder_hours_before = reminderHours;
    }
    try {
      await createAppointment(patientId, payload);
      onSaved();
    } catch (err) {
      // Surfaces the backend's 422s (scheduled_at in the past, fasting_hours
      // without fasting_required) as an inline form error — same convention
      // RecordModal uses above, instead of a bare alert().
      setError(err?.response?.data?.detail || "Failed to save. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-panel">
        <h3 className="font-semibold text-slate-800 mb-4">Add Appointment</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="alert-error">{error}</div>}

          <div>
            <label className="field-label">
              Facility name<span className="text-red-600"> *</span>
            </label>
            <input
              className="field-input"
              type="text"
              value={facilityName}
              onChange={(e) => setFacilityName(e.target.value)}
            />
          </div>

          <div>
            <label className="field-label">Venue</label>
            <input
              className="field-input"
              type="text"
              placeholder="e.g. Clinic 3B, Level 2"
              value={venue}
              onChange={(e) => setVenue(e.target.value)}
            />
          </div>

          <div>
            <label className="field-label">
              Date &amp; time<span className="text-red-600"> *</span>
            </label>
            <input
              className="field-input"
              type="datetime-local"
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
            />
          </div>

          <div>
            <label className="field-label">Reason</label>
            <input
              className="field-input"
              type="text"
              placeholder="e.g. Follow-up, blood test"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>

          <div>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={fastingRequired}
                onChange={(e) => setFastingRequired(e.target.checked)}
              />
              Fasting required
            </label>
            {fastingRequired && (
              <div className="mt-2 pl-6">
                <label className="field-label">Fast for how many hours before?</label>
                <input
                  className="w-24 border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  type="number"
                  min="1"
                  value={fastingHours}
                  onChange={(e) => setFastingHours(e.target.value)}
                />
              </div>
            )}
          </div>

          <div>
            <label className="field-label">Precaution notes</label>
            <textarea
              className="field-input"
              rows={2}
              placeholder="e.g. bring previous scan results, stop blood thinners 2 days prior"
              value={precautionNotes}
              onChange={(e) => setPrecautionNotes(e.target.value)}
            />
          </div>

          {/* Reminder timing is auto-computed by the backend from
              scheduled_at/fasting_hours (see AppointmentOut.reminders) —
              this is only for bolting on EXTRA reminders beyond that
              default set, an edge case, so it's tucked behind a toggle
              instead of cluttering the primary form above. */}
          <div className="pt-1">
            <button type="button" onClick={() => setShowAdvanced((s) => !s)} className="text-xs text-blue-700">
              {showAdvanced ? "Hide" : "Show"} extra reminder options
            </button>
            {showAdvanced && (
              <div className="mt-2 space-y-2 bg-slate-50 border border-slate-200 rounded-lg p-3">
                <p className="text-xs text-slate-400">
                  Extra reminders on top of the default schedule (hours before the appointment).
                </p>
                {extraReminders.map((v, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <input
                      className="w-24 border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      type="number"
                      min="1"
                      value={v}
                      onChange={(e) => updateReminderField(idx, e.target.value)}
                    />
                    <span className="text-xs text-slate-400">hours before</span>
                    <button type="button" onClick={() => removeReminderField(idx)} className="text-xs text-red-700">
                      Remove
                    </button>
                  </div>
                ))}
                <button type="button" onClick={addReminderField} className="text-xs text-blue-700">
                  + add another reminder
                </button>
              </div>
            )}
          </div>

          <div className="flex gap-2 pt-2">
            <button disabled={saving} className="btn-primary">
              {saving ? "Saving..." : "Save"}
            </button>
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Staff-only reschedule for a single (still-"scheduled") appointment —
// picks a new date/time and a reason code, mirroring AppointmentModal's
// shell/classes and datetime-local <-> ISO handling above rather than
// inventing a different look for it.
function RescheduleModal({ patientId, appointment, onClose, onSaved }) {
  const [scheduledAt, setScheduledAt] = useState(""); // raw <input type="datetime-local"> value
  const [reasonCode, setReasonCode] = useState(STAFF_RESCHEDULE_REASON_OPTIONS[0].value);
  const [reasonOther, setReasonOther] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!scheduledAt) {
      setError("New date & time is required.");
      return;
    }
    const newDate = new Date(scheduledAt);
    if (Number.isNaN(newDate.getTime()) || newDate.getTime() <= Date.now()) {
      setError("New date & time must be in the future.");
      return;
    }
    if (reasonCode === "other" && !reasonOther.trim()) {
      setError("Please describe the reason when selecting \"Other\".");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await rescheduleAppointment(patientId, appointment.id, {
        // datetime-local carries no timezone suffix, so both the browser
        // and this Date constructor treat it as local time — toISOString()
        // then hands the backend the correct absolute instant regardless
        // of what timezone the server itself runs in (same convention as
        // AppointmentModal above).
        new_scheduled_at: newDate.toISOString(),
        reason_code: reasonCode,
        reason_other: reasonCode === "other" ? reasonOther.trim() : null,
      });
      onSaved();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to reschedule. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-panel">
        <h3 className="font-semibold text-slate-800 mb-1">Reschedule Appointment</h3>
        <p className="text-xs text-slate-400 mb-4">
          {appointment.facility_name}{appointment.venue && ` — ${appointment.venue}`} · currently{" "}
          {formatAppointmentTime(appointment.scheduled_at)}
        </p>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="alert-error">{error}</div>}

          <div>
            <label className="field-label">
              New date &amp; time<span className="text-red-600"> *</span>
            </label>
            <input
              className="field-input"
              type="datetime-local"
              value={scheduledAt}
              onChange={(e) => setScheduledAt(e.target.value)}
            />
          </div>

          <div>
            <label className="field-label">
              Reason<span className="text-red-600"> *</span>
            </label>
            <select
              className="field-input"
              value={reasonCode}
              onChange={(e) => setReasonCode(e.target.value)}
            >
              {STAFF_RESCHEDULE_REASON_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          {reasonCode === "other" && (
            <div>
              <label className="field-label">
                Please describe<span className="text-red-600"> *</span>
              </label>
              <textarea
                className="field-input"
                rows={2}
                value={reasonOther}
                onChange={(e) => setReasonOther(e.target.value)}
              />
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <button disabled={saving} className="btn-primary">
              {saving ? "Saving..." : "Save"}
            </button>
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// No date library in this codebase (see the low-dependency style
// throughout this file) — a plain toLocaleString() matches every other
// timestamp here that's rendered straight from whatever the browser's
// locale settings produce, rather than a raw ISO string.
function formatAppointmentTime(iso) {
  return new Date(iso).toLocaleString();
}

// List + staff add/cancel for scheduled appointments. Patients see their
// own list read-only (GET is patient-own-record + staff); add/cancel are
// staff-only on the backend, so isStaff gates both actions here too.
function AppointmentsSection({ patientId, appointments, isStaff, onChanged }) {
  const [showAddModal, setShowAddModal] = useState(false);
  // Which appointment (if any) currently has the reschedule modal open —
  // holds the whole appointment object (RescheduleModal needs it for its
  // header) rather than just an id.
  const [rescheduling, setRescheduling] = useState(null);
  // Reminders are metadata, not the main content of a row — collapsed by
  // default per-appointment, expandable on demand.
  const [expandedReminders, setExpandedReminders] = useState({});
  const [busyId, setBusyId] = useState(null);
  // Separate busy flag for accept/reject on a reschedule *request* — keyed
  // by request id, distinct from busyId (cancel/reschedule) above since a
  // single appointment row can show both an appointment-level action and a
  // request-level action at once.
  const [requestBusyId, setRequestBusyId] = useState(null);

  async function cancelAppointment(appt) {
    if (!confirm(`Cancel the appointment at ${appt.facility_name} on ${formatAppointmentTime(appt.scheduled_at)}?`)) return;
    setBusyId(appt.id);
    try {
      await updateAppointment(patientId, appt.id, { status: "cancelled" });
      onChanged();
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to cancel appointment.");
    } finally {
      setBusyId(null);
    }
  }

  async function acceptRequest(appt, request) {
    setRequestBusyId(request.id);
    try {
      await acceptRescheduleRequest(patientId, appt.id, request.id);
      onChanged();
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to accept reschedule request.");
    } finally {
      setRequestBusyId(null);
    }
  }

  async function rejectRequest(appt, request) {
    const note = prompt("Optional note to the patient explaining why (leave blank for none):");
    // prompt() returns null on Cancel — treat that as "don't reject after all",
    // same as this file's other prompt()-gated flows.
    if (note === null) return;
    setRequestBusyId(request.id);
    try {
      await rejectRescheduleRequest(patientId, appt.id, request.id, { clinician_note: note || null });
      onChanged();
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to reject reschedule request.");
    } finally {
      setRequestBusyId(null);
    }
  }

  return (
    <Section
      title="Appointments"
      action={isStaff && <button onClick={() => setShowAddModal(true)} className="btn-add">+ Add</button>}
    >
      {appointments.length === 0 ? (
        <p className="text-sm text-slate-400">No appointments scheduled.</p>
      ) : (
        <div className="space-y-2">
          {appointments.map((a) => {
            const cancelled = a.status === "cancelled";
            return (
              <div
                key={a.id}
                // Same "dim it but keep it visible, with an explicit label"
                // treatment as a revoked emergency card elsewhere in this
                // file (see the Emergency Access Card section) — reused
                // here rather than inventing a different cancelled-state
                // convention.
                className={`bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 ${cancelled ? "opacity-50" : ""}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm text-slate-700">
                    {cancelled && (
                      <p className="text-xs font-semibold text-red-700 uppercase mb-0.5">Cancelled</p>
                    )}
                    <p className={cancelled ? "line-through" : ""}>
                      {a.facility_name}{a.venue && ` — ${a.venue}`}
                    </p>
                    <p className="text-xs text-slate-400">{formatAppointmentTime(a.scheduled_at)}</p>
                    {a.previous_scheduled_at && (
                      <p className="text-xs text-slate-400 italic">
                        Previously: {formatAppointmentTime(a.previous_scheduled_at)}
                        {a.reschedule_reason_code && ` — ${STAFF_RESCHEDULE_REASON_LABELS[a.reschedule_reason_code] || a.reschedule_reason_code}`}
                        {a.reschedule_reason_other && `: ${a.reschedule_reason_other}`}
                      </p>
                    )}
                    {a.reason && <p className="text-xs text-slate-600 mt-0.5">Reason: {a.reason}</p>}
                    {a.fasting_required && (
                      <p className="text-xs text-amber-700 font-medium mt-0.5">
                        ⚠ Fasting required{a.fasting_hours ? `: ${a.fasting_hours}h before` : ""}
                      </p>
                    )}
                    {a.precaution_notes && (
                      <p className="text-xs text-slate-500 mt-0.5">Note: {a.precaution_notes}</p>
                    )}
                  </div>
                  {isStaff && !cancelled && (
                    <div className="flex gap-2 whitespace-nowrap">
                      {a.status === "scheduled" && (
                        <button
                          onClick={() => setRescheduling(a)}
                          disabled={busyId === a.id}
                          className="text-xs text-blue-700"
                        >
                          Reschedule
                        </button>
                      )}
                      <button
                        onClick={() => cancelAppointment(a)}
                        disabled={busyId === a.id}
                        className="text-xs text-red-700"
                      >
                        {busyId === a.id ? "Cancelling..." : "Cancel"}
                      </button>
                    </div>
                  )}
                </div>

                {/* reminders is server-computed (from scheduled_at /
                    fasting_hours / extra_reminder_hours_before) — displayed
                    verbatim, never recalculated client-side. */}
                {a.reminders && a.reminders.length > 0 && (
                  <div className="mt-1">
                    <button
                      type="button"
                      onClick={() => setExpandedReminders((s) => ({ ...s, [a.id]: !s[a.id] }))}
                      className="text-xs text-slate-400 hover:text-slate-600"
                    >
                      {expandedReminders[a.id]
                        ? "Hide reminders"
                        : `${a.reminders.length} reminder${a.reminders.length === 1 ? "" : "s"} scheduled`}
                    </button>
                    {expandedReminders[a.id] && (
                      <ul className="mt-1 pl-3 text-xs text-slate-400 list-disc list-inside">
                        {a.reminders.map((r, idx) => (
                          <li key={idx}>{r.label} — {formatAppointmentTime(r.fires_at)}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {/* The PATIENT's own reschedule request (filed from the mobile
                    app, not from web) — web's job is only to show it and let
                    staff accept/reject while it's pending. */}
                {a.latest_reschedule_request && (
                  <div className="mt-2 pt-2 border-t border-slate-200">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-xs font-medium text-slate-600">Patient requested reschedule</span>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${RESCHEDULE_REQUEST_STATUS_BADGE_CLASSES[a.latest_reschedule_request.status] || "bg-slate-100 text-slate-600"}`}>
                        {a.latest_reschedule_request.status}
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Reason: {PATIENT_RESCHEDULE_REASON_LABELS[a.latest_reschedule_request.reason_code] || a.latest_reschedule_request.reason_code}
                      {a.latest_reschedule_request.reason_other && ` — ${a.latest_reschedule_request.reason_other}`}
                    </p>

                    {a.latest_reschedule_request.status === "pending" && isStaff ? (
                      <div className="flex gap-3 mt-1">
                        <button
                          onClick={() => acceptRequest(a, a.latest_reschedule_request)}
                          disabled={requestBusyId === a.latest_reschedule_request.id}
                          className="text-xs text-green-700"
                        >
                          {requestBusyId === a.latest_reschedule_request.id ? "Working..." : "Accept"}
                        </button>
                        <button
                          onClick={() => rejectRequest(a, a.latest_reschedule_request)}
                          disabled={requestBusyId === a.latest_reschedule_request.id}
                          className="text-xs text-red-700"
                        >
                          {requestBusyId === a.latest_reschedule_request.id ? "Working..." : "Reject"}
                        </button>
                      </div>
                    ) : (
                      a.latest_reschedule_request.clinician_note && (
                        <p className="text-xs text-slate-500 mt-0.5">
                          {a.latest_reschedule_request.status === "rejected" ? "Rejected" : "Note"}: {a.latest_reschedule_request.clinician_note}
                        </p>
                      )
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {showAddModal && (
        <AppointmentModal
          patientId={patientId}
          onClose={() => setShowAddModal(false)}
          onSaved={() => { setShowAddModal(false); onChanged(); }}
        />
      )}

      {rescheduling && (
        <RescheduleModal
          patientId={patientId}
          appointment={rescheduling}
          onClose={() => setRescheduling(null)}
          onSaved={() => { setRescheduling(null); onChanged(); }}
        />
      )}
    </Section>
  );
}

const SECTION_ICON = { Conditions: "🩺", Medications: "💊", Allergies: "⚠️", "Visit / Transfer Timeline": "🕒" };

function Section({ title, children, action, count }) {
  return (
    <section className="bg-white border border-slate-200 rounded-xl shadow-sm mb-4 overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 bg-slate-50 px-5 py-3">
        <h2 className="flex items-center gap-2 font-semibold text-slate-800">
          {SECTION_ICON[title] && <span aria-hidden="true">{SECTION_ICON[title]}</span>}
          {title}
          {count > 0 && (
            <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800">{count}</span>
          )}
        </h2>
        {action}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

// The page used to be one long vertical scroll of every section below —
// fine for a single patient looked at once, but a clinician working through
// ~50 patients a day was scrolling past NFC/audit-log/QR chrome every time
// just to reach Conditions/Medications. Split into in-page tabs (plain
// useState, no router involvement — see module docstring-equivalent in the
// task notes) so "what does this patient have" stays the default view and
// the secondary/administrative sections are one click away instead of
// always in the way.
const TABS = [
  { key: "overview", label: "Overview" },
  { key: "documents", label: "Documents" },
  { key: "ai", label: "AI & Interactions" },
  { key: "access", label: "Emergency & Access" },
];

function TabBar({ active, onChange }) {
  return (
    <div className="mb-5 inline-flex max-w-full gap-1 overflow-x-auto rounded-xl bg-slate-200/70 p-1">
      {TABS.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`px-4 py-1.5 text-sm font-medium rounded-lg whitespace-nowrap transition ${
            active === t.key
              ? "bg-white text-blue-900 shadow-sm"
              : "text-slate-600 hover:text-slate-900"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

// Access audit log rows: actor_name resolves live (so it's null for a
// system-originated row, or an account that's since been deleted) and
// actor_facility is a point-in-time snapshot taken when the access
// happened — both are additive/nullable, so fall back gracefully rather
// than ever rendering "· null" or an empty facility chip.
function formatAuditActor(l) {
  // Emergency-responder rows have no actor_name (they're never a real
  // users.id -- see get_audit_log's docstring) but the name the responder
  // typed in is still recoverable from the raw `actor` string, and their
  // claimed org from `detail` -- see backend/app/routers/emergency.py's
  // scan_emergency_card/scan_nfc_card: actor=f"emergency_responder:{name}",
  // detail=f"org={org}". Neither is verified against any account (there's
  // no login on this path at all), so this is deliberately labeled
  // "self-reported, unverified" rather than shown the same way as a real
  // staff actor_name -- a patient reading this shouldn't mistake a typed
  // name for an authenticated one. `detail` can literally be the string
  // "org=None" when the responder left the org field blank (an f-string
  // over Optional[str] on the backend) -- treat that the same as "no org
  // given", not as a literal value to display.
  if (l.actor && l.actor.startsWith("emergency_responder:")) {
    const respName = l.actor.slice("emergency_responder:".length) || "unidentified";
    const orgMatch = typeof l.detail === "string" ? l.detail.match(/^org=(.*)$/) : null;
    const org = orgMatch && orgMatch[1] && orgMatch[1] !== "None" ? orgMatch[1] : null;
    const who = `${respName} (emergency responder — self-reported, unverified)`;
    return org ? `${who} · ${org}` : who;
  }

  const who = l.actor_name
    ? `${l.actor_name}${l.actor_role ? ` (${l.actor_role})` : ""}`
    : (l.actor_role || "system");
  return l.actor_facility ? `${who} · ${l.actor_facility}` : who;
}

// Edit affordance for one condition/medication/allergy/encounter row.
// `editable` comes straight off each entry in GET /patients/{id}: it's true
// only when the acting user's facility authored the record AND the patient
// is currently checked in here. When it's false a PATCH to that record 403s
// (the add-a-new-entry flow is the sanctioned way to amend), so instead of
// a dead "Edit" button we show a subtle lock + caption naming the authoring
// facility. A missing `editable` field (older payloads) falls back to
// showing Edit rather than hiding it. Still gated by isStaff upstream — a
// patient viewer never sees any edit control here.
function RecordEditControl({ record, onEdit }) {
  if (record.editable === false) {
    const facility = record.authored_by_facility || "another facility";
    return (
      <span
        className="inline-flex items-start gap-1 text-xs text-slate-400 max-w-[9rem] shrink-0 leading-tight"
        title={`This record can only be edited by ${facility} while the patient is checked in there. Add a new entry to amend it.`}
      >
        <svg viewBox="0 0 24 24" className="w-3 h-3 mt-px shrink-0" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <rect x="5" y="11" width="14" height="10" rx="2" />
          <path d="M8 11V7a4 4 0 0 1 8 0v4" />
        </svg>
        <span>Recorded by {facility} · read-only here</span>
      </span>
    );
  }
  return (
    <button onClick={onEdit} className="text-xs text-blue-700 whitespace-nowrap">Edit</button>
  );
}

// Python `str(datetime)` comes back as "2026-08-27 10:15:00" (space, no
// zone) — Chrome parses that but Safari doesn't, so fall back to the raw
// string rather than render "Invalid Date". Same low-dependency, built-in
// formatting approach as formatAppointmentTime above.
function formatSignedAt(s) {
  if (!s) return "";
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString();
}

// One glyph per annotation kind (see the backend's ANNOTATION_KINDS).
const ANNOTATION_KIND_ICON = {
  resolved: "✔",
  discontinued: "⊘",
  correction: "✎",
  note: "🗒",
};

// Which annotation kinds a given record type can be signed off with — mirrors
// the backend's kind/target-type cross-rules (resolved → condition only,
// discontinued → medication only; both 400 otherwise).
const SIGN_OFF_KINDS_BY_TYPE = {
  condition: [
    { value: "resolved", label: "Resolved" },
    { value: "correction", label: "Correction" },
    { value: "note", label: "Note" },
  ],
  medication: [
    { value: "discontinued", label: "Discontinued" },
    { value: "correction", label: "Correction" },
    { value: "note", label: "Note" },
  ],
  allergy: [
    { value: "correction", label: "Correction" },
    { value: "note", label: "Note" },
  ],
  encounter: [
    { value: "correction", label: "Correction" },
    { value: "note", label: "Note" },
  ],
};

// Tamper-seal result from the server (backend/app/seal.py): "valid" means the
// row still matches what the signer's session sealed; "altered" means it was
// changed after signing. "unsealed" = created before sealing existed.
function SealBadge({ status }) {
  if (status === "valid") {
    return <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 ring-1 ring-emerald-200" title="Digitally sealed; unchanged since signing">🔒 sealed</span>;
  }
  if (status === "altered") {
    return <span className="rounded-full bg-red-50 px-2 py-0.5 text-[11px] font-semibold text-red-700 ring-1 ring-red-300" title="This record no longer matches its seal">✖ altered after signing</span>;
  }
  if (status === "unknown_key") {
    return <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800 ring-1 ring-amber-200" title="Sealed with a key this server no longer holds">seal key unknown</span>;
  }
  return null;
}

// The signed-off annotations stacked under one clinical-record row — one line
// each: kind icon, note text, muted attribution, and a signature thumbnail
// link. Newest-first ordering is whatever the backend returned.
function AnnotationList({ annotations }) {
  if (!annotations || annotations.length === 0) return null;
  return (
    <div className="mt-1 space-y-1 border-l-2 border-slate-100 pl-2">
      {annotations.map((a) => (
        <div key={a.id} className="flex flex-wrap items-baseline gap-x-1 text-xs text-slate-600">
          <span aria-hidden="true">{ANNOTATION_KIND_ICON[a.kind] || "•"}</span>
          {a.note && <span className="text-slate-700">{a.note}</span>}
          <span className="text-slate-400">
            — {a.signed_by_name} ({a.signed_by_role}) · {a.facility_name} · {formatSignedAt(a.created_at)}
          </span>
          <SealBadge status={a.seal_status} />
        </div>
      ))}
    </div>
  );
}

// Condition status badge that respects the computed effective_status: when a
// "resolved" sign-off exists it differs from the raw `status` column, so show
// the raw value struck through with an arrow to the effective one.
function ConditionStatusBadge({ condition }) {
  const raw = condition.status;
  const effective = condition.effective_status || raw;
  if (effective !== raw) {
    return (
      <span className="text-xs">
        <span className="text-slate-400 line-through">{raw}</span>
        <span className="text-slate-400"> → </span>
        <span className="font-medium text-green-700">{effective}</span>
      </span>
    );
  }
  return <span className="text-xs text-slate-400">{effective}</span>;
}

// Medication active/inactive badge. effective_active === false while the raw
// `active` column is still true means someone signed it off as discontinued.
function MedicationStatusBadge({ medication }) {
  if (medication.effective_active === false && medication.active === true) {
    return <span className="text-xs font-medium text-amber-700">(Discontinued — signed off)</span>;
  }
  if (!medication.active) return <span className="text-xs text-slate-400">(inactive)</span>;
  return null;
}

// Append-only sign-off on a clinical record — POSTs a signed
// ClinicalRecordAnnotation (never mutates the underlying row; that's the
// whole point). The signer needs a saved signature; if they don't have one
// the SignaturePad is shown and its PNG rides along as signature_b64, which
// also saves it to their profile.
function SignOffModal({ patientId, targetType, target, targetLabel, onClose, onSaved }) {
  const user = getCurrentUser();
  const hasSignature = !!user?.has_signature;
  const kinds = SIGN_OFF_KINDS_BY_TYPE[targetType];
  const [kind, setKind] = useState(kinds[0].value);
  const [note, setNote] = useState("");
  const [drawn, setDrawn] = useState(null); // pad data-URL, only used when no saved signature
  const [savedSigUrl, setSavedSigUrl] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
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

  // Note is optional for resolved/discontinued (the kind says it all) but
  // required for a free-text correction/note.
  const noteRequired = kind === "correction" || kind === "note";

  async function handleSubmit(e) {
    e.preventDefault();
    if (noteRequired && !note.trim()) {
      setError("A note is required for a correction or note sign-off.");
      return;
    }
    if (!hasSignature && !drawn) {
      setError("Draw your signature to sign off.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const body = {
        target_type: targetType,
        target_id: target.id,
        kind,
        note: note.trim() || null,
      };
      // Only send signature_b64 when there's nothing saved — otherwise the
      // backend uses the profile signature and ignores this anyway.
      if (!hasSignature && drawn) body.signature_b64 = drawn;
      await addPatientAnnotation(patientId, body);
      onSaved();
    } catch (err) {
      // 400 = illegal kind/target-type combo, 409 = no signature on file —
      // both carry a human-readable `detail`, so surface it verbatim.
      setError(err?.response?.data?.detail || "Failed to sign off. Try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-panel">
        <h3 className="font-semibold text-slate-800 mb-1">Sign off record</h3>
        <p className="text-xs text-slate-400 mb-4">{targetLabel}</p>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="alert-error">{error}</div>}

          <div>
            <label className="field-label">Kind</label>
            <select
              className="field-input"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            >
              {kinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}
            </select>
          </div>

          <div>
            <label className="field-label">
              Note{noteRequired
                ? <span className="text-red-600"> *</span>
                : <span className="text-slate-400"> (optional)</span>}
            </label>
            <textarea
              className="field-input"
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>

          <div className="border-t border-slate-100 pt-3">
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
                  You have no saved signature — draw one to sign off (also saved to your profile).
                </p>
                <SignaturePad onChange={setDrawn} />
              </>
            )}
          </div>

          <div className="flex gap-2 pt-2">
            <button disabled={saving} className="btn-primary">
              {saving ? "Signing…" : "Sign off"}
            </button>
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function PatientDetail() {
  const { id } = useParams();
  // The backend restricts several actions here (AI brief, interaction
  // check, adding conditions/medications/allergies/encounters, NFC
  // register/revoke) to admin/records_officer/clinician — a patient viewing
  // their own record via GET /patients/{id} is allowed to *read* it, but
  // would get a 403 clicking any of those buttons. Hide them for a patient
  // viewer instead of showing an action that's guaranteed to fail.
  const isStaff = getCurrentUser()?.role !== "patient";
  // Narrower than isStaff: POST /auth/patients/{id}/issue-account is
  // admin/records_officer-only on the backend (a clinician or
  // emergency_responder gets a 403), unlike the AI brief/NFC/quick-add
  // actions above which clinicians *are* allowed to use. isStaff alone
  // would show this button to roles that always 403 on click.
  const canManageLogins = ["admin", "records_officer"].includes(getCurrentUser()?.role);
  // Patient viewing their own record — the only case profile self-editing
  // (and the missing-data nudge) applies. A patient can't reach anyone
  // else's /patients/:id at all (backend scopes GET /patients/{id} to
  // staff or the matching patient_id), but double-check here too rather
  // than assume that's the only guard.
  const currentUser = getCurrentUser();
  const isOwnRecord = currentUser?.role === "patient" && currentUser?.patient_id === id;
  const [missingProfileFields, setMissingProfileFields] = useState(currentUser?.missing_profile_fields || []);
  const [editingProfile, setEditingProfile] = useState(false);
  const [profileForm, setProfileForm] = useState(null);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [patient, setPatient] = useState(null);
  const [brief, setBrief] = useState(null);
  const [interactions, setInteractions] = useState(null);
  const [emergencyCard, setEmergencyCard] = useState(null);
  const [cardStatus, setCardStatus] = useState(null); // {active, card_reference, scope, grant_valid_until} | null (not loaded yet)
  const [auditLog, setAuditLog] = useState([]);
  const [auditDays, setAuditDays] = useState(7);
  const [nfcCards, setNfcCards] = useState([]);
  const [appointments, setAppointments] = useState([]);
  // Set once, right after a successful issue/reset call — holds the ONLY
  // moment the plaintext temp password is ever visible anywhere (the
  // backend never stores or logs it in plaintext). Cleared when the staff
  // member dismisses the dialog; never persisted, never re-fetchable.
  const [issuedAccount, setIssuedAccount] = useState(null);
  const [busy, setBusy] = useState("");
  // { kind: 'condition'|'medication'|'allergy'|'encounter', mode: 'add'|'edit', initial } | null
  const [recordModal, setRecordModal] = useState(null);
  // { targetType, target, targetLabel } | null — drives the append-only
  // "Sign off…" annotation modal (separate from the in-place Edit above).
  const [signOff, setSignOff] = useState(null);
  // In-page tab state (see TABS/TabBar above) — "overview" is the default
  // since that's what a clinician needs first when opening a patient.
  const [activeTab, setActiveTab] = useState("overview");
  const emergencyCardRef = useRef(null);
  emergencyCardRef.current = emergencyCard;

  // Both memoized on `id` only (every getter is a stable module import, every
  // setter is a stable useState setter, emergencyCardRef is a stable ref) so
  // the effects below can list honest dependencies instead of an
  // exhaustive-deps disable.
  const refreshCardStatus = useCallback(() => {
    getCurrentCardStatus(id)
      .then((status) => {
        setCardStatus(status);
        const current = emergencyCardRef.current;
        if (!current || current.revoked) return;
        const staleOrRevoked = !status.active || status.card_reference !== current.card_reference;
        if (staleOrRevoked) {
          setEmergencyCard((prev) => (prev ? { ...prev, revoked: true } : prev));
        }
      })
      .catch(() => {
        /* transient poll failure — try again next interval */
      });
  }, [id]);

  const refresh = useCallback(() => {
    getPatient(id).then(setPatient);
    getAuditLog(id, auditDays).then(setAuditLog);
    listNfcCards(id).then(setNfcCards);
    getAppointments(id).then(setAppointments);
    refreshCardStatus();
  }, [id, refreshCardStatus, auditDays]);

  // FIX (previously reported: "revoke/replace a card from the app, but the
  // web console doesn't reflect it until I refresh the page"): the web
  // console used to have no way at all to find out about a card issued or
  // revoked somewhere else — it only ever showed whatever *it itself* had
  // issued in the current browser tab. It now polls the read-only
  // GET /emergency/current/{id} status endpoint, and reconciles the
  // locally-displayed QR image against it: if the currently-active card's
  // reference no longer matches what's on screen (revoked, or replaced by
  // a newer one issued elsewhere), the on-screen card is marked revoked
  // without requiring a manual refresh.
  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    const interval = setInterval(refreshCardStatus, CARD_STATUS_POLL_MS);
    return () => clearInterval(interval);
  }, [refreshCardStatus]);

  async function loadBrief() {
    setBusy("brief");
    const data = await getSummary(id);
    setBrief(data.handover_brief);
    setBusy("");
  }

  async function loadInteractions() {
    setBusy("interactions");
    const data = await getInteractionCheck(id);
    setInteractions(data);
    setBusy("");
  }

  async function issueCard() {
    setBusy("card");
    try {
      const data = await issueEmergencyCard(id, ["allergies", "medications", "conditions", "blood_type"]);
      setEmergencyCard({ ...data, revoked: false });
      refreshCardStatus();
    } finally {
      setBusy("");
    }
  }

  async function revokeCard() {
    if (!emergencyCard || emergencyCard.revoked) return;
    if (!confirm(`Revoke card ${emergencyCard.card_reference}? It will stop working immediately.`)) return;
    setBusy("card");
    try {
      await revokeEmergencyCard(emergencyCard.card_reference);
      setEmergencyCard((prev) => (prev ? { ...prev, revoked: true } : prev));
      refreshCardStatus();
    } finally {
      setBusy("");
    }
  }

  async function registerNfc() {
    const nfcUid = prompt(
      "NFC card UID (tap the physical card against a USB/phone NFC reader to read its UID, " +
      "or use the UID printed on the card):"
    );
    if (!nfcUid) return;
    const scopeInput = prompt(
      "Fields to share on tap (comma-separated: allergies, medications, conditions, blood_type)",
      "allergies, medications, conditions, blood_type"
    );
    const scope = (scopeInput || "").split(",").map((s) => s.trim()).filter(Boolean);
    // Every tag type works; only an NTAG 424 DNA has the tamper-proof read
    // counter, so anything else gets a warning in the prompt below.
    const tagType = window.confirm("Is this an NTAG 424 DNA tag?\n\nOK = yes. Cancel = NTAG213/215/216 or not sure (still works, with a warning).")
      ? "ntag424" : "ntag21x";
    setBusy("nfc");
    try {
      const result = await registerNfcCard(id, nfcUid, scope.length ? scope : ["allergies", "medications", "conditions", "blood_type"], tagType);
      refresh();
      // tag_text is the compact fallback meant to be written DIRECTLY onto
      // the physical tag's own NDEF memory (readable with zero network —
      // see app/campus_registry... no, app/routers/emergency.py's
      // _build_compact_tag_text docstring) -- this pointer-based /register
      // call can't write it itself (no browser API does generic NDEF write
      // on desktop), so hand it to staff to carry to a phone running the
      // CLARION app's "Write Offline Tag" screen (same physical card).
      // Prefer the encrypted blob (opens only on a signed-in CLARION device,
      // every offline read is attributed); plaintext tag_text is the legacy
      // fallback for a tag too small to hold a sealed record.
      const toWrite = result?.tag_blob || result?.tag_text;
      if (toWrite) {
        const kind = result.tag_blob
          ? " This is ENCRYPTED: only a signed-in CLARION staff device can read it offline."
          : " This is plaintext (the tag is too small for an encrypted record).";
        const truncated = result.tag_blob ? result.tag_blob_truncated : result.tag_text_truncated;
        const note = truncated
          ? "\n\n(truncated to fit the tag — not everything critical fit)"
          : "";
        const securityWarning = result.tag_security?.warning ? "\n\n⚠ " + result.tag_security.warning : "";
        prompt(
          "Card registered. To make this card readable with NO network at all, copy this " +
          "text and write it to the SAME physical card from a phone: open the CLARION app, " +
          "tap the NFC icon in the top bar (\"Write Offline Tag\" — staff only), paste, and tap." + kind + note + securityWarning,
          toWrite,
        );
      }
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to register NFC card.");
    } finally {
      setBusy("");
    }
  }

  async function issueAccount() {
    if (!confirm(
      "Issue a login for this patient? If they already have one, this immediately " +
      "replaces their password with a new temporary one — their current password " +
      "(if any) stops working right away. Only do this after verifying their " +
      "identity in person."
    )) return;
    setBusy("account");
    try {
      const data = await issuePatientAccount(id);
      setIssuedAccount(data);
    } catch (e) {
      alert(e?.response?.data?.detail || "Failed to issue/reset login.");
    } finally {
      setBusy("");
    }
  }

  function startEditingProfile() {
    setProfileForm({
      email: patient.email || "",
      phone: patient.phone || "",
      emergency_contact_name: patient.emergency_contact_name || "",
      emergency_contact_phone: patient.emergency_contact_phone || "",
      emergency_contact_relationship: patient.emergency_contact_relationship || "",
    });
    setProfileError("");
    setEditingProfile(true);
  }

  async function saveProfile(e) {
    e.preventDefault();
    setProfileSaving(true);
    setProfileError("");
    try {
      const updated = await updateOwnProfile(id, profileForm);
      setPatient((prev) => ({ ...prev, ...updated }));
      setEditingProfile(false);
      // Re-fetch so missing_profile_fields (computed at login/me time)
      // reflects whatever was just filled in, without requiring a fresh
      // login.
      const me = await refreshCurrentUser();
      setMissingProfileFields(me.missing_profile_fields || []);
    } catch (err) {
      setProfileError(err?.response?.data?.detail || "Failed to save. Check your details and try again.");
    } finally {
      setProfileSaving(false);
    }
  }

  async function revokeNfc(card) {
    if (!confirm(`Revoke NFC card ••${card.nfc_uid_last4 || "?"}? This cannot be undone from here — you'd need to re-register it.`)) return;
    await revokeNfcCard(card.id);
    refresh();
  }

  function openAddRecord(kind) {
    setRecordModal({ kind, mode: "add", initial: { patientId: id } });
  }

  function openEditRecord(kind, record) {
    setRecordModal({ kind, mode: "edit", initial: { ...record, patientId: id } });
  }

  function handleRecordSaved() {
    setRecordModal(null);
    refresh();
  }

  if (!patient) return <Layout><p className="text-slate-400">Loading...</p></Layout>;

  return (
    <Layout>
      <div className="mb-6 flex flex-wrap items-center gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div
          aria-hidden="true"
          className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-blue-900 text-xl font-semibold text-white"
        >
          {(patient.full_name || "?").split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="page-title truncate">{patient.full_name}</h1>
          <p className="text-sm text-slate-500">DOB {patient.date_of_birth}</p>
        </div>
        <div className="flex flex-wrap gap-2 text-xs font-medium">
          <span className="rounded-full bg-red-50 px-3 py-1 text-red-700 ring-1 ring-red-200">
            Blood type {patient.blood_type || "unknown"}
          </span>
          {patient.allergies.length > 0 && (
            <span className="rounded-full bg-amber-50 px-3 py-1 text-amber-800 ring-1 ring-amber-200">
              {patient.allergies.length} {patient.allergies.length === 1 ? "allergy" : "allergies"}
            </span>
          )}
          {patient.conditions.some((c) => c.is_chronic) && (
            <span className="rounded-full bg-blue-50 px-3 py-1 text-blue-800 ring-1 ring-blue-200">Chronic condition</span>
          )}
        </div>
      </div>

      {isOwnRecord && missingProfileFields.length > 0 && !editingProfile && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-4 flex items-center justify-between gap-4">
          <p className="text-sm text-amber-800">
            Your profile is missing: {missingProfileFields.map((f) => PROFILE_FIELD_LABELS[f] || f).join(", ")}.
          </p>
          <button onClick={startEditingProfile} className="text-sm bg-amber-600 text-white px-3 py-1.5 rounded-lg whitespace-nowrap">
            Complete profile
          </button>
        </div>
      )}

      <TabBar active={activeTab} onChange={setActiveTab} />

      {activeTab === "overview" && (
        <>
          {isOwnRecord && (
            <Section title="My Contact Info" action={
              !editingProfile && <button onClick={startEditingProfile} className="btn-primary">Edit</button>
            }>
              <p className="text-xs text-slate-400 mb-3">
                Name, date of birth, and NRIC can't be changed here — contact your clinic if any of those are wrong.
              </p>
              {editingProfile ? (
                <form onSubmit={saveProfile} className="space-y-3">
                  {profileError && <div className="alert-error">{profileError}</div>}
                  {[
                    ["email", "Contact email", "email"],
                    ["phone", "Phone number", "tel"],
                    ["emergency_contact_name", "Emergency contact name", "text"],
                    ["emergency_contact_phone", "Emergency contact phone", "tel"],
                    ["emergency_contact_relationship", "Relationship", "text"],
                  ].map(([key, label, type]) => (
                    <div key={key}>
                      <label className="field-label">{label}</label>
                      <input
                        className="field-input"
                        type={type}
                        value={profileForm[key]}
                        onChange={(e) => setProfileForm((f) => ({ ...f, [key]: e.target.value }))}
                      />
                    </div>
                  ))}
                  <div className="flex gap-2 pt-1">
                    <button disabled={profileSaving} className="btn-primary">
                      {profileSaving ? "Saving..." : "Save"}
                    </button>
                    <button type="button" onClick={() => setEditingProfile(false)} className="btn-secondary">
                      Cancel
                    </button>
                  </div>
                </form>
              ) : (
                <div className="text-sm text-slate-700 space-y-1">
                  <p>Email: {patient.email || <span className="text-slate-400">not set</span>}</p>
                  <p>Phone: {patient.phone || <span className="text-slate-400">not set</span>}</p>
                  <p>Emergency contact: {patient.emergency_contact_name
                    ? `${patient.emergency_contact_name} (${patient.emergency_contact_relationship || "relationship not set"}) — ${patient.emergency_contact_phone || "no phone on file"}`
                    : <span className="text-slate-400">not set</span>}
                  </p>
                </div>
              )}
            </Section>
          )}

          <div className="grid grid-cols-1 gap-x-4 lg:grid-cols-2">
            <Section title="Conditions" count={patient.conditions.length} action={isStaff && <button onClick={() => openAddRecord("condition")} className="btn-add">+ Add</button>}>
              {patient.conditions.length === 0 && <p className="empty-state">None on file.</p>}
              {patient.conditions.map((c) => (
                <div key={c.id} className="record-row">
                  <div className="text-sm text-slate-700">
                    <p>
                      {c.name}{" "}
                      {c.is_chronic && <span className="text-xs text-amber-600">(chronic)</span>}{" "}
                      <ConditionStatusBadge condition={c} />
                    </p>
                    {c.diagnosed_at && <p className="text-xs text-slate-400">Diagnosed {c.diagnosed_at}</p>}
                    <AnnotationList annotations={c.annotations} />
                  </div>
                  {isStaff && (
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <RecordEditControl record={c} onEdit={() => openEditRecord("condition", c)} />
                      <button
                        onClick={() => setSignOff({ targetType: "condition", target: c, targetLabel: c.name })}
                        className="btn-chip"
                      >
                        Sign off…
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </Section>
            <Section title="Medications" count={patient.medications.length} action={isStaff && <button onClick={() => openAddRecord("medication")} className="btn-add">+ Add</button>}>
              {patient.medications.length === 0 && <p className="empty-state">None on file.</p>}
              {patient.medications.map((m) => (
                <div key={m.id} className="record-row">
                  <div className="text-sm text-slate-700">
                    <p>
                      {m.drug_name}{" "}
                      <MedicationStatusBadge medication={m} />
                    </p>
                    <p className="text-xs text-slate-400">
                      {[m.dosage, m.frequency].filter(Boolean).join(" · ") || "no dosage/frequency on file"}
                      {m.prescribed_by_facility && ` — ${m.prescribed_by_facility}`}
                    </p>
                    <AnnotationList annotations={m.annotations} />
                  </div>
                  {isStaff && (
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <RecordEditControl record={m} onEdit={() => openEditRecord("medication", m)} />
                      <button
                        onClick={() => setSignOff({ targetType: "medication", target: m, targetLabel: m.drug_name })}
                        className="btn-chip"
                      >
                        Sign off…
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </Section>
            <Section title="Allergies" count={patient.allergies.length} action={isStaff && <button onClick={() => openAddRecord("allergy")} className="btn-add">+ Add</button>}>
              {patient.allergies.length === 0 && <p className="empty-state">None on file.</p>}
              {patient.allergies.map((a) => (
                <div key={a.id} className="record-row">
                  <div className="text-sm text-slate-700">
                    <p>{a.substance} <span className="text-xs text-red-600">({a.severity})</span></p>
                    {a.reaction && <p className="text-xs text-slate-400">Reaction: {a.reaction}</p>}
                    <AnnotationList annotations={a.annotations} />
                  </div>
                  {isStaff && (
                    <div className="flex flex-col items-end gap-1 shrink-0">
                      <RecordEditControl record={a} onEdit={() => openEditRecord("allergy", a)} />
                      <button
                        onClick={() => setSignOff({ targetType: "allergy", target: a, targetLabel: a.substance })}
                        className="btn-chip"
                      >
                        Sign off…
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </Section>
            <Section title="Visit / Transfer Timeline" count={patient.encounters.length} action={isStaff && <button onClick={() => openAddRecord("encounter")} className="btn-add">+ Add</button>}>
              {patient.encounters.length === 0 && <p className="empty-state">None on file.</p>}
              <div className="space-y-2 max-h-72 overflow-y-auto">
                {[...patient.encounters]
                  .sort((a, b) => new Date(b.started_at) - new Date(a.started_at))
                  .map((e) => (
                    <div key={e.id} className="record-row">
                      <div className="text-sm text-slate-700">
                        <p>
                          {e.facility_name} <span className="text-xs text-slate-400">({e.encounter_type})</span>
                        </p>
                        <p className="text-xs text-slate-400">{e.started_at}</p>
                        {e.reason && <p className="text-xs text-slate-600 mt-0.5">Reason: {e.reason}</p>}
                        {e.notes && <p className="text-xs text-slate-500 mt-0.5">Notes: {e.notes}</p>}
                        {/* Signed consultation-complete (from the clinician's
                            "My Room" flow) — signature snapshot lives on the
                            staff profile, not the annotation store. */}
                        {e.signed_by_name && (
                          <p className="text-xs text-slate-500 mt-0.5">
                            ✔ Consultation completed — signed by {e.signed_by_name}
                            {e.signed_by_role ? ` (${e.signed_by_role})` : ""}{" "}
                            <SealBadge status={e.seal_status} />
                          </p>
                        )}
                        <AnnotationList annotations={e.annotations} />
                      </div>
                      {isStaff && (
                        <div className="flex flex-col items-end gap-1 shrink-0">
                          <RecordEditControl record={e} onEdit={() => openEditRecord("encounter", e)} />
                          <button
                            onClick={() => setSignOff({
                              targetType: "encounter",
                              target: e,
                              targetLabel: `${e.facility_name} (${e.encounter_type})`,
                            })}
                            className="btn-chip"
                          >
                            Sign off…
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
              </div>
            </Section>
          </div>

          {/* Forward-looking/basic-info-adjacent, same reasoning that put
              "My Contact Info" in Overview during the tab split — this is
              day-to-day "what's coming up for this patient" info, not an
              administrative/secondary concern like Documents or Access. */}
          <AppointmentsSection
            patientId={id}
            appointments={appointments}
            isStaff={isStaff}
            onChanged={refresh}
          />
        </>
      )}

      {activeTab === "documents" && (
        <DocumentsSection
          patientId={id}
          documents={patient.documents || []}
          isStaff={isStaff}
          onUploaded={refresh}
        />
      )}

      {activeTab === "ai" && (
        <>
          <Section title="AI Clinical Handover Brief" action={
            isStaff ? (
              <button onClick={loadBrief} disabled={busy === "brief"} className="btn-primary">
                {busy === "brief" ? "Generating..." : "Generate"}
              </button>
            ) : null
          }>
            {/* GET /ai/summary/{id} is staff-only on the backend (admin/records_officer/clinician) —
                a patient viewer would get a 403 clicking Generate, so the button is hidden above and
                this note is shown instead of a dead-end action. */}
            {!isStaff ? <p className="text-sm text-slate-400">Available to clinical staff.</p>
              : brief ? <pre className="whitespace-pre-wrap text-sm text-slate-700 font-sans">{brief}</pre>
              : <p className="text-sm text-slate-400">Generate a 30-second orientation brief for a receiving clinician.</p>}
          </Section>

          <Section title="Medication Interaction Check" action={
            isStaff ? (
              <button onClick={loadInteractions} disabled={busy === "interactions"} className="btn-primary">
                {busy === "interactions" ? "Checking..." : "Run Check"}
              </button>
            ) : null
          }>
            {!isStaff ? (
              <p className="text-sm text-slate-400">Available to clinical staff.</p>
            ) : interactions ? (
              <div className="space-y-2">
                {interactions.interactions.length === 0 && interactions.cross_facility_duplicates.length === 0 && (
                  <p className="text-sm text-green-700">No interactions or duplicates found.</p>
                )}
                {interactions.interactions.map((i, idx) => (
                  <div key={idx} className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm">
                    <span className="font-semibold text-red-700 uppercase text-xs">{i.severity}</span>
                    <p className="text-red-800">{i.drug_a} + {i.drug_b}: {i.explanation}</p>
                  </div>
                ))}
                {interactions.cross_facility_duplicates.map((d, idx) => (
                  <div key={idx} className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">{d}</div>
                ))}
              </div>
            ) : <p className="text-sm text-slate-400">Check for dangerous combinations across all prescribing facilities.</p>}
          </Section>
        </>
      )}

      {activeTab === "access" && (
        <>
          <Section title="Emergency Access Card / QR" action={
            <div className="flex gap-2">
              {emergencyCard && !emergencyCard.revoked && (
                <button onClick={revokeCard} disabled={busy === "card"} className="text-sm border border-red-700 text-red-700 px-3 py-1.5 rounded-lg">
                  Revoke
                </button>
              )}
              <button onClick={issueCard} disabled={busy === "card"} className="text-sm bg-red-700 text-white px-3 py-1.5 rounded-lg">
                {busy === "card" ? "Issuing..." : "Issue Card"}
              </button>
            </div>
          }>
            {emergencyCard ? (
              <div className="flex items-center gap-4">
                <img
                  src={emergencyCard.qr_code_base64}
                  alt="Emergency QR"
                  className={`w-32 h-32 border rounded-lg ${emergencyCard.revoked ? "opacity-30" : ""}`}
                />
                <div className="text-sm text-slate-600">
                  {emergencyCard.revoked && (
                    <p className="text-xs font-semibold text-red-700 uppercase mb-1">
                      Revoked — this QR code no longer works
                    </p>
                  )}
                  <p>Card reference: <code className="bg-slate-100 px-1 rounded">{emergencyCard.card_reference}</code></p>
                  <p className="text-xs text-slate-400 mt-1">Scope: {emergencyCard.scope.join(", ")}</p>
                  <p className="text-xs text-slate-400">Print this for a physical senior-citizen card.</p>
                </div>
              </div>
            ) : cardStatus?.active ? (
              <div className="flex items-center gap-4">
                <img
                  src={cardStatus.qr_code_base64}
                  alt="Emergency QR"
                  className="w-32 h-32 border rounded-lg"
                />
                <div className="text-sm text-slate-600">
                  <p>Card reference: <code className="bg-slate-100 px-1 rounded">{cardStatus.card_reference}</code></p>
                  <p className="text-xs text-slate-400 mt-1">Scope: {cardStatus.scope.join(", ")}</p>
                  <p className="text-xs text-slate-400">
                    Issued from elsewhere (e.g. the patient's phone). Click "Issue Card" to generate a
                    new one you can view/print here (this will automatically revoke the one above).
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-slate-400">Generates a scoped QR — scanning it (no login required) returns only critical fields.</p>
            )}
          </Section>

          {canManageLogins && (
            <Section title="Patient Login Account" action={
              <button onClick={issueAccount} disabled={busy === "account"} className="btn-primary">
                {busy === "account" ? "Working..." : "Issue / Reset Login"}
              </button>
            }>
              <p className="text-xs text-slate-400">
                Patients don't self-register — NRIC alone isn't secret in Malaysia (it's on every IC
                and form), so anyone claiming an account with just an NRIC would be a takeover risk.
                Verify identity in person, then issue a one-time temporary password here; the patient
                sets their own password on first login. Also use this to reset a forgotten password
                for a patient who can't self-serve via NRIC + date of birth in the app.
              </p>
            </Section>
          )}

          <Section title="NFC Physical Card (senior citizens / no smartphone)" action={
            isStaff ? (
              <button onClick={registerNfc} disabled={busy === "nfc"} className="btn-primary">
                {busy === "nfc" ? "Registering..." : "Register NFC Card"}
              </button>
            ) : null
          }>
            <p className="text-xs text-slate-400 mb-2">
              For patients who cannot use the mobile app: tap a blank NFC card/sticker against a
              reader to get its UID, register it here against this patient, then hand the physical
              card to them. A responder taps it against any NFC-capable phone — no login, no app
              install required on the responder's side (same trust model as the QR flow).
            </p>
            {nfcCards.length === 0 ? (
              <p className="text-sm text-slate-400">No NFC card registered for this patient yet.</p>
            ) : (
              <div className="space-y-2">
                {nfcCards.map((n) => (
                  <div key={n.id} className="flex items-center justify-between bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
                    <div className="text-sm">
                      {/* The raw UID is stored hashed server-side (M7) and never sent back;
                          the last 4 chars are enough to tell two cards apart. */}
                      <code className="bg-slate-100 px-1 rounded">card ••{n.nfc_uid_last4 || "????"}</code>
                      <span className={`ml-2 text-xs ${n.revoked ? "text-red-600" : "text-green-700"}`}>
                        {n.revoked ? "REVOKED" : "active"}
                      </span>
                      <p className="text-xs text-slate-400 mt-0.5">Scope: {n.scope.join(", ")} · valid until {n.grant_valid_until}</p>
                    </div>
                    {!n.revoked && isStaff && (
                      <button onClick={() => revokeNfc(n)} className="text-xs text-red-700">Revoke</button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Section>

          <Section
            title="Access Audit Log (who viewed this record)"
            action={
              <select
                aria-label="Audit log window"
                value={auditDays}
                onChange={(e) => setAuditDays(Number(e.target.value))}
                className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs"
              >
                <option value={7}>Last 7 days</option>
                <option value={30}>Last 30 days</option>
                <option value={365}>Last year</option>
                <option value={2555}>Last 7 years</option>
              </select>
            }
          >
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {auditLog.map((l, i) => (
                <p key={i} className="text-xs text-slate-500">
                  <span className="font-mono">{l.timestamp}</span> — {formatAuditActor(l)} — {l.action}
                </p>
              ))}
            </div>
          </Section>
        </>
      )}

      {issuedAccount && (
        <div className="modal-backdrop">
          <div className="bg-white rounded-xl p-6 max-w-sm w-full">
            <h3 className="font-semibold text-slate-800 mb-1">Temporary login issued</h3>
            <p className="text-xs text-red-700 font-semibold uppercase mb-3">
              Shown once — write it down or hand it to the patient now
            </p>
            <div className="bg-slate-50 border border-slate-200 rounded-lg p-3 mb-3 text-sm space-y-1">
              <p>NRIC: <code className="bg-slate-100 px-1 rounded">{issuedAccount.national_id || "—"}</code></p>
              <p>Temporary password: <code className="bg-slate-100 px-1 rounded font-bold">{issuedAccount.temporary_password}</code></p>
            </div>
            <p className="text-xs text-slate-400 mb-4">
              The patient will be required to set their own password the first time they sign in.
            </p>
            <button
              onClick={() => setIssuedAccount(null)}
              className="w-full text-sm bg-blue-800 text-white px-3 py-2 rounded-lg"
            >
              Done
            </button>
          </div>
        </div>
      )}

      {recordModal && (
        <RecordModal
          kind={recordModal.kind}
          mode={recordModal.mode}
          initial={recordModal.initial}
          onClose={() => setRecordModal(null)}
          onSaved={handleRecordSaved}
        />
      )}

      {signOff && (
        <SignOffModal
          patientId={id}
          targetType={signOff.targetType}
          target={signOff.target}
          targetLabel={signOff.targetLabel}
          onClose={() => setSignOff(null)}
          onSaved={() => { setSignOff(null); refresh(); }}
        />
      )}
    </Layout>
  );
}
