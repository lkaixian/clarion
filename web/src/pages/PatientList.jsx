import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Layout from "../components/Layout";
import { listPatients, createPatient } from "../api/client";

export default function PatientList() {
  const [patients, setPatients] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ full_name: "", date_of_birth: "", blood_type: "", senior_citizen_mode: false });
  const [loading, setLoading] = useState(true);
  // Client-side only — listPatients() already fetches the whole array, and
  // at this project's demo/hackathon scale (a clinic's patient list, not a
  // national registry) a dedicated backend search endpoint would be scope
  // creep. Filters as-you-type; no debounce needed since it's just an
  // in-memory Array.filter, not a network call.
  const [search, setSearch] = useState("");

  function refresh() {
    listPatients().then(setPatients).finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  const filteredPatients = (() => {
    const q = search.trim().toLowerCase();
    if (!q) return patients;
    return patients.filter((p) =>
      p.full_name?.toLowerCase().includes(q) || p.national_id?.toLowerCase().includes(q)
    );
  })();

  async function handleCreate(e) {
    e.preventDefault();
    await createPatient(form);
    setShowForm(false);
    setForm({ full_name: "", date_of_birth: "", blood_type: "", senior_citizen_mode: false });
    refresh();
  }

  return (
    <Layout>
      <div className="flex items-center justify-between mb-6 gap-4">
        <h1 className="text-xl font-bold text-slate-800">Patients</h1>
        <div className="flex items-center gap-3">
          <input
            type="text"
            placeholder="Search by name or NRIC..."
            className="border rounded-lg px-3 py-2 text-sm w-64"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button
            onClick={() => setShowForm((s) => !s)}
            className="bg-blue-800 hover:bg-blue-900 text-white px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap"
          >
            {showForm ? "Cancel" : "+ New Patient (One-Click Intake)"}
          </button>
        </div>
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="bg-white border border-slate-200 rounded-xl p-5 mb-6 grid grid-cols-2 gap-4">
          <input required placeholder="Full name" className="border rounded-lg px-3 py-2 col-span-2"
            value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <input required placeholder="Date of birth (YYYY-MM-DD)" className="border rounded-lg px-3 py-2"
            value={form.date_of_birth} onChange={(e) => setForm({ ...form, date_of_birth: e.target.value })} />
          <input placeholder="Blood type (e.g. O+)" className="border rounded-lg px-3 py-2"
            value={form.blood_type} onChange={(e) => setForm({ ...form, blood_type: e.target.value })} />
          <label className="flex items-center gap-2 col-span-2 text-sm text-slate-600">
            <input type="checkbox" checked={form.senior_citizen_mode}
              onChange={(e) => setForm({ ...form, senior_citizen_mode: e.target.checked })} />
            Enable senior-citizen mode (physical card fallback)
          </label>
          <button className="bg-blue-800 text-white rounded-lg py-2 col-span-2 font-medium">Create</button>
        </form>
      )}

      {loading ? (
        <p className="text-slate-400">Loading...</p>
      ) : (
        <div className="bg-white border border-slate-200 rounded-xl divide-y">
          {patients.length === 0 ? (
            <p className="p-5 text-slate-400 text-sm">No patients yet — create one above.</p>
          ) : filteredPatients.length === 0 ? (
            // Distinct from the "zero patients in the system" state above —
            // this means the search just didn't match anything, not that
            // the clinic has no patients on file.
            <p className="p-5 text-slate-400 text-sm">No patients match "{search}".</p>
          ) : null}
          {filteredPatients.map((p) => (
            <Link key={p.id} to={`/patients/${p.id}`} className="flex items-center justify-between p-4 hover:bg-slate-50">
              <div>
                <p className="font-medium text-slate-800">{p.full_name}</p>
                <p className="text-xs text-slate-400">DOB {p.date_of_birth} · {p.blood_type || "blood type unknown"}</p>
              </div>
              {p.senior_citizen_mode && (
                <span className="text-xs bg-amber-100 text-amber-700 px-2 py-1 rounded-full">Senior mode</span>
              )}
            </Link>
          ))}
        </div>
      )}
    </Layout>
  );
}
