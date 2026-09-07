import { useEffect, useState } from "react";
import {
  getSections, createSection, updateSection, deleteSection,
} from "../../api/client";
import { Section } from "./_shared";

// ---------- Sections (front-desk registration counters) ----------
// Admin-managed list of the hospital's front-desk counters (e.g. General
// Registration, O&G, ICU). A receptionist/clinician pinned to a section in
// the Staff Roster tab only ever sees that section's reception queue; the
// backend hard-scopes them server-side. Mirrors RoomsTab / RoomModal.
function SectionModal({ mode, initial, onClose, onSaved }) {
  const [name, setName] = useState(initial?.name ?? "");
  const [active, setActive] = useState(initial?.active ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Section name is required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (mode === "add") await createSection({ name: name.trim() });
      // active is only collected on edit — a brand-new section is active.
      else await updateSection(initial.id, { name: name.trim(), active });
      onSaved();
    } catch (err) {
      if (err?.response?.status === 409) {
        setError("A section with that name already exists at this facility.");
      } else {
        setError(err?.response?.data?.detail || "Failed to save. Check the name and try again.");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl p-6 max-w-md w-full max-h-[90vh] overflow-y-auto">
        <h3 className="font-semibold text-slate-800 mb-4">{mode === "add" ? "Add Section" : "Edit Section"}</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error}</div>}

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Section name<span className="text-red-600"> *</span></label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              type="text"
              placeholder="e.g. General Registration, O&G, ICU"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {mode === "edit" && (
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
              Active (assignable to staff and offered as a check-in counter)
            </label>
          )}

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

export default function SectionsTab() {
  const [sections, setSections] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);

  function refresh() {
    setLoading(true);
    getSections().then(setSections).finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  async function handleDelete(section) {
    if (!confirm(`Delete section "${section.name}"? Staff assigned to it will be unassigned.`)) return;
    await deleteSection(section.id);
    refresh();
  }

  return (
    <Section
      title="Sections"
      action={<button onClick={() => setModal({ mode: "add", initial: null })} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">+ Add section</button>}
    >
      <p className="text-sm text-slate-500 mb-4 max-w-2xl">
        Front-desk registration counters for this hospital (e.g. General Registration, O&G, ICU).
        Assign staff to a section in the Staff Roster tab; a section-assigned receptionist only
        sees that section's queue.
      </p>

      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : sections.length === 0 ? (
        <p className="text-sm text-slate-400">No sections yet — add one above (e.g. General Registration).</p>
      ) : (
        <div className="space-y-2">
          {sections.map((section) => (
            <div
              key={section.id}
              className={`flex items-center justify-between gap-3 rounded-lg px-3 py-2 border ${
                section.active ? "bg-slate-50 border-slate-200" : "bg-white border-slate-200 opacity-60"
              }`}
            >
              <div className="text-sm text-slate-700 min-w-0">
                <p className="font-medium">
                  {section.name}
                  <span className={`ml-2 text-xs font-semibold uppercase ${section.active ? "text-green-700" : "text-slate-500"}`}>
                    {section.active ? "Active" : "Inactive"}
                  </span>
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <button onClick={() => setModal({ mode: "edit", initial: section })} className="text-xs text-blue-700">Edit</button>
                <button onClick={() => handleDelete(section)} className="text-xs text-red-700">Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {modal && (
        <SectionModal
          mode={modal.mode}
          initial={modal.initial}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); refresh(); }}
        />
      )}
    </Section>
  );
}
