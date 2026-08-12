import base64
import io
import secrets
from datetime import datetime, timedelta

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access

router = APIRouter(prefix="/emergency", tags=["emergency"])


def _render_qr_base64(card_reference: str) -> str:
    """Render the emergency QR PNG for a given card_reference and return it
    as a `data:image/png;base64,...` string.

    The QR content is fully deterministic (`MEDIBRIDGE-EMERGENCY:{card_reference}`),
    so this can be called as many times as needed — nothing about the image
    itself is ever persisted, only the card_reference it's derived from."""
    qr_payload = f"MEDIBRIDGE-EMERGENCY:{card_reference}"
    img = qrcode.make(qr_payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{qr_base64}"


def _scoped_fields(patient: models.Patient, scope: set) -> dict:
    """Shared by /emergency/scan and /emergency/nfc/scan so both a QR-code
    scan and an NFC tap return exactly the same shape for the same scope."""
    result = {"full_name": patient.full_name, "date_of_birth": patient.date_of_birth}

    if "blood_type" in scope:
        result["blood_type"] = patient.blood_type
    if "allergies" in scope:
        result["allergies"] = [
            {"substance": a.substance, "severity": a.severity, "reaction": a.reaction}
            for a in patient.allergies if a.critical_for_emergency
        ]
    if "medications" in scope:
        result["medications"] = [
            m.drug_name for m in patient.medications if m.active and m.critical_for_emergency
        ]
    if "conditions" in scope:
        result["conditions"] = [
            c.name for c in patient.conditions if c.critical_for_emergency
        ]
    return result


@router.post("/issue")
def issue_emergency_card(
    payload: schemas.EmergencyProfileRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Called from the patient app (or a guardian acting for a senior citizen)
    to (re)issue their emergency QR / physical card.

    IMPORTANT design point for your demo pitch: the QR code does NOT encode
    medical data. It encodes only a `card_reference` — a pointer. Every scan
    mints a fresh, short-lived token via /emergency/scan. This is what
    prevents a lost card or a screenshot of the QR from leaking a static
    data payload.

    A patient is only ever meant to have **one live QR card** at a time —
    generating a new one automatically revokes any previous, still-valid
    QR grants for this patient first (registered NFC physical cards are
    untouched; those are a separate, admin-managed medium — see
    /emergency/nfc/register). The count of auto-revoked cards is returned
    as `previous_cards_revoked` so the client can tell the user what
    happened, instead of silently leaving old QR codes scannable.
    """
    if current_user.role == "patient" and current_user.patient_id != payload.patient_id:
        raise HTTPException(status_code=403, detail="Cannot issue a card for another patient")

    previous = (
        db.query(models.EmergencyToken)
        .filter(
            models.EmergencyToken.patient_id == payload.patient_id,
            models.EmergencyToken.card_reference.isnot(None),
            models.EmergencyToken.revoked.is_(False),
            models.EmergencyToken.expires_at > datetime.utcnow(),
        )
        .all()
    )
    for grant in previous:
        grant.revoked = True

    card_reference = secrets.token_urlsafe(8)
    token_value = secrets.token_urlsafe(32)

    grant = models.EmergencyToken(
        patient_id=payload.patient_id,
        token=token_value,
        card_reference=card_reference,
        scope=payload.scope,
        expires_at=datetime.utcnow() + timedelta(minutes=payload.valid_minutes),
    )
    db.add(grant)
    db.commit()

    # QR encodes only the card_reference — the pointer, not the data.
    qr_code_base64 = _render_qr_base64(card_reference)

    log_access(
        db, payload.patient_id, current_user.id, current_user.role, "issue_emergency_card",
        detail=f"auto_revoked={len(previous)}",
    )

    return {
        "card_reference": card_reference,
        "qr_code_base64": qr_code_base64,
        "scope": payload.scope,
        "grant_valid_until": grant.expires_at.isoformat(),
        "previous_cards_revoked": len(previous),
        "note": "Printable on a physical card for senior-citizen / offline use. "
                "The printed card should also show blood type + top allergy in "
                "plain text as a fallback if no scanner is available.",
    }


@router.post("/scan")
def scan_emergency_card(payload: schemas.EmergencyScanRequest, db: Session = Depends(get_db)):
    """
    Called by an emergency responder's device after scanning the QR or
    keying in the physical card's printed reference. No login required —
    this is the whole point — but every scan is logged, and only the
    pre-approved scope is ever returned.
    """
    grant = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.card_reference == payload.card_reference)
        .first()
    )
    if not grant or grant.revoked or grant.expires_at < datetime.utcnow():
        raise HTTPException(status_code=404, detail="Invalid or expired emergency card")

    patient = db.query(models.Patient).filter(models.Patient.id == grant.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    scope = set(grant.scope or [])
    result = _scoped_fields(patient, scope)

    log_access(
        db, patient.id,
        actor=f"emergency_responder:{payload.responder_name or 'unidentified'}",
        actor_role="emergency_responder",
        action="emergency_access",
        fields=list(scope),
        detail=f"org={payload.responder_org}",
    )

    return result


@router.post("/revoke/{card_reference}")
def revoke_card(
    card_reference: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    grant = db.query(models.EmergencyToken).filter(models.EmergencyToken.card_reference == card_reference).first()
    if not grant:
        raise HTTPException(status_code=404, detail="Card not found")
    if current_user.role == "patient" and current_user.patient_id != grant.patient_id:
        raise HTTPException(status_code=403, detail="Not your card")
    grant.revoked = True
    db.commit()
    return {"status": "revoked"}


@router.get("/current/{patient_id}")
def get_current_card_status(
    patient_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """
    Read-only status check: "does this patient currently have a live QR
    card, and if so what's its reference/expiry?" — with no side effects
    (doesn't issue anything, doesn't log an access).

    When active, the response also includes `qr_code_base64` — the QR image
    is never stored anywhere; it's cheaply re-rendered on every call from
    the grant's `card_reference` via `_render_qr_base64`, since the image
    content is fully deterministic (`MEDIBRIDGE-EMERGENCY:{card_reference}`).
    This is what lets a viewer that *didn't* itself issue the card actually
    display it, not just know it exists.

    This exists so a viewer that *didn't* itself issue the card (e.g. the
    web console, or the same patient reopening the app) can find out a
    card was issued/revoked/replaced **elsewhere** (the mobile app, a
    different browser tab, etc.) without needing to click "Issue" again.
    Poll this endpoint for a "reflects changes made elsewhere" experience
    — see web/src/pages/PatientDetail.jsx.
    """
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's card status")

    grant = (
        db.query(models.EmergencyToken)
        .filter(
            models.EmergencyToken.patient_id == patient_id,
            models.EmergencyToken.card_reference.isnot(None),
            models.EmergencyToken.revoked.is_(False),
            models.EmergencyToken.expires_at > datetime.utcnow(),
        )
        .order_by(models.EmergencyToken.created_at.desc())
        .first()
    )
    if not grant:
        return {"active": False}

    return {
        "active": True,
        "card_reference": grant.card_reference,
        "qr_code_base64": _render_qr_base64(grant.card_reference),
        "scope": grant.scope,
        "grant_valid_until": grant.expires_at.isoformat(),
    }


# ---------- NFC physical cards ----------
# For senior citizens / anyone without a smartphone: a hospital-issued
# physical NFC card (or a wristband/sticker) can be tapped against a
# responder's NFC-capable phone instead of scanning a QR code. Registration
# is staff-only (done from the web console) — patients cannot self-register
# a physical card, mirroring how a real hospital would issue one.

@router.post("/nfc/register")
def register_nfc_card(
    payload: schemas.NfcRegisterRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Create or update the grant for a physical NFC card's UID. Re-running
    this with the same `nfc_uid` (e.g. to fix a typo'd scope, or renew an
    expiring card) updates the existing grant in place instead of leaving
    an orphaned duplicate — there is exactly one grant per physical card."""
    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    existing = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.nfc_uid == payload.nfc_uid)
        .first()
    )
    if existing and existing.patient_id != payload.patient_id:
        raise HTTPException(
            status_code=409,
            detail="This NFC card is already registered to a different patient. "
                   "Revoke it first if you're re-issuing the physical card.",
        )

    if existing:
        existing.scope = payload.scope
        existing.expires_at = datetime.utcnow() + timedelta(minutes=payload.valid_minutes)
        existing.revoked = False
        existing.registered_by = current_user.id
        grant = existing
        action = "update_nfc_card"
    else:
        grant = models.EmergencyToken(
            patient_id=payload.patient_id,
            token=secrets.token_urlsafe(32),
            nfc_uid=payload.nfc_uid,
            scope=payload.scope,
            expires_at=datetime.utcnow() + timedelta(minutes=payload.valid_minutes),
            registered_by=current_user.id,
        )
        db.add(grant)
        action = "register_nfc_card"

    db.commit()
    db.refresh(grant)

    log_access(db, payload.patient_id, current_user.id, current_user.role, action, detail=payload.nfc_uid)

    return {
        "nfc_uid": grant.nfc_uid,
        "scope": grant.scope,
        "grant_valid_until": grant.expires_at.isoformat(),
        "revoked": grant.revoked,
    }


@router.post("/nfc/scan")
def scan_nfc_card(payload: schemas.NfcScanRequest, db: Session = Depends(get_db)):
    """No login required — same design as /emergency/scan, but keyed by the
    physical card's NFC UID instead of a QR-encoded card_reference."""
    grant = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.nfc_uid == payload.nfc_uid)
        .first()
    )
    if not grant or grant.revoked or grant.expires_at < datetime.utcnow():
        raise HTTPException(status_code=404, detail="This NFC card is not registered, revoked, or expired")

    patient = db.query(models.Patient).filter(models.Patient.id == grant.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    scope = set(grant.scope or [])
    result = _scoped_fields(patient, scope)

    log_access(
        db, patient.id,
        actor=f"emergency_responder:{payload.responder_name or 'unidentified'}",
        actor_role="emergency_responder",
        action="emergency_access_nfc",
        fields=list(scope),
        detail=f"org={payload.responder_org}",
    )

    return result


@router.post("/nfc/revoke/{nfc_uid}")
def revoke_nfc_card(
    nfc_uid: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    grant = db.query(models.EmergencyToken).filter(models.EmergencyToken.nfc_uid == nfc_uid).first()
    if not grant:
        raise HTTPException(status_code=404, detail="NFC card not found")
    grant.revoked = True
    db.commit()
    log_access(db, grant.patient_id, current_user.id, current_user.role, "revoke_nfc_card", detail=nfc_uid)
    return {"status": "revoked"}


@router.get("/nfc/{patient_id}")
def list_nfc_cards(
    patient_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Staff can see every registered card; a patient can see (read-only)
    the cards registered to their own record."""
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's NFC cards")

    grants = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.patient_id == patient_id, models.EmergencyToken.nfc_uid.isnot(None))
        .order_by(models.EmergencyToken.created_at.desc())
        .all()
    )
    return [
        {
            "nfc_uid": g.nfc_uid,
            "scope": g.scope,
            "grant_valid_until": g.expires_at.isoformat(),
            "revoked": g.revoked,
            "registered_by": g.registered_by,
            "created_at": g.created_at.isoformat(),
        }
        for g in grants
    ]
