import { useCallback, useEffect, useRef, useState } from "react";
import { getWardMap, admitPatient, dischargeAdmission, updateAdmission } from "../api/client";
import { formatDateTime } from "../lib/format";

// Match Reception.jsx's QUEUE_BOARD_POLL_MS — the ward map is a live board,
// same "responsive in a demo, not hammering the backend" tradeoff.
const WARD_MAP_POLL_MS = 4000;

function genderRuleLabel(g) {
  if (g === "male") return "Male only";
  if (g === "female") return "Female only";
  return "Mixed";
}

// Occupancy ramp for the read-only "Heat map" view — same
// green/amber/red "needs attention" vocabulary as AdminConsole.jsx's
// occupancyColor(), just expressed as tile tints instead of a bar fill.
function heatTile(pct) {
  if (pct >= 90) return "bg-red-100 border-red-300";
  if (pct >= 75) return "bg-amber-100 border-amber-300";
  if (pct > 0) return "bg-green-100 border-green-300";
  return "bg-slate-50 border-slate-200";
}
function heatText(pct) {
  if (pct >= 90) return "text-red-700";
  if (pct >= 75) return "text-amber-700";
  if (pct > 0) return "text-green-700";
  return "text-slate-400";
}

// Green = free, red = occupied — reuses AdminConsole.jsx occupancyColor's
// green/red vocabulary rather than introducing a new palette.
function BedBox({ bed, selected, onClick }) {
  const occupied = bed.occupied;
  return (
    <button
      type="button"
      onClick={onClick}
      title={occupied ? `Bed ${bed.bed_number} — ${bed.admission?.patient_name || "occupied"}` : `Bed ${bed.bed_number} — free`}
      className={`h-9 w-9 shrink-0 rounded text-xs font-semibold border flex items-center justify-center ${
        occupied
          ? "bg-red-100 border-red-300 text-red-700 hover:bg-red-200"
          : "bg-green-100 border-green-300 text-green-700 hover:bg-green-200"
      } ${selected ? "ring-2 ring-blue-500" : ""}`}
    >
      {bed.bed_number}
    </button>
  );
}

// Inline "admit to this free bed" mini-form.
function AdmitPanel({ wardName, bedNumber, onAdmit, onCancel, busy, error }) {
  const [ic, setIc] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (ic.trim()) onAdmit(ic.trim());
      }}
      className="mt-2 border border-slate-200 rounded-lg p-3 bg-slate-50 space-y-2"
    >
      <p className="text-xs font-medium text-slate-600">
        Admit to {wardName} · bed {bedNumber}
      </p>
      {error && <div className="bg-red-50 text-red-700 text-xs p-2 rounded">{error}</div>}
      <input
        type="text"
        value={ic}
        onChange={(e) => setIc(e.target.value)}
        placeholder="Patient IC number e.g. 520314-01-1234"
        className="field-input"
        autoFocus
      />
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy || !ic.trim()}
          className="btn-primary"
        >
          {busy ? "Admitting…" : "Admit"}
        </button>
        <button type="button" onClick={onCancel} className="btn-secondary">
          Cancel
        </button>
      </div>
    </form>
  );
}

// Occupied-bed detail + Discharge / Move.
function OccupiedPanel({ map, bed, wardName, onDischarge, onMove, onCancel, busy, error }) {
  const adm = bed.admission || {};
  const [moving, setMoving] = useState(false);
  const [wardId, setWardId] = useState("");
  const [moveBed, setMoveBed] = useState("");

  const allWards = map.floors.flatMap((f) =>
    f.wards.map((w) => ({ id: w.id, label: `${f.floor_label} · ${w.ward_name}`, beds: w.beds })),
  );
  const chosenWard = allWards.find((w) => w.id === wardId);
  const freeBeds = chosenWard ? chosenWard.beds.filter((b) => !b.occupied).map((b) => b.bed_number) : [];

  return (
    <div className="mt-2 border border-slate-200 rounded-lg p-3 bg-slate-50 space-y-2">
      <p className="text-sm font-medium text-slate-700">{adm.patient_name}</p>
      <p className="text-xs text-slate-500">
        IC {adm.national_id || "—"} · {wardName} bed {bed.bed_number}
      </p>
      <p className="text-xs text-slate-400">Admitted {formatDateTime(adm.admitted_at)}</p>
      {adm.notes && <p className="text-xs text-slate-600">Note: {adm.notes}</p>}
      {error && <div className="bg-red-50 text-red-700 text-xs p-2 rounded">{error}</div>}

      {moving ? (
        <div className="space-y-2 border-t border-slate-200 pt-2">
          <select
            value={wardId}
            onChange={(e) => { setWardId(e.target.value); setMoveBed(""); }}
            className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm bg-white"
          >
            <option value="">Choose a ward…</option>
            {allWards.map((w) => (
              <option key={w.id} value={w.id}>{w.label}</option>
            ))}
          </select>
          <select
            value={moveBed}
            onChange={(e) => setMoveBed(e.target.value)}
            disabled={!chosenWard}
            className="w-full border border-slate-300 rounded-lg px-2 py-1.5 text-sm bg-white disabled:opacity-50"
          >
            <option value="">{chosenWard ? "Choose a free bed…" : "Pick a ward first"}</option>
            {freeBeds.map((b) => (
              <option key={b} value={b}>Bed {b}</option>
            ))}
          </select>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={busy || !wardId || !moveBed}
              onClick={() => onMove(adm.id, wardId, Number(moveBed))}
              className="btn-primary"
            >
              {busy ? "Moving…" : "Confirm move"}
            </button>
            <button type="button" onClick={() => setMoving(false)} className="btn-secondary">
              Back
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2 pt-1">
          <button
            type="button"
            disabled={busy}
            onClick={() => onDischarge(adm.id)}
            className="text-sm bg-red-600 hover:bg-red-500 text-white px-3 py-1.5 rounded-lg disabled:opacity-50"
          >
            {busy ? "Working…" : "Discharge"}
          </button>
          <button type="button" onClick={() => setMoving(true)} className="btn-secondary">
            Move
          </button>
          <button type="button" onClick={onCancel} className="text-sm text-slate-500 px-2 py-1.5">
            Close
          </button>
        </div>
      )}
    </div>
  );
}

// Shared by the AdminConsole "Wards" tab (both its "Heat map" and "Full
// details" sub-views) and the Reception "Ward Map" tab.
//   mode="interactive" (default) — bed-level admit / discharge / move board.
//   mode="heatmap"                — read-only, wards tinted by occupancy.
export default function WardMap({ mode = "interactive" }) {
  const heatmap = mode === "heatmap";
  const [map, setMap] = useState(null);
  const [loading, setLoading] = useState(true);
  // { floorId, wardId, wardName, bedNumber } — the live bed object is
  // re-derived from `map` on every render so a poll refresh keeps it current.
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const timerRef = useRef(null);

  const refresh = useCallback(
    () => getWardMap().then(setMap).catch(() => {}).finally(() => setLoading(false)),
    [],
  );

  useEffect(() => {
    refresh();
    timerRef.current = setInterval(refresh, WARD_MAP_POLL_MS);
    return () => clearInterval(timerRef.current);
  }, [refresh]);

  let selectedBed = null;
  if (selected && map) {
    const f = map.floors.find((x) => x.id === selected.floorId);
    const w = f?.wards.find((x) => x.id === selected.wardId);
    selectedBed = w?.beds.find((x) => x.bed_number === selected.bedNumber) || null;
  }

  function pick(floor, ward, bed) {
    setActionError("");
    if (selected && selected.wardId === ward.id && selected.bedNumber === bed.bed_number) {
      setSelected(null);
      return;
    }
    setSelected({ floorId: floor.id, wardId: ward.id, wardName: ward.ward_name, bedNumber: bed.bed_number });
  }

  async function run(fn) {
    setBusy(true);
    setActionError("");
    try {
      await fn();
      setSelected(null);
      await refresh();
    } catch (err) {
      setActionError(err?.response?.data?.detail || "Action failed — try again.");
    } finally {
      setBusy(false);
    }
  }

  const handleAdmit = (nationalId) =>
    run(() => admitPatient({ national_id: nationalId, ward_id: selected.wardId, bed_number: selected.bedNumber }));
  const handleDischarge = (admissionId) => run(() => dischargeAdmission(admissionId));
  const handleMove = (admissionId, wardId, bedNumber) =>
    run(() => updateAdmission(admissionId, { ward_id: wardId, bed_number: bedNumber }));

  if (loading) return <p className="text-sm text-slate-400">Loading ward map…</p>;
  if (!map || map.floors.length === 0) {
    return (
      <p className="text-sm text-slate-400">
        No floors configured for this facility yet — an admin can add them from the “Floors” view above.
      </p>
    );
  }

  if (heatmap) {
    return (
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500">
          <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded border bg-slate-50 border-slate-200" /> Empty</span>
          <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded border bg-green-100 border-green-300" /> &lt; 75%</span>
          <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded border bg-amber-100 border-amber-300" /> 75–90%</span>
          <span className="flex items-center gap-1.5"><span className="h-3 w-3 rounded border bg-red-100 border-red-300" /> ≥ 90%</span>
        </div>
        {map.floors.map((floor) => {
          const totalBeds = floor.wards.reduce((n, w) => n + w.beds.length, 0);
          const occupied = floor.wards.reduce((n, w) => n + w.beds.filter((b) => b.occupied).length, 0);
          return (
            <div key={floor.id} className="bg-white border border-slate-200 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <div>
                  <h3 className="font-semibold text-slate-800">{floor.floor_label}</h3>
                  <p className="text-xs text-slate-400">{genderRuleLabel(floor.gender_restriction)}</p>
                </div>
                <span className="text-xs font-semibold text-slate-500">{occupied} / {totalBeds} beds</span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {floor.wards.map((ward) => {
                  const wTotal = ward.beds.length;
                  const wOcc = ward.beds.filter((b) => b.occupied).length;
                  const pct = wTotal ? Math.round((wOcc / wTotal) * 100) : 0;
                  return (
                    <div key={ward.id} className={`rounded-lg border p-2.5 ${heatTile(pct)}`}>
                      <div className="flex items-center justify-between gap-2">
                        <p className="text-xs font-medium text-slate-700 truncate">{ward.ward_name}</p>
                        <span className={`text-xs font-semibold ${heatText(pct)}`}>{pct}%</span>
                      </div>
                      <p className="text-[11px] text-slate-500 mb-1.5">{wOcc} / {wTotal} beds</p>
                      <div className="flex flex-wrap gap-1">
                        {ward.beds.map((bed) => (
                          <span
                            key={bed.bed_number}
                            title={bed.occupied ? `Bed ${bed.bed_number} — ${bed.admission?.patient_name || "occupied"}` : `Bed ${bed.bed_number} — free`}
                            className={`h-3.5 w-3.5 rounded-sm border ${
                              bed.occupied ? "bg-red-400 border-red-500" : "bg-white border-slate-300"
                            }`}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {map.floors.map((floor) => {
        const totalBeds = floor.wards.reduce((n, w) => n + w.beds.length, 0);
        const occupied = floor.wards.reduce((n, w) => n + w.beds.filter((b) => b.occupied).length, 0);
        return (
          <div key={floor.id} className="bg-white border border-slate-200 rounded-xl p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="font-semibold text-slate-800">{floor.floor_label}</h3>
                <p className="text-xs text-slate-400">{genderRuleLabel(floor.gender_restriction)}</p>
              </div>
              <span className="text-xs font-semibold text-slate-500">
                {occupied} / {totalBeds} beds
              </span>
            </div>

            <div className="space-y-3">
              {floor.wards.map((ward) => (
                <div key={ward.id} className="border border-slate-200 rounded-lg p-3">
                  <p className="text-xs font-medium text-slate-600 mb-2">{ward.ward_name}</p>
                  <div className="flex gap-2 overflow-x-auto pb-1">
                    {ward.beds.map((bed) => (
                      <BedBox
                        key={bed.bed_number}
                        bed={bed}
                        selected={selected?.wardId === ward.id && selected?.bedNumber === bed.bed_number}
                        onClick={() => pick(floor, ward, bed)}
                      />
                    ))}
                  </div>

                  {selected?.wardId === ward.id && selectedBed && !selectedBed.occupied && (
                    <AdmitPanel
                      wardName={ward.ward_name}
                      bedNumber={selected.bedNumber}
                      onAdmit={handleAdmit}
                      onCancel={() => setSelected(null)}
                      busy={busy}
                      error={actionError}
                    />
                  )}
                  {selected?.wardId === ward.id && selectedBed && selectedBed.occupied && (
                    <OccupiedPanel
                      map={map}
                      bed={selectedBed}
                      wardName={ward.ward_name}
                      onDischarge={handleDischarge}
                      onMove={handleMove}
                      onCancel={() => setSelected(null)}
                      busy={busy}
                      error={actionError}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
