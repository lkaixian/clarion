import { useEffect, useState } from "react";
import { listAnnouncements, createAnnouncement, deleteAnnouncement } from "../../api/client";
import { formatDateTime } from "../../lib/format";
import { Section } from "./_shared";

// ---------- Announcements (P3.10) ----------
// Health-campaign / clinic notices the mobile app polls for and shows
// alongside its local reminders. Simpler than SectionsTab's modal-driven
// CRUD — no update endpoint (an announcement is short-lived; publish a new
// one instead of editing an old one), so this is just a form + list.
const EMPTY_FORM = { title: "", body: "", expires_at: "" };

export default function AnnouncementsTab() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function refresh() {
    setLoading(true);
    listAnnouncements().then(setRows).finally(() => setLoading(false));
  }

  useEffect(refresh, []);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.title.trim() || !form.body.trim()) {
      setError("Title and body are required.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await createAnnouncement({
        title: form.title.trim(),
        body: form.body.trim(),
        // datetime-local has no timezone; the browser's local offset is what
        // the admin intends, same as every other datetime-local field in
        // this console (e.g. AppointmentsTab).
        expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : undefined,
      });
      setForm(EMPTY_FORM);
      refresh();
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to publish announcement.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(row) {
    if (!confirm(`Remove announcement "${row.title}"?`)) return;
    await deleteAnnouncement(row.id);
    refresh();
  }

  const now = new Date();

  return (
    <Section title="Announcements">
      <p className="text-sm text-slate-500 mb-4 max-w-2xl">
        Health-campaign / clinic notices shown in the patient mobile app (real-time alerts,
). Scoped to this facility's patients only.
      </p>

      <form onSubmit={handleSubmit} className="space-y-3 max-w-lg mb-6 border border-slate-200 rounded-lg p-3">
        {error && <div className="alert-error">{error}</div>}
        <div>
          <label className="field-label">Title<span className="text-red-600"> *</span></label>
          <input
            className="field-input"
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder="e.g. Flu vaccination drive"
          />
        </div>
        <div>
          <label className="field-label">Message<span className="text-red-600"> *</span></label>
          <textarea
            className="field-input"
            rows={3}
            value={form.body}
            onChange={(e) => setForm((f) => ({ ...f, body: e.target.value }))}
          />
        </div>
        <div>
          <label className="field-label">Expires (optional)</label>
          <input
            type="datetime-local"
            className="border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={form.expires_at}
            onChange={(e) => setForm((f) => ({ ...f, expires_at: e.target.value }))}
          />
          <p className="text-xs text-slate-400 mt-1">Left blank, the announcement never expires on its own — remove it manually.</p>
        </div>
        <button disabled={saving} className="btn-primary">
          {saving ? "Publishing..." : "Publish"}
        </button>
      </form>

      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : rows.length === 0 ? (
        <p className="text-sm text-slate-400">No announcements yet.</p>
      ) : (
        <div className="space-y-2">
          {rows.map((row) => {
            const expired = row.expires_at && new Date(row.expires_at) < now;
            return (
              <div key={row.id} className={`rounded-lg px-3 py-2 border border-slate-200 ${expired ? "opacity-50" : "bg-slate-50"}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium text-sm text-slate-800">
                      {row.title}
                      {expired && <span className="ml-2 text-xs uppercase text-slate-500">Expired</span>}
                    </p>
                    <p className="text-sm text-slate-600 mt-0.5">{row.body}</p>
                    <p className="text-xs text-slate-400 mt-1">
                      Published {formatDateTime(row.created_at)}
                      {row.expires_at ? ` · expires ${formatDateTime(row.expires_at)}` : ""}
                    </p>
                  </div>
                  <button onClick={() => handleDelete(row)} className="text-xs text-red-700 shrink-0">Delete</button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}
