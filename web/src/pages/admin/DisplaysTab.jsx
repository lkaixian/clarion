import { useEffect, useState } from "react";
import {
  getSections,
  getWaitingRoomDisplays, createWaitingRoomDisplay, revokeWaitingRoomDisplay,
} from "../../api/client";
import { formatDateTime } from "../../lib/format";
import { Section } from "./_shared";
import { tr } from "../../lib/i18n";

// ---------- Waiting Room Displays ----------
// Shareable, revocable tokens for a public lobby big-screen (/display/{token}
// — no auth). Each display is scoped to the whole facility or one section,
// and either masks patient names (recommended for a public screen) or shows
// them in full. The list includes revoked rows (greyed, no copy).
function DisplayRow({ display, onRevoke }) {
  const [copied, setCopied] = useState(false);
  const url = `${window.location.origin}/display/${display.token}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API blocked (e.g. non-HTTPS origin) — the URL is still
      // shown in full for a manual copy.
    }
  }

  return (
    <div
      className={`rounded-lg px-3 py-2 border ${
        display.revoked ? "bg-white border-slate-200 opacity-60" : "bg-slate-50 border-slate-200"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="text-sm text-slate-700 min-w-0">
          <p className="font-medium">
            {display.section || "Whole facility"}
            <span className="ml-2 text-xs font-semibold uppercase text-slate-500">
              {display.show_full_names ? "Full names" : "Masked names"}
            </span>
            {display.revoked && (
              <span className="ml-2 text-xs font-semibold uppercase text-red-700">{tr("Revoked")}</span>
            )}
          </p>
          <p className="text-xs text-slate-400">Created {formatDateTime(display.created_at)}</p>
          {!display.revoked && (
            <p className="text-xs text-slate-500 mt-1 font-mono break-all">{url}</p>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {!display.revoked && (
            <>
              <button onClick={copy} className="text-xs text-blue-700">
                {copied ? "Copied" : "Copy"}
              </button>
              <button onClick={() => onRevoke(display)} className="text-xs text-red-700">{tr("Revoke")}</button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function WaitingRoomDisplaysTab() {
  const [displays, setDisplays] = useState([]);
  const [sectionNames, setSectionNames] = useState([]);
  const [loading, setLoading] = useState(true);
  const [section, setSection] = useState("");
  const [showFullNames, setShowFullNames] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [newUrl, setNewUrl] = useState(""); // prominently surfaced right after a create

  function refresh() {
    setLoading(true);
    getWaitingRoomDisplays().then(setDisplays).finally(() => setLoading(false));
  }

  useEffect(() => {
    refresh();
    getSections()
      .then((list) => setSectionNames(list.filter((s) => s.active).map((s) => s.name)))
      .catch(() => setSectionNames([]));
  }, []);

  async function create(e) {
    e.preventDefault();
    setCreating(true);
    setError("");
    try {
      const row = await createWaitingRoomDisplay({ section: section || null, show_full_names: showFullNames });
      setNewUrl(`${window.location.origin}/display/${row.token}`);
      setSection("");
      setShowFullNames(false);
      refresh();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to create display.");
    } finally {
      setCreating(false);
    }
  }

  async function revoke(display) {
    if (!confirm(`Revoke this display link? Any screen using it goes dark immediately.`)) return;
    try {
      await revokeWaitingRoomDisplay(display.id);
      refresh();
    } catch (err) {
      alert(err?.response?.data?.detail || "Failed to revoke.");
    }
  }

  return (
    <Section title={tr("Waiting Room Displays")}>
      <p className="text-sm text-slate-500 mb-4 max-w-2xl">
        Generate a shareable link for a public lobby screen. It shows who's being called and who's
        waiting, refreshing on its own — no login needed. Revoke a link to kill it instantly.
      </p>

      <form onSubmit={create} className="flex flex-wrap items-end gap-3 mb-4">
        <div>
          <label className="field-label">{tr("Scope")}</label>
          <select
            className="border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={section}
            onChange={(e) => setSection(e.target.value)}
          >
            <option value="">{tr("Whole facility")}</option>
            {sectionNames.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <label className="flex items-start gap-2 text-sm text-slate-700 max-w-xs">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={showFullNames}
            onChange={(e) => setShowFullNames(e.target.checked)}
          />
          <span>
            Show full patient names
            <span className="block text-xs text-slate-400">
              Off = names are masked, e.g. "Ahmad I." — recommended for a public screen
            </span>
          </span>
        </label>
        <button disabled={creating} className="btn-primary">
          {creating ? "Creating..." : "Create"}
        </button>
      </form>

      {error && <div className="alert-error mb-3">{error}</div>}
      {newUrl && (
        <div className="bg-green-50 border border-green-200 text-green-800 text-sm p-3 rounded mb-3">
          <p className="font-medium mb-1">{tr("New display link created")}</p>
          <p className="font-mono break-all">{newUrl}</p>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-400">{tr("Loading...")}</p>
      ) : displays.length === 0 ? (
        <p className="text-sm text-slate-400">{tr("No displays yet — create one above.")}</p>
      ) : (
        <div className="space-y-2">
          {displays.map((d) => <DisplayRow key={d.id} display={d} onRevoke={revoke} />)}
        </div>
      )}
    </Section>
  );
}
