import { useEffect, useState } from "react";
import { getOtherAdmins, resetStaffPassword, resetUserMfa } from "../../api/client";
import { Section } from "./_shared";
import StepUpForm from "./StepUpForm";
import { tr } from "../../lib/i18n";

// Other administrators at this facility. An admin who forgot their password,
// or lost their phone AND recovery codes, is recovered here by a colleague
// (who re-enters their own password + code first). The last admin recovers
// from the server: db/reset_admin_password.py --reset-mfa / --mfa-only.
export default function AdminAccountsPanel() {
  const [admins, setAdmins] = useState(null);
  const [pending, setPending] = useState(null); // { id, kind: "password" | "mfa" }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null); // { id, kind, email, password? }

  useEffect(() => {
    getOtherAdmins().then(setAdmins).catch(() => setAdmins([]));
  }, []);

  async function run(a, kind, stepUp) {
    setBusy(true);
    setError("");
    try {
      if (kind === "password") {
        const r = await resetStaffPassword(a.id, stepUp);
        setResult({ id: a.id, kind, email: r.email, password: r.temporary_password });
      } else {
        await resetUserMfa(a.id, stepUp);
        setResult({ id: a.id, kind, email: a.email });
      }
      setPending(null);
    } catch (err) {
      setError(err?.response?.data?.detail || "That didn't work.");
    } finally {
      setBusy(false);
    }
  }

  if (!admins || admins.length === 0) return null;

  return (
    <Section title={tr("Administrators")}>
      <p className="text-xs text-slate-500 mb-2">
        Recover a colleague who forgot their password or lost their authenticator. You'll be asked for your own
        password and code. Your own account can't be reset here.
      </p>
      <div className="space-y-2">
        {admins.map((a) => (
          <div key={a.id} className="border border-slate-200 rounded-lg overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <div className="text-sm text-slate-700 min-w-0">
                <p className="font-medium">
                  {a.full_name}
                  {a.must_change_password && (
                    <span className="ml-2 text-xs font-semibold text-amber-700 uppercase">{tr("⚠ Pending first login")}</span>
                  )}
                </p>
                <p className="text-xs text-slate-400">
                  {a.email} · authenticator {a.mfa_enabled ? "set up" : "not set up"}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => { setError(""); setPending({ id: a.id, kind: "password" }); }}
                  className="text-xs border border-slate-300 rounded-lg px-2 py-1 hover:bg-slate-50"
                >
                  Reset password
                </button>
                <button
                  type="button"
                  onClick={() => { setError(""); setPending({ id: a.id, kind: "mfa" }); }}
                  className="text-xs border border-slate-300 rounded-lg px-2 py-1 hover:bg-slate-50"
                >
                  Reset authenticator
                </button>
              </div>
            </div>
            {pending?.id === a.id && (
              <StepUpForm
                title={
                  pending.kind === "password"
                    ? `Issue a temporary password for ${a.full_name}. Their authenticator is not changed.`
                    : `Clear ${a.full_name}'s authenticator and recovery codes. They'll set up a new one at next sign-in.`
                }
                busy={busy}
                error={error}
                onSubmit={(s) => run(a, pending.kind, s)}
                onCancel={() => setPending(null)}
              />
            )}
            {result?.id === a.id && (
              <div className="border-t border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 space-y-1" role="status">
                {result.kind === "password" ? (
                  <>
                    <p>{tr("Temporary password for")} <b>{result.email}</b> {tr("(shown once — give it to them in person):")}</p>
                    <p className="font-mono text-sm break-all select-all">{result.password}</p>
                    <p>{tr("They must choose a new password at next sign-in and still need their authenticator.")}</p>
                  </>
                ) : (
                  <p>{tr("Authenticator cleared for")} <b>{result.email}</b>{tr(". They'll enrol a new one at next sign-in.")}</p>
                )}
                <button type="button" onClick={() => setResult(null)} className="underline">{tr("Done, hide it")}</button>
              </div>
            )}
          </div>
        ))}
      </div>
    </Section>
  );
}
