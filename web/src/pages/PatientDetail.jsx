import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import Layout from "../components/Layout";
import {
  getPatient, getSummary, getInteractionCheck, issueEmergencyCard,
  revokeEmergencyCard, getCurrentCardStatus,
  addCondition, addMedication, addAllergy, addEncounter, getAuditLog,
  listNfcCards, registerNfcCard, revokeNfcCard, getCurrentUser,
} from "../api/client";

// How often to re-check "is there still a live QR card, and is it the one
// we're displaying?" — this is what makes a revoke/reissue done *elsewhere*
// (e.g. from the patient's phone) show up here without a manual browser
// refresh. Short enough to feel responsive in a demo, long enough not to
// hammer the backend.
const CARD_STATUS_POLL_MS = 4000;

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
  const [patient, setPatient] = useState(null);
  const [brief, setBrief] = useState(null);
  const [interactions, setInteractions] = useState(null);
  const [emergencyCard, setEmergencyCard] = useState(null);
  const [cardStatus, setCardStatus] = useState(null); // {active, card_reference, scope, grant_valid_until} | null (not loaded yet)
  const [auditLog, setAuditLog] = useState([]);
  const [nfcCards, setNfcCards] = useState([]);
  const [busy, setBusy] = useState("");
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

  async function revokeNfc(nfcUid) {
    if (!confirm(`Revoke NFC card ${nfcUid}? This cannot be undone from here — you'd need to re-register it.`)) return;
    await revokeNfcCard(nfcUid);
    refresh();
  }

  async function quickAdd(kind) {
    if (kind === "condition") {
      const name = prompt("Condition name:");
      if (name) await addCondition(id, { name, critical_for_emergency: true });
    } else if (kind === "medication") {
      const drug_name = prompt("Drug name:");
      const prescribed_by_facility = prompt("Prescribing facility:");
      if (drug_name) await addMedication(id, { drug_name, prescribed_by_facility, active: true, critical_for_emergency: true });
    } else if (kind === "allergy") {
      const substance = prompt("Allergen:");
      if (substance) await addAllergy(id, { substance, critical_for_emergency: true });
    } else if (kind === "encounter") {
      const facility_name = prompt("Facility name:");
      const reason = prompt("Reason for visit:");
      if (facility_name) await addEncounter(id, { facility_name, encounter_type: "outpatient", reason });
    }
    refresh();
  }

  if (!patient) return <Layout><p className="text-slate-400">Loading...</p></Layout>;

  return (
    <Layout>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-800">{patient.full_name}</h1>
        <p className="text-sm text-slate-500">DOB {patient.date_of_birth} · Blood type {patient.blood_type || "unknown"}</p>
      </div>

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
        <Section title="Conditions" action={isStaff && <button onClick={() => quickAdd("condition")} className="text-xs text-blue-700">+ Add</button>}>
          {patient.conditions.map((c, i) => <p key={i} className="text-sm text-slate-700">{c.name} {c.is_chronic && <span className="text-xs text-amber-600">(chronic)</span>}</p>)}
        </Section>
        <Section title="Medications" action={isStaff && <button onClick={() => quickAdd("medication")} className="text-xs text-blue-700">+ Add</button>}>
          {patient.medications.map((m, i) => <p key={i} className="text-sm text-slate-700">{m.drug_name} <span className="text-xs text-slate-400">({m.prescribed_by_facility})</span></p>)}
        </Section>
        <Section title="Allergies" action={isStaff && <button onClick={() => quickAdd("allergy")} className="text-xs text-blue-700">+ Add</button>}>
          {patient.allergies.map((a, i) => <p key={i} className="text-sm text-slate-700">{a.substance} <span className="text-xs text-red-600">({a.severity})</span></p>)}
        </Section>
        <Section title="Visit / Transfer History" action={isStaff && <button onClick={() => quickAdd("encounter")} className="text-xs text-blue-700">+ Add</button>}>
          {patient.encounters.map((e, i) => <p key={i} className="text-sm text-slate-700">{e.facility_name} <span className="text-xs text-slate-400">({e.encounter_type})</span></p>)}
        </Section>
      </div>

      <Section title="Access Audit Log (who viewed this record)">
        <div className="space-y-1 max-h-48 overflow-y-auto">
          {auditLog.map((l, i) => (
            <p key={i} className="text-xs text-slate-500">
              <span className="font-mono">{l.timestamp}</span> — {l.actor_role || "system"} — {l.action}
            </p>
          ))}
        </div>
      </Section>
    </Layout>
  );
}
