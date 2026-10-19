import { useEffect, useState } from "react";
import { listRegistrationClaims, decideRegistrationClaim, errorMessage } from "../api/client";
import { tr } from "../lib/i18n";

// Staff: people who signed up on the web for this record and are still unverified.
// Approving one makes it the account; every other pending sign-up is rejected and its
// (inbox-proven) email is flagged as likely spam/scam.
export default function RegistrationClaims({ patientId }) {
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const load = () => listRegistrationClaims(patientId).then(setRows).catch(() => {});
  useEffect(() => { load(); }, [patientId]);

  async function decide(id, action) {
    if (action === "approve" && !window.confirm("Approve this sign-up? Only do this after checking the patient's IC. All other pending sign-ups will be rejected and flagged.")) return;
    setError("");
    try { await decideRegistrationClaim(patientId, id, action); await load(); }
    catch (err) { setError(errorMessage(err, "Could not save that decision.")); }
  }

  const pending = rows.filter((r) => r.status === "pending");
  if (!rows.length) return null;
  return (
    <div className="mt-3">
      <p className="text-sm font-semibold text-slate-700">Web sign-ups waiting for verification ({pending.length})</p>
      {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
      <ul className="mt-1 space-y-1">
        {rows.map((r) => (
          <li key={r.id} className="flex items-center justify-between bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 text-sm">
            <span>
              {r.email} <span className="text-xs text-slate-500">
                {r.email_verified ? "email confirmed" : "email NOT confirmed"} · {r.status}{r.flagged ? " · flagged" : ""}
              </span>
            </span>
            {r.status === "pending" && (
              <span className="space-x-3">
                <button onClick={() => decide(r.id, "approve")} className="text-xs font-semibold text-green-700">{tr("Approve")}</button>
                <button onClick={() => decide(r.id, "reject")} className="text-xs text-red-700">{tr("Reject")}</button>
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
