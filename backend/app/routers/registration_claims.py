"""Web/phone sign-up that needs no app and no hospital-side email: a PENDING claim.

Anyone who knows an NRIC + name can file a claim (own email, own password); a claim grants
nothing. It becomes the account when it is verified: the claimant's emailed code matches the
email already on the record, or an IC photo scan passes, or staff approve it. Every other
pending claim for that NRIC is then rejected and its email flagged as likely spam/scam, and
flagged emails are refused on later sign-ups. See app/claims.py."""
import asyncio
import re
from datetime import datetime, timedelta, timezone

from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import auth, claims, models, schemas
from ..ai.nric_ocr import dob_from_ic_number, extract_nric_fields
from ..audit import log_access
from ..database import get_db
from ..rate_limit import limiter
from .auth_router import _resolve_patient_by_nric, _with_missing_profile_fields
from . import self_registration as sr

router = APIRouter(tags=["registration-claims"])

MAX_PENDING_PER_PATIENT = 10
_FLAGGED_ERROR = ("This email address has been flagged as a possible spam or scam source and can't be "
                  "used to register. Use a different email, or visit a registration counter.")
_BAD_CODE = "Invalid or expired verification code."


class ClaimStart(BaseModel):
    national_id: str
    full_name: str
    email: EmailStr


class ClaimVerify(BaseModel):
    """The password is chosen HERE, by whoever proves the inbox -- never at /start, or a stranger
    who knows the NRIC + name could overwrite it."""
    national_id: str
    email: EmailStr
    otp_code: str
    password: str

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return schemas._validate_password_length(v)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _claim(db: Session, patient, email: str):
    if not patient:
        return None
    return (db.query(models.RegistrationClaim)
            .filter(models.RegistrationClaim.patient_id == patient.id,
                    models.RegistrationClaim.email == claims.norm_email(email)).first())


def _session(user: models.User) -> dict:
    token = auth.create_access_token({"sub": user.id, "role": user.role}, password_changed_at=user.password_changed_at)
    return {"status": "approved",
            "session": schemas.Token(access_token=token, user=_with_missing_profile_fields(user)).model_dump(mode="json")}


@router.post("/auth/self-register/claim/start")
@limiter.limit("10/minute")
def claim_start(request: Request, payload: ClaimStart, db: Session = Depends(get_db)):
    name = " ".join((payload.full_name or "").upper().split())
    nric_digits = re.sub(r"\D", "", payload.national_id or "")
    patient = _resolve_patient_by_nric(db, payload.national_id)
    if not patient:
        # No hospital has this person: open a PROVISIONAL record so they can still sign up. Its
        # name and identity stay unproven until a claim is verified (IC photo scan or staff).
        dob = dob_from_ic_number(nric_digits)
        if not name or not dob:
            raise HTTPException(status_code=400, detail="Enter a valid 12-digit NRIC and your full name.")
        patient = models.Patient(full_name=name, date_of_birth=dob, national_id=nric_digits, provisional=True)
        db.add(patient)
        try:
            db.commit()
        except IntegrityError:  # someone created it a moment ago
            db.rollback()
            patient = _resolve_patient_by_nric(db, payload.national_id)
        log_access(db, patient.id, "system", None, "provisional_patient_created")
    elif not patient.provisional:
        dob_ok = dob_from_ic_number(nric_digits) == patient.date_of_birth
        if not (sr._names_reasonably_match(name, patient.full_name) and dob_ok):
            raise HTTPException(status_code=400, detail=sr._START_MISMATCH_ERROR)
    if db.query(models.User).filter(models.User.patient_id == patient.id).first():
        raise HTTPException(status_code=409, detail=sr._ACCOUNT_EXISTS_ERROR)  # registered and verified: reject
    email = claims.norm_email(payload.email)
    if claims.email_flagged(db, email):
        raise HTTPException(status_code=403, detail=_FLAGGED_ERROR)

    claim = _claim(db, patient, email)
    if claim is None:
        pending = (db.query(models.RegistrationClaim)
                   .filter_by(patient_id=patient.id, status="pending", email_verified=True).count())  # unverified ones cannot lock others out
        if pending >= MAX_PENDING_PER_PATIENT:
            raise HTTPException(status_code=429, detail="Too many pending registrations for this NRIC. "
                                                         "Please visit a registration counter.")
        claim = models.RegistrationClaim(patient_id=patient.id, email=email, otp_request_count=0, password_hash="", full_name=name)
    elif claim.status == "approved":
        raise HTTPException(status_code=409, detail=sr._ACCOUNT_EXISTS_ERROR)
    elif claim.status == "rejected":  # a decision is final; do not let a re-start revive it
        raise HTTPException(status_code=403, detail="This registration was rejected. Please visit a registration counter.")
    elif claim.email_verified:
        raise HTTPException(status_code=409, detail="This email is already confirmed for this NRIC and is waiting for verification.")

    now = _now()
    if not claim.otp_request_window_start or now - claim.otp_request_window_start > timedelta(minutes=auth.OTP_REQUEST_WINDOW_MINUTES):
        claim.otp_request_window_start, claim.otp_request_count = now, 0
    if (claim.otp_request_count or 0) >= auth.OTP_MAX_REQUESTS_PER_WINDOW:
        raise HTTPException(status_code=429, detail="Too many verification code requests. Try again later.")
    claim.otp_request_count = (claim.otp_request_count or 0) + 1
    code = auth.generate_otp_code()
    claim.status, claim.otp_attempt_count = "pending", 0
    claim.otp_code_hash, claim.otp_expires_at = auth.hash_otp_code(code), now + timedelta(minutes=auth.OTP_EXPIRY_MINUTES)
    db.add(claim)
    db.commit()
    sr.send_self_registration_otp_email(email, code, patient.full_name)
    log_access(db, patient.id, "system", None, "registration_claim_started")
    return {"status": "ok", "next_step": "verify_otp",
            "detail": "A verification code was sent to the email provided."}


@router.post("/auth/self-register/claim/verify-otp")
@limiter.limit("10/minute")
def claim_verify_otp(request: Request, payload: ClaimVerify, db: Session = Depends(get_db)):
    patient = _resolve_patient_by_nric(db, payload.national_id)
    claim = _claim(db, patient, payload.email)
    if not claim or claim.status != "pending" or not claim.otp_code_hash or not claim.otp_expires_at:
        raise HTTPException(status_code=400, detail=_BAD_CODE)
    if _now() > claim.otp_expires_at:
        claim.otp_code_hash = claim.otp_expires_at = None
        db.commit()
        raise HTTPException(status_code=400, detail=_BAD_CODE)
    if not auth.verify_otp_code(payload.otp_code, claim.otp_code_hash):
        claim.otp_attempt_count = (claim.otp_attempt_count or 0) + 1
        if claim.otp_attempt_count >= auth.OTP_MAX_VERIFY_ATTEMPTS:
            claim.otp_code_hash = claim.otp_expires_at = None
        db.commit()
        raise HTTPException(status_code=400, detail=_BAD_CODE)
    claim.email_verified, claim.otp_code_hash, claim.otp_expires_at = True, None, None
    claim.password_hash = auth.hash_password(payload.password)  # set by the person who proved the inbox
    db.commit()
    log_access(db, patient.id, "system", None, "registration_claim_email_verified")
    if claim.email == claims.norm_email(patient.email):  # the record's own inbox: identity proven
        user = claims.approve_claim(db, claim, actor="self_registration", actor_role="patient")
        if user:
            return _session(user)
        raise HTTPException(status_code=409, detail=sr._ACCOUNT_EXISTS_ERROR)
    return {"status": "pending", "photo_check": sr._photo_check_on(),
            "detail": "Email confirmed. Your registration is waiting to be verified."}


@router.post("/auth/self-register/claim/verify-photos")
@limiter.limit("10/minute")
async def claim_verify_photos(
    request: Request,
    national_id: str = Form(...),
    email: EmailStr = Form(...),
    front_image: UploadFile = File(...),
    back_image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Auto-verify a pending claim from photos of the IC. Same OCR + match rules as the app flow."""
    if not sr._photo_check_on():
        raise HTTPException(status_code=400, detail="Photo verification is not available. Ask the counter to verify you.")
    patient = _resolve_patient_by_nric(db, national_id)
    claim = _claim(db, patient, email)
    if not claim or claim.status != "pending" or not claim.email_verified:
        raise HTTPException(status_code=400, detail=sr._RESTART_REQUIRED_ERROR)
    used = sum(c.photo_attempts or 0 for c in db.query(models.RegistrationClaim).filter_by(patient_id=patient.id))
    if used >= sr.PHOTO_VERIFY_MAX_ATTEMPTS:  # per NRIC, not per email: fresh emails get no fresh quota
        return JSONResponse(status_code=403, content={
            "next_step": "manual_registration_required",
            "detail": "Automatic verification is locked. Please visit a registration counter with your IC."})
    front, back = await front_image.read(), await back_image.read()
    if max(len(front), len(back)) > sr.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    f, b = await asyncio.gather(
        run_in_threadpool(extract_nric_fields, front, front_image.content_type or "image/jpeg"),
        run_in_threadpool(extract_nric_fields, back, back_image.content_type or "image/jpeg"))
    # A provisional record has no trusted name: the IC must match what the claimant typed.
    subject = SimpleNamespace(national_id=patient.national_id, date_of_birth=patient.date_of_birth,
                              full_name=claim.full_name or patient.full_name) if patient.provisional else patient
    matched, message, _note = sr._evaluate_photo_verification(f, b, subject)
    if matched:
        user = claims.approve_claim(db, claim, actor="self_registration", actor_role="patient")
        if user:
            return _session(user)
        raise HTTPException(status_code=409, detail=sr._ACCOUNT_EXISTS_ERROR)
    claim.photo_attempts = (claim.photo_attempts or 0) + 1
    db.commit()
    return JSONResponse(status_code=400, content={
        "detail": message, "photo_attempts_remaining": max(0, sr.PHOTO_VERIFY_MAX_ATTEMPTS - used - 1)})


# ---- staff: see and decide pending claims (manual verification) -----------------------------
_STAFF = ("admin", "records_officer")


def _claim_or_404(db, patient_id, claim_id):
    c = db.get(models.RegistrationClaim, claim_id)
    if not c or c.patient_id != patient_id:
        raise HTTPException(status_code=404, detail="Claim not found")
    return c


@router.get("/auth/patients/{patient_id}/registration-claims")
def list_claims(patient_id: str, db: Session = Depends(get_db),
                current_user: models.User = Depends(auth.require_roles(*_STAFF))):
    if not db.get(models.Patient, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    rows = (db.query(models.RegistrationClaim).filter_by(patient_id=patient_id)
            .order_by(models.RegistrationClaim.created_at).all())
    log_access(db, patient_id, current_user.id, current_user.role, "registration_claims_listed",
               actor_facility=current_user.facility)
    return [{"id": c.id, "email": c.email, "email_verified": c.email_verified, "status": c.status,
             "created_at": c.created_at, "flagged": claims.email_flagged(db, c.email)} for c in rows]


@router.post("/auth/patients/{patient_id}/registration-claims/{claim_id}/approve")
def approve(patient_id: str, claim_id: str, db: Session = Depends(get_db),
            current_user: models.User = Depends(auth.require_roles(*_STAFF))):
    c = _claim_or_404(db, patient_id, claim_id)
    if c.status != "pending":
        raise HTTPException(status_code=409, detail="This claim is already decided.")
    if not claims.approve_claim(db, c, actor=current_user.id, actor_role=current_user.role,
                                actor_facility=current_user.facility):
        raise HTTPException(status_code=409, detail="An account already exists for this patient.")
    return {"status": "approved"}


@router.post("/auth/patients/{patient_id}/registration-claims/{claim_id}/reject")
def reject(patient_id: str, claim_id: str, db: Session = Depends(get_db),
           current_user: models.User = Depends(auth.require_roles(*_STAFF))):
    c = _claim_or_404(db, patient_id, claim_id)
    if c.status != "pending":
        raise HTTPException(status_code=409, detail="This claim is already decided.")
    patient = db.get(models.Patient, patient_id)
    claims.reject_claim(db, c, flag=c.email != claims.norm_email(patient.email), reason="rejected by staff")
    db.commit()
    log_access(db, patient_id, current_user.id, current_user.role, "registration_claim_rejected",
               detail=f"claim={c.id}", actor_facility=current_user.facility)
    return {"status": "rejected"}


@router.delete("/auth/flagged-emails/{email}")
def unflag(email: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_roles("admin"))):
    """Undo a wrong flag (e.g. a family member's shared email)."""
    row = db.get(models.FlaggedEmail, claims.norm_email(email))
    if not row:
        raise HTTPException(status_code=404, detail="Email is not flagged")
    db.delete(row)
    db.commit()
    log_access(db, row.patient_id, current_user.id, current_user.role, "flagged_email_removed",
               actor_facility=current_user.facility)
    return {"status": "ok"}
