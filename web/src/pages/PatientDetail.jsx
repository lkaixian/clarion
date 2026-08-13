import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import Layout from "../components/Layout";
import {
  getPatient, getSummary, getInteractionCheck, issueEmergencyCard,
  revokeEmergencyCard, getCurrentCardStatus,
  addCondition, addMedication, addAllergy, addEncounter, getAuditLog,
  updateCondition, updateMedication, updateAllergy, updateEncounter,
  listNfcCards, registerNfcCard, revokeNfcCard, getCurrentUser,
  issuePatientAccount, updateOwnProfile, refreshCurrentUser,
  digitiseDocument, getDocumentDetail, getDocumentFileBlob,
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
      { key: "facility_name", label: "Facility name", type: "text", required: true },
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

  async function handleSubmit(e) {
    e.preventDefault();
    const missing = config.fields.find((f) => f.required && !String(values[f.key] || "").trim());
    if (missing) {
      setError(`${missing.label} is required.`);
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (mode === "add") {
        await config.addFn(initial.patientId, values);
      } else {
        await config.updateFn(initial.patientId, initial.id, values);
      }
      onSaved();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl p-6 max-w-md w-full max-h-[90vh] overflow-y-auto">
        <h3 className="font-semibold text-slate-800 mb-4">
          {mode === "add" ? `Add ${config.label}` : `Edit ${config.label}`}
        </h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error}</div>}
          {config.fields.map((f) => (
            <div key={f.key}>
              {f.type === "checkbox" ? (
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
                  <label className="block text-xs font-medium text-slate-600 mb-1">
                    {f.label}{f.required && <span className="text-red-600"> *</span>}
                  </label>
                  {f.type === "select" ? (
                    <select
                      className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      value={values[f.key]}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                    >
                      {f.options.map((o) => <option key={o} value={o}>{o.replace(/_/g, " ")}</option>)}
                    </select>
                  ) : f.type === "textarea" ? (
                    <textarea
                      className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                      rows={3}
                      value={values[f.key]}
                      placeholder={f.placeholder}
                      onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                    />
                  ) : (
                    <input
                      className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
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
          <div className="flex gap-2 pt-2">
            <button disabled={saving} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50">
              {saving ? "Saving..." : "Save"}
            </button>
            <button type="button" onClick={onClose} className="text-sm border border-slate-300 px-3 py-1.5 rounded-lg">
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
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl p-6 max-w-lg w-full max-h-[90vh] overflow-y-auto">
        {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}
        {!detail && !error && <p className="text-sm text-slate-400">Loading...</p>}
        {detail && (
          <>
            <h3 className="font-semibold text-slate-800 mb-1">
              {DOC_TYPE_LABELS[detail.doc_type] || detail.doc_type}
            </h3>
            <p className="text-xs text-slate-400 mb-4">
              {detail.original_filename || "unnamed file"} · {detail.uploaded_by_facility || "unknown facility"} · {detail.uploaded_at}
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
                <h4 className="text-xs font-semibold text-slate-600 uppercase mb-1">Extracted Text (OCR)</h4>
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
      {isStaff && (
        <form onSubmit={handleUpload} className="flex flex-wrap items-end gap-2 mb-4 pb-4 border-b border-slate-100">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Document type</label>
            <select
              className="border border-slate-300 rounded-lg px-3 py-1.5 text-sm"
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
            >
              {DOC_TYPE_OPTIONS.map((t) => <option key={t} value={t}>{DOC_TYPE_LABELS[t]}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">File</label>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*,.pdf"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="text-sm"
            />
          </div>
          <button disabled={uploading} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50">
            {uploading ? "Uploading & digitising..." : "Upload & Digitise"}
          </button>
        </form>
      )}
      {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}

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
                <p className="text-sm text-slate-700">{DOC_TYPE_LABELS[d.doc_type] || d.doc_type}</p>
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

function Section({ title, children, action }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 mb-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-slate-800">{title}</h2>
        {action}
      </div>
      {children}
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
  const [nfcCards, setNfcCards] = useState([]);
  // Set once, right after a successful issue/reset call — holds the ONLY
  // moment the plaintext temp password is ever visible anywhere (the
  // backend never stores or logs it in plaintext). Cleared when the staff
  // member dismisses the dialog; never persisted, never re-fetchable.
  const [issuedAccount, setIssuedAccount] = useState(null);
  const [busy, setBusy] = useState("");
  // { kind: 'condition'|'medication'|'allergy'|'encounter', mode: 'add'|'edit', initial } | null
  const [recordModal, setRecordModal] = useState(null);
  const emergencyCardRef = useRef(null);
  emergencyCardRef.current = emergencyCard;

  function refresh() {
    getPatient(id).then(setPatient);
    getAuditLog(id).then(setAuditLog);
    listNfcCards(id).then(setNfcCards);
    refreshCardStatus();
  }

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
  function refreshCardStatus() {
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
  }

  useEffect(refresh, [id]);

  useEffect(() => {
    const interval = setInterval(refreshCardStatus, CARD_STATUS_POLL_MS);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

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
    setBusy("nfc");
    try {
      await registerNfcCard(id, nfcUid, scope.length ? scope : ["allergies", "medications", "conditions", "blood_type"]);
      refresh();
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

  async function revokeNfc(nfcUid) {
    if (!confirm(`Revoke NFC card ${nfcUid}? This cannot be undone from here — you'd need to re-register it.`)) return;
    await revokeNfcCard(nfcUid);
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
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">{patient.full_name}</h1>
        <p className="text-sm text-slate-500">DOB {patient.date_of_birth} · Blood type {patient.blood_type || "unknown"}</p>
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

      {isOwnRecord && (
        <Section title="My Contact Info" action={
          !editingProfile && <button onClick={startEditingProfile} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">Edit</button>
        }>
          <p className="text-xs text-slate-400 mb-3">
            Name, date of birth, and NRIC can't be changed here — contact your clinic if any of those are wrong.
          </p>
          {editingProfile ? (
            <form onSubmit={saveProfile} className="space-y-3">
              {profileError && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{profileError}</div>}
              {[
                ["email", "Contact email", "email"],
                ["phone", "Phone number", "tel"],
                ["emergency_contact_name", "Emergency contact name", "text"],
                ["emergency_contact_phone", "Emergency contact phone", "tel"],
                ["emergency_contact_relationship", "Relationship", "text"],
              ].map(([key, label, type]) => (
                <div key={key}>
                  <label className="block text-xs font-medium text-slate-600 mb-1">{label}</label>
                  <input
                    className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    type={type}
                    value={profileForm[key]}
                    onChange={(e) => setProfileForm((f) => ({ ...f, [key]: e.target.value }))}
                  />
                </div>
              ))}
              <div className="flex gap-2 pt-1">
                <button disabled={profileSaving} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50">
                  {profileSaving ? "Saving..." : "Save"}
                </button>
                <button type="button" onClick={() => setEditingProfile(false)} className="text-sm border border-slate-300 px-3 py-1.5 rounded-lg">
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

      <Section title="AI Clinical Handover Brief" action={
        isStaff ? (
          <button onClick={loadBrief} disabled={busy === "brief"} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">
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
          <button onClick={loadInteractions} disabled={busy === "interactions"} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">
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
          <button onClick={issueAccount} disabled={busy === "account"} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">
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

      {issuedAccount && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
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

      <Section title="NFC Physical Card (senior citizens / no smartphone)" action={
        isStaff ? (
          <button onClick={registerNfc} disabled={busy === "nfc"} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">
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
              <div key={n.nfc_uid} className="flex items-center justify-between bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
                <div className="text-sm">
                  <code className="bg-slate-100 px-1 rounded">{n.nfc_uid}</code>
                  <span className={`ml-2 text-xs ${n.revoked ? "text-red-600" : "text-green-700"}`}>
                    {n.revoked ? "REVOKED" : "active"}
                  </span>
                  <p className="text-xs text-slate-400 mt-0.5">Scope: {n.scope.join(", ")} · valid until {n.grant_valid_until}</p>
                </div>
                {!n.revoked && isStaff && (
                  <button onClick={() => revokeNfc(n.nfc_uid)} className="text-xs text-red-700">Revoke</button>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>

      <div className="grid grid-cols-2 gap-4">
        <Section title="Conditions" action={isStaff && <button onClick={() => openAddRecord("condition")} className="text-xs text-blue-700">+ Add</button>}>
          {patient.conditions.length === 0 && <p className="text-sm text-slate-400">None on file.</p>}
          {patient.conditions.map((c) => (
            <div key={c.id} className="flex items-start justify-between gap-2 py-1.5 border-b border-slate-50 last:border-0">
              <div className="text-sm text-slate-700">
                <p>
                  {c.name}{" "}
                  {c.is_chronic && <span className="text-xs text-amber-600">(chronic)</span>}{" "}
                  <span className="text-xs text-slate-400">{c.status}</span>
                </p>
                {c.diagnosed_at && <p className="text-xs text-slate-400">Diagnosed {c.diagnosed_at}</p>}
              </div>
              {isStaff && <button onClick={() => openEditRecord("condition", c)} className="text-xs text-blue-700 whitespace-nowrap">Edit</button>}
            </div>
          ))}
        </Section>
        <Section title="Medications" action={isStaff && <button onClick={() => openAddRecord("medication")} className="text-xs text-blue-700">+ Add</button>}>
          {patient.medications.length === 0 && <p className="text-sm text-slate-400">None on file.</p>}
          {patient.medications.map((m) => (
            <div key={m.id} className="flex items-start justify-between gap-2 py-1.5 border-b border-slate-50 last:border-0">
              <div className="text-sm text-slate-700">
                <p>
                  {m.drug_name}{" "}
                  {!m.active && <span className="text-xs text-slate-400">(inactive)</span>}
                </p>
                <p className="text-xs text-slate-400">
                  {[m.dosage, m.frequency].filter(Boolean).join(" · ") || "no dosage/frequency on file"}
                  {m.prescribed_by_facility && ` — ${m.prescribed_by_facility}`}
                </p>
              </div>
              {isStaff && <button onClick={() => openEditRecord("medication", m)} className="text-xs text-blue-700 whitespace-nowrap">Edit</button>}
            </div>
          ))}
        </Section>
        <Section title="Allergies" action={isStaff && <button onClick={() => openAddRecord("allergy")} className="text-xs text-blue-700">+ Add</button>}>
          {patient.allergies.length === 0 && <p className="text-sm text-slate-400">None on file.</p>}
          {patient.allergies.map((a) => (
            <div key={a.id} className="flex items-start justify-between gap-2 py-1.5 border-b border-slate-50 last:border-0">
              <div className="text-sm text-slate-700">
                <p>{a.substance} <span className="text-xs text-red-600">({a.severity})</span></p>
                {a.reaction && <p className="text-xs text-slate-400">Reaction: {a.reaction}</p>}
              </div>
              {isStaff && <button onClick={() => openEditRecord("allergy", a)} className="text-xs text-blue-700 whitespace-nowrap">Edit</button>}
            </div>
          ))}
        </Section>
        <Section title="Visit / Transfer Timeline" action={isStaff && <button onClick={() => openAddRecord("encounter")} className="text-xs text-blue-700">+ Add</button>}>
          {patient.encounters.length === 0 && <p className="text-sm text-slate-400">None on file.</p>}
          <div className="space-y-2 max-h-72 overflow-y-auto">
            {[...patient.encounters]
              .sort((a, b) => new Date(b.started_at) - new Date(a.started_at))
              .map((e) => (
                <div key={e.id} className="flex items-start justify-between gap-2 py-1.5 border-b border-slate-50 last:border-0">
                  <div className="text-sm text-slate-700">
                    <p>
                      {e.facility_name} <span className="text-xs text-slate-400">({e.encounter_type})</span>
                    </p>
                    <p className="text-xs text-slate-400">{e.started_at}</p>
                    {e.reason && <p className="text-xs text-slate-600 mt-0.5">Reason: {e.reason}</p>}
                    {e.notes && <p className="text-xs text-slate-500 mt-0.5">Notes: {e.notes}</p>}
                  </div>
                  {isStaff && <button onClick={() => openEditRecord("encounter", e)} className="text-xs text-blue-700 whitespace-nowrap">Edit</button>}
                </div>
              ))}
          </div>
        </Section>
      </div>

      <DocumentsSection
        patientId={id}
        documents={patient.documents || []}
        isStaff={isStaff}
        onUploaded={refresh}
      />

      <Section title="Access Audit Log (who viewed this record)">
        <div className="space-y-1 max-h-48 overflow-y-auto">
          {auditLog.map((l, i) => (
            <p key={i} className="text-xs text-slate-500">
              <span className="font-mono">{l.timestamp}</span> — {l.actor_role || "system"} — {l.action}
            </p>
          ))}
        </div>
      </Section>

      {recordModal && (
        <RecordModal
          kind={recordModal.kind}
          mode={recordModal.mode}
          initial={recordModal.initial}
          onClose={() => setRecordModal(null)}
          onSaved={handleRecordSaved}
        />
      )}
    </Layout>
  );
}
