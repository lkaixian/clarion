import { useEffect, useState } from "react";
import { getHospitalSettings, updateHospitalSettings } from "../../api/client";
import { formatDateTime } from "../../lib/format";
import { Section } from "./_shared";

// ---------- Hospital Settings ----------
// Facility profile (display name / address / contact / timezone) plus the
// CLARION network records-sharing switch. The backend lazily creates the
// settings row with defaults on first GET, so there's always something to
// render; PUT takes only the changed subset and rejects unknown keys.
// facility_name is the immutable registered name — shown read-only for
// context, never sent. Visual weight mirrors BudgetPanel's simple settings
// form rather than the modal-driven CRUD tabs.
const COMMON_TIMEZONES = [
  "Asia/Kuala_Lumpur",
  "Asia/Kuching",
  "Asia/Singapore",
  "Asia/Jakarta",
  "Asia/Bangkok",
  "Asia/Manila",
  "Asia/Hong_Kong",
  "Asia/Kolkata",
  "UTC",
];

function hospitalFormFrom(s) {
  return {
    display_name: s.display_name ?? "",
    address: s.address ?? "",
    contact_phone: s.contact_phone ?? "",
    timezone: s.timezone ?? "Asia/Kuala_Lumpur",
    records_shared_publicly: !!s.records_shared_publicly,
    brand_primary_color: s.brand_primary_color ?? "",
    logo_data_url: s.logo_data_url ?? "",
  };
}

// P3.9: 200KB caps the base64 text server-side
// (schemas.MAX_LOGO_DATA_URL_LENGTH) -- a waiting-room-TV-sized wordmark,
// not a print-resolution asset, so reject an oversized file client-side
// with a clear message instead of a 422 after upload.
const MAX_LOGO_FILE_BYTES = 150_000; // base64 inflates ~33%, stays under the 200KB server cap

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export default function HospitalSettingsTab() {
  const [settings, setSettings] = useState(null);
  const [form, setForm] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [justSaved, setJustSaved] = useState(false);

  useEffect(() => {
    setLoading(true);
    getHospitalSettings()
      .then((s) => {
        setSettings(s);
        setForm(hospitalFormFrom(s));
      })
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load hospital settings."))
      .finally(() => setLoading(false));
  }, []);

  // Only send fields that actually changed (text fields compared trimmed) —
  // the backend rejects unknown keys and applies only what's present.
  function changedFields() {
    if (!settings || !form) return {};
    const diff = {};
    for (const k of ["display_name", "address", "contact_phone", "timezone", "brand_primary_color", "logo_data_url"]) {
      const next = form[k].trim();
      if (next !== (settings[k] ?? "")) diff[k] = next || null;
    }
    if (form.records_shared_publicly !== !!settings.records_shared_publicly) {
      diff.records_shared_publicly = form.records_shared_publicly;
    }
    return diff;
  }

  const diff = changedFields();
  const dirty = Object.keys(diff).length > 0;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!dirty) return;
    setSaving(true);
    setError("");
    setJustSaved(false);
    try {
      const updated = await updateHospitalSettings(diff);
      setSettings(updated);
      setForm(hospitalFormFrom(updated));
      setJustSaved(true);
    } catch (err) {
      setError(err?.response?.data?.detail || "Failed to save hospital settings.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <Section title="Hospital Settings"><p className="text-sm text-slate-400">Loading...</p></Section>;
  }
  if (!form) {
    return (
      <Section title="Hospital Settings">
        <div className="bg-red-50 text-red-700 text-sm p-2 rounded">{error || "Failed to load hospital settings."}</div>
      </Section>
    );
  }

  return (
    <Section title="Hospital Settings">
      {error && <div className="bg-red-50 text-red-700 text-sm p-2 rounded mb-3">{error}</div>}
      {justSaved && !dirty && (
        <div className="bg-green-50 text-green-700 text-sm p-2 rounded mb-3">Hospital settings saved.</div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4 max-w-lg">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Facility name</label>
          <input
            className="w-full border border-slate-200 bg-slate-50 text-slate-500 rounded-lg px-3 py-1.5 text-sm"
            type="text"
            value={settings.facility_name || ""}
            disabled
          />
          <p className="text-xs text-slate-400 mt-1">The registered facility name can't be changed here.</p>
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Display name</label>
          <input
            className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            type="text"
            value={form.display_name}
            onChange={(e) => setForm((f) => ({ ...f, display_name: e.target.value }))}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Address</label>
          <textarea
            className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={3}
            value={form.address}
            onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Contact phone</label>
          <input
            className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            type="tel"
            value={form.contact_phone}
            onChange={(e) => setForm((f) => ({ ...f, contact_phone: e.target.value }))}
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">Timezone</label>
          <select
            className="w-full border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={form.timezone}
            onChange={(e) => setForm((f) => ({ ...f, timezone: e.target.value }))}
          >
            {/* Keep whatever the backend already stores even if it's outside
                our shortlist, so opening the form never silently rewrites it. */}
            {form.timezone && !COMMON_TIMEZONES.includes(form.timezone) && (
              <option value={form.timezone}>{form.timezone}</option>
            )}
            {COMMON_TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
          </select>
        </div>

        <div className="border border-slate-200 rounded-lg p-3">
          <p className="text-xs font-medium text-slate-600 mb-2">Calling-system TV branding</p>
          <div className="flex items-center gap-4">
            <div>
              <label className="block text-xs text-slate-500 mb-1">Accent color</label>
              <input
                type="color"
                className="h-8 w-14 border border-slate-300 rounded cursor-pointer"
                value={form.brand_primary_color || "#10b981"}
                onChange={(e) => setForm((f) => ({ ...f, brand_primary_color: e.target.value }))}
              />
            </div>
            <div className="flex-1">
              <label className="block text-xs text-slate-500 mb-1">Logo</label>
              <div className="flex items-center gap-3">
                {form.logo_data_url && (
                  <img src={form.logo_data_url} alt="Logo preview" className="h-10 w-10 object-contain border border-slate-200 rounded" />
                )}
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="text-xs"
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    if (!file) return;
                    if (file.size > MAX_LOGO_FILE_BYTES) {
                      setError("Logo image is too large (150KB max) — pick a smaller file.");
                      return;
                    }
                    setError("");
                    setForm((f) => ({ ...f, logo_data_url: await readFileAsDataUrl(file) }));
                  }}
                />
                {form.logo_data_url && (
                  <button
                    type="button"
                    className="text-xs text-slate-500 underline hover:no-underline"
                    onClick={() => setForm((f) => ({ ...f, logo_data_url: "" }))}
                  >
                    Remove
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="border border-slate-200 rounded-lg p-3 bg-slate-50">
          <label className="flex items-start gap-3 text-sm text-slate-700">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={form.records_shared_publicly}
              onChange={(e) => setForm((f) => ({ ...f, records_shared_publicly: e.target.checked }))}
            />
            <span>
              <span className="font-medium">Share records with other hospitals in the network</span>
              <span className="block text-xs text-slate-500 mt-0.5">
                When on, hospitals across the CLARION network can view clinical records your facility
                authored (they still can't edit them). When off, only your facility — and emergency
                responders during an emergency scan — can see records you authored.
              </span>
            </span>
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            disabled={saving || !dirty}
            className="text-sm bg-blue-800 text-white px-3 py-1.5 rounded-lg disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
          {settings.updated_at && (
            <span className="text-xs text-slate-400">
              Last updated {formatDateTime(settings.updated_at)}
              {settings.updated_by ? ` by ${settings.updated_by}` : ""}
            </span>
          )}
        </div>
      </form>
    </Section>
  );
}
