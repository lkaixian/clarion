// Demo plugin. DELETE THIS FOLDER (and backend/app/demo_plugin/) for production.
// Login.jsx loads it with import.meta.glob, so the build still passes without it.
import { tr } from "../lib/i18n";

const ACCOUNTS = [
  ["patient@clarion.demo", "patient123"],
  ["receptionist@clarion.demo", "receptionist123"],
  ["pharmacist@clarion.demo", "pharmacist123"],
  ["clinician@clarion.demo", "clinician123"],
  ["admin@clarion.demo", "admin123"],
];

export const prefill = { identifier: ACCOUNTS[0][0], password: ACCOUNTS[0][1] };

export function Banner() {
  return (
    <div role="note" className="bg-amber-50 border border-amber-200 text-amber-900 text-xs p-3 rounded-lg mb-4">
      <p className="font-semibold">{tr("Demo system, synthetic data only")}</p>
      <p className="mb-1">{tr("DEMO PURPOSE: two-step verification (2FA) is disabled for these demo accounts. Other accounts still get the 2FA page.")}</p>
      <ul className="font-mono space-y-0.5">
        {ACCOUNTS.map(([e, pw]) => <li key={e}>{e} / {pw}</li>)}
      </ul>
    </div>
  );
}
