import { useEffect, useState } from "react";
import {
  getWards, createWard, updateWard, deleteWard,
  getFloors, createFloor, updateFloor, deleteFloor,
} from "../../api/client";
import WardMap from "../../components/WardMap";
import { Section } from "./_shared";
import { occupancyColor, occupancyTextColor } from "./occupancy";

// ---------- Ward capacity ----------
const WARD_TYPE_OPTIONS = ["general", "icu", "pediatric", "maternity", "emergency", "other"];

function WardModal({ mode, initial, onClose, onSaved }) {
  const [wardName, setWardName] = useState(initial?.ward_name ?? "");
  const [wardType, setWardType] = useState(initial?.ward_type ?? "general");
  const [totalBeds, setTotalBeds] = useState(initial?.total_beds ?? "");
  // occupied_beds is only collected here on CREATE (defaults to 0 if left
  // blank) — on EDIT it's deliberately left out of this modal in favor of
  // the day-to-day +/- stepper on the ward card, per the task's "fastest
  // possible interaction" requirement for that field.
  const [occupiedBeds, setOccupiedBeds] = useState(initial?.occupied_beds ?? 0);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!wardName.trim()) {
      setError("Ward name is required.");
      return;
    }
    if (!totalBeds || Number(totalBeds) <= 0) {
      setError("Total beds must be greater than 0.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (mode === "add") {
        await createWard({
          ward_name: wardName.trim(),
          ward_type: wardType,
          total_beds: Number(totalBeds),
          occupied_beds: Number(occupiedBeds) || 0,
        });
      } else {
        await updateWard(initial.id, {
          ward_name: wardName.trim(),
          ward_type: wardType,
          total_beds: Number(totalBeds),
        });
      }
      onSaved();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-panel">
        <h3 className="font-semibold text-slate-800 mb-4">{mode === "add" ? "Add Ward" : "Edit Ward"}</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="alert-error">{error}</div>}

          <div>
            <label className="field-label">Ward name<span className="text-red-600"> *</span></label>
            <input
              className="field-input"
              type="text"
              value={wardName}
              onChange={(e) => setWardName(e.target.value)}
            />
          </div>

          <div>
            <label className="field-label">Ward type</label>
            <select
              className="field-input"
              value={wardType}
              onChange={(e) => setWardType(e.target.value)}
            >
              {WARD_TYPE_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          <div>
            <label className="field-label">Total beds<span className="text-red-600"> *</span></label>
            <input
              className="field-input"
              type="number"
              min="1"
              value={totalBeds}
              onChange={(e) => setTotalBeds(e.target.value)}
            />
          </div>

          {mode === "add" && (
            <div>
              <label className="field-label">Occupied beds (at creation)</label>
              <input
                className="field-input"
                type="number"
                min="0"
                value={occupiedBeds}
                onChange={(e) => setOccupiedBeds(e.target.value)}
              />
            </div>
          )}

          <div className="flex gap-2 pt-2">
            <button disabled={saving} className="btn-primary">
              {saving ? "Saving..." : "Save"}
            </button>
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// The non-floor "Ward Capacity" cards — standalone Ward rows with aggregate
// total/occupied bed counts (as opposed to floor-generated wards). Shown
// under the "Floors" view of WardsTab.
function StandaloneWardsTab() {
  const [wards, setWards] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null); // { mode: 'add'|'edit', initial } | null
  const [busyId, setBusyId] = useState(null);

  function refresh() {
    setLoading(true);
    getWards().then(setWards).finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  // Same "fast, no modal" reasoning as InventoryTab's quantity stepper —
  // occupied_beds is a day-to-day ward-board update, not an occasional edit,
  // so it gets a dedicated +/-1 affordance instead of requiring the full
  // edit modal every time a bed turns over.
  async function adjustOccupied(ward, delta) {
    const next = ward.occupied_beds + delta;
    if (next < 0 || next > ward.total_beds) return;
    setBusyId(ward.id);
    try {
      const updated = await updateWard(ward.id, { occupied_beds: next });
      setWards((prev) => prev.map((w) => (w.id === ward.id ? updated : w)));
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to update bed count.");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(ward) {
    if (!confirm(`Remove ward "${ward.ward_name}"? This can't be undone.`)) return;
    await deleteWard(ward.id);
    refresh();
  }

  return (
    <Section
      title="Ward Capacity"
      action={<button onClick={() => setModal({ mode: "add", initial: null })} className="btn-primary">+ Add Ward</button>}
    >
      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : wards.length === 0 ? (
        <p className="text-sm text-slate-400">No wards on file yet — add one above.</p>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          {wards.map((w) => (
            <div key={w.id} className="border border-slate-200 rounded-lg p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-slate-800">{w.ward_name}</p>
                  <p className="text-xs text-slate-400 capitalize">{w.ward_type || "unspecified type"}</p>
                </div>
                <span className={`text-xs font-semibold whitespace-nowrap ${occupancyTextColor(w.occupancy_pct)}`}>
                  {w.occupancy_pct}%
                </span>
              </div>

              <div className="w-full bg-slate-100 rounded-full h-2 mt-2 overflow-hidden">
                <div
                  className={`h-2 rounded-full ${occupancyColor(w.occupancy_pct)}`}
                  style={{ width: `${Math.min(100, w.occupancy_pct)}%` }}
                />
              </div>
              <p className="text-xs text-slate-500 mt-1">
                {w.occupied_beds} / {w.total_beds} beds occupied · {w.available_beds} available
              </p>

              <div className="flex items-center justify-between mt-3">
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => adjustOccupied(w, -1)}
                    disabled={busyId === w.id || w.occupied_beds <= 0}
                    className="w-6 h-6 text-sm border border-slate-300 rounded disabled:opacity-30"
                    title="Discharge one bed"
                  >
                    −
                  </button>
                  <span className="text-xs text-slate-500 w-6 text-center">{w.occupied_beds}</span>
                  <button
                    onClick={() => adjustOccupied(w, 1)}
                    disabled={busyId === w.id || w.occupied_beds >= w.total_beds}
                    className="w-6 h-6 text-sm border border-slate-300 rounded disabled:opacity-30"
                    title="Admit one bed"
                  >
                    +
                  </button>
                </div>
                <div className="flex items-center gap-3">
                  <button onClick={() => setModal({ mode: "edit", initial: w })} className="text-xs text-blue-700">Edit</button>
                  <button onClick={() => handleDelete(w)} className="text-xs text-red-700">Delete</button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {modal && (
        <WardModal
          mode={modal.mode}
          initial={modal.initial}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); refresh(); }}
        />
      )}
    </Section>
  );
}

// ---------- Floors (auto-generated wards) ----------
// A floor is a number-driven block of uniform wards: set ward_count +
// beds_per_ward and the backend creates/adjusts that many general Ward rows
// (routers/admin.py). gender_restriction is a soft routing rule applied at
// admission time only — changing it never moves patients already in a bed.
// Mirrors WardModal's shell exactly.
const FLOOR_GENDER_OPTIONS = [
  { value: "", label: "— mixed —" },
  { value: "male", label: "Male only" },
  { value: "female", label: "Female only" },
];

function FloorModal({ mode, initial, onClose, onSaved }) {
  const [floorLabel, setFloorLabel] = useState(initial?.floor_label ?? "");
  const [gender, setGender] = useState(initial?.gender_restriction ?? "");
  const [wardCount, setWardCount] = useState(initial?.ward_count ?? "");
  const [bedsPerWard, setBedsPerWard] = useState(initial?.beds_per_ward ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!floorLabel.trim()) {
      setError("Floor label is required.");
      return;
    }
    if (!wardCount || Number(wardCount) < 1) {
      setError("Ward count must be at least 1.");
      return;
    }
    if (!bedsPerWard || Number(bedsPerWard) < 1) {
      setError("Beds per ward must be at least 1.");
      return;
    }
    setSaving(true);
    setError("");
    const payload = {
      floor_label: floorLabel.trim(),
      gender_restriction: gender || null,
      ward_count: Number(wardCount),
      beds_per_ward: Number(bedsPerWard),
    };
    try {
      if (mode === "add") await createFloor(payload);
      else await updateFloor(initial.id, payload);
      onSaved();
    } catch (err) {
      // Surfaces the backend's cross-field 400s inline (e.g. "can't reduce
      // ward_count: a ward still has an admitted patient").
      setError(err?.response?.data?.detail || "Failed to save. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <div className="modal-panel">
        <h3 className="font-semibold text-slate-800 mb-4">{mode === "add" ? "Add Floor" : "Edit Floor"}</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="alert-error">{error}</div>}

          <div>
            <label className="field-label">Floor label<span className="text-red-600"> *</span></label>
            <input
              className="field-input"
              type="text"
              placeholder="e.g. Level 3 Male Medical"
              value={floorLabel}
              onChange={(e) => setFloorLabel(e.target.value)}
            />
          </div>

          <div>
            <label className="field-label">Gender restriction</label>
            <select
              className="field-input"
              value={gender}
              onChange={(e) => setGender(e.target.value)}
            >
              {FLOOR_GENDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>

          <div>
            <label className="field-label">Ward count<span className="text-red-600"> *</span></label>
            <input
              className="field-input"
              type="number"
              min="1"
              value={wardCount}
              onChange={(e) => setWardCount(e.target.value)}
            />
          </div>

          <div>
            <label className="field-label">Beds per ward<span className="text-red-600"> *</span></label>
            <input
              className="field-input"
              type="number"
              min="1"
              value={bedsPerWard}
              onChange={(e) => setBedsPerWard(e.target.value)}
            />
          </div>

          {mode === "edit" && (
            <p className="text-xs text-slate-400">
              Lowering the ward count or shrinking beds per ward is refused while a patient still
              occupies an affected bed. Changing the label or gender rule never moves anyone.
            </p>
          )}

          <div className="flex gap-2 pt-2">
            <button disabled={saving} className="btn-primary">
              {saving ? "Saving..." : "Save"}
            </button>
            <button type="button" onClick={onClose} className="btn-secondary">
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function FloorsTab() {
  const [floors, setFloors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null); // { mode: 'add'|'edit', initial } | null
  const [busyId, setBusyId] = useState(null);

  function refresh() {
    setLoading(true);
    getFloors().then(setFloors).finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  async function handleDelete(floor) {
    if (!confirm(`Remove "${floor.floor_label}" and its ${floor.ward_count} ward(s)? This can't be undone.`)) return;
    setBusyId(floor.id);
    try {
      await deleteFloor(floor.id);
      refresh();
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to delete floor.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <Section
      title="Floors"
      action={<button onClick={() => setModal({ mode: "add", initial: null })} className="btn-primary">+ Add Floor</button>}
    >
      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : floors.length === 0 ? (
        <p className="text-sm text-slate-400">No floors yet — add one above (e.g. Level 3 Male Medical).</p>
      ) : (
        <div className="space-y-2">
          {floors.map((f) => {
            const pct = f.total_beds ? Math.round((f.occupied_beds / f.total_beds) * 100) : 0;
            return (
              <div key={f.id} className="border border-slate-200 rounded-lg px-3 py-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm text-slate-700 min-w-0">
                    <p className="font-medium">{f.floor_label}</p>
                    <p className="text-xs text-slate-400">
                      {f.gender_restriction ? `${f.gender_restriction} only` : "Mixed"}
                      {" · "}{f.ward_count} ward(s) × {f.beds_per_ward} beds
                      {" · "}<span className={occupancyTextColor(pct)}>{f.occupied_beds} / {f.total_beds} beds used</span>
                    </p>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <button onClick={() => setModal({ mode: "edit", initial: f })} className="text-xs text-blue-700">Edit</button>
                    <button onClick={() => handleDelete(f)} disabled={busyId === f.id} className="text-xs text-red-700 disabled:opacity-40">Delete</button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {modal && (
        <FloorModal
          mode={modal.mode}
          initial={modal.initial}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); refresh(); }}
        />
      )}
    </Section>
  );
}

// ---------- Wards (Floors + Heat map + Full details) ----------
// One tab replacing the former "Ward Capacity", "Floors" and "Ward Map"
// tabs. A segmented control switches between three views of the same
// facility layout:
//   floors  — structure: add/edit floors and standalone wards
//   heatmap — read-only, wards tinted by occupancy (at-a-glance board)
//   full    — bed-level admit / discharge / move (the old Ward Map)
const WARD_VIEWS = [
  { key: "floors", label: "Floors" },
  { key: "heatmap", label: "Heat map" },
  { key: "full", label: "Full details" },
];

export default function WardsTab() {
  const [view, setView] = useState("floors");
  return (
    <div>
      <div className="inline-flex rounded-lg border border-slate-200 p-0.5 mb-4 bg-slate-50">
        {WARD_VIEWS.map((v) => (
          <button
            key={v.key}
            onClick={() => setView(v.key)}
            className={`px-3 py-1.5 text-sm font-medium rounded-md ${
              view === v.key ? "bg-white text-blue-800 shadow-sm" : "text-slate-500 hover:text-slate-700"
            }`}
          >
            {v.label}
          </button>
        ))}
      </div>

      {view === "floors" && (
        <>
          <FloorsTab />
          <StandaloneWardsTab />
        </>
      )}
      {view === "heatmap" && (
        <Section title="Occupancy heat map">
          <WardMap mode="heatmap" />
        </Section>
      )}
      {view === "full" && (
        <Section title="Bed board">
          <WardMap />
        </Section>
      )}
    </div>
  );
}
