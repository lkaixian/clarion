"""Payments: patients paying their own bills, and the hospital's cashier side.

Two routers, kept apart because their gates differ:

* `patient_router` (/payments): a patient account sees ITS OWN finalized bills
  and pays them online. The gateway is behind payment_providers.py (mock only
  for now). Money enters the books exactly one way: a succeeded PaymentIntent
  is settled into an ordinary `Payment` row by `settle_intent`, which both the
  signed webhook and the demo "simulate" button go through. Settling twice is
  a no-op, so a replayed webhook cannot double-credit a bill.
* `staff_router` (/billing, same "billing" page gate as billing.py): cashier
  reconciliation, outstanding/ageing, refunds (request -> a different admin
  approves) and admission deposits. Facility-local like the rest of billing.

Bill arithmetic is never duplicated here: it comes from billing._serialize_bill.
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import account_lock, auth, email_service, models, payment_providers as providers
from ..audit import log_access
from ..database import get_db
from ..rate_limit import limiter
from ..day_close_pdf import render_day_close
from ..receipt_pdf import render_receipt, rm
from .billing import (
    BILLING_READ_ROLES, BILLING_WRITE_ROLES, _bill_or_404, _load_bill_with_relations, _serialize_bill,
    cancel_open_intents,
)

logger = logging.getLogger("clarion.payments")

patient_router = APIRouter(prefix="/payments", tags=["payments"])
staff_router = APIRouter(prefix="/billing", tags=["payments"])

INTENT_TTL = timedelta(minutes=30)
REFUNDABLE_METHODS = ("cash", "card", "online", "other")  # insurance/panel/deposit are voided instead
BILLING_APPROVE_ROLES = ("admin",)
AGE_BUCKETS = ((30, "0-30"), (60, "31-60"), (90, "61-90"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lock(db: Session, model, row_id: str, column: str) -> None:
    """Serialise money decisions on one row (a bill, a payment, a deposit).

    Call AFTER the request is authorised and BEFORE re-reading what the decision
    depends on. A no-op write holds the row's write lock until commit on SQLite and
    MariaDB alike (SELECT ... FOR UPDATE is ignored by SQLite, which is exactly what
    let parallel requests double-spend in testing). The commit first ends the read
    snapshot taken while authorising, so the re-read sees what the previous holder
    committed; expire_all drops any cached copies."""
    db.commit()
    attr = getattr(model, column)
    db.query(model).filter(model.id == row_id).update({attr: attr}, synchronize_session=False)
    db.expire_all()


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


# ---------------------------------------------------------------------------
# Settlement (the only place an online payment becomes money)
# ---------------------------------------------------------------------------
def settle_intent(db: Session, intent: models.PaymentIntent, outcome: str, reason: Optional[str] = None):
    """Idempotent and safe under concurrent calls. The state change is ONE
    conditional UPDATE (compare-and-set on `status`), so exactly one caller can
    win it on any database; only that caller books the Payment. A read-then-write
    guard is not enough: two workers both read 'pending' and both credit the bill
    (reproduced on SQLite with 16 parallel webhooks)."""
    if outcome not in ("succeeded", "failed"):
        raise ValueError("outcome must be 'succeeded' or 'failed'")
    I = models.PaymentIntent
    now = _now()
    if outcome == "failed":
        # Only an open attempt can fail; a late 'failed' never undoes a success.
        db.query(I).filter(I.id == intent.id, I.status == "pending").update(
            {"status": "failed", "failure_reason": (reason or "Payment was not completed")[:500],
             "completed_at": now}, synchronize_session=False)
        db.commit()
        db.refresh(intent)
        return intent

    # Money arriving for an attempt we had already closed (failed/cancelled/expired)
    # is still booked: the gateway took it, so the books must show it.
    won = db.query(I).filter(
        I.id == intent.id, I.status.in_(("pending", "expired", "failed", "cancelled"))
    ).update({"status": "succeeded", "completed_at": now}, synchronize_session=False)
    if won != 1:
        db.rollback()
        db.refresh(intent)
        return intent
    payment = models.Payment(
        bill_id=intent.bill_id, amount_cents=intent.amount_cents, method="online",
        reference_no=intent.provider_ref, received_by=None, received_by_name="Online payment",
        received_by_role="patient", facility_name=intent.facility_name,
    )
    db.add(payment)
    db.flush()
    db.query(I).filter(I.id == intent.id).update({"payment_id": payment.id}, synchronize_session=False)
    db.commit()
    db.refresh(intent)
    patient_id = db.query(models.Bill.patient_id).filter(models.Bill.id == intent.bill_id).scalar()
    log_access(
        db, patient_id, "system", None, "payment_online_settled",
        detail=f"bill_id={intent.bill_id} intent_id={intent.id} amount_cents={intent.amount_cents}",
        actor_facility=intent.facility_name,
    )
    return intent


def _apply_event(db: Session, body: bytes, signature: Optional[str]) -> dict:
    if not providers.verify(body, signature or ""):
        raise HTTPException(status_code=401, detail="Bad signature")
    try:
        event = json.loads(body)
        ref, status, amount = event["provider_ref"], event["status"], int(event["amount_cents"])
    except (ValueError, KeyError, TypeError):
        raise HTTPException(status_code=400, detail="Malformed event")
    if status not in ("succeeded", "failed"):
        raise HTTPException(status_code=400, detail="Unsupported status")
    intent = db.query(models.PaymentIntent).filter(models.PaymentIntent.provider_ref == ref).first()
    if intent is None:
        raise HTTPException(status_code=404, detail="Unknown payment reference")
    if amount != intent.amount_cents:
        raise HTTPException(status_code=409, detail="Amount does not match the payment attempt")
    done = settle_intent(db, intent, status, event.get("reason"))
    return {"status": done.status}


# ---------------------------------------------------------------------------
# Patient side
# ---------------------------------------------------------------------------
class IntentCreate(BaseModel):
    amount_cents: Optional[int] = Field(default=None, ge=1, le=100_000_000)  # default: the whole patient due
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=64)


class SimulateBody(BaseModel):
    outcome: str = Field(pattern="^(succeeded|failed)$")


def _intent_out(i: models.PaymentIntent) -> dict:
    return {
        "id": i.id, "bill_id": i.bill_id, "amount_cents": i.amount_cents, "status": i.status,
        "provider": i.provider, "provider_ref": i.provider_ref, "expires_at": i.expires_at,
        "failure_reason": i.failure_reason, "payment_id": i.payment_id,
        "simulated": i.provider == "mock",
    }


def _patient_only(user: models.User = Depends(auth.require_roles("patient"))) -> models.User:
    if not user.patient_id:
        raise HTTPException(status_code=403, detail="This account is not linked to a patient record")
    return user


def _own_bill(db: Session, user: models.User, bill_id: str) -> models.Bill:
    bill = _load_bill_with_relations(db, bill_id)
    if bill is None or bill.patient_id != user.patient_id:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


def _own_intent(db: Session, user: models.User, intent_id: str) -> models.PaymentIntent:
    i = db.query(models.PaymentIntent).filter(models.PaymentIntent.id == intent_id).first()
    if i is None or i.patient_id != user.patient_id:
        raise HTTPException(status_code=404, detail="Payment not found")
    return i


@patient_router.get("/my-bills")
def my_bills(db: Session = Depends(get_db), user: models.User = Depends(_patient_only)):
    bills = (
        db.query(models.Bill).filter(models.Bill.patient_id == user.patient_id, models.Bill.status == "finalized")
        .order_by(models.Bill.finalized_at.desc()).all()
    )
    out = []
    for b in bills:
        b = _load_bill_with_relations(db, b.id)
        s = _serialize_bill(b)
        pending = (
            db.query(models.PaymentIntent)
            .filter(models.PaymentIntent.bill_id == b.id, models.PaymentIntent.status == "pending",
                    models.PaymentIntent.expires_at > _now())
            .first()
        )
        out.append({
            "id": b.id, "facility_name": b.facility_name, "finalized_at": b.finalized_at,
            "total_cents": s.total_cents, "paid_cents": s.paid_cents,
            "claimed_pending_cents": s.claimed_pending_cents, "amount_due_cents": s.amount_due_cents,
            "patient_due_cents": s.patient_due_cents,
            "items": [{"description": i.description, "quantity": i.quantity, "amount_cents": i.amount_cents}
                      for i in b.items if not i.voided_at],
            "payments": [{"id": p.id, "amount_cents": p.amount_cents, "method": p.method,
                          "received_at": p.received_at} for p in b.payments if not p.voided_at],
            "pending_intent": _intent_out(pending) if pending else None,
        })
    return out


@patient_router.post("/bills/{bill_id}/intents", status_code=201)
@limiter.limit("20/minute")
def create_intent(
    request: Request, bill_id: str, payload: IntentCreate,
    db: Session = Depends(get_db), user: models.User = Depends(_patient_only),
):
    account_lock.require_account_mature(user)
    bill = _own_bill(db, user, bill_id)
    if bill.status != "finalized":
        raise HTTPException(status_code=400, detail="This bill is not ready for payment")
    _lock(db, models.Bill, bill.id, "status")  # one open attempt per bill, whatever the taps
    bill = _load_bill_with_relations(db, bill_id)
    if bill.status != "finalized":
        raise HTTPException(status_code=400, detail="This bill is not ready for payment")
    due = _serialize_bill(bill).patient_due_cents
    if due <= 0:
        raise HTTPException(status_code=400, detail="Nothing is due on this bill")
    amount = payload.amount_cents or due
    if amount > due:
        raise HTTPException(status_code=400, detail=f"Amount cannot exceed the amount due ({due})")

    if payload.idempotency_key:
        prior = db.query(models.PaymentIntent).filter_by(
            patient_id=user.patient_id, idempotency_key=payload.idempotency_key).first()
        if prior is not None:
            if prior.bill_id != bill.id or prior.amount_cents != amount:
                raise HTTPException(status_code=409, detail="That idempotency key was used for a different payment")
            return _intent_out(prior)

    now = _now()
    open_intents = db.query(models.PaymentIntent).filter_by(bill_id=bill.id, status="pending").all()
    for i in open_intents:
        if _aware(i.expires_at) <= now:
            i.status = "expired"
        elif i.amount_cents != amount:
            raise HTTPException(status_code=409, detail="A payment for this bill is already in progress")
        else:
            return _intent_out(i)

    try:
        provider = providers.get_provider()
    except providers.ProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc))
    intent = models.PaymentIntent(
        bill_id=bill.id, patient_id=user.patient_id, facility_name=bill.facility_name, amount_cents=amount,
        provider=provider.name, idempotency_key=payload.idempotency_key, expires_at=now + INTENT_TTL,
    )
    db.add(intent)
    db.commit()  # the open attempt is visible (and the bill lock released) before any gateway call
    try:
        intent.provider_ref = provider.create(amount, bill.id)["provider_ref"]
    except providers.ProviderError as exc:
        intent.status, intent.failure_reason, intent.completed_at = "failed", str(exc)[:500], _now()
        db.commit()
        raise HTTPException(status_code=503, detail=str(exc))
    db.commit()
    log_access(db, bill.patient_id, user.id, user.role, "payment_intent_created",
               detail=f"bill_id={bill.id} amount_cents={amount}", actor_facility=bill.facility_name)
    return _intent_out(intent)


@patient_router.get("/intents/{intent_id}")
def get_intent(intent_id: str, db: Session = Depends(get_db), user: models.User = Depends(_patient_only)):
    return _intent_out(_own_intent(db, user, intent_id))


@patient_router.post("/intents/{intent_id}/cancel")
def cancel_intent(intent_id: str, db: Session = Depends(get_db), user: models.User = Depends(_patient_only)):
    i = _own_intent(db, user, intent_id)
    if i.status != "pending":
        raise HTTPException(status_code=409, detail=f"This payment is already {i.status}")
    i.status = "cancelled"
    i.completed_at = _now()
    db.commit()
    return _intent_out(i)


@patient_router.post("/intents/{intent_id}/simulate")
@limiter.limit("20/minute")
def simulate_outcome(
    request: Request, intent_id: str, payload: SimulateBody,
    db: Session = Depends(get_db), user: models.User = Depends(_patient_only),
):
    """Demo gateway: signs the same event a real gateway would POST to the
    webhook and runs it through the same code. Refused on a real provider."""
    i = _own_intent(db, user, intent_id)
    if i.provider != "mock" or not providers.mock_allowed():
        raise HTTPException(status_code=403, detail="Simulation is not available")
    body = json.dumps({"provider_ref": i.provider_ref, "status": payload.outcome,
                       "amount_cents": i.amount_cents,
                       "reason": "Declined by simulated bank" if payload.outcome == "failed" else None}).encode()
    _apply_event(db, body, providers.sign(body))
    db.refresh(i)
    return _intent_out(i)


@patient_router.post("/webhook/{provider}")
@limiter.limit("240/minute")
async def webhook(request: Request, provider: str, db: Session = Depends(get_db)):
    if provider != "mock" or not providers.mock_allowed():
        raise HTTPException(status_code=404, detail="Unknown provider")
    return _apply_event(db, await request.body(), request.headers.get("x-signature"))


def _receipt(db: Session, payment: models.Payment) -> dict:
    bill = _load_bill_with_relations(db, payment.bill_id)
    s = _serialize_bill(bill)
    refunded = sum(r.amount_cents for r in bill.refunds if r.status == "approved" and r.payment_id == payment.id)
    return {
        "receipt_no": payment.id[:8].upper(), "payment_id": payment.id, "bill_id": bill.id,
        "facility_name": bill.facility_name, "patient_full_name": bill.patient.full_name if bill.patient else None,
        "amount_cents": payment.amount_cents, "refunded_cents": refunded, "method": payment.method,
        "reference_no": payment.reference_no, "received_at": payment.received_at,
        "received_by_name": payment.received_by_name, "voided": payment.voided_at is not None,
        "bill_total_cents": s.total_cents, "bill_balance_after_cents": s.amount_due_cents,
        "items": [{"description": i.description, "quantity": i.quantity, "amount_cents": i.amount_cents}
                  for i in bill.items if not i.voided_at],
    }


def _readable_payment(db: Session, user: models.User, payment_id: str) -> models.Payment:
    """The payment if this user may see its receipt, else 404 (never confirms it exists)."""
    payment = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    bill = db.query(models.Bill).filter(models.Bill.id == payment.bill_id).first() if payment else None
    if bill is None:
        raise HTTPException(status_code=404, detail="Receipt not found")
    if user.role == "patient":
        allowed = user.patient_id is not None and bill.patient_id == user.patient_id
    else:
        allowed = user.role in BILLING_READ_ROLES and bool(user.facility) and bill.facility_name == user.facility
    if not allowed:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return payment


@patient_router.get("/receipts/{payment_id}")
def get_receipt(
    payment_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.get_current_user),
):
    return _receipt(db, _readable_payment(db, user, payment_id))


@patient_router.get("/receipts/{payment_id}/pdf")
@limiter.limit("60/minute")
def get_receipt_pdf(
    request: Request, payment_id: str, db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    r = _receipt(db, _readable_payment(db, user, payment_id))
    return Response(
        render_receipt(r), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="receipt-{r["receipt_no"]}.pdf"',
                 "Cache-Control": "no-store"},
    )


@patient_router.post("/receipts/{payment_id}/email")
@limiter.limit("5/minute")
def email_receipt(
    request: Request, payment_id: str, db: Session = Depends(get_db),
    user: models.User = Depends(auth.get_current_user),
):
    """Always goes to the patient's own contact email on file; the caller cannot choose a
    recipient, so this cannot be used to send a bill to someone else."""
    payment = _readable_payment(db, user, payment_id)
    r = _receipt(db, payment)
    bill = db.query(models.Bill).filter(models.Bill.id == payment.bill_id).first()
    to = (bill.patient.email or "").strip() if bill is not None and bill.patient else ""
    if not to or "@" not in to:
        raise HTTPException(status_code=400, detail="This patient has no email address on file")
    summary = f"{rm(r['amount_cents'])} paid to {r['facility_name']}. Balance: {rm(r['bill_balance_after_cents'])}."
    sent = email_service.send_receipt_email(
        to, r["patient_full_name"] or "", r["receipt_no"], summary, render_receipt(r))
    log_access(db, bill.patient_id, user.email, user.role,
               "receipt_email_sent" if sent else "receipt_email_failed",
               detail=f"receipt {r['receipt_no']}", actor_facility=user.facility)
    if not sent:
        raise HTTPException(status_code=503, detail="Email could not be sent right now. Download the PDF instead.")
    return {"sent": True, "to_masked": to[:1] + "***" + to[to.find("@"):]}


@patient_router.get("/my-history")
def my_history(db: Session = Depends(get_db), user: models.User = Depends(_patient_only)):
    rows = (
        db.query(models.Payment).join(models.Bill, models.Bill.id == models.Payment.bill_id)
        .filter(models.Bill.patient_id == user.patient_id, models.Payment.voided_at.is_(None))
        .order_by(models.Payment.received_at.desc()).limit(200).all()
    )
    return [{"payment_id": p.id, "bill_id": p.bill_id, "amount_cents": p.amount_cents, "method": p.method,
             "received_at": p.received_at, "facility_name": p.facility_name, "receipt_no": p.id[:8].upper()}
            for p in rows]


# ---------------------------------------------------------------------------
# Hospital side: reconciliation, outstanding, refunds, deposits
# ---------------------------------------------------------------------------
MAX_CLOSE_DAYS = 186  # six months


def _window(day: Optional[date], tz_offset_minutes: int, days: int = 1):
    """`days` local days ending on (and including) `day`."""
    offset = timedelta(minutes=tz_offset_minutes)
    local_day = day or (_now() + offset).date()
    end_start = datetime(local_day.year, local_day.month, local_day.day, tzinfo=timezone.utc) - offset
    return local_day, end_start - timedelta(days=days - 1), end_start + timedelta(days=1)


@staff_router.get("/reconciliation")
def reconciliation(
    day: Optional[date] = Query(default=None, description="Last day of the range (local); default today"),
    tz_offset_minutes: int = Query(default=480, ge=-720, le=840),  # Malaysia is UTC+8
    days: int = Query(default=1, ge=1, le=MAX_CLOSE_DAYS, description="How many days, ending on `day`"),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    """Cashier close for one local day (or the `days` days ending on it), in money actually received.

    collected = non-voided payments taken in the window, EXCLUDING payments
    settled from a deposit (that cash arrived on the deposit day and is counted
    there; counting it again when applied would inflate the drawer).
    net = collected + deposits received - approved refunds - deposit refunds.
    Voids are listed, not netted, so a supervisor reviews them."""
    local_day, start, end = _window(day, tz_offset_minutes, days)
    P, R, D, I = models.Payment, models.Refund, models.Deposit, models.PaymentIntent
    pays = db.query(P).filter(P.facility_name == user.facility, P.received_at >= start, P.received_at < end).all()
    live = [p for p in pays if not p.voided_at]
    applied = [p for p in live if p.method == "deposit"]
    live = [p for p in live if p.method != "deposit"]
    by_method, by_cashier = {}, {}
    for p in live:
        m = by_method.setdefault(p.method, {"count": 0, "total_cents": 0})
        m["count"] += 1
        m["total_cents"] += p.amount_cents
        c = by_cashier.setdefault(p.received_by_name or "Unknown", {"name": p.received_by_name or "Unknown",
                                                                      "count": 0, "total_cents": 0})
        c["count"] += 1
        c["total_cents"] += p.amount_cents
    collected = sum(p.amount_cents for p in live)
    voided = [p for p in pays if p.voided_at]
    refunds = db.query(R).filter(R.facility_name == user.facility, R.status == "approved",
                                 R.decided_at >= start, R.decided_at < end).all()
    refunded = sum(r.amount_cents for r in refunds)
    deposits = db.query(D).filter(D.facility_name == user.facility, D.received_at >= start, D.received_at < end).all()
    deposits_total = sum(d.amount_cents for d in deposits)
    DR = models.DepositRefund
    dep_refunds = db.query(DR).filter(DR.facility_name == user.facility, DR.refunded_at >= start,
                                      DR.refunded_at < end).all()
    dep_refunded = sum(r.amount_cents for r in dep_refunds)
    pending = db.query(I).filter(I.facility_name == user.facility, I.status == "pending",
                                 I.created_at >= start, I.created_at < end).all()
    return {
        "day": local_day.isoformat(), "days": days,
        "from_day": (local_day - timedelta(days=days - 1)).isoformat(),
        "tz_offset_minutes": tz_offset_minutes, "facility_name": user.facility,
        "collected_cents": collected, "by_method": by_method,
        "by_cashier": sorted(by_cashier.values(), key=lambda c: -c["total_cents"]),
        "voided": {"count": len(voided), "total_cents": sum(p.amount_cents for p in voided)},
        "refunds": {"count": len(refunds), "total_cents": refunded},
        "net_cents": collected + deposits_total - refunded - dep_refunded,
        "deposit_refunds": {"count": len(dep_refunds), "total_cents": dep_refunded},
        "deposits_received": {"count": len(deposits), "total_cents": deposits_total},
        "applied_from_deposits": {"count": len(applied), "total_cents": sum(p.amount_cents for p in applied)},
        "online_pending": {"count": len(pending), "total_cents": sum(i.amount_cents for i in pending)},
    }


@staff_router.get("/reconciliation/pdf")
def reconciliation_pdf(
    day: Optional[date] = Query(default=None),
    tz_offset_minutes: int = Query(default=480, ge=-720, le=840),
    days: int = Query(default=1, ge=1, le=MAX_CLOSE_DAYS),
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    """The same figures as /reconciliation, as a printable one-page PDF."""
    rec = reconciliation(day=day, days=days, tz_offset_minutes=tz_offset_minutes, db=db, user=user)
    log_access(db, None, user.id, user.role, "day_close_pdf", detail=f'{rec["from_day"]}..{rec["day"]}', actor_facility=user.facility)
    name = rec["day"] if rec["days"] == 1 else f'{rec["from_day"]}_to_{rec["day"]}'
    return Response(
        render_day_close(rec, user.full_name or user.email), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="day-close-{name}.pdf"',
                 "Cache-Control": "no-store"},
    )


@staff_router.get("/outstanding")
def outstanding(
    db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*BILLING_READ_ROLES)),
):
    """Finalized bills with a balance, aged from finalization. Whole-facility
    scan; fine at clinic scale (ponytail: add a SQL aggregate if a facility
    holds tens of thousands of open bills)."""
    ids = [b.id for b in db.query(models.Bill.id).filter(
        models.Bill.facility_name == user.facility, models.Bill.status == "finalized")]
    now = _now()
    buckets = {label: {"label": label, "count": 0, "total_cents": 0} for _, label in AGE_BUCKETS}
    buckets["90+"] = {"label": "90+", "count": 0, "total_cents": 0}
    rows = []
    for bid in ids:
        b = _load_bill_with_relations(db, bid)
        s = _serialize_bill(b)
        if s.amount_due_cents <= 0:
            continue
        age = max(0, (now - _aware(b.finalized_at or b.created_at)).days)
        label = next((lbl for limit, lbl in AGE_BUCKETS if age <= limit), "90+")
        buckets[label]["count"] += 1
        buckets[label]["total_cents"] += s.amount_due_cents
        rows.append({"bill_id": b.id, "patient_id": b.patient_id, "patient_full_name": s.patient_full_name,
                     "finalized_at": b.finalized_at, "age_days": age, "bucket": label,
                     "amount_due_cents": s.amount_due_cents, "patient_due_cents": s.patient_due_cents})
    rows.sort(key=lambda r: -r["age_days"])
    return {"total_cents": sum(r["amount_due_cents"] for r in rows), "buckets": list(buckets.values()),
            "bills": rows[:500]}


# ---- refunds ----------------------------------------------------------------
class RefundCreate(BaseModel):
    amount_cents: int = Field(ge=1, le=100_000_000)
    reason: str = Field(min_length=1, max_length=2000)


class RefundDecision(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


def _refund_out(r: models.Refund) -> dict:
    return {
        "id": r.id, "payment_id": r.payment_id, "bill_id": r.bill_id, "amount_cents": r.amount_cents,
        "reason": r.reason, "status": r.status, "requested_by_name": r.requested_by_name,
        "requested_at": r.requested_at, "decided_by_name": r.decided_by_name, "decided_at": r.decided_at,
        "decision_note": r.decision_note, "provider_ref": r.provider_ref,
    }


def _refundable_left(db: Session, payment: models.Payment, exclude_id: Optional[str] = None) -> int:
    taken = sum(
        r.amount_cents for r in db.query(models.Refund).filter(
            models.Refund.payment_id == payment.id, models.Refund.status.in_(("requested", "approved")))
        if r.id != exclude_id
    )
    return payment.amount_cents - taken


def _refund_or_404(db: Session, refund_id: str, user: models.User) -> models.Refund:
    r = db.query(models.Refund).filter(models.Refund.id == refund_id).first()
    if r is None or not user.facility or r.facility_name != user.facility:
        raise HTTPException(status_code=404, detail="Refund not found")
    return r


@staff_router.post("/payments/{payment_id}/refunds", status_code=201)
def request_refund(
    payment_id: str, payload: RefundCreate, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    payment = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    bill = _bill_or_404(db, payment.bill_id, user)  # the facility gate
    if payment.voided_at:
        raise HTTPException(status_code=400, detail="This payment is voided")
    if payment.method not in REFUNDABLE_METHODS:
        raise HTTPException(status_code=400, detail=f"A {payment.method} payment is voided, not refunded")
    _lock(db, models.Payment, payment.id, "amount_cents")
    payment = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if payment.voided_at:
        raise HTTPException(status_code=400, detail="This payment is voided")
    left = _refundable_left(db, payment)
    if payload.amount_cents > left:
        raise HTTPException(status_code=400, detail=f"Only {left} cents of this payment can still be refunded")
    bill_id_, facility_, patient_id_ = bill.id, bill.facility_name, bill.patient_id
    r = models.Refund(
        payment_id=payment.id, bill_id=bill_id_, facility_name=facility_, amount_cents=payload.amount_cents,
        reason=payload.reason, requested_by=user.id, requested_by_name=user.full_name,
    )
    db.add(r)
    db.commit()
    log_access(db, patient_id_, user.id, user.role, "refund_requested",
               detail=f"refund_id={r.id} payment_id={payment.id} amount_cents={r.amount_cents}",
               actor_facility=user.facility)
    return _refund_out(r)


@staff_router.get("/refunds")
def list_refunds(
    status: Optional[str] = Query(default=None), db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    q = db.query(models.Refund).filter(models.Refund.facility_name == user.facility)
    if status:
        if status not in models.REFUND_STATUSES:
            raise HTTPException(status_code=422, detail="Unknown status")
        q = q.filter(models.Refund.status == status)
    return [_refund_out(r) for r in q.order_by(models.Refund.requested_at.desc()).limit(200)]


@staff_router.post("/refunds/{refund_id}/approve")
def approve_refund(
    refund_id: str, payload: RefundDecision, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*BILLING_APPROVE_ROLES)),
):
    r = _refund_or_404(db, refund_id, user)
    if r.requested_by == user.id:
        raise HTTPException(status_code=403, detail="A different admin must approve your own refund request")
    # Two approvals (or an approval racing a new request) serialise on the payment.
    # ponytail: the gateway call below runs under this row lock; fine for a rare
    # admin action, switch to claim-then-call if refunds ever become high volume.
    _lock(db, models.Payment, r.payment_id, "amount_cents")
    r = _refund_or_404(db, refund_id, user)
    if r.status != "requested":
        raise HTTPException(status_code=409, detail=f"This refund is already {r.status}")
    payment = db.query(models.Payment).filter(models.Payment.id == r.payment_id).first()
    if payment.voided_at:
        raise HTTPException(status_code=409, detail="The payment was voided after this refund was requested")
    if r.amount_cents > _refundable_left(db, payment, exclude_id=r.id):
        raise HTTPException(status_code=409, detail="The payment no longer has this much left to refund")
    if payment.method == "online":
        try:
            r.provider_ref = providers.get_provider().refund(payment.reference_no, r.amount_cents)
        except providers.ProviderError as exc:
            raise HTTPException(status_code=502, detail=f"Gateway refused the refund: {exc}")
    r.status, r.decided_by, r.decided_by_name = "approved", user.id, user.full_name
    r.decided_at, r.decision_note = _now(), payload.note
    db.commit()
    bill = _load_bill_with_relations(db, r.bill_id)
    log_access(db, bill.patient_id, user.id, user.role, "refund_approved",
               detail=f"refund_id={r.id} amount_cents={r.amount_cents}", actor_facility=user.facility)
    return _refund_out(r)


@staff_router.post("/refunds/{refund_id}/reject")
def reject_refund(
    refund_id: str, payload: RefundDecision, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*BILLING_APPROVE_ROLES)),
):
    r = _refund_or_404(db, refund_id, user)
    if r.status != "requested":
        raise HTTPException(status_code=409, detail=f"This refund is already {r.status}")
    r.status, r.decided_by, r.decided_by_name = "rejected", user.id, user.full_name
    r.decided_at, r.decision_note = _now(), payload.note
    db.commit()
    bill = _load_bill_with_relations(db, r.bill_id)
    log_access(db, bill.patient_id, user.id, user.role, "refund_rejected",
               detail=f"refund_id={r.id}", actor_facility=user.facility)
    return _refund_out(r)


# ---- deposits ---------------------------------------------------------------
DEPOSIT_METHODS = ("cash", "card", "other")


class DepositCreate(BaseModel):
    patient_id: str
    amount_cents: int = Field(ge=1, le=100_000_000)
    method: str
    reference_no: Optional[str] = Field(default=None, max_length=128)


class DepositApply(BaseModel):
    bill_id: str
    amount_cents: int = Field(ge=1, le=100_000_000)


class DepositRefund(BaseModel):
    amount_cents: Optional[int] = Field(default=None, ge=1, le=100_000_000)  # default: the whole balance


def _deposit_out(d: models.Deposit) -> dict:
    return {
        "id": d.id, "patient_id": d.patient_id, "patient_full_name": d.patient.full_name if d.patient else None,
        "facility_name": d.facility_name, "amount_cents": d.amount_cents,
        "applied_cents": d.applied_cents, "refunded_cents": d.refunded_cents,
        "balance_cents": d.amount_cents - d.applied_cents - d.refunded_cents, "method": d.method,
        "reference_no": d.reference_no, "received_by_name": d.received_by_name, "received_at": d.received_at,
    }


def _deposit_or_404(db: Session, deposit_id: str, user: models.User) -> models.Deposit:
    d = db.query(models.Deposit).filter(models.Deposit.id == deposit_id).first()
    if d is None or not user.facility or d.facility_name != user.facility:
        raise HTTPException(status_code=404, detail="Deposit not found")
    return d


@staff_router.post("/deposits", status_code=201)
def create_deposit(
    payload: DepositCreate, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    if payload.method not in DEPOSIT_METHODS:
        raise HTTPException(status_code=422, detail=f"method must be one of: {', '.join(DEPOSIT_METHODS)}")
    if db.query(models.Patient.id).filter(models.Patient.id == payload.patient_id).first() is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    d = models.Deposit(
        patient_id=payload.patient_id, facility_name=user.facility, amount_cents=payload.amount_cents,
        method=payload.method, reference_no=payload.reference_no, received_by=user.id,
        received_by_name=user.full_name,
    )
    db.add(d)
    db.commit()
    log_access(db, d.patient_id, user.id, user.role, "deposit_received",
               detail=f"deposit_id={d.id} amount_cents={d.amount_cents}", actor_facility=user.facility)
    return _deposit_out(d)


@staff_router.get("/deposits")
def list_deposits(
    patient_id: Optional[str] = Query(default=None), db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*BILLING_READ_ROLES)),
):
    q = db.query(models.Deposit).filter(models.Deposit.facility_name == user.facility)
    if patient_id:
        q = q.filter(models.Deposit.patient_id == patient_id)
    return [_deposit_out(d) for d in q.order_by(models.Deposit.received_at.desc()).limit(200)]


@staff_router.post("/deposits/{deposit_id}/apply", response_model=None)
def apply_deposit(
    deposit_id: str, payload: DepositApply, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    d = _deposit_or_404(db, deposit_id, user)
    bill = _bill_or_404(db, payload.bill_id, user)
    if bill.patient_id != d.patient_id:
        raise HTTPException(status_code=400, detail="The deposit belongs to a different patient")
    if bill.status == "voided":
        raise HTTPException(status_code=400, detail="Cannot pay a voided bill")
    # Lock order is always deposit, then bill. The deposit counters below are also
    # a conditional UPDATE, so the balance can never be spent twice.
    _lock(db, models.Deposit, d.id, "amount_cents")
    _lock(db, models.Bill, bill.id, "status")
    d = _deposit_or_404(db, deposit_id, user)
    bill = _bill_or_404(db, payload.bill_id, user)
    if bill.status == "voided":
        raise HTTPException(status_code=400, detail="Cannot pay a voided bill")
    balance = d.amount_cents - d.applied_cents - d.refunded_cents
    due = _serialize_bill(bill).amount_due_cents
    if payload.amount_cents > balance:
        raise HTTPException(status_code=400, detail=f"The deposit only has {balance} cents left")
    if payload.amount_cents > due:
        raise HTTPException(status_code=400, detail=f"The bill only has {due} cents due")
    D = models.Deposit
    spent = db.query(D).filter(
        D.id == d.id, D.amount_cents - D.applied_cents - D.refunded_cents >= payload.amount_cents
    ).update({D.applied_cents: D.applied_cents + payload.amount_cents}, synchronize_session=False)
    if spent != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="The deposit no longer has enough left")
    db.add(models.Payment(
        bill_id=bill.id, amount_cents=payload.amount_cents, method="deposit", reference_no=d.id,
        received_by=user.id, received_by_name=user.full_name, received_by_role=user.role,
        facility_name=user.facility,
    ))
    cancel_open_intents(db, bill.id)
    db.commit()
    log_access(db, bill.patient_id, user.id, user.role, "deposit_applied",
               detail=f"deposit_id={d.id} bill_id={bill.id} amount_cents={payload.amount_cents}",
               actor_facility=user.facility)
    return {"deposit": _deposit_out(d), "bill": _serialize_bill(_load_bill_with_relations(db, bill.id))}


@staff_router.post("/deposits/{deposit_id}/refund")
def refund_deposit(
    deposit_id: str, payload: DepositRefund, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*BILLING_APPROVE_ROLES)),
):
    d = _deposit_or_404(db, deposit_id, user)
    _lock(db, models.Deposit, d.id, "amount_cents")
    d = _deposit_or_404(db, deposit_id, user)
    balance = d.amount_cents - d.applied_cents - d.refunded_cents
    amount = payload.amount_cents or balance
    if balance <= 0 or amount > balance:
        raise HTTPException(status_code=400, detail=f"The deposit only has {balance} cents left")
    D = models.Deposit
    got = db.query(D).filter(
        D.id == d.id, D.amount_cents - D.applied_cents - D.refunded_cents >= amount
    ).update({D.refunded_cents: D.refunded_cents + amount}, synchronize_session=False)
    if got != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="The deposit no longer has enough left")
    db.add(models.DepositRefund(deposit_id=d.id, facility_name=d.facility_name, amount_cents=amount,
                                refunded_by=user.id, refunded_by_name=user.full_name))
    db.commit()
    db.refresh(d)
    log_access(db, d.patient_id, user.id, user.role, "deposit_refunded",
               detail=f"deposit_id={d.id} amount_cents={amount}", actor_facility=user.facility)
    return _deposit_out(d)
