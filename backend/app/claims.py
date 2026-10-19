"""Pending registration claims: who becomes the account, and who gets flagged.

Several people can claim one patient record (own email + password, no access). The first
claim to be verified (record's own inbox, IC photo scan, or staff) becomes the account; the
rest are rejected and any email that had proven its inbox is flagged as likely spam/scam."""
import logging
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import account_lock, models
from .audit import log_access
from .email_service import send_account_created_notice

logger = logging.getLogger("clarion.claims")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


def email_flagged(db: Session, email: str) -> bool:
    return db.get(models.FlaggedEmail, norm_email(email)) is not None


def flag_email(db: Session, email: str, patient_id: str, reason: str) -> None:
    email = norm_email(email)
    if not db.get(models.FlaggedEmail, email):
        db.add(models.FlaggedEmail(email=email, patient_id=patient_id, reason=reason[:255]))


def reject_claim(db: Session, claim: models.RegistrationClaim, *, flag: bool, reason: str) -> None:
    """Caller commits. Only an email that proved its inbox is flagged: flagging an unverified
    address would let a stranger get a victim's real email blacklisted."""
    claim.status, claim.decided_at = "rejected", _now()
    claim.otp_code_hash = None
    claim.password_hash = ""  # a stranger's password hash has no reason to stay
    if flag and claim.email_verified:
        flag_email(db, claim.email, claim.patient_id, reason)


def reject_other_claims(db: Session, patient: models.Patient, *, keep_claim_id: str | None,
                        winner_email: str | None, flag: bool = True) -> int:
    """Reject every other pending claim for this patient; flag their (verified) emails unless
    the address is the winner's or the one on the record. Commits. Returns how many."""
    safe = {norm_email(winner_email), norm_email(patient.email)} - {""}
    rows = (db.query(models.RegistrationClaim)
            .filter(models.RegistrationClaim.patient_id == patient.id,
                    models.RegistrationClaim.status == "pending",
                    models.RegistrationClaim.id != (keep_claim_id or ""))
            .all())
    for c in rows:
        reject_claim(db, c, flag=flag and c.email not in safe, reason="lost to a verified account for this NRIC")
    db.commit()
    return len(rows)


def approve_claim(db: Session, claim: models.RegistrationClaim, *, actor: str,
                  actor_role: str | None = None, actor_facility: str | None = None) -> "models.User | None":
    """Make this claim the patient's account. None if it lost the race or an account exists.
    The placeholder login email is unique per patient, so two simultaneous approvals cannot both
    create a User (the loser gets IntegrityError -> None)."""
    patient = db.get(models.Patient, claim.patient_id)
    if patient is None or db.query(models.User).filter(models.User.patient_id == patient.id).first():
        return None
    won = (db.query(models.RegistrationClaim)
           .filter(models.RegistrationClaim.id == claim.id, models.RegistrationClaim.status == "pending")
           .update({"status": "approved", "decided_at": _now()}, synchronize_session=False))
    if won != 1:
        db.rollback()
        return None
    user = models.User(
        email=f"patient-{patient.id}@clarion.local",  # patients sign in by NRIC; placeholder keeps NOT NULL/unique
        hashed_password=claim.password_hash, full_name=patient.full_name, role="patient",
        patient_id=patient.id, must_change_password=False, self_registered_at=_now(),
    )
    if patient.provisional:  # identity now proven: the verified claimant's name becomes the record's
        patient.full_name = claim.full_name or patient.full_name
        patient.provisional = False
        user.full_name = patient.full_name
        db.add(patient)
    db.add(user)
    if not patient.email and claim.email_verified:
        patient.email = claim.email
        db.add(patient)
    claim.password_hash = ""  # the live hash now belongs to the User
    try:
        db.commit()
    except IntegrityError:  # the placeholder email is unique per patient: a concurrent approval won
        db.rollback()
        return None
    db.refresh(user)
    reject_other_claims(db, patient, keep_claim_id=claim.id, winner_email=claim.email)
    log_access(db, patient.id, actor=actor, actor_role=actor_role, action="registration_claim_approved",
               detail=f"claim={claim.id}", actor_facility=actor_facility)
    link = account_lock.lock_url(user)
    if patient.email and link:
        try:
            send_account_created_notice(patient.email, patient.full_name, link)
        except Exception:  # noqa: BLE001 -- a notice must never break registration
            logger.exception("account-created notice failed")
    return user
