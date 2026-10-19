import { useEffect, useState } from "react";
import { errorMessage, getConsent, recordConsent } from "../api/client";

// Opt-in: until it is ticked, other facilities can neither see this patient's
// visits nor be told about new ones. Each change is a new row in the PDPA
// consent ledger (the newest row wins), so withdrawing keeps the history.
export default function SharingConsent({ patientId }) {
  const [granted, setGranted] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getConsent(patientId)
      .then((c) => setGranted(c.effective?.cross_facility_sharing === true))
      .catch((e) => setError(errorMessage(e, "Could not load consent.")));
  }, [patientId]);

  async function toggle(next) {
    setBusy(true);
    setError("");
    try {
      await recordConsent(patientId, "cross_facility_sharing", next, "Recorded at the front desk");
      setGranted(next);
    } catch (e) {
      setError(errorMessage(e, "Could not record consent."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="text-sm text-slate-700">
      <label className="flex items-start gap-2">
        <input type="checkbox" className="mt-1" disabled={busy || granted === null}
          checked={granted === true} onChange={(e) => toggle(e.target.checked)} />
        <span>
          The patient agrees that other CLARION facilities may view their visit history.
          <span className="block text-xs text-slate-500">
            Ask them first. Ticking it also shares their latest visits from this facility; withdrawing stops
            access straight away and removes this facility's entries from the central index.
          </span>
        </span>
      </label>
      {error && <p className="text-xs text-red-600 mt-1" role="alert">{error}</p>}
    </div>
  );
}
