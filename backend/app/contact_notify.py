"""Tell a patient's emergency contact that the patient's card was scanned.

Delivery order: the CLARION app first (an in-app alert on the contact's own account, if the
contact's phone number belongs to exactly one registered patient account), otherwise SMS.

The scan itself only queues a job (`safe_queue()`), so a slow or dead SMS gateway never delays
-- or fails -- a life-safety scan. The job is retried with a long, spaced policy (see the
`jobs.register` call at the bottom) so a network or gateway outage delays the alert instead
of losing it; an offline tag read is queued the same way when its log is uploaded later.

The message carries the patient's first name and the time, nothing clinical. Limits: one alert
per patient per THROTTLE_MINUTES, and at most MAX_PER_DESTINATION_PER_HOUR per phone number
across all patients (so a number entered on many records can't be used to spam one person).
The audit log still records every scan.

Known gap: `Patient.phone` is self-entered and not verified, so the "registered contact" match
can be claimed by someone who types another person's number into their own profile. Verify
phone numbers (OTP) before relying on the in-app channel alone.
"""
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import jobs, models, sms_service
from .database import SessionLocal
from .phone import normalize_phone, sms_allowed
from .routers.notifications import notify

logger = logging.getLogger("clarion.contact_notify")

JOB_KIND = "notify_contact"
THROTTLE_MINUTES = 10
MAX_PER_DESTINATION_PER_HOUR = 3
_MYT = timezone(timedelta(hours=8))  # Malaysia has no DST


def _dest_key(phone: str) -> str:
    return hashlib.sha256(phone.encode()).hexdigest()[:16]


def queue(db: Session, patient: models.Patient, when: Optional[datetime] = None, late: bool = False) -> str:
    """'none' (no usable contact), 'throttled' or 'queued'. Commits (the job must be visible
    to the worker's own session). `late` = reported after the fact from an offline tag read."""
    phone = normalize_phone(patient.emergency_contact_phone)
    if not phone or not sms_allowed(phone):
        return "none"
    now = datetime.now(timezone.utc)
    dest = _dest_key(phone)
    recent = db.query(models.Job).filter(
        models.Job.kind == JOB_KIND, models.Job.created_at >= now - timedelta(hours=1),
        models.Job.payload.like(f'%"dest": "{dest}"%')).count()
    if recent >= MAX_PER_DESTINATION_PER_HOUR:
        return "throttled"
    # Conditional UPDATE = an atomic claim on the per-patient window across gunicorn workers.
    claimed = db.query(models.Patient).filter(
        models.Patient.id == patient.id,
        or_(models.Patient.emergency_contact_notified_at.is_(None),
            models.Patient.emergency_contact_notified_at < now - timedelta(minutes=THROTTLE_MINUTES)),
    ).update({"emergency_contact_notified_at": now}, synchronize_session=False)
    if not claimed:
        db.commit()
        return "throttled"
    jobs.enqueue(db, JOB_KIND, {"patient_id": patient.id, "dest": dest, "late": late,
                                "scanned_at": (when or now).isoformat()})
    return "queued"


def safe_queue(db: Session, patient: Optional[models.Patient], when: Optional[datetime] = None,
               late: bool = False) -> str:
    """queue() that can never raise: the scan (and its audit row) matter more than the alert."""
    if patient is None:
        return "none"
    try:
        return queue(db, patient, when, late)
    except Exception:  # noqa: BLE001 - a DB hiccup here must not turn a successful scan into a 500
        logger.exception("could not queue emergency-contact alert for patient %s", patient.id)
        db.rollback()
        return "error"


def _registered_account(db: Session, phone: str, patient_id: str) -> Optional[models.User]:
    """The patient account owning `phone`, only if exactly one patient does (a number shared
    by a family is ambiguous, so it falls back to SMS).
    # ponytail: scans (id, phone) of every patient with a phone, in Python, inside the background
    # job; add an indexed normalized_phone column if the patient table gets large."""
    owners = [
        pid for pid, raw in db.query(models.Patient.id, models.Patient.phone).filter(
            models.Patient.phone.isnot(None), models.Patient.id != patient_id).all()
        if normalize_phone(raw) == phone
    ]
    if len(owners) != 1:
        return None
    return db.query(models.User).filter(
        models.User.role == "patient", models.User.patient_id == owners[0]).first()


def _deliver(payload: dict) -> None:
    db = SessionLocal()
    try:
        patient = db.get(models.Patient, payload["patient_id"])
        phone = normalize_phone(patient.emergency_contact_phone) if patient else None
        if not phone or not sms_allowed(phone):
            return  # contact removed or changed to something we won't text since the scan
        first = (patient.full_name or "A patient").split()[0][:30]
        when = datetime.fromisoformat(payload["scanned_at"]).astimezone(_MYT).strftime("%d %b %H:%M")
        what = ("a scan of {}'s emergency card made without network was reported at {}"
                if payload.get("late") else "{}'s emergency card was scanned at {}").format(first, when)
        account = _registered_account(db, phone, patient.id)
        if account:
            notify(db, account.id, "contact_card_scanned", f"{first}'s emergency card was scanned",
                   body=f"{what[0].upper()}{what[1:]} (MYT). You are listed as their emergency contact.", urgent=True)
            db.commit()
            return
        try:
            sent = sms_service.send_sms(
                phone, f"CLARION: {what} (MYT). You are listed as their emergency contact.")
        except sms_service.SmsRejected as exc:
            logger.error("emergency-contact SMS for patient %s rejected for good: %s", patient.id, exc)
            raise jobs.PermanentFailure(str(exc))
        if not sent:
            raise RuntimeError("SMS not delivered")  # transient: the job queue retries it
    finally:
        db.close()


# Retry every 5 minutes, up to 20 times (~100 min), before giving up.
jobs.register(JOB_KIND, _deliver, max_attempts=20, retry_delay_seconds=300)
