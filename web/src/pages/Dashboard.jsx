// P3.8 Management Dashboard -- KPI summary, operational health
// score, and patient-flow forecast. Reachable by
// admin/records_officer/clinician only (require_page_access("dashboard") +
// DASHBOARD_ROLES in routers/dashboard.py). Everything here is a plain stat
// tile or a thin proportion bar -- no chart library -- reusing the app's
// existing status-color convention (green/amber/red) rather than
// introducing a new palette.
import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import { getDashboardSummary, getDashboardFlowForecast } from "../api/client";
import { tr } from "../lib/i18n";

const REFRESH_MS = 60_000;

function scoreColor(score) {
  if (score >= 70) return "text-green-600";
  if (score >= 40) return "text-amber-600";
  return "text-red-600";
}
function barColor(score) {
  if (score >= 70) return "bg-green-500";
  if (score >= 40) return "bg-amber-500";
  return "bg-red-500";
}

function StatTile({ label, value, sub }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      <div className="text-2xl font-bold text-slate-800 mt-1">{value}</div>
      {sub && <div className="text-xs text-slate-400 mt-1">{sub}</div>}
    </div>
  );
}

function BreakdownBar({ label, score }) {
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-500 mb-0.5">
        <span>{label}</span>
        <span>{Math.round(score)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full rounded-full ${barColor(score)}`} style={{ width: `${Math.round(score)}%` }} />
      </div>
    </div>
  );
}

const BREAKDOWN_LABELS = {
  wait_score: "Wait time", availability_score: "Physician availability",
  queue_score: "Queue length", referral_score: "Unresolved referrals",
};

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [forecast, setForecast] = useState(null);
  const [error, setError] = useState("");

  function refresh() {
    Promise.all([getDashboardSummary(), getDashboardFlowForecast()])
      .then(([s, f]) => { setSummary(s); setForecast(f); setError(""); })
      .catch((e) => setError(e?.response?.data?.detail || "Failed to load dashboard data."));
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  return (
    <Layout>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="page-title">{tr("Dashboard")}</h1>
          <p className="text-sm text-slate-500">Live operational snapshot for your facility{summary ? ` -- ${summary.date}` : ""}.</p>
        </div>
        <button onClick={refresh} className="text-xs bg-slate-100 hover:bg-slate-200 px-3 py-1.5 rounded">{tr("Refresh")}</button>
      </div>

      {error && (
        <div className="mb-4 text-sm rounded-lg px-3 py-2 bg-red-50 border border-red-200 text-red-700 flex items-start justify-between gap-3">
          <span>{error}</span>
          <button onClick={() => setError("")} className="shrink-0 font-medium">✕</button>
        </div>
      )}

      {summary && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <StatTile label={tr("Patients in queue")} value={summary.patients_in_queue} />
            <StatTile label={tr("Attended today")} value={summary.patients_attended_today} />
            <StatTile label={tr("Physicians on duty")} value={`${summary.physicians_on_duty} / ${summary.physicians_total}`} />
            <StatTile label={tr("Avg wait (min)")} value={summary.avg_wait_minutes ?? "-"} sub={summary.avg_wait_minutes === null ? "No one called yet today" : undefined} />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
            <div className="lg:col-span-1 bg-white rounded-xl border border-slate-200 p-4 flex flex-col items-center justify-center text-center">
              <div className="text-xs font-semibold text-slate-500 mb-1">{tr("Operational health score")}</div>
              <div className={`text-5xl font-bold ${scoreColor(summary.health_score)}`}>{summary.health_score}</div>
              <div className="text-xs text-slate-400 mt-1">{tr("out of 100")}</div>
            </div>
            <div className="lg:col-span-2 bg-white rounded-xl border border-slate-200 p-4 space-y-3">
              <div className="text-xs font-semibold text-slate-500 mb-1">{tr("Breakdown")}</div>
              {Object.entries(summary.health_score_breakdown).map(([key, score]) => (
                <BreakdownBar key={key} label={BREAKDOWN_LABELS[key] || key} score={score} />
              ))}
            </div>
          </div>
        </>
      )}

      {forecast && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="text-xs font-semibold text-slate-500 mb-2">{tr("Today's clinic load")}</div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div><div className="text-slate-400 text-xs">{tr("Checked in so far")}</div><div className="font-semibold text-slate-800">{forecast.today_so_far}</div></div>
              <div><div className="text-slate-400 text-xs">{tr("Forecast total")}</div><div className="font-semibold text-slate-800">{forecast.today_forecast_total}</div></div>
              <div><div className="text-slate-400 text-xs">{tr("Forecast remaining")}</div><div className="font-semibold text-slate-800">{forecast.today_forecast_remaining}</div></div>
              <div><div className="text-slate-400 text-xs">{tr("Scheduled appointments")}</div><div className="font-semibold text-slate-800">{forecast.today_scheduled_appointments}</div></div>
            </div>
          </div>
          <div className="bg-white rounded-xl border border-slate-200 p-4">
            <div className="text-xs font-semibold text-slate-500 mb-2">{tr("Tomorrow's forecast")}</div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div><div className="text-slate-400 text-xs">{tr("Forecast total")}</div><div className="font-semibold text-slate-800">{forecast.tomorrow_forecast_total}</div></div>
              <div><div className="text-slate-400 text-xs">{tr("Scheduled appointments")}</div><div className="font-semibold text-slate-800">{forecast.tomorrow_scheduled_appointments}</div></div>
            </div>
            <p className="text-xs text-slate-400 mt-3">
              Forecast from the same weekday's last {forecast.weeks_of_history_used} weeks of visit history, plus already-booked appointments.
            </p>
          </div>
        </div>
      )}
    </Layout>
  );
}
