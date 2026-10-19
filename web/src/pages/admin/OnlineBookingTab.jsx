import { useEffect, useState } from "react";
import { getBookingAdminSettings, saveBookingAdminSettings } from "../../api/client";
import { Section } from "./_shared";
import { tr } from "../../lib/i18n";

// ---------- Online booking ----------
// Hospital-level switch + coordinates + one timetable card per booking
// category. The working copy `form` is what gets PUT whole; validation
// mirrors the server rules (end > start, no overlap per weekday, at least one
// slot fits a range) so the admin sees the problem before saving.
// ponytail: <input type="time"> can't express 24:00, so a range cannot end at
// midnight here; use 23:59 or add a text input if that is ever needed.
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const INPUT = "border border-slate-300 rounded-lg px-2 py-1 text-sm";

const toMin = (hhmm) => {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm || "");
  return m ? Number(m[1]) * 60 + Number(m[2]) : null;
};

function formFrom(s) {
  return {
    online_booking_enabled: !!s.online_booking_enabled,
    latitude: s.latitude == null ? "" : String(s.latitude),
    longitude: s.longitude == null ? "" : String(s.longitude),
    services: (s.services || []).map((v) => ({
      ...v,
      hours: (v.hours || []).map((h) => ({ weekday: h.weekday, start: h.start, end: h.end })),
    })),
  };
}

function coordError(value, lo, hi, name) {
  if (value.trim() === "") return "";
  const n = Number(value);
  if (!Number.isFinite(n)) return `${name} must be a number.`;
  if (n < lo || n > hi) return `${name} must be between ${lo} and ${hi}.`;
  return "";
}

// Returns { slotsByDay: number[7], errors: string[] } for one service.
function checkService(svc) {
  const errors = [];
  const slotsByDay = [0, 0, 0, 0, 0, 0, 0];
  const slot = Number(svc.slot_minutes);
  const num = (v, lo, hi, label) => {
    const n = Number(v);
    if (!Number.isInteger(n) || n < lo || n > hi) errors.push(`${label} must be a whole number from ${lo} to ${hi}.`);
  };
  num(svc.slot_minutes, 5, 240, "Slot length");
  num(svc.capacity, 1, 50, "People per slot");
  num(svc.advance_days, 1, 90, "Days ahead");
  num(svc.min_notice_minutes, 0, 10080, "Minimum notice");
  for (let d = 0; d < 7; d++) {
    const ranges = svc.hours.filter((h) => h.weekday === d).map((h) => ({ s: toMin(h.start), e: toMin(h.end) }));
    let ok = true;
    for (const r of ranges) {
      if (r.s == null || r.e == null) { errors.push(`${WEEKDAYS[d]}: enter both start and end times.`); ok = false; }
      else if (r.e <= r.s) { errors.push(`${WEEKDAYS[d]}: end time must be after start time.`); ok = false; }
      else if (slot >= 5 && Math.floor((r.e - r.s) / slot) < 1) {
        errors.push(`${WEEKDAYS[d]}: a ${slot} minute slot does not fit in a range this short.`); ok = false;
      }
    }
    if (!ok) continue;
    const sorted = [...ranges].sort((a, b) => a.s - b.s);
    for (let i = 1; i < sorted.length; i++) {
      if (sorted[i].s < sorted[i - 1].e) { errors.push(`${WEEKDAYS[d]}: time ranges overlap.`); ok = false; break; }
    }
    if (ok && slot >= 5) slotsByDay[d] = ranges.reduce((n, r) => n + Math.floor((r.e - r.s) / slot), 0);
  }
  return { slotsByDay, errors };
}

function serverMessage(e) {
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || String(x)).join("; ");
  return "Failed to save online booking settings.";
}

export default function OnlineBookingTab() {
  const [saved, setSaved] = useState(null); // server copy as a form shape
  const [meta, setMeta] = useState(null);
  const [form, setForm] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [justSaved, setJustSaved] = useState(false);
  const [geoNote, setGeoNote] = useState("");

  function load() {
    setLoading(true);
    setLoadError("");
    getBookingAdminSettings()
      .then((s) => {
        setMeta(s);
        setSaved(formFrom(s));
        setForm(formFrom(s));
      })
      .catch((e) => setLoadError(e?.response?.data?.detail || "Failed to load online booking settings."))
      .finally(() => setLoading(false));
  }
  useEffect(load, []);

  if (loading) return <Section title={tr("Online booking")}><p className="text-sm text-slate-400">{tr("Loading...")}</p></Section>;
  if (!form) {
    return (
      <Section title={tr("Online booking")}>
        <div className="alert-error mb-3">{loadError || "Failed to load online booking settings."}</div>
        <button type="button" className="btn-primary" onClick={load}>{tr("Try again")}</button>
      </Section>
    );
  }

  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  const latErr = coordError(form.latitude, -90, 90, "Latitude");
  const lngErr = coordError(form.longitude, -180, 180, "Longitude");
  const pairErr =
    !latErr && !lngErr && (form.latitude.trim() === "") !== (form.longitude.trim() === "")
      ? "Enter both latitude and longitude, or leave both empty." : "";
  const checks = form.services.map(checkService);
  const hasErrors = !!(latErr || lngErr || pairErr) || checks.some((c) => c.errors.length);

  const patch = (patchObj) => { setJustSaved(false); setForm((f) => ({ ...f, ...patchObj })); };
  const patchService = (i, fn) =>
    patch({ services: form.services.map((s, j) => (j === i ? fn(s) : s)) });

  function useDeviceLocation() {
    setGeoNote("");
    if (!navigator.geolocation) { setGeoNote("This browser cannot share its location. Type the coordinates instead."); return; }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        patch({ latitude: pos.coords.latitude.toFixed(6), longitude: pos.coords.longitude.toFixed(6) });
        setGeoNote("Location filled in from this device. Check it is the hospital, then save.");
      },
      () => setGeoNote("Location was not shared. Type the coordinates instead."),
    );
  }

  async function handleSave(e) {
    e.preventDefault();
    if (!dirty || hasErrors) return;
    setSaving(true);
    setError("");
    setJustSaved(false);
    try {
      const lat = form.latitude.trim();
      const lng = form.longitude.trim();
      const updated = await saveBookingAdminSettings({
        facility_name: meta.facility_name,
        display_name: meta.display_name,
        address: meta.address,
        online_booking_enabled: form.online_booking_enabled,
        latitude: lat === "" ? null : Number(lat),
        longitude: lng === "" ? null : Number(lng),
        services: form.services.map((s) => ({
          category: s.category,
          label: s.label,
          active: s.active,
          slot_minutes: Number(s.slot_minutes),
          capacity: Number(s.capacity),
          advance_days: Number(s.advance_days),
          min_notice_minutes: Number(s.min_notice_minutes),
          hours: s.hours.map((h) => ({ weekday: h.weekday, start: h.start, end: h.end })),
        })),
      });
      setMeta(updated);
      setSaved(formFrom(updated));
      setForm(formFrom(updated));
      setJustSaved(true);
    } catch (err) {
      setError(serverMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSave}>
      <Section
        title={tr("Online booking")}
        action={dirty && <span className="text-xs font-medium text-amber-600">{tr("Unsaved changes")}</span>}
      >
        {error && <div className="alert-error mb-3" role="alert">{error}</div>}
        {justSaved && !dirty && (
          <div className="bg-green-50 text-green-700 text-sm p-2 rounded mb-3" role="status">{tr("Online booking settings saved.")}</div>
        )}

        <label className="flex items-start gap-3 text-sm text-slate-700 border border-slate-200 rounded-lg p-3 bg-slate-50">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={form.online_booking_enabled}
            onChange={(e) => patch({ online_booking_enabled: e.target.checked })}
          />
          <span>
            <span className="font-medium">{tr("Allow patients to book online at this hospital")}</span>
            <span className="block text-xs text-slate-500 mt-0.5">
              When off, patients using the app are offered MySejahtera for booking instead and cannot book
              here. Turn it on only after at least one category below is active and has opening hours.
            </span>
          </span>
        </label>

        <fieldset className="mt-4 max-w-lg">
          <legend className="text-sm font-medium text-slate-700 mb-1">{tr("Hospital location")}</legend>
          <p className="text-xs text-slate-500 mb-2">
            Coordinates let patients find the nearest hospital. Without them this hospital is listed after the
            ones that have them.
          </p>
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label htmlFor="ob-lat" className="field-label">{tr("Latitude")}</label>
              <input id="ob-lat" className={INPUT} inputMode="decimal" value={form.latitude}
                aria-invalid={!!latErr} onChange={(e) => patch({ latitude: e.target.value })} />
            </div>
            <div>
              <label htmlFor="ob-lng" className="field-label">{tr("Longitude")}</label>
              <input id="ob-lng" className={INPUT} inputMode="decimal" value={form.longitude}
                aria-invalid={!!lngErr} onChange={(e) => patch({ longitude: e.target.value })} />
            </div>
            <button type="button" className="text-sm text-blue-800 underline hover:no-underline pb-1" onClick={useDeviceLocation}>
              Use this device's location
            </button>
          </div>
          {(latErr || lngErr || pairErr) && (
            <p className="text-xs text-red-600 mt-1">{latErr || lngErr || pairErr}</p>
          )}
          {geoNote && <p className="text-xs text-slate-500 mt-1" role="status">{geoNote}</p>}
        </fieldset>
      </Section>

      {form.services.length === 0 && (
        <Section title={tr("Categories")}><p className="text-sm text-slate-400">{tr("The server returned no booking categories.")}</p></Section>
      )}

      {form.services.map((svc, i) => (
        <ServiceCard
          key={svc.category}
          svc={svc}
          check={checks[i]}
          onChange={(fn) => patchService(i, fn)}
        />
      ))}

      <div className="flex items-center gap-3 mb-4">
        <button className="btn-primary" disabled={saving || !dirty || hasErrors}>
          {saving ? "Saving..." : "Save online booking settings"}
        </button>
        {hasErrors && <span className="text-xs text-red-600">{tr("Fix the highlighted problems to save.")}</span>}
      </div>
    </form>
  );
}

function ServiceCard({ svc, check, onChange }) {
  const id = `ob-${svc.category}`;
  const total = check.slotsByDay.reduce((a, b) => a + b, 0);
  const setField = (k) => (e) => onChange((s) => ({ ...s, [k]: e.target.value }));
  const setRange = (idx, k, v) =>
    onChange((s) => ({ ...s, hours: s.hours.map((h, j) => (j === idx ? { ...h, [k]: v } : h)) }));

  function copyMonday() {
    onChange((s) => {
      const monday = s.hours.filter((h) => h.weekday === 0);
      const rest = s.hours.filter((h) => h.weekday > 4);
      const copies = [1, 2, 3, 4].flatMap((d) => monday.map((h) => ({ ...h, weekday: d })));
      return { ...s, hours: [...s.hours.filter((h) => h.weekday === 0), ...copies, ...rest] };
    });
  }

  const numField = (k, label, suffix) => (
    <div>
      <label htmlFor={`${id}-${k}`} className="field-label">{label}</label>
      <div className="flex items-center gap-1">
        <input id={`${id}-${k}`} type="number" className={`${INPUT} w-24`} value={svc[k]} onChange={setField(k)} />
        <span className="text-xs text-slate-500">{suffix}</span>
      </div>
    </div>
  );

  return (
    <Section
      title={svc.label}
      action={
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={svc.active}
            onChange={(e) => onChange((s) => ({ ...s, active: e.target.checked }))} />
          Active
          <span className="sr-only"> for {svc.label}</span>
        </label>
      }
    >
      <div className={svc.active ? "" : "opacity-60"}>
        <div className="flex flex-wrap gap-4 mb-4">
          {numField("slot_minutes", "Slot length", "minutes")}
          {numField("capacity", "People per slot", "people")}
          {numField("advance_days", "Book up to", "days ahead")}
          {numField("min_notice_minutes", "Minimum notice", "minutes")}
        </div>

        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-slate-700">{tr("Weekly timetable")}</h3>
          <button type="button" className="text-xs text-blue-800 underline hover:no-underline" onClick={copyMonday}>
            Copy Monday to weekdays
          </button>
        </div>

        <div className="space-y-2">
          {WEEKDAYS.map((name, d) => {
            const rows = svc.hours.map((h, idx) => ({ h, idx })).filter((r) => r.h.weekday === d);
            return (
              <div key={d} className="flex flex-wrap items-start gap-3 border-t border-slate-100 pt-2">
                <span className="w-24 text-sm text-slate-600 pt-1">{name}</span>
                <div className="flex-1 space-y-1">
                  {rows.length === 0 && <span className="text-xs text-slate-400">{tr("Closed")}</span>}
                  {rows.map(({ h, idx }) => (
                    <div key={idx} className="flex items-center gap-2">
                      <input type="time" className={INPUT} value={h.start}
                        aria-label={`${svc.label} ${name} start time`}
                        onChange={(e) => setRange(idx, "start", e.target.value)} />
                      <span className="text-xs text-slate-400">{tr("to")}</span>
                      <input type="time" className={INPUT} value={h.end}
                        aria-label={`${svc.label} ${name} end time`}
                        onChange={(e) => setRange(idx, "end", e.target.value)} />
                      <button type="button" className="text-xs text-red-600 underline hover:no-underline"
                        aria-label={`Remove ${name} range for ${svc.label}`}
                        onClick={() => onChange((s) => ({ ...s, hours: s.hours.filter((_, j) => j !== idx) }))}>
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
                <span className="text-xs text-slate-500 pt-1 w-24 text-right">
                  {check.slotsByDay[d]} slot{check.slotsByDay[d] === 1 ? "" : "s"}
                </span>
                <button type="button" className="text-xs text-blue-800 underline hover:no-underline pt-1"
                  aria-label={`Add time range on ${name} for ${svc.label}`}
                  onClick={() => onChange((s) => ({ ...s, hours: [...s.hours, { weekday: d, start: "09:00", end: "17:00" }] }))}>
                  Add range
                </button>
              </div>
            );
          })}
        </div>

        <p className="text-xs text-slate-500 mt-3" data-testid={`${id}-preview`}>
          This creates {total} slot{total === 1 ? "" : "s"} per week
          {total > 0 ? ` (${check.slotsByDay.filter(Boolean).map((n) => n).join(", ")} per open day)` : ""}.
        </p>
        {check.errors.length > 0 && (
          <ul className="mt-2 text-xs text-red-600 list-disc pl-5" role="alert">
            {check.errors.map((m, k) => <li key={k}>{m}</li>)}
          </ul>
        )}
      </div>
    </Section>
  );
}
