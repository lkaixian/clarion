import { useEffect, useState } from "react";
import { createResponder, listResponders, revokeResponder, updateResponderExpiry } from "../../api/client";
import { Section } from "./_shared";

const DAY = 24 * 60 * 60 * 1000;
// The server caps the window (CLARION_RESPONDER_MAX_DAYS, default 90) and
// refuses anything past it; this only picks the form's starting value.
const defaultExpiry = () => new Date(Date.now() + 7 * DAY - new Date().getTimezoneOffset() * 60000)
  .toISOString().slice(0, 16);

function state(r) {
  // The server reports an expired account as inactive too, so check the date first.
  if (new Date(r.access_expires_at) <= new Date()) return "Expired";
  return r.active ? "Active" : "Revoked";
}

// Guards / volunteers who may scan emergency cards and nothing else. Every
// account has a mandatory expiry; the temporary password is shown once.
export default function RespondersTab() {
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState({ full_name: "", email: "", expires: defaultExpiry() });
  const [issued, setIssued] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => listResponders().then(setRows).catch(() => setRows([]));
  useEffect(() => { load(); }, []);

  async function run(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err?.response?.data?.detail || "That didn't work.");
    } finally {
      setBusy(false);
    }
  }

  const create = (e) => {
    e.preventDefault();
    run(async () => {
      // A datetime-local value has no offset; the server insists on one.
      const expires_at = new Date(form.expires).toISOString();
      setIssued(await createResponder({ full_name: form.full_name, email: form.email, expires_at }));
      setForm({ full_name: "", email: "", expires: defaultExpiry() });
    });
  };

  return (
    <Section title="Community responders">
      <p className="text-xs text-slate-500 mb-3">
        Guards and volunteers get a login that can scan emergency cards and nothing else. It ends on the expiry
        date you set, or at once if you revoke it. Every scan is recorded under their name.
      </p>

      <form onSubmit={create} className="flex flex-wrap items-end gap-2 mb-3">
        <label className="text-xs text-slate-600">Name
          <input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })}
            className="block border border-slate-300 rounded-lg px-2 py-1 text-sm" />
        </label>
        <label className="text-xs text-slate-600">Email
          <input required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })}
            className="block border border-slate-300 rounded-lg px-2 py-1 text-sm" />
        </label>
        <label className="text-xs text-slate-600">Access ends
          <input required type="datetime-local" value={form.expires} onChange={(e) => setForm({ ...form, expires: e.target.value })}
            className="block border border-slate-300 rounded-lg px-2 py-1 text-sm" />
        </label>
        <button type="submit" disabled={busy} className="btn-primary text-sm">Create responder</button>
      </form>
      {error && <p className="text-xs text-red-600 mb-2" role="alert">{error}</p>}

      {issued && (
        <div className="border border-amber-200 bg-amber-50 rounded-lg px-3 py-2 text-xs text-amber-900 mb-3 space-y-1" role="status">
          <p>Temporary password for <b>{issued.email}</b> (shown once, give it to them in person):</p>
          <p className="font-mono text-sm break-all select-all">{issued.temporary_password}</p>
          <button type="button" onClick={() => setIssued(null)} className="underline">Done, hide it</button>
        </div>
      )}

      {rows && rows.length === 0 && <p className="text-sm text-slate-500">No responder accounts yet.</p>}
      <div className="space-y-2">
        {(rows || []).map((r) => (
          <div key={r.id} className="flex flex-wrap items-center justify-between gap-2 border border-slate-200 rounded-lg px-3 py-2">
            <div className="text-sm text-slate-700 min-w-0">
              <p className="font-medium">{r.full_name} <span className="text-xs text-slate-500">· {state(r)}</span></p>
              <p className="text-xs text-slate-500">{r.email} · ends {new Date(r.access_expires_at).toLocaleString()}</p>
            </div>
            <div className="flex gap-2">
              <button type="button" disabled={busy}
                onClick={() => run(() => updateResponderExpiry(r.id, new Date(Date.now() + 7 * DAY).toISOString()))}
                className="text-xs border border-slate-300 rounded-lg px-2 py-1 hover:bg-slate-50">
                {r.active ? "Set to 7 days from now" : "Reinstate for 7 days"}
              </button>
              {r.active && (
                <button type="button" disabled={busy}
                  onClick={() => window.confirm(`Revoke ${r.full_name}'s access now?`) && run(() => revokeResponder(r.id))}
                  className="text-xs border border-red-300 text-red-700 rounded-lg px-2 py-1 hover:bg-red-50">
                  Revoke
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}
