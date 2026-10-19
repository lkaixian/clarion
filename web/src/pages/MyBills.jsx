import { useCallback, useEffect, useState } from "react";
import Layout from "../components/Layout";
import {
  getMyBills, createPaymentIntent, simulatePayment, cancelPaymentIntent,
  getReceipt, getReceiptPdf, emailReceipt, getMyPaymentHistory, errorMessage,
} from "../api/client";
import { formatDateTime } from "../lib/format";
import { rm, toCents } from "../lib/money";
import { tr } from "../lib/i18n";

export function Receipt({ receipt, onClose }) {
  const [note, setNote] = useState(null); // { ok, text }
  const [busy, setBusy] = useState(false);

  async function download() {
    setBusy(true); setNote(null);
    try {
      const url = URL.createObjectURL(await getReceiptPdf(receipt.payment_id));
      const a = document.createElement("a");
      a.href = url; a.download = `receipt-${receipt.receipt_no}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { setNote({ ok: false, text: errorMessage(e, "Could not download the PDF.") }); }
    finally { setBusy(false); }
  }

  async function email() {
    setBusy(true); setNote(null);
    try {
      const r = await emailReceipt(receipt.payment_id);
      setNote({ ok: true, text: `Receipt sent to ${r.to_masked}.` });
    } catch (e) { setNote({ ok: false, text: errorMessage(e, "Could not send the email.") }); }
    finally { setBusy(false); }
  }

  return (
    <section className="card space-y-3" aria-label={tr("Receipt")}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Receipt {receipt.receipt_no}</h2>
          <p className="text-xs text-slate-500">{receipt.facility_name} · {formatDateTime(receipt.received_at)}</p>
        </div>
        <div className="flex gap-2 print:hidden">
          <button type="button" className="btn-secondary" disabled={busy} onClick={download}>{tr("Download PDF")}</button>
          <button type="button" className="btn-secondary" disabled={busy} onClick={email}>{tr("Email receipt")}</button>
          <button type="button" className="btn-secondary" onClick={() => window.print()}>{tr("Print")}</button>
          {onClose && <button type="button" className="btn-secondary" onClick={onClose}>{tr("Close")}</button>}
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <div><dt className="text-xs text-slate-500">{tr("Patient")}</dt><dd>{receipt.patient_full_name}</dd></div>
        <div><dt className="text-xs text-slate-500">{tr("Paid")}</dt><dd className="font-medium">{rm(receipt.amount_cents)}</dd></div>
        <div><dt className="text-xs text-slate-500">{tr("Method")}</dt><dd>{receipt.method}</dd></div>
        {receipt.reference_no && <div><dt className="text-xs text-slate-500">{tr("Reference")}</dt><dd className="break-all">{receipt.reference_no}</dd></div>}
        {receipt.refunded_cents > 0 && <div><dt className="text-xs text-slate-500">{tr("Refunded")}</dt><dd>{rm(receipt.refunded_cents)}</dd></div>}
        <div><dt className="text-xs text-slate-500">{tr("Bill balance after")}</dt><dd>{rm(receipt.bill_balance_after_cents)}</dd></div>
      </dl>
      {note && <p className={note.ok ? "bg-green-50 text-green-800 text-sm px-3 py-2 rounded-lg border border-green-200" : "alert-error"} role={note.ok ? "status" : "alert"}>{note.text}</p>}
      {receipt.voided && <p className="alert-error">{tr("This payment has been voided.")}</p>}
      <ul className="divide-y divide-slate-100 text-sm">
        {receipt.items.map((i, n) => (
          <li key={n} className="flex justify-between py-1.5">
            <span>{i.description}{i.quantity > 1 ? ` x${i.quantity}` : ""}</span><span>{rm(i.amount_cents)}</span>
          </li>
        ))}
        <li className="flex justify-between py-1.5 font-medium"><span>{tr("Bill total")}</span><span>{rm(receipt.bill_total_cents)}</span></li>
      </ul>
    </section>
  );
}

// Checkout for one bill. Steps: amount -> (gateway) -> result. The simulated gateway
// is labelled as such on screen; it only exists on demo nodes (backend refuses it elsewhere).
function Checkout({ bill, onDone, onCancel }) {
  const [amount, setAmount] = useState((bill.patient_due_cents / 100).toFixed(2));
  const [intent, setIntent] = useState(bill.pending_intent);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  async function start(e) {
    e.preventDefault();
    const cents = toCents(amount);
    if (cents === null) return setError("Enter an amount in RM, for example 25.00.");
    if (cents > bill.patient_due_cents) return setError(`The most you can pay is ${rm(bill.patient_due_cents)}.`);
    setBusy(true);
    setError("");
    try {
      setIntent(await createPaymentIntent(bill.id, { amount_cents: cents, idempotency_key: crypto.randomUUID() }));
    } catch (err) {
      setError(errorMessage(err, "Could not start the payment."));
    } finally {
      setBusy(false);
    }
  }

  async function finish(outcome) {
    setBusy(true);
    setError("");
    try {
      const done = await simulatePayment(intent.id, outcome);
      if (done.status === "succeeded") {
        setResult({ ok: true, receipt: await getReceipt(done.payment_id) });
        onDone();
      } else {
        setResult({ ok: false, reason: done.failure_reason || "The payment was declined." });
      }
    } catch (err) {
      setError(errorMessage(err, "Could not complete the payment."));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (intent) {
      try { await cancelPaymentIntent(intent.id); } catch { /* already closed: nothing to undo */ }
    }
    onCancel();
  }

  if (result?.ok) {
    return (
      <div className="space-y-3">
        <p className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800" role="status">
          Payment received. Thank you.
        </p>
        <Receipt receipt={result.receipt} onClose={onCancel} />
      </div>
    );
  }
  return (
    <div className="mt-3 space-y-3 border-t border-slate-100 pt-3">
      {error && <p className="alert-error" role="alert">{error}</p>}
      {result && !result.ok && <p className="alert-error" role="alert">{result.reason} You have not been charged.</p>}
      {!intent || result ? (
        <form onSubmit={start} className="flex flex-wrap items-end gap-3">
          <div>
            <label htmlFor={`amt-${bill.id}`} className="field-label">{tr("Amount to pay (RM)")}</label>
            <input id={`amt-${bill.id}`} className="field-input w-40" inputMode="decimal" value={amount}
                   onChange={(e) => setAmount(e.target.value)} />
          </div>
          <button type="submit" className="btn-primary" disabled={busy}>{busy ? "Starting..." : "Continue"}</button>
          <button type="button" className="btn-secondary" onClick={onCancel}>{tr("Cancel")}</button>
        </form>
      ) : (
        <div className="space-y-3">
          <p className="text-sm text-slate-700">
            Paying <strong>{rm(intent.amount_cents)}</strong> to {bill.facility_name}.
          </p>
          {intent.simulated && (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              Simulated payment page. This is a demo gateway: no real money moves.
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            {intent.simulated && (
              <>
                <button type="button" className="btn-primary" disabled={busy} onClick={() => finish("succeeded")}>
                  {busy ? "Processing..." : "Approve payment"}
                </button>
                <button type="button" className="btn-secondary" disabled={busy} onClick={() => finish("failed")}>
                  Decline payment
                </button>
              </>
            )}
            <button type="button" className="btn-secondary" disabled={busy} onClick={cancel}>{tr("Cancel payment")}</button>
          </div>
        </div>
      )}
    </div>
  );
}

function BillCard({ bill, onChanged }) {
  const [paying, setPaying] = useState(false);
  const [open, setOpen] = useState(false);
  const due = bill.patient_due_cents;
  return (
    <li className="card">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-900">{bill.facility_name}</h3>
          <p className="text-xs text-slate-500">Issued {formatDateTime(bill.finalized_at)}</p>
        </div>
        <div className="text-right">
          <p className="text-lg font-semibold text-slate-900">{rm(due)}</p>
          <p className="text-xs text-slate-500">
            {due > 0 ? "to pay" : bill.amount_due_cents > 0 ? "waiting on your insurer" : "paid in full"}
          </p>
        </div>
      </div>
      <dl className="mt-3 grid grid-cols-3 gap-2 text-sm">
        <div><dt className="text-xs text-slate-500">{tr("Total")}</dt><dd>{rm(bill.total_cents)}</dd></div>
        <div><dt className="text-xs text-slate-500">{tr("Paid")}</dt><dd>{rm(bill.paid_cents)}</dd></div>
        <div><dt className="text-xs text-slate-500">{tr("Insurer pending")}</dt><dd>{rm(bill.claimed_pending_cents)}</dd></div>
      </dl>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className="btn-secondary" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? "Hide items" : "View items"}
        </button>
        {due > 0 && !paying && (
          <button type="button" className="btn-primary" onClick={() => setPaying(true)}>
            {bill.pending_intent ? "Resume payment" : "Pay now"}
          </button>
        )}
      </div>
      {open && (
        <ul className="mt-3 divide-y divide-slate-100 text-sm">
          {bill.items.map((i, n) => (
            <li key={n} className="flex justify-between py-1.5">
              <span>{i.description}{i.quantity > 1 ? ` x${i.quantity}` : ""}</span><span>{rm(i.amount_cents)}</span>
            </li>
          ))}
        </ul>
      )}
      {paying && <Checkout bill={bill} onDone={onChanged} onCancel={() => { setPaying(false); onChanged(); }} />}
    </li>
  );
}

// Patient self-service: own finalized bills, pay online, receipts. The API only ever
// returns this patient's bills; the page does not filter anything itself.
export default function MyBills() {
  const [bills, setBills] = useState(null);
  const [history, setHistory] = useState(null);
  const [error, setError] = useState("");
  const [receipt, setReceipt] = useState(null);

  const load = useCallback(() => {
    setError("");
    Promise.all([getMyBills(), getMyPaymentHistory()])
      .then(([b, h]) => { setBills(b); setHistory(h); })
      .catch((e) => setError(errorMessage(e, "Could not load your bills.")));
  }, []);
  useEffect(load, [load]);

  async function openReceipt(id) {
    try { setReceipt(await getReceipt(id)); } catch (e) { setError(errorMessage(e, "Could not load the receipt.")); }
  }

  return (
    <Layout>
      <div className="mx-auto max-w-3xl space-y-5">
        <h1 className="page-title">{tr("My bills")}</h1>
        {error && <p className="alert-error" role="alert">{error}</p>}
        {!error && bills === null && <p className="empty-state">{tr("Loading...")}</p>}
        {receipt && <Receipt receipt={receipt} onClose={() => setReceipt(null)} />}
        {bills && bills.length === 0 && <p className="empty-state">{tr("You have no bills.")}</p>}
        {bills && bills.length > 0 && (
          <ul className="space-y-3">
            {bills.map((b) => <BillCard key={b.id} bill={b} onChanged={load} />)}
          </ul>
        )}
        {history && history.length > 0 && (
          <section aria-labelledby="hist">
            <h2 id="hist" className="mb-2 text-sm font-semibold text-slate-700">{tr("Payment history")}</h2>
            <ul className="card divide-y divide-slate-100 p-0">
              {history.map((h) => (
                <li key={h.payment_id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
                  <span className="min-w-0">
                    <span className="block font-medium text-slate-900">{rm(h.amount_cents)} · {h.method}</span>
                    <span className="block truncate text-xs text-slate-500">{h.facility_name} · {formatDateTime(h.received_at)}</span>
                  </span>
                  <button type="button" className="btn-secondary" onClick={() => openReceipt(h.payment_id)}>
                    Receipt {h.receipt_no}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </Layout>
  );
}
