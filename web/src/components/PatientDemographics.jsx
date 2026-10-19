import { useCallback, useEffect, useState } from "react";
import {
  updateDemographics, getReferenceList, listSponsors, listDependants, addDependant, removeDependant,
  listPatients, errorMessage, getCurrentUser,
} from "../api/client";
import { tr } from "../lib/i18n";

// [field, label, reference kind]
const CODED = [
  ["title_code", "Title", "titles"], ["religion_code", "Religion", "religions"], ["race_code", "Race", "races"],
  ["nation_code", "Nationality", "nations"], ["marital_code", "Marital status", "marital_statuses"],
  ["occupation_code", "Occupation", "occupations"],
];
const EDIT_ROLES = ["admin", "records_officer", "clinician", "receptionist"];

function nameOf(list, code) {
  return list?.find((x) => x.code === code)?.name || code || null;
}

function Dependants({ patientId, relationships, canEdit }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [matches, setMatches] = useState([]);
  const [relation, setRelation] = useState("");

  const load = useCallback(() => {
    listDependants(patientId).then(setRows).catch((e) => setError(errorMessage(e, "Could not load dependants.")));
  }, [patientId]);
  useEffect(load, [load]);

  async function find(e) {
    e.preventDefault();
    setError("");
    try {
      const all = await listPatients({});
      const q = search.trim().toLowerCase();
      setMatches(all.filter((p) => p.id !== patientId && (p.full_name.toLowerCase().includes(q) || (p.national_id || "").includes(q))).slice(0, 6));
    } catch (err) { setError(errorMessage(err, "Search failed.")); }
  }
  async function link(p) {
    setError("");
    try {
      await addDependant(patientId, { dependant_id: p.id, relation_code: relation || null });
      setMatches([]);
      setSearch("");
      load();
    } catch (err) { setError(errorMessage(err, "Could not link.")); }
  }
  async function unlink(id) {
    setError("");
    try { await removeDependant(patientId, id); load(); } catch (err) { setError(errorMessage(err, "Could not remove.")); }
  }

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-slate-800">{tr("Dependants")}</h3>
      {error && <p className="alert-error" role="alert">{error}</p>}
      {rows === null && !error && <p className="empty-state">{tr("Loading...")}</p>}
      {rows && rows.length === 0 && <p className="empty-state">{tr("No dependants linked.")}</p>}
      {rows && rows.length > 0 && (
        <ul>
          {rows.map((d) => (
            <li key={d.id} className="record-row">
              <span className="text-sm text-slate-900">{d.dependant_name}{d.relation ? ` (${d.relation})` : ""}</span>
              {canEdit && <button type="button" className="btn-chip" onClick={() => unlink(d.id)}>{tr("Remove")}</button>}
            </li>
          ))}
        </ul>
      )}
      {canEdit && (
        <form onSubmit={find} className="flex flex-wrap items-end gap-2" aria-label={tr("Add dependant")}>
          <div>
            <label htmlFor="dep-search" className="field-label">{tr("Find a patient")}</label>
            <input id="dep-search" className="field-input" value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder={tr("Name or NRIC")} />
          </div>
          <div>
            <label htmlFor="dep-rel" className="field-label">{tr("Relationship")}</label>
            <select id="dep-rel" className="field-input" value={relation} onChange={(e) => setRelation(e.target.value)}>
              <option value="">{tr("Not stated")}</option>
              {(relationships || []).map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
            </select>
          </div>
          <button type="submit" className="btn-secondary" disabled={!search.trim()}>{tr("Search")}</button>
        </form>
      )}
      {matches.length > 0 && (
        <ul className="rounded-lg border border-slate-200">
          {matches.map((p) => (
            <li key={p.id} className="flex items-center justify-between px-3 py-2 text-sm">
              <span>{p.full_name}</span>
              <button type="button" className="btn-add" onClick={() => link(p)}>{tr("Link")}</button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// View and edit the coded demographics, sponsor and dependants of one patient.
// `demographics` is the object on the full patient record.
export default function PatientDemographics({ patientId, demographics, onChanged }) {
  const user = getCurrentUser();
  const canEdit = EDIT_ROLES.includes(user?.role);
  const [lists, setLists] = useState({});
  const [sponsors, setSponsors] = useState([]);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState(demographics || {});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let off = false;
    const kinds = [...CODED.map((c) => c[2]), "states", "relationships"];
    Promise.all(kinds.map((k) => getReferenceList(k).then((r) => [k, r]).catch(() => [k, []]))).then((pairs) => {
      if (!off) setLists(Object.fromEntries(pairs));
    });
    listSponsors().then((s) => !off && setSponsors(s)).catch(() => {});
    return () => { off = true; };
  }, []);
  useEffect(() => setForm(demographics || {}), [demographics]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  async function save(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const body = {};
      for (const k of Object.keys(demographics || {})) {
        if ((form[k] || "") !== (demographics[k] || "")) body[k] = form[k] || "";
      }
      if (Object.keys(body).length) await updateDemographics(patientId, body);
      setEditing(false);
      onChanged?.();
    } catch (err) { setError(errorMessage(err, "Could not save.")); } finally { setSaving(false); }
  }

  const d = demographics || {};
  const rows = [
    ...CODED.map(([field, label, kind]) => [label, nameOf(lists[kind], d[field])]),
    ["Address", d.address_line],
    ["Postcode", d.postcode],
    ["City", d.city],
    ["State", nameOf(lists.states, d.state_code)],
    ["Sponsor", sponsors.find((s) => s.code === d.sponsor_code)?.name || d.sponsor_code],
    ["Sponsor member no.", d.sponsor_member_no],
  ];

  return (
    <div className="space-y-5">
      {!editing ? (
        <div className="space-y-3">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
            {rows.map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-slate-500">{label}</dt>
                <dd className="text-sm text-slate-900">{value || <span className="text-slate-400">{tr("Not recorded")}</span>}</dd>
              </div>
            ))}
          </dl>
          {canEdit && <button type="button" className="btn-secondary" onClick={() => setEditing(true)}>{tr("Edit demographics")}</button>}
        </div>
      ) : (
        <form onSubmit={save} className="space-y-3" aria-label={tr("Edit demographics")}>
          <div className="grid gap-3 sm:grid-cols-3">
            {CODED.map(([field, label, kind]) => (
              <div key={field}>
                <label htmlFor={`dm-${field}`} className="field-label">{label}</label>
                <select id={`dm-${field}`} className="field-input" value={form[field] || ""} onChange={set(field)}>
                  <option value="">{tr("Not recorded")}</option>
                  {(lists[kind] || []).map((o) => <option key={o.code} value={o.code}>{o.name}</option>)}
                </select>
              </div>
            ))}
            <div className="sm:col-span-3">
              <label htmlFor="dm-address" className="field-label">{tr("Address")}</label>
              <input id="dm-address" className="field-input" value={form.address_line || ""} onChange={set("address_line")} maxLength={255} />
            </div>
            <div>
              <label htmlFor="dm-postcode" className="field-label">{tr("Postcode")}</label>
              <input id="dm-postcode" className="field-input" value={form.postcode || ""} onChange={set("postcode")} maxLength={16} />
            </div>
            <div>
              <label htmlFor="dm-city" className="field-label">{tr("City")}</label>
              <input id="dm-city" className="field-input" value={form.city || ""} onChange={set("city")} maxLength={128} />
            </div>
            <div>
              <label htmlFor="dm-state" className="field-label">{tr("State")}</label>
              <select id="dm-state" className="field-input" value={form.state_code || ""} onChange={set("state_code")}>
                <option value="">{tr("Not recorded")}</option>
                {(lists.states || []).map((o) => <option key={o.code} value={o.code}>{o.name}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="dm-sponsor" className="field-label">{tr("Sponsor")}</label>
              <select id="dm-sponsor" className="field-input" value={form.sponsor_code || ""} onChange={set("sponsor_code")}>
                <option value="">{tr("None")}</option>
                {sponsors.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
              </select>
            </div>
            <div>
              <label htmlFor="dm-member" className="field-label">{tr("Sponsor member no.")}</label>
              <input id="dm-member" className="field-input" value={form.sponsor_member_no || ""} onChange={set("sponsor_member_no")} maxLength={64} />
            </div>
          </div>
          <p className="text-xs text-slate-500">{tr("A known postcode fills in the city and state when those are left empty.")}</p>
          {error && <p className="alert-error" role="alert">{error}</p>}
          <div className="flex gap-2">
            <button type="submit" className="btn-primary" disabled={saving}>{saving ? "Saving..." : "Save"}</button>
            <button type="button" className="btn-secondary" onClick={() => { setEditing(false); setForm(demographics || {}); setError(""); }}>{tr("Cancel")}</button>
          </div>
        </form>
      )}
      <Dependants patientId={patientId} relationships={lists.relationships} canEdit={canEdit} />
    </div>
  );
}
