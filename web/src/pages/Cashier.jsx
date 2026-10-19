import { useCallback, useEffect, useRef, useState } from "react";
import Layout from "../components/Layout";
import {
  getReconciliation, getReconciliationPdf, getOutstanding, listRefunds, approveRefund, rejectRefund,
  listDeposits, createDeposit, applyDeposit, refundDeposit, listPatients, listBills,
  getCurrentUser, errorMessage,
} from "../api/client";
import { formatDateTime } from "../lib/format";
import { rm, toCents } from "../lib/money";
import { tr } from "../lib/i18n";

const TABS = [["close", "Day close"], ["outstanding", "Outstanding"], ["refunds", "Refunds"], ["deposits", "Deposits"]];
const todayLocal = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
// Range presets for the close report. Months are calendar months, so "3 months" ending on
// 2026-10-13 starts 2026-07-14 and is 92 days, whatever the months' lengths.
const RANGES = [["1d", "1 day"], ["7d", "7 days"], ["14d", "14 days"], ["30d", "30 days"], ["3m", "3 months"], ["6m", "6 months"]];
function rangeDays(endDay, key) {
  if (key.endsWith("d")) return parseInt(key, 10);
  const [y, m, d] = endDay.split("-").map(Number);
  const end = Date.UTC(y, m - 1, d);
  const back = new Date(end);
  back.setUTCMonth(back.getUTCMonth() - parseInt(key, 10));
  return Math.round((end - back.getTime()) / 86400000);
}
// Minutes east of UTC for the browser's own zone, so "a day" means the cashier's day.
const tzMinutes = () => -new Date().getTimezoneOffset();

// Loads on mount and whenever `key` changes (a string naming the inputs, so the
// effect's dependency is explicit); the latest `fn` is always the one called.
function useLoad(fn, key) {
  const latest = useRef(fn);
  latest.current = fn;
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let off = false;
    setData(null);
    setError("");
    latest.current().then((d) => !off && setData(d)).catch((e) => !off && setError(errorMessage(e, "Could not load this view.")));
    return () => { off = true; };
  }, [key]);
  return [data, error];
}

function Tile({ label, value, tone }) {
  const tones = {
    green: "bg-green-50 border-green-200 text-green-800",
    amber: "bg-amber-50 border-amber-200 text-amber-800",
    slate: "bg-slate-50 border-slate-200 text-slate-800",
  };
  return (
    <div className={`rounded-lg border p-3 ${tones[tone || "slate"]}`}>
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-xs opacity-80">{label}</p>
    </div>
  );
}

function Status({ error, loading }) {
  if (error) return <p className="alert-error" role="alert">{error}</p>;
  if (loading) return <p className="empty-state">{tr("Loading...")}</p>;
  return null;
}

function DayClose() {
  const [day, setDay] = useState(todayLocal());
  const [range, setRange] = useState("1d");
  const days = rangeDays(day, range);
  const [rec, error] = useLoad(() => getReconciliation({ day, days, tzOffsetMinutes: tzMinutes() }), `${day}|${days}`);
  const methods = rec ? Object.entries(rec.by_method) : [];
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfError, setPdfError] = useState("");
  async function downloadPdf() {
    setPdfBusy(true);
    setPdfError("");
    try {
      const url = URL.createObjectURL(await getReconciliationPdf({ day, days, tzOffsetMinutes: tzMinutes() }));
      const a = document.createElement("a");
      a.href = url;
      a.download = days === 1 ? `day-close-${day}.pdf` : `day-close-${rec?.from_day || day}_to_${day}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setPdfError(errorMessage(e, "Could not create the PDF."));
    } finally {
      setPdfBusy(false);
    }
  }
  return (
    <div className="space-y-4">
      <h2 className="hidden print:block text-lg font-semibold text-slate-900">
        {rec && rec.days > 1 ? "Cashier close" : "Cashier day close"}
        {rec ? `: ${rec.facility_name}, ${rec.days > 1 ? `${rec.from_day} to ${rec.day}` : rec.day}` : ""}
      </h2>
      <div className="flex flex-wrap items-end gap-3 print:hidden">
        <div>
          <label htmlFor="rc-day" className="field-label">{days === 1 ? "Day" : "Last day"}</label>
          <input id="rc-day" type="date" className="field-input" value={day} max={todayLocal()}
                 onChange={(e) => e.target.value && setDay(e.target.value)} />
        </div>
        <div role="group" aria-label={tr("Period")} className="flex flex-wrap gap-1">
          {RANGES.map(([key, label]) => (
            <button
              key={key} type="button" aria-pressed={range === key} onClick={() => setRange(key)}
              className={`rounded-full border px-3 py-1.5 text-sm ${
                range === key ? "border-blue-800 bg-blue-800 text-white" : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <button type="button" className="btn-secondary" disabled={pdfBusy || !rec} onClick={downloadPdf}>
          {pdfBusy ? "Creating PDF..." : "Download PDF"}
        </button>
        <button type="button" className="btn-secondary" onClick={() => window.print()}>{tr("Print")}</button>
      </div>
      {pdfError && <p className="alert-error print:hidden" role="alert">{pdfError}</p>}
      <Status error={error} loading={!rec} />
      {rec && rec.days > 1 && (
        <p className="text-sm text-slate-600">Showing {rec.from_day} to {rec.day} ({rec.days} days).</p>
      )}
      {rec && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Tile label={tr("Collected")} value={rm(rec.collected_cents)} tone="green" />
            <Tile label={`Refunds (${rec.refunds.count})`} value={rm(rec.refunds.total_cents)} tone="amber" />
            <Tile label={tr("Net (collected + deposits - refunds)")} value={rm(rec.net_cents)} />
            <Tile label={tr("Deposits received")} value={rm(rec.deposits_received.total_cents)} />
          </div>
          {methods.length === 0 ? (
            <p className="empty-state">{tr("No payments were taken on this day.")}</p>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <section className="card p-0">
                <h2 className="px-4 pt-3 text-sm font-semibold text-slate-700">{tr("By method")}</h2>
                <table className="w-full text-sm">
                  <tbody>
                    {methods.map(([m, v]) => (
                      <tr key={m} className="border-t border-slate-100">
                        <td className="px-4 py-2 capitalize">{m}</td>
                        <td className="px-4 py-2 text-right text-slate-500">{v.count}</td>
                        <td className="px-4 py-2 text-right font-medium">{rm(v.total_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
              <section className="card p-0">
                <h2 className="px-4 pt-3 text-sm font-semibold text-slate-700">{tr("By cashier")}</h2>
                <table className="w-full text-sm">
                  <tbody>
                    {rec.by_cashier.map((c) => (
                      <tr key={c.name} className="border-t border-slate-100">
                        <td className="px-4 py-2">{c.name}</td>
                        <td className="px-4 py-2 text-right text-slate-500">{c.count}</td>
                        <td className="px-4 py-2 text-right font-medium">{rm(c.total_cents)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            </div>
          )}
          <p className="text-sm text-slate-600">
            Voided: {rec.voided.count} ({rm(rec.voided.total_cents)}), not counted above, review before closing.
            {rec.deposit_refunds.count > 0 && ` Deposit refunds: ${rec.deposit_refunds.count} (${rm(rec.deposit_refunds.total_cents)}), already netted.`}
            {rec.applied_from_deposits.count > 0 && ` Paid from deposits: ${rec.applied_from_deposits.count} (${rm(rec.applied_from_deposits.total_cents)}), not new cash.`}
            {rec.online_pending.count > 0 && ` Online payments still waiting for the gateway: ${rec.online_pending.count} (${rm(rec.online_pending.total_cents)}).`}
          </p>
        </>
      )}
    </div>
  );
}

function Outstanding() {
  const [data, error] = useLoad(() => getOutstanding(), "outstanding");
  return (
    <div className="space-y-4">
      <Status error={error} loading={!data} />
      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            <Tile label={tr("Total outstanding")} value={rm(data.total_cents)} tone="amber" />
            {data.buckets.map((b) => (
              <Tile key={b.label} label={`${b.label} days (${b.count})`} value={rm(b.total_cents)} />
            ))}
          </div>
          {data.bills.length === 0 ? (
            <p className="empty-state">{tr("No unpaid bills.")}</p>
          ) : (
            <div className="card overflow-x-auto p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-slate-500">
                    <th className="px-4 py-2 font-medium">{tr("Patient")}</th><th className="px-4 py-2 font-medium">{tr("Issued")}</th>
                    <th className="px-4 py-2 font-medium">{tr("Age")}</th><th className="px-4 py-2 text-right font-medium">{tr("Due")}</th>
                    <th className="px-4 py-2 text-right font-medium">{tr("Patient share")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.bills.map((b) => (
                    <tr key={b.bill_id} className="border-t border-slate-100">
                      <td className="px-4 py-2">{b.patient_full_name}</td>
                      <td className="px-4 py-2">{formatDateTime(b.finalized_at)}</td>
                      <td className="px-4 py-2">{b.age_days} days</td>
                      <td className="px-4 py-2 text-right">{rm(b.amount_due_cents)}</td>
                      <td className="px-4 py-2 text-right">{rm(b.patient_due_cents)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

const REFUND_TONE = {
  requested: "bg-amber-100 text-amber-800", approved: "bg-green-100 text-green-800", rejected: "bg-slate-200 text-slate-600",
};

function Refunds({ isAdmin }) {
  const [status, setStatus] = useState("requested");
  const [tick, setTick] = useState(0);
  const [notice, setNotice] = useState(null);
  const [rows, error] = useLoad(() => listRefunds(status), `${status}|${tick}`);

  async function decide(id, approve) {
    const note = window.prompt(approve ? "Note for the approval (optional):" : "Reason for rejecting:");
    if (note === null || (!approve && !note.trim())) return;
    try {
      await (approve ? approveRefund(id, note) : rejectRefund(id, note));
      setNotice({ ok: true, text: approve ? "Refund approved." : "Refund rejected." });
      setTick((t) => t + 1);
    } catch (e) {
      setNotice({ ok: false, text: errorMessage(e, "Could not record the decision.") });
    }
  }

  return (
    <div className="space-y-3">
      <div className="max-w-xs">
        <label htmlFor="rf-status" className="field-label">{tr("Show")}</label>
        <select id="rf-status" className="field-input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="requested">{tr("Waiting for approval")}</option>
          <option value="approved">{tr("Approved")}</option>
          <option value="rejected">{tr("Rejected")}</option>
          <option value="">{tr("All")}</option>
        </select>
      </div>
      {notice && <p className={notice.ok ? "rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800" : "alert-error"} role="status">{notice.text}</p>}
      <Status error={error} loading={!rows} />
      {rows && rows.length === 0 && <p className="empty-state">{tr("No refunds here.")}</p>}
      {rows && rows.length > 0 && (
        <ul className="card divide-y divide-slate-100 p-0">
          {rows.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
              <div className="min-w-0">
                <p className="font-medium text-slate-900">
                  {rm(r.amount_cents)}{" "}
                  <span className={`ml-1 rounded-full px-2 py-0.5 text-xs ${REFUND_TONE[r.status]}`}>{r.status}</span>
                </p>
                <p className="text-xs text-slate-500">
                  {r.reason} · requested by {r.requested_by_name} {formatDateTime(r.requested_at)}
                  {r.decided_by_name && ` · ${r.status} by ${r.decided_by_name}`}
                </p>
              </div>
              {isAdmin && r.status === "requested" && (
                <div className="flex gap-2">
                  <button type="button" className="btn-primary" onClick={() => decide(r.id, true)}>{tr("Approve")}</button>
                  <button type="button" className="btn-secondary" onClick={() => decide(r.id, false)}>{tr("Reject")}</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {!isAdmin && <p className="text-xs text-slate-500">{tr("Only an admin can approve or reject a refund. Request one from the payment on the bill.")}</p>}
    </div>
  );
}

function Deposits({ isAdmin }) {
  const [tick, setTick] = useState(0);
  // null = still loading, false = this role cannot browse patients (receptionists
  // cannot: GET /patients is 403 for them), so the cashier types a patient ID instead.
  const [patients, setPatients] = useState(null);
  const [pid, setPid] = useState("");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("cash");
  const [ref, setRef] = useState("");
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rows, error] = useLoad(() => listDeposits(), String(tick));

  useEffect(() => { listPatients({ limit: 200 }).then(setPatients).catch(() => setPatients(false)); }, []);
  const nameOf = (d) => d.patient_full_name || d.patient_id.slice(0, 8);

  async function add(e) {
    e.preventDefault();
    const cents = toCents(amount);
    if (!pid) return setNotice({ ok: false, text: patients === false ? "Enter the patient ID." : "Choose a patient." });
    if (cents === null) return setNotice({ ok: false, text: "Enter an amount in RM, for example 200.00." });
    setBusy(true);
    try {
      await createDeposit({ patient_id: pid, amount_cents: cents, method, reference_no: ref || undefined });
      setNotice({ ok: true, text: "Deposit recorded." });
      setAmount("");
      setRef("");
      setTick((t) => t + 1);
    } catch (err) {
      setNotice({ ok: false, text: errorMessage(err, "Could not record the deposit.") });
    } finally {
      setBusy(false);
    }
  }

  async function apply(d) {
    try {
      const bills = (await listBills({ patientId: d.patient_id })).filter((b) => b.status !== "voided" && b.amount_due_cents > 0);
      if (bills.length === 0) return setNotice({ ok: false, text: "This patient has no bill with a balance." });
      const pick = bills.length === 1 ? bills[0] : bills[Number(window.prompt(
        `Apply to which bill? Enter 1-${bills.length}:\n` + bills.map((b, i) => `${i + 1}. ${formatDateTime(b.created_at)} due ${rm(b.amount_due_cents)}`).join("\n")) || 0) - 1];
      if (!pick) return;
      const cents = Math.min(d.balance_cents, pick.amount_due_cents);
      await applyDeposit(d.id, { bill_id: pick.id, amount_cents: cents });
      setNotice({ ok: true, text: `${rm(cents)} applied to the bill.` });
      setTick((t) => t + 1);
    } catch (err) {
      setNotice({ ok: false, text: errorMessage(err, "Could not apply the deposit.") });
    }
  }

  async function refund(d) {
    if (!window.confirm(`Refund the remaining ${rm(d.balance_cents)} to ${nameOf(d)}?`)) return;
    try {
      await refundDeposit(d.id, {});
      setNotice({ ok: true, text: "Deposit refunded." });
      setTick((t) => t + 1);
    } catch (err) {
      setNotice({ ok: false, text: errorMessage(err, "Could not refund the deposit.") });
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={add} className="card grid gap-3 sm:grid-cols-5 sm:items-end">
        <div className="sm:col-span-2">
          <label htmlFor="dp-patient" className="field-label">
            {patients === false ? "Patient ID (from Reception check-in)" : "Patient"}
          </label>
          {patients === false ? (
            <input id="dp-patient" className="field-input" value={pid} autoComplete="off"
                   onChange={(e) => setPid(e.target.value.trim())} />
          ) : (
            <select id="dp-patient" className="field-input" value={pid} onChange={(e) => setPid(e.target.value)}>
              <option value="">{tr("Choose...")}</option>
              {(patients || []).map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
            </select>
          )}
        </div>
        <div>
          <label htmlFor="dp-amount" className="field-label">Amount (RM)</label>
          <input id="dp-amount" className="field-input" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </div>
        <div>
          <label htmlFor="dp-method" className="field-label">{tr("Method")}</label>
          <select id="dp-method" className="field-input" value={method} onChange={(e) => setMethod(e.target.value)}>
            <option value="cash">{tr("Cash")}</option><option value="card">{tr("Card")}</option><option value="other">{tr("Other")}</option>
          </select>
        </div>
        <div>
          <label htmlFor="dp-ref" className="field-label">{tr("Reference")}</label>
          <input id="dp-ref" className="field-input" value={ref} onChange={(e) => setRef(e.target.value)} />
        </div>
        <div className="sm:col-span-5">
          <button type="submit" className="btn-primary" disabled={busy}>{busy ? "Saving..." : "Record deposit"}</button>
        </div>
      </form>
      {notice && <p className={notice.ok ? "rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800" : "alert-error"} role="status">{notice.text}</p>}
      <Status error={error} loading={!rows} />
      {rows && rows.length === 0 && <p className="empty-state">{tr("No deposits held.")}</p>}
      {rows && rows.length > 0 && (
        <ul className="card divide-y divide-slate-100 p-0">
          {rows.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
              <div className="min-w-0">
                <p className="font-medium text-slate-900">{nameOf(d)} · balance {rm(d.balance_cents)}</p>
                <p className="text-xs text-slate-500">
                  {rm(d.amount_cents)} received {formatDateTime(d.received_at)} by {d.received_by_name} ({d.method})
                  · applied {rm(d.applied_cents)} · refunded {rm(d.refunded_cents)}
                </p>
              </div>
              {d.balance_cents > 0 && (
                <div className="flex gap-2">
                  <button type="button" className="btn-secondary" onClick={() => apply(d)}>{tr("Apply to bill")}</button>
                  {isAdmin && <button type="button" className="btn-secondary" onClick={() => refund(d)}>{tr("Refund balance")}</button>}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Hospital-side cashier desk: day close, receivables, refund approvals, deposits.
// Same facility scoping and "billing" page permission as the Billing page; the API
// enforces both, this page only hides what the role cannot do.
export default function Cashier() {
  const [tab, setTab] = useState("close");
  const user = getCurrentUser();
  const isAdmin = user?.role === "admin";
  const select = useCallback((k) => setTab(k), []);
  return (
    <Layout>
      <div className="mx-auto max-w-4xl space-y-4">
        <h1 className="page-title">{tr("Cashier")}</h1>
        <div role="tablist" aria-label={tr("Cashier sections")} className="flex flex-wrap gap-2 print:hidden">
          {TABS.map(([key, text]) => (
            <button key={key} type="button" role="tab" id={`ctab-${key}`} aria-selected={tab === key}
                    aria-controls="cashier-panel" onClick={() => select(key)}
                    className={tab === key ? "btn-primary" : "btn-secondary"}>
              {text}
            </button>
          ))}
        </div>
        <div role="tabpanel" id="cashier-panel" aria-labelledby={`ctab-${tab}`}>
          {tab === "close" && <DayClose />}
          {tab === "outstanding" && <Outstanding />}
          {tab === "refunds" && <Refunds isAdmin={isAdmin} />}
          {tab === "deposits" && <Deposits isAdmin={isAdmin} />}
        </div>
      </div>
    </Layout>
  );
}
