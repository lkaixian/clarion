import { useEffect, useState } from "react";
import { getAdminAppointments } from "../../api/client";
import { formatDateTime } from "../../lib/format";
import { Section } from "./_shared";
import { tr } from "../../lib/i18n";

// ---------- Appointments (read-only monitoring) ----------
// Deliberately no create/edit/cancel here — appointments are still made
// from a specific patient's own record (PatientDetail.jsx's
// AppointmentsSection); this tab exists so an admin can see the whole
// facility's queue at a glance, not to duplicate that flow.
export default function AppointmentsTab() {
  const [appointments, setAppointments] = useState([]);
  const [includeAll, setIncludeAll] = useState(false);
  const [loading, setLoading] = useState(true);

  function refresh() {
    setLoading(true);
    getAdminAppointments(includeAll).then(setAppointments).finally(() => setLoading(false));
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(refresh, [includeAll]);

  return (
    <Section
      title={tr("Facility Appointments")}
      action={
        <label className="flex items-center gap-2 text-xs text-slate-600">
          <input type="checkbox" checked={includeAll} onChange={(e) => setIncludeAll(e.target.checked)} />
          Show cancelled &amp; completed too
        </label>
      }
    >
      {loading ? (
        <p className="text-sm text-slate-400">{tr("Loading...")}</p>
      ) : appointments.length === 0 ? (
        <p className="text-sm text-slate-400">
          {includeAll ? "No appointments on file for this facility." : "No upcoming appointments scheduled."}
        </p>
      ) : (
        <div className="space-y-2">
          {appointments.map((a) => {
            const cancelled = a.status === "cancelled";
            return (
              <div
                key={a.id}
                // Same "dim it but keep it visible, with an explicit label"
                // treatment PatientDetail.jsx's AppointmentsSection uses for
                // a cancelled row — reused here rather than inventing a
                // different cancelled-state convention.
                className={`bg-slate-50 border border-slate-200 rounded-lg px-3 py-2 ${cancelled ? "opacity-50" : ""}`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="text-sm text-slate-700">
                    {cancelled && <p className="text-xs font-semibold text-red-700 uppercase mb-0.5">{tr("Cancelled")}</p>}
                    {a.status === "completed" && (
                      <p className="text-xs font-semibold text-slate-500 uppercase mb-0.5">{tr("Completed")}</p>
                    )}
                    <p className={cancelled ? "line-through" : ""}>
                      {a.patient_name} — {a.venue || a.facility_name}
                    </p>
                    <p className="text-xs text-slate-400">
                      {formatDateTime(a.scheduled_at)} · Booked by {a.created_by_name || "—"}
                    </p>
                    {a.reason && <p className="text-xs text-slate-600 mt-0.5">Reason: {a.reason}</p>}
                    {/* Same fasting-precaution callout convention as
                        PatientDetail.jsx's AppointmentsSection. */}
                    {a.fasting_required && (
                      <p className="text-xs text-amber-700 font-medium mt-0.5">
                        ⚠ Fasting required{a.fasting_hours ? `: ${a.fasting_hours}h before` : ""}
                      </p>
                    )}
                    {a.precaution_notes && (
                      <p className="text-xs text-slate-500 mt-0.5">Note: {a.precaution_notes}</p>
                    )}
                  </div>
                  <span className="text-xs text-slate-400 whitespace-nowrap capitalize">{a.status}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Section>
  );
}
