import { useEffect, useState } from "react";
import { getRolePermissions, updateRolePermissions } from "../../api/client";
import { Section } from "./_shared";

// ---------- Access Control (role → console-page matrix) ----------
// Per-facility control over which console pages each staff role can open
// (routers/admin.py::role-permissions). Rows are roles; columns are the
// configurable pages the backend hands back (always Patients / Reception /
// Pharmacy — `admin` is never an editable cell). The `admin` row is shown
// read-only and all-checked ("Admin always has full access"). Edits only
// affect a user the next time they sign in, because the client caches
// allowed_pages from login / GET /auth/me. Visual weight mirrors
// BudgetPanel / HospitalSettingsTab rather than the modal-driven CRUD tabs.
const PAGE_LABELS = { patients: "Patients", reception: "Reception", pharmacy: "Pharmacy", ancillary: "Ancillary", dental: "Dental" };

function roleLabel(role) {
  return role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Order-independent comparison of two allowed_pages lists.
function samePages(a, b) {
  if (a.length !== b.length) return false;
  const set = new Set(a);
  return b.every((p) => set.has(p));
}

export default function AccessControlTab() {
  const [entries, setEntries] = useState([]); // server truth, as returned
  const [edited, setEdited] = useState({}); // role -> allowed_pages[] (editable rows only)
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [justSaved, setJustSaved] = useState(false);

  function hydrate(data) {
    setEntries(data);
    const next = {};
    for (const e of data) {
      if (e.editable) next[e.role] = [...e.allowed_pages];
    }
    setEdited(next);
  }

  function refresh() {
    setLoading(true);
    getRolePermissions()
      .then(hydrate)
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load access control."))
      .finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  // Column set — identical on every entry per the backend contract, but read
  // it off an editable row rather than hard-coding in case that ever changes.
  const columns =
    entries.find((e) => e.editable)?.configurable_pages ||
    entries[0]?.configurable_pages ||
    ["patients", "reception", "pharmacy", "ancillary", "dental"];

  function toggle(role, page) {
    setJustSaved(false);
    setEdited((prev) => {
      const current = prev[role] || [];
      const nextPages = current.includes(page)
        ? current.filter((p) => p !== page)
        : [...current, page];
      return { ...prev, [role]: nextPages };
    });
  }

  // Only the editable rows whose selection actually differs from the server.
  const changedRoles = entries
    .filter((e) => e.editable && !samePages(edited[e.role] || [], e.allowed_pages))
    .map((e) => e.role);
  const dirty = changedRoles.length > 0;

  async function save() {
    if (!dirty) return;
    setSaving(true);
    setError("");
    setJustSaved(false);
    try {
      // Bulk PUT — send every editable role (not just the changed ones) so
      // the payload is a full, self-describing snapshot of the matrix.
      const body = entries
        .filter((e) => e.editable)
        .map((e) => ({ role: e.role, allowed_pages: edited[e.role] || [] }));
      const fresh = await updateRolePermissions(body);
      hydrate(fresh);
      setJustSaved(true);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save access control.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <Section title="Access Control"><p className="text-sm text-slate-400">Loading...</p></Section>;
  }

  return (
    <Section title="Access Control">
      <p className="text-sm text-slate-500 mb-4 max-w-2xl">
        Controls which console pages each staff role can open at this facility.
        Changes take effect the next time that user signs in.
      </p>

      {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}
      {justSaved && !dirty && (
        <div className="bg-green-50 text-green-700 text-sm p-2 rounded mb-3">Access control saved.</div>
      )}

      <div className="overflow-x-auto">
        <table className="text-sm border-collapse">
          <thead>
            <tr className="text-slate-500">
              <th className="text-left font-medium px-3 py-2">Role</th>
              {columns.map((page) => (
                <th key={page} className="font-medium px-3 py-2 text-center">
                  {PAGE_LABELS[page] || roleLabel(page)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => {
              const isAdmin = !entry.editable;
              const selected = isAdmin ? entry.allowed_pages : edited[entry.role] || [];
              return (
                <tr
                  key={entry.role}
                  className={`border-t border-slate-200 ${isAdmin ? "bg-slate-50 text-slate-400" : "text-slate-700"}`}
                >
                  <td className="px-3 py-2 font-medium capitalize whitespace-nowrap">
                    {roleLabel(entry.role)}
                    {isAdmin && (
                      <span className="block text-xs font-normal text-slate-400">
                        Admin always has full access.
                      </span>
                    )}
                  </td>
                  {columns.map((page) => (
                    <td key={page} className="px-3 py-2 text-center">
                      <input
                        type="checkbox"
                        checked={isAdmin ? true : selected.includes(page)}
                        disabled={isAdmin || saving}
                        onChange={() => toggle(entry.role, page)}
                      />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-3 mt-4">
        <button
          onClick={save}
          disabled={saving || !dirty}
          className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save changes"}
        </button>
        {dirty && (
          <span className="text-xs text-slate-400">
            Unsaved changes to: {changedRoles.map(roleLabel).join(", ")}
          </span>
        )}
      </div>
    </Section>
  );
}
