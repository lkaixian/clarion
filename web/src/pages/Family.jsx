import { useCallback, useEffect, useState } from "react";
import Layout from "../components/Layout";
import { useProfileSwitch } from "../components/ProfileSwitcher";
import { createProfile, errorMessage, getCurrentUser, approveGuardian, getGuardians, getProfiles, removeGuardian } from "../api/client";
import { tr } from "../lib/i18n";

const INPUT = "border border-slate-300 rounded-lg px-3 py-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-600";
const BTN = "bg-blue-800 hover:bg-blue-900 text-white text-sm font-semibold px-4 py-2 rounded-lg disabled:opacity-50";
const BTN2 = "border border-slate-300 text-sm px-3 py-1.5 rounded-lg hover:bg-slate-50 disabled:opacity-50";

const RELATIONS = [
  ["1", "Child"], ["3", "Mother"], ["4", "Father"], ["9", "Grandmother"],
  ["10", "Grandfather"], ["12", "Guardian (of a ward)"], ["99", "Others"],
];

const today = () => new Date().toISOString().slice(0, 10);

export function AddProfileForm({ onAdded }) {
  const [f, setF] = useState({ full_name: "", date_of_birth: "", relation_code: "" });
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    setErr("");
    if (!f.full_name.trim()) return setErr(tr("Enter the full name."));
    if (!f.date_of_birth || f.date_of_birth > today()) return setErr(tr("Enter a valid date of birth."));
    if (!f.relation_code) return setErr(tr("Choose the relationship."));
    const body = { full_name: f.full_name.trim(), date_of_birth: f.date_of_birth, relation_code: f.relation_code };
    setBusy(true);
    try {
      await createProfile(body);
      setF({ full_name: "", date_of_birth: "", relation_code: "" });
      onAdded();
    } catch (ex) {
      const s = ex?.response?.status;
      if (s === 409) setErr(errorMessage(ex, tr("Could not save this profile. Please try again.")));
      else if (s === 400) setErr(tr("You can have at most 10 profiles."));
      else setErr(errorMessage(ex, tr("Could not add the profile.")));
    } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit} noValidate className="space-y-3 max-w-md">
      <div>
        <label htmlFor="fp-name" className="block text-sm font-medium text-slate-700">{tr("Full name")}</label>
        <input id="fp-name" className={INPUT} value={f.full_name} onChange={set("full_name")} />
      </div>
      <div>
        <label htmlFor="fp-dob" className="block text-sm font-medium text-slate-700">{tr("Date of birth")}</label>
        <input id="fp-dob" type="date" max={today()} className={INPUT} value={f.date_of_birth} onChange={set("date_of_birth")} />
      </div>
      <div>
        <label htmlFor="fp-rel" className="block text-sm font-medium text-slate-700">{tr("Relationship")}</label>
        <select id="fp-rel" className={INPUT} value={f.relation_code} onChange={set("relation_code")}>
          <option value="">{tr("Choose…")}</option>
          {RELATIONS.map(([code, label]) => <option key={code} value={code}>{tr(label)}</option>)}
        </select>
      </div>
      <p className="text-xs text-slate-500">{tr("If your family member already has an IC record at the clinic, ask the clinic desk to link it for you.")}</p>
      {err && <p role="alert" className="text-sm text-red-700">{err}</p>}
      <button type="submit" className={BTN} disabled={busy}>{tr("Add")}</button>
    </form>
  );
}

export default function Family() {
  const user = getCurrentUser();
  const doSwitch = useProfileSwitch();
  const [profiles, setProfiles] = useState(null);
  const [guardians, setGuardians] = useState([]);
  const [msg, setMsg] = useState("");
  const acting = !!user?.acting_for;

  const load = useCallback(async () => {
    try {
      setProfiles((await getProfiles()).profiles);
      if (!acting) setGuardians(await getGuardians());
    } catch (e) { setMsg(errorMessage(e, tr("Could not load your family."))); }
  }, [acting]);
  useEffect(() => { load(); }, [load]);

  const pending = guardians.filter((g) => g.pending);
  const approvedGuardians = guardians.filter((g) => !g.pending);
  const self = profiles?.find((p) => p.is_self);
  const isMinor = self ? self.age < 18 : false;

  async function pick(id) {
    setMsg("");
    try { await doSwitch(id); } catch (e) { setMsg(errorMessage(e, tr("Could not switch profile."))); }
  }

  async function approve(g) {
    setMsg("");
    try {
      await approveGuardian(g.link_id);
      setGuardians((l) => l.map((x) => (x.link_id === g.link_id ? { ...x, pending: false, approved: true } : x)));
    } catch (e) { setMsg(errorMessage(e, tr("Could not approve."))); }
  }

  async function remove(g) {
    setMsg("");
    try { await removeGuardian(g.link_id); setGuardians((l) => l.filter((x) => x.link_id !== g.link_id)); }
    catch (e) {
      setMsg(e?.response?.status === 403
        ? tr("A parent or guardian of someone under 18 can't be removed here.")
        : errorMessage(e, tr("Could not remove.")));
    }
  }

  return (
    <Layout>
      <h1 className="text-xl font-semibold text-slate-900 mb-4">{tr("My family")}</h1>
      {msg && <p role="alert" className="mb-3 text-sm text-red-700">{msg}</p>}
      <div className="space-y-6 max-w-2xl">
        <section aria-labelledby="fam-profiles">
          <h2 id="fam-profiles" className="font-semibold text-slate-800 mb-2">{tr("Profiles")}</h2>
          {!profiles ? <p>{tr("Loading…")}</p> : (
            <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
              {profiles.map((p) => (
                <li key={p.patient_id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <span>
                    <span className="font-medium text-slate-900">{p.full_name}</span>
                    {p.is_self && <span className="ml-2 text-xs text-slate-500">({tr("You")})</span>}
                    <span className="block text-xs text-slate-500">{tr("Age")} {p.age}</span>
                  </span>
                  {p.patient_id === user.patient_id
                    ? <span className="text-xs text-slate-500">{tr("Current")}</span>
                    : p.pending_approval
                    ? <span className="text-xs text-amber-700">{tr("Waiting for their approval")}</span>
                    : <button type="button" className={BTN2} onClick={() => pick(p.patient_id)}>{tr("Switch")}</button>}
                </li>
              ))}
            </ul>
          )}
        </section>

        {pending.length > 0 && (
          <section aria-labelledby="fam-pending" className="rounded-xl border border-amber-300 bg-amber-50 p-4">
            <h2 id="fam-pending" className="font-semibold text-amber-900 mb-2">{tr("Waiting for your approval")}</h2>
            <ul className="space-y-2">
              {pending.map((g) => (
                <li key={g.link_id} className="flex flex-wrap items-center justify-between gap-3">
                  <span>{g.full_name} {tr("wants to manage your account")}</span>
                  <span className="flex gap-2">
                    <button type="button" className={BTN} onClick={() => approve(g)}>{tr("Approve")}<span className="sr-only"> {g.full_name}</span></button>
                    <button type="button" className={BTN2} onClick={() => remove(g)}>{tr("Remove")}<span className="sr-only"> {g.full_name}</span></button>
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section aria-labelledby="fam-add">
          <h2 id="fam-add" className="font-semibold text-slate-800 mb-2">{tr("Add a child or parent")}</h2>
          <AddProfileForm onAdded={load} />
        </section>

        <section aria-labelledby="fam-guard">
          <h2 id="fam-guard" className="font-semibold text-slate-800 mb-2">{tr("Who can act for my account")}</h2>
          {acting ? (
            <p className="text-sm text-slate-600">{tr("Account settings are available on your own profile.")}</p>
          ) : approvedGuardians.length === 0 ? (
            <p className="text-sm text-slate-600">{tr("No one else can act for you.")}</p>
          ) : (
            <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
              {approvedGuardians.map((g) => (
                <li key={g.link_id} className="flex items-center justify-between gap-3 px-4 py-3">
                  <span>{g.full_name}</span>
                  {!isMinor && (
                    <button type="button" className={BTN2} onClick={() => remove(g)}>
                      {tr("Remove")}<span className="sr-only"> {g.full_name}</span>
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {isMinor && <p className="mt-2 text-sm text-slate-600">{tr("A parent or guardian of someone under 18 can't be removed here.")}</p>}
        </section>
      </div>
    </Layout>
  );
}
