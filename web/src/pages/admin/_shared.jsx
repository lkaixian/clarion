export function Section({ title, children, action }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 mb-4">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-slate-800">{title}</h2>
        {action}
      </div>
      {children}
    </div>
  );
}

// In-page tabs, same pattern (and same classes, for visual consistency) as
// PatientDetail.jsx's TABS/TabBar — a clinician bouncing between that page
// and this one shouldn't have to learn a second tab convention.
const TABS = [
  { key: "appointments", label: "Appointments" },
  { key: "inventory", label: "Medicine Inventory" },
  // Floors + standalone ward capacity + the bed-level ward map used to be
  // three separate tabs; they're now one "Wards" tab with an internal
  // Floors / Heat map / Full details view switcher (see WardsTab).
  { key: "wards", label: "Wards" },
  { key: "rooms", label: "Consultation Rooms" },
  { key: "sections", label: "Sections" },
  { key: "displays", label: "Waiting Room Displays" },
  { key: "staff", label: "Staff Roster" },
  { key: "hospital", label: "Hospital Settings" },
  { key: "access", label: "Access Control" },
];

export function TabBar({ active, onChange }) {
  return (
    <div className="flex gap-1 border-b border-slate-200 mb-4 overflow-x-auto">
      {TABS.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px whitespace-nowrap ${
            active === t.key
              ? "border-blue-800 text-blue-800"
              : "border-transparent text-slate-500 hover:text-slate-700"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
