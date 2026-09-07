import { useEffect, useState } from "react";
import {
  getRooms, createRoom, updateRoom, deleteRoom,
  getSections,
} from "../../api/client";
import { Section } from "./_shared";

// ---------- Consultation rooms ("Bilik") ----------
// Physical consult rooms reception round-robins walk-in check-ins across
// (routers/reception.py::_assign_room) and clinicians claim from the
// Reception "My Room" tab. `department` is an optional tag — leaving it
// blank means the room takes any department's overflow. The options are the
// facility's active section names (passed down from RoomsTab).
function RoomModal({ mode, initial, onClose, onSaved, sectionNames = [] }) {
  const [roomName, setRoomName] = useState(initial?.room_name ?? "");
  const [department, setDepartment] = useState(initial?.department ?? "");
  const [active, setActive] = useState(initial?.active ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e) {
    e.preventDefault();
    if (!roomName.trim()) {
      setError("Room name is required.");
      return;
    }
    setSaving(true);
    setError("");
    const payload = {
      room_name: roomName.trim(),
      department: department || null,
      active,
    };
    try {
      if (mode === "add") await createRoom(payload);
      else await updateRoom(initial.id, payload);
      onSaved();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save. Check the fields and try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl p-6 max-w-md w-full max-h-[90vh] overflow-y-auto">
        <h3 className="font-semibold text-slate-800 mb-4">{mode === "add" ? "Add Consultation Room" : "Edit Consultation Room"}</h3>
        <form onSubmit={handleSubmit} className="space-y-3">
          {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error}</div>}

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Room name<span className="text-red-600"> *</span></label>
            <input
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              type="text"
              placeholder="e.g. Bilik A"
              value={roomName}
              onChange={(e) => setRoomName(e.target.value)}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">Department tag (optional)</label>
            <select
              className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
            >
              <option value="">— any department —</option>
              {/* Keep an existing out-of-list value selectable so a PATCH
                  doesn't silently wipe a room tagged before sections changed. */}
              {department && !sectionNames.includes(department) && (
                <option value={department}>{department} (not a current section)</option>
              )}
              {sectionNames.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>

          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            Active (available for round-robin and claiming)
          </label>

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

export default function RoomsTab() {
  const [rooms, setRooms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  // Active section names — the option set for a room's department tag.
  const [sectionNames, setSectionNames] = useState([]);

  function refresh() {
    setLoading(true);
    getRooms().then(setRooms).finally(() => setLoading(false));
  }

  useEffect(() => {
    refresh();
    getSections()
      .then((list) => setSectionNames(list.filter((s) => s.active).map((s) => s.name)))
      .catch(() => setSectionNames([]));
  }, []);

  async function handleDelete(room) {
    if (!confirm(`Remove "${room.room_name}"? Any clinician currently in it is released. This can't be undone.`)) return;
    await deleteRoom(room.id);
    refresh();
  }

  return (
    <Section
      title="Consultation Rooms"
      action={<button onClick={() => setModal({ mode: "add", initial: null })} className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg">+ Add Room</button>}
    >
      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : rooms.length === 0 ? (
        <p className="text-sm text-slate-400">No consultation rooms yet — add one above (e.g. Bilik A–E).</p>
      ) : (
        <div className="space-y-2">
          {rooms.map((room) => (
            <div
              key={room.id}
              className={`flex items-center justify-between gap-3 rounded-lg px-3 py-2 border ${
                room.active ? "bg-slate-50 border-slate-200" : "bg-white border-slate-200 opacity-60"
              }`}
            >
              <div className="text-sm text-slate-700 min-w-0">
                <p className="font-medium">
                  {room.room_name}
                  {!room.active && <span className="ml-2 text-xs font-semibold text-slate-500 uppercase">Inactive</span>}
                </p>
                <p className="text-xs text-slate-400">
                  {room.department || "Any department"} · {room.waiting_today} in queue today
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <button onClick={() => setModal({ mode: "edit", initial: room })} className="text-xs text-blue-700">Edit</button>
                <button onClick={() => handleDelete(room)} className="text-xs text-red-700">Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {modal && (
        <RoomModal
          mode={modal.mode}
          initial={modal.initial}
          sectionNames={sectionNames}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); refresh(); }}
        />
      )}
    </Section>
  );
}
