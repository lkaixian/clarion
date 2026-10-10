import base64
import io
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import NamedTuple

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas, auth, tag_crypto
from ..database import get_db
from ..audit import log_access
from ..rate_limit import limiter
from ..clinical_access import _patient_present_at

router = APIRouter(prefix="/emergency", tags=["emergency"])


def _require_patient_present_for_staff(db: Session, current_user: models.User, patient_id: str) -> None:
    """Facility scoping (Security Audit finding H1): a staff caller (not the
    patient themself -- their own self-service issue/revoke/view is
    location-independent by design, e.g. from home via the mobile app) may
    only act on a patient's emergency card when that patient is CURRENTLY
    present at the staff member's own facility -- an active admission or an
    open today's queue ticket, the SAME `_patient_present_at` rule
    routers/patients.py's cross-facility clinical-record immutability guard
    uses. No admin override, matching that guard's own precedent exactly
    (need-to-know, not role seniority) -- see
    `_guard_cross_facility_amend`'s docstring in patients.py."""
    if current_user.role == "patient":
        return
    if not current_user.facility or not _patient_present_at(db, patient_id, current_user.facility):
        raise HTTPException(
            status_code=403,
            detail="This patient is not currently checked in at your facility.",
        )


def _age_from_dob(dob: "str | None", *, today: "date | None" = None) -> "int | None":
    """Whole years from an ISO `YYYY-MM-DD` date-of-birth string (the format
    this app stores). Security Audit M7b: the unauthenticated emergency scan
    returns age, not the full DOB -- age covers the clinical need
    (weight/dose banding, "is this a child") without handing an anonymous
    caller an exact birthdate. Returns None for a missing/unparseable/future
    value (older/incomplete record) -- the scan screen shows that gracefully.
    `today` is injectable for deterministic tests."""
    if not dob:
        return None
    ref = today or datetime.now(timezone.utc).replace(tzinfo=None).date()
    try:
        year, month, day = (int(p) for p in str(dob)[:10].split("-"))
        age = ref.year - year - ((ref.month, ref.day) < (month, day))
    except (ValueError, TypeError):
        return None
    return age if 0 <= age <= 150 else None  # reject a future / garbage DOB


def _render_qr_base64(card_reference: str) -> str:
    """Render the emergency QR PNG for a given card_reference and return it
    as a `data:image/png;base64,...` string.

    The QR content is fully deterministic (`CLARION-EMERGENCY:{card_reference}`),
    so this can be called as many times as needed — nothing about the image
    itself is ever persisted, only the card_reference it's derived from."""
    qr_payload = f"CLARION-EMERGENCY:{card_reference}"
    img = qrcode.make(qr_payload)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_base64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{qr_base64}"


# Security Audit M7c: a legitimate emergency is a handful of scans of one
# card; many scans of the SAME card in a short window is the signature of a
# cloned/dumped card being probed. We can't block it (life-safety), so we
# make it conspicuous.
_NFC_SCAN_ANOMALY_WINDOW = timedelta(hours=1)
_NFC_SCAN_ANOMALY_THRESHOLD = 8


def _flag_nfc_scan_anomaly_if_needed(
    db: Session, nfc_hash: str, patient_id: "str | None"
) -> None:
    """M7c: once per hour per card, if this card's scan count over the last
    hour crosses the threshold, drop one `emergency_card_scan_anomaly` audit
    row. Every NFC scan carries `nfc_hash=<hash16>` in its detail so this
    can find them -- it's an HMAC prefix, never a usable key.

    Runs on the (life-safety) scan path, so both queries are `.count()`
    (no row materialisation) and windowed on the indexed `timestamp`
    column."""
    since = datetime.now(timezone.utc).replace(tzinfo=None) - _NFC_SCAN_ANOMALY_WINDOW
    marker = f"nfc_hash={nfc_hash[:16]}"
    windowed = db.query(models.AuditLog).filter(
        models.AuditLog.timestamp >= since,
        models.AuditLog.detail.like(f"%{marker}%"),
    )
    scans = windowed.filter(
        models.AuditLog.action.in_(("emergency_access_nfc", "emergency_access_failed"))
    ).count()
    if scans < _NFC_SCAN_ANOMALY_THRESHOLD:
        return
    if windowed.filter(models.AuditLog.action == "emergency_card_scan_anomaly").count():
        return  # already flagged this card within the window -- debounce
    log_access(
        db, patient_id,
        actor="system", actor_role="system",
        action="emergency_card_scan_anomaly",
        # The `nfc_hash=` marker below is load-bearing: the debounce query
        # above finds this row by the same `marker` LIKE. Keep it as the
        # detail prefix.
        detail=f"{marker} count={scans} window=1h -- possible cloned/dumped card",
    )


class _ResponderAudit(NamedTuple):
    actor: str
    actor_role: str
    actor_facility: "str | None"
    detail_suffix: str


def _responder_audit(current_user: "models.User | None", payload) -> _ResponderAudit:
    """Security Audit M6: the emergency scan is unauthenticated by design, so
    `responder_name` / `responder_org` in the request body are self-asserted
    and unverifiable.

    - **No/invalid token (the common field case):** audited EXACTLY as
      before -- `actor="emergency_responder:<name>"`,
      `actor_role="emergency_responder"`. That role value already *means*
      "self-asserted, unverified" and every existing audit-trail consumer
      (web `PatientDetail.jsx`, `mobile_flutter/.../audit_log_screen.dart`)
      keys on it; a reviewer filtering `actor_role == "emergency_responder"`
      gets precisely the unverified accesses.
    - **Valid staff bearer token:** bind the REAL identity -- `actor` is the
      user id, `actor_role` their real role, `actor_facility` recorded, and
      `detail` is prefixed `verified` with the typed-in name kept as
      `self_asserted=<name>`. The audit-trail UIs already resolve a real
      user id to a name, so these rows render as an attributed staff access,
      not an anonymous responder.

    Audit *action* strings are untouched (`emergency_access` / `_nfc` /
    `_failed` / `_sharing_bypass`) -- audit_log_screen.dart switches on the
    exact action for severity/icons. Unauthenticated flow otherwise
    unchanged: no new field, no 401, identical data returned."""
    org = getattr(payload, "responder_org", None)
    said = getattr(payload, "responder_name", None) or None
    if current_user is not None:
        return _ResponderAudit(
            actor=current_user.id,
            actor_role=current_user.role,
            actor_facility=current_user.facility,
            detail_suffix=f"verified org={org}" + (f" self_asserted={said}" if said else ""),
        )
    return _ResponderAudit(
        actor=f"emergency_responder:{said or 'unidentified'}",
        actor_role="emergency_responder",
        actor_facility=None,
        detail_suffix=f"org={org}",
    )


def _audit_sharing_bypass_if_any(
    db: Session, patient: models.Patient, ident: _ResponderAudit
) -> None:
    """The unauthenticated emergency-token scan is a life-safety override: it
    ALWAYS ignores HospitalSetting.records_shared_publicly (unlike the
    authenticated patient-record path in routers/patients.py, which filters
    out records authored by a facility that opted out of cross-hospital
    sharing). This never routes through the filtered _serialize_patient in
    the first place -- it builds its own scoped payload via _scoped_fields --
    but when a facility that authored any of this patient's data HAS opted
    out, we still drop an audit line making the bypass explicit and
    reviewable in the patient's trail."""
    restricted = {
        f for (f,) in (
            db.query(models.HospitalSetting.facility_name)
            .filter(models.HospitalSetting.records_shared_publicly.is_(False))
            .all()
        ) if f
    }
    if not restricted:
        return
    authored = (
        {c.authored_by_facility for c in patient.conditions}
        | {m.prescribed_by_facility for m in patient.medications}
        | {a.authored_by_facility for a in patient.allergies}
        | {e.facility_name for e in patient.encounters}
    )
    bypassed = sorted(f for f in authored if f in restricted)
    if not bypassed:
        return
    log_access(
        db, patient.id,
        actor=ident.actor,
        actor_role=ident.actor_role,
        action="emergency_access_sharing_bypass",
        detail=f"life-safety override: showed records from opted-out facilities {bypassed}",
        actor_facility=ident.actor_facility,
    )


def _scoped_fields(
    patient: models.Patient,
    scope: set,
    resolved_condition_ids: "set | frozenset" = frozenset(),
    discontinued_medication_ids: "set | frozenset" = frozenset(),
) -> dict:
    """Shared by /emergency/scan and /emergency/nfc/scan so both a QR-code
    scan and an NFC tap return exactly the same shape for the same scope.

    Only `critical_for_emergency` items are ever included per category
    (a deliberate "show less, but trustworthy" tradeoff for an
    unauthenticated, first-responder-facing endpoint) -- `medications` is
    additionally filtered to `active` items only, same as elsewhere in this
    API. `medications` entries are `{"drug_name", "dosage", "frequency"}`
    objects, not bare strings: a responder seeing "Warfarin" with no dose
    is meaningfully less useful (and more dangerous to act on) than seeing
    "Warfarin -- 5mg, once daily". `dosage`/`frequency` are nullable columns,
    so either may come through as `null` for an older/incomplete record --
    that's expected, not an error.

    `omitted_non_critical` surfaces a count of items that were filtered out
    per category (only for categories actually in `scope`, and only when
    at least one item was filtered) -- without this, a responder has no way
    to tell "this patient truly has nothing else on file" apart from "there
    IS more, it's just not flagged critical for this view", which is a real
    safety gap for an emergency-facing screen."""
    # M7b: age, not the full date_of_birth -- see _age_from_dob.
    result = {"full_name": patient.full_name, "age": _age_from_dob(patient.date_of_birth)}
    omitted_non_critical = {}

    # A `resolved` condition annotation / `discontinued` medication
    # annotation (models.ClinicalRecordAnnotation) drops that row from the
    # emergency view entirely -- it's neither shown nor counted as
    # "non-critical omitted". The existing critical_for_emergency / active
    # filters still apply on top.
    conditions = [c for c in patient.conditions if c.id not in resolved_condition_ids]
    medications = [m for m in patient.medications if m.id not in discontinued_medication_ids]

    if "blood_type" in scope:
        result["blood_type"] = patient.blood_type
    if "allergies" in scope:
        result["allergies"] = [
            {"substance": a.substance, "severity": a.severity, "reaction": a.reaction}
            for a in patient.allergies if a.critical_for_emergency
        ]
        non_critical_count = sum(1 for a in patient.allergies if not a.critical_for_emergency)
        if non_critical_count:
            omitted_non_critical["allergies"] = non_critical_count
    if "medications" in scope:
        result["medications"] = [
            {"drug_name": m.drug_name, "dosage": m.dosage, "frequency": m.frequency}
            for m in medications if m.active and m.critical_for_emergency
        ]
        non_critical_count = sum(
            1 for m in medications if m.active and not m.critical_for_emergency
        )
        if non_critical_count:
            omitted_non_critical["medications"] = non_critical_count
    if "conditions" in scope:
        result["conditions"] = [
            c.name for c in conditions if c.critical_for_emergency
        ]
        non_critical_count = sum(1 for c in conditions if not c.critical_for_emergency)
        if non_critical_count:
            omitted_non_critical["conditions"] = non_critical_count

    result["omitted_non_critical"] = omitted_non_critical
    return result


# Conservative default: fits an NTAG213 (144B usable) several times over
# and leaves headroom under an NTAG215 (504B) for the NDEF record's own
# type/length overhead -- register_nfc_card lets the caller override this
# with the physical tag's real capacity once it's actually been tapped.
_TAG_TEXT_MAX_BYTES_DEFAULT = 128


def _build_compact_tag_text(patient, scope: set, resolved_cond_ids, discontinued_med_ids,
                             max_bytes: int = _TAG_TEXT_MAX_BYTES_DEFAULT) -> "tuple[str, bool]":
    """Ultra-compact plaintext for writing DIRECTLY onto a physical NFC
    tag's own NDEF memory -- readable by ANY standard NFC reader (even a
    generic phone with no CLARION app installed), with ZERO network,
    app, or server dependency. This is the true "the entire backend is
    unreachable, not just a WAN link" fallback the QR/NFC *pointer* model
    (_scoped_fields, looked up server-side by UID/reference) can't cover
    on its own. Reuses _scoped_fields rather than re-deriving "what's
    critical" a second way, so the two can't drift apart.

    Fixed truncation priority when the tag can't fit everything (most
    life-threatening-to-miss first): blood type, then allergies, then
    active medications, then conditions. A responder who at minimum
    avoids the wrong blood product and a known severe allergic reaction
    has covered the two highest-stakes mistakes even if nothing else
    fits on a small tag. Returns (text, truncated) -- truncated is True
    if ANY item had to be dropped to fit `max_bytes`."""
    fields = _scoped_fields(patient, scope, resolved_cond_ids, discontinued_med_ids)
    parts: list = []
    truncated = False

    def _sanitize(text: str) -> str:
        # `|` is this format's field separator with no escaping -- free-text
        # clinical fields (substance/drug name/condition) could in principle
        # contain one, which would otherwise silently corrupt the parse on
        # the reading side (mobile_flutter's fromCompactTagText). Strip it;
        # losing a literal pipe character from a name is a far smaller harm
        # than misattributing which allergy/medication a value belongs to.
        return text.replace("|", "/")

    def _try_add(label: str, text: str) -> bool:
        nonlocal truncated
        text = _sanitize(text)
        joined = "|".join(parts + [f"{label}:{text}"])
        if len(joined.encode("utf-8")) > max_bytes:
            truncated = True
            return False
        parts.append(f"{label}:{text}")
        return True

    if fields.get("blood_type"):
        _try_add("BT", fields["blood_type"])
    for a in fields.get("allergies", []):
        if not _try_add("AL", f"{a['substance']}({a['severity']})"):
            break
    for m in fields.get("medications", []):
        dose = f" {m['dosage']}" if m.get("dosage") else ""
        if not _try_add("MED", f"{m['drug_name']}{dose}"):
            break
    for c in fields.get("conditions", []):
        if not _try_add("COND", c):
            break

    return "|".join(parts), truncated


def _resolved_discontinued_ids(db: Session, patient_id: str) -> "tuple[set, set]":
    """(resolved_condition_ids, discontinued_medication_ids) from the
    patient's append-only ClinicalRecordAnnotation rows -- threaded into
    _scoped_fields so a resolved condition / discontinued med drops out of
    the emergency view WITHOUT the underlying row ever being mutated.

    SAFETY GATE: only an annotation authored by the SAME facility that
    recorded the target row suppresses it here. Anyone (admin/records_officer/
    clinician at any facility) can file a `resolved`/`discontinued`
    annotation, and the normal record view honours it via
    `effective_status`/`effective_active` -- but a random other-facility
    opinion must NOT silently remove a `critical_for_emergency` condition or
    an active drug from the unauthenticated first-responder card. Only the
    authoritative source (the recording facility) discontinuing its own
    entry does that. Legacy rows with a NULL author are never suppressed
    (nothing can match), which is the safe default."""
    ann_rows = (
        db.query(models.ClinicalRecordAnnotation)
        .filter(
            models.ClinicalRecordAnnotation.patient_id == patient_id,
            models.ClinicalRecordAnnotation.kind.in_(("resolved", "discontinued")),
        )
        .all()
    )
    if not ann_rows:
        return set(), set()

    cond_author = {
        c.id: c.authored_by_facility
        for c in db.query(models.Condition).filter(models.Condition.patient_id == patient_id).all()
    }
    med_author = {
        m.id: m.recorded_by_facility
        for m in db.query(models.MedicationStatement).filter(models.MedicationStatement.patient_id == patient_id).all()
    }

    resolved_conditions: set = set()
    discontinued_meds: set = set()
    for row in ann_rows:
        if row.kind == "resolved":
            author = cond_author.get(row.target_id)
            if author and row.facility_name == author:
                resolved_conditions.add(row.target_id)
        elif row.kind == "discontinued":
            author = med_author.get(row.target_id)
            if author and row.facility_name == author:
                discontinued_meds.add(row.target_id)
    return resolved_conditions, discontinued_meds


@router.post("/issue")
def issue_emergency_card(
    payload: schemas.EmergencyProfileRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_page_access("patients")),
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
    _require_patient_present_for_staff(db, current_user, payload.patient_id)

    previous = (
        db.query(models.EmergencyToken)
        .filter(
            models.EmergencyToken.patient_id == payload.patient_id,
            models.EmergencyToken.card_reference.isnot(None),
            models.EmergencyToken.revoked.is_(False),
            models.EmergencyToken.expires_at > datetime.now(timezone.utc).replace(tzinfo=None),
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
        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=payload.valid_minutes),
    )
    db.add(grant)
    db.commit()

    # QR encodes only the card_reference — the pointer, not the data.
    qr_code_base64 = _render_qr_base64(card_reference)

    log_access(
        db, payload.patient_id, current_user.id, current_user.role, "issue_emergency_card",
        detail=f"auto_revoked={len(previous)}", actor_facility=current_user.facility,
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
@limiter.limit("10/minute")  # per-IP -- unauthenticated by design, so this is
# the only thing standing between a legitimate fumbled scan and a
# card_reference brute-force loop. Generous enough for a real responder
# mistyping/rescanning a few times, tight enough to make guessing
# infeasible (see also the failed-scan audit-log entries below).
def scan_emergency_card(
    request: Request,
    payload: schemas.EmergencyScanRequest,
    db: Session = Depends(get_db),
    current_user: "models.User | None" = Depends(auth.get_optional_current_user),
):
    """
    Called by an emergency responder's device after scanning the QR or
    keying in the physical card's printed reference. No login required —
    this is the whole point — but every scan is logged, and only the
    pre-approved scope is ever returned. If the caller happens to be a
    logged-in staff member, their real identity is bound to the audit
    entry (M6); otherwise the typed-in responder name is recorded but
    flagged unverified.
    """
    ident = _responder_audit(current_user, payload)
    grant = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.card_reference == payload.card_reference)
        .first()
    )
    if not grant or grant.revoked or grant.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        # Failed scan (invalid/expired/revoked card_reference) -- no
        # patient_id available since the lookup itself failed
        # (AuditLog.patient_id is nullable for exactly this reason). Only
        # successful scans used to leave a trace here; a brute-force probe
        # against card_reference values (now also rate-limited above) was
        # previously invisible in the audit log.
        log_access(
            db, None,
            actor=ident.actor, actor_role=ident.actor_role,
            action="emergency_access_failed",
            detail=f"card_reference={payload.card_reference} {ident.detail_suffix}",
            actor_facility=ident.actor_facility,
        )
        raise HTTPException(status_code=404, detail="Invalid or expired emergency card")

    patient = db.query(models.Patient).filter(models.Patient.id == grant.patient_id).first()
    if not patient:
        log_access(
            db, None,
            actor=ident.actor, actor_role=ident.actor_role,
            action="emergency_access_failed",
            detail=f"card_reference={payload.card_reference} {ident.detail_suffix} (grant found, patient missing)",
            actor_facility=ident.actor_facility,
        )
        raise HTTPException(status_code=404, detail="Patient not found")

    scope = set(grant.scope or [])
    resolved_cond_ids, discontinued_med_ids = _resolved_discontinued_ids(db, patient.id)
    result = _scoped_fields(patient, scope, resolved_cond_ids, discontinued_med_ids)

    log_access(
        db, patient.id,
        actor=ident.actor, actor_role=ident.actor_role,
        action="emergency_access",
        fields=list(scope),
        detail=ident.detail_suffix,
        actor_facility=ident.actor_facility,
    )
    _audit_sharing_bypass_if_any(db, patient, ident)

    return result


@router.post("/revoke/{card_reference}")
def revoke_card(
    card_reference: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_page_access("patients")),
):
    grant = db.query(models.EmergencyToken).filter(models.EmergencyToken.card_reference == card_reference).first()
    if not grant:
        raise HTTPException(status_code=404, detail="Card not found")
    if current_user.role == "patient" and current_user.patient_id != grant.patient_id:
        raise HTTPException(status_code=403, detail="Not your card")
    _require_patient_present_for_staff(db, current_user, grant.patient_id)
    grant.revoked = True
    db.commit()
    return {"status": "revoked"}


@router.get("/current/{patient_id}")
def get_current_card_status(
    patient_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_page_access("patients")),
):
    """
    Read-only status check: "does this patient currently have a live QR
    card, and if so what's its reference/expiry?" — with no side effects
    (doesn't issue anything, doesn't log an access).

    When active, the response also includes `qr_code_base64` — the QR image
    is never stored anywhere; it's cheaply re-rendered on every call from
    the grant's `card_reference` via `_render_qr_base64`, since the image
    content is fully deterministic (`CLARION-EMERGENCY:{card_reference}`).
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
    _require_patient_present_for_staff(db, current_user, patient_id)

    grant = (
        db.query(models.EmergencyToken)
        .filter(
            models.EmergencyToken.patient_id == patient_id,
            models.EmergencyToken.card_reference.isnot(None),
            models.EmergencyToken.revoked.is_(False),
            models.EmergencyToken.expires_at > datetime.now(timezone.utc).replace(tzinfo=None),
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

def _tag_security(tag_type: str) -> dict:
    """Every tag type works (the sealed record is plain NDEF); only the
    NTAG 424 DNA has the tamper-proof read counter that makes a dropped
    offline-read log detectable. Anything else gets an explicit warning for
    the web and mobile UIs to show."""
    has_counter = tag_type == "ntag424"
    return {
        "read_counter": has_counter,
        "warning": None if has_counter else (
            "This tag has no tamper-proof read counter (NTAG213/215/216 or "
            "unknown type). It works, but offline reads of it cannot be "
            "checked for missing entries -- use an NTAG 424 DNA where "
            "accountability matters."
        ),
    }


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

    # M7: the raw UID is hashed for storage + lookup and never persisted.
    uid_hash = auth.hash_nfc_uid(payload.nfc_uid)
    existing = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.nfc_uid == uid_hash)
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
        existing.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=payload.valid_minutes)
        existing.revoked = False
        existing.registered_by = current_user.id
        existing.nfc_uid_last4 = auth.nfc_uid_last4(payload.nfc_uid)
        grant = existing
        action = "update_nfc_card"
    else:
        grant = models.EmergencyToken(
            patient_id=payload.patient_id,
            token=secrets.token_urlsafe(32),
            nfc_uid=uid_hash,
            nfc_uid_last4=auth.nfc_uid_last4(payload.nfc_uid),
            scope=payload.scope,
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=payload.valid_minutes),
            registered_by=current_user.id,
        )
        db.add(grant)
        action = "register_nfc_card"

    db.commit()
    db.refresh(grant)

    # detail = the grant id + last4, never the raw UID (M7 / M8).
    log_access(db, payload.patient_id, current_user.id, current_user.role, action,
               detail=f"card_id={grant.id} last4={grant.nfc_uid_last4}",
               actor_facility=current_user.facility)

    # tag_text: the compact, write-it-directly-onto-the-physical-tag
    # fallback (see _build_compact_tag_text's own docstring for why this
    # exists alongside the UID pointer above) -- computed with the SAME
    # scope just granted, so the tag never carries more than the patient
    # already consented to share via this card's pointer half. The
    # registering app is expected to write this into an NDEF text record
    # on the same physical tag right after this call returns.
    resolved_cond_ids, discontinued_med_ids = _resolved_discontinued_ids(db, payload.patient_id)
    max_bytes = payload.tag_max_bytes or _TAG_TEXT_MAX_BYTES_DEFAULT
    tag_text, tag_text_truncated = _build_compact_tag_text(
        patient, set(payload.scope or []), resolved_cond_ids, discontinued_med_ids, max_bytes,
    )

    # tag_blob: the SAME data AES-GCM sealed to this physical tag's UID --
    # what staff should actually write. tag_text stays as the legacy
    # plaintext form (readable by any NFC reader; no per-read attribution).
    tag_blob = None
    tag_blob_truncated = False
    # X:<yyyymmdd> = the grant's own expiry, sealed in so an offline reader
    # refuses a lapsed tag. (A revoked-but-unexpired tag still opens offline:
    # revocation needs connectivity.)
    expiry = f"X:{grant.expires_at:%Y%m%d}"
    budget = tag_crypto.plaintext_budget(max_bytes) - len(expiry) - 1
    if budget >= 24:
        blob_plain, tag_blob_truncated = _build_compact_tag_text(
            patient, set(payload.scope or []), resolved_cond_ids, discontinued_med_ids, budget,
        )
        if blob_plain:
            tag_blob = tag_crypto.seal(f"{expiry}|{blob_plain}", auth.canonical_nfc_uid(payload.nfc_uid))

    return {
        "id": grant.id,
        "nfc_uid_last4": grant.nfc_uid_last4,
        "scope": grant.scope,
        "tag_text": tag_text,
        "tag_text_truncated": tag_text_truncated,
        "tag_blob": tag_blob,
        "tag_blob_key_id": tag_crypto.current_key_id() if tag_blob else None,
        "tag_blob_truncated": tag_blob_truncated,
        "tag_security": _tag_security(payload.tag_type),
        "grant_valid_until": grant.expires_at.isoformat(),
        "revoked": grant.revoked,
    }


@router.post("/nfc/scan")
@limiter.limit("10/minute")  # per-IP -- same rationale as POST /emergency/scan above.
def scan_nfc_card(
    request: Request,
    payload: schemas.NfcScanRequest,
    db: Session = Depends(get_db),
    current_user: "models.User | None" = Depends(auth.get_optional_current_user),
):
    """No login required — same design as /emergency/scan, but keyed by the
    physical card's NFC UID instead of a QR-encoded card_reference. A
    logged-in staff caller is bound to the audit entry (M6)."""
    ident = _responder_audit(current_user, payload)
    uid_hash = auth.hash_nfc_uid(payload.nfc_uid)
    hash_marker = f"nfc_hash={uid_hash[:16]}"  # M7c anomaly-count marker
    grant = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.nfc_uid == uid_hash)
        .first()
    )
    if not grant or grant.revoked or grant.expires_at < datetime.now(timezone.utc).replace(tzinfo=None):
        # Failed scan -- see POST /emergency/scan above for why this is
        # logged with patient_id=None. The raw UID is never logged (M7).
        log_access(
            db, None,
            actor=ident.actor, actor_role=ident.actor_role,
            action="emergency_access_failed",
            detail=f"{hash_marker} {ident.detail_suffix}",
            actor_facility=ident.actor_facility,
        )
        # patient_id=None on this branch too -- same reasoning as the
        # failed-scan row above: don't correlate a probe of a revoked/
        # expired card to the patient. The nfc_hash marker identifies the
        # card for a reviewer.
        _flag_nfc_scan_anomaly_if_needed(db, uid_hash, None)
        raise HTTPException(status_code=404, detail="This NFC card is not registered, revoked, or expired")

    patient = db.query(models.Patient).filter(models.Patient.id == grant.patient_id).first()
    if not patient:
        log_access(
            db, None,
            actor=ident.actor, actor_role=ident.actor_role,
            action="emergency_access_failed",
            detail=f"{hash_marker} {ident.detail_suffix} (grant found, patient missing)",
            actor_facility=ident.actor_facility,
        )
        raise HTTPException(status_code=404, detail="Patient not found")

    scope = set(grant.scope or [])
    resolved_cond_ids, discontinued_med_ids = _resolved_discontinued_ids(db, patient.id)
    result = _scoped_fields(patient, scope, resolved_cond_ids, discontinued_med_ids)

    log_access(
        db, patient.id,
        actor=ident.actor, actor_role=ident.actor_role,
        action="emergency_access_nfc",
        fields=list(scope),
        detail=f"{hash_marker} {ident.detail_suffix}",
        actor_facility=ident.actor_facility,
    )
    _audit_sharing_bypass_if_any(db, patient, ident)
    _flag_nfc_scan_anomaly_if_needed(db, uid_hash, patient.id)

    return result


# ---------- Offline (no-network) reads of encrypted tags ----------
# A CLARION device decrypts a tag with a cached data key and no server round
# trip. Both endpoints below are authenticated on purpose: the key only goes
# to a signed-in user in a role with an emergency/clinical need, and every
# offline read is uploaded under that user's identity afterwards -- the only
# way an offline read becomes attributable.
#
# What this does NOT give you (see models.OfflineTagRead): the device log is
# client-asserted. It records reads honestly made; it cannot prove a device
# did not drop entries. Any key holder can open any sealed tag offline.

_TAG_KEY_ROLES = ("admin", "clinician", "records_officer", "emergency_responder")
_MAX_OFFLINE_BATCH = 25


@router.get("/tag-keys")
@limiter.limit("20/minute")
def get_tag_keys(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_TAG_KEY_ROLES)),
):
    """Data keys a device caches so it can open an encrypted tag with no
    network. Every fetch is audited."""
    keys = tag_crypto.active_keys()
    response.headers["Cache-Control"] = "no-store"
    log_access(db, None, current_user.id, current_user.role, "tag_keys_fetch",
               detail=f"key_ids={','.join(keys)}", actor_facility=current_user.facility)
    return {"current_key_id": tag_crypto.current_key_id(), "keys": keys}


@router.post("/offline-reads")
@limiter.limit("30/minute")
def upload_offline_reads(
    request: Request,
    payload: schemas.OfflineTagReadsUpload,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_TAG_KEY_ROLES)),
):
    """Ingest a device's hash-chained log of offline tag reads. Idempotent
    per (user, device, seq) for an identical entry. A *different* entry for an
    already-stored seq is a `conflict` (never silently dropped): it is audited
    and reported so the client can re-base under a fresh device id. A bad hash
    link is stored with chain_ok=False and audited as such."""
    if len(payload.entries) > _MAX_OFFLINE_BATCH:
        raise HTTPException(status_code=413, detail=f"At most {_MAX_OFFLINE_BATCH} entries per upload")
    entries = sorted(payload.entries, key=lambda e: e.seq)
    stored = duplicates = conflicts = broken = 0
    prev_cache: dict = {}  # seq -> entry_hash, for this user+device (batch + DB)

    def _prev_hash_for(seq: int):
        if seq == 0:
            return tag_crypto.GENESIS_HASH
        if seq - 1 in prev_cache:
            return prev_cache[seq - 1]
        row = (
            db.query(models.OfflineTagRead.entry_hash)
            .filter_by(user_id=current_user.id, device_id=payload.device_id, seq=seq - 1)
            .first()
        )
        return row[0] if row else None

    for e in entries:
        canon_uid = auth.canonical_nfc_uid(e.nfc_uid)
        existing = (
            db.query(models.OfflineTagRead)
            .filter_by(user_id=current_user.id, device_id=payload.device_id, seq=e.seq)
            .first()
        )
        if existing:
            if existing.entry_hash == e.entry_hash:
                duplicates += 1
                prev_cache[e.seq] = existing.entry_hash
            else:
                conflicts += 1
                log_access(
                    db, None, current_user.id, current_user.role, "offline_read_seq_conflict",
                    detail=f"device={payload.device_id} seq={e.seq}",
                    actor_facility=current_user.facility,
                )
            continue

        expected = tag_crypto.read_entry_hash(
            e.prev_hash, e.seq, e.read_at, canon_uid, e.key_id, e.outcome)
        chain_ok = _prev_hash_for(e.seq) == e.prev_hash and expected == e.entry_hash

        uid_hash = auth.hash_nfc_uid(e.nfc_uid)
        grant = db.query(models.EmergencyToken).filter(models.EmergencyToken.nfc_uid == uid_hash).first()
        read_at = datetime.fromisoformat(e.read_at.replace("Z", "+00:00"))
        if read_at.tzinfo is None:
            read_at = read_at.replace(tzinfo=timezone.utc)
        skew_s = int((datetime.now(timezone.utc) - read_at).total_seconds())
        patient_id = grant.patient_id if grant else None

        # Audit FIRST: a crash between the two writes then leaves a (possibly
        # duplicated on retry) audit row, never a stored read with no audit.
        log_access(
            db, patient_id, current_user.id, current_user.role,
            "emergency_access_nfc_offline",
            detail=(f"nfc_hash={uid_hash[:16]} device={payload.device_id} seq={e.seq} "
                    f"read_at={e.read_at} skew_s={skew_s} outcome={e.outcome} "
                    f"chain_ok={chain_ok} source=device_asserted"),
            actor_facility=current_user.facility,
        )
        db.add(models.OfflineTagRead(
            user_id=current_user.id, device_id=payload.device_id, seq=e.seq,
            read_at=read_at, patient_id=patient_id,
            nfc_uid_hash=uid_hash, key_id=e.key_id, outcome=e.outcome,
            prev_hash=e.prev_hash, entry_hash=e.entry_hash, chain_ok=chain_ok,
        ))
        try:
            db.commit()
        except IntegrityError:
            # A concurrent upload of the same batch won the race.
            db.rollback()
            duplicates += 1
            prev_cache[e.seq] = e.entry_hash
            continue
        prev_cache[e.seq] = e.entry_hash
        stored += 1
        broken += 0 if chain_ok else 1

    return {"stored": stored, "duplicates": duplicates, "conflicts": conflicts, "chain_broken": broken}


@router.post("/nfc/revoke/{token_id}")
def revoke_nfc_card(
    token_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Revoke by the grant's id (from GET /emergency/nfc/{patient_id}) -- the
    raw NFC UID is no longer round-trippable to the client (M7)."""
    grant = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.id == token_id, models.EmergencyToken.nfc_uid.isnot(None))
        .first()
    )
    if not grant:
        raise HTTPException(status_code=404, detail="NFC card not found")
    grant.revoked = True
    db.commit()
    log_access(db, grant.patient_id, current_user.id, current_user.role, "revoke_nfc_card",
               detail=f"card_id={grant.id} last4={grant.nfc_uid_last4}",
               actor_facility=current_user.facility)
    return {"status": "revoked"}


@router.get("/nfc/{patient_id}")
def list_nfc_cards(
    patient_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_page_access("patients")),
):
    """Staff can see every registered card (scoped to their own facility's
    currently-present patients -- see _require_patient_present_for_staff);
    a patient can see (read-only) the cards registered to their own
    record."""
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's NFC cards")
    _require_patient_present_for_staff(db, current_user, patient_id)

    grants = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.patient_id == patient_id, models.EmergencyToken.nfc_uid.isnot(None))
        .order_by(models.EmergencyToken.created_at.desc())
        .all()
    )
    return [
        {
            "id": g.id,
            "nfc_uid_last4": g.nfc_uid_last4,
            "scope": g.scope,
            "grant_valid_until": g.expires_at.isoformat(),
            "revoked": g.revoked,
            "registered_by": g.registered_by,
            "created_at": g.created_at.isoformat(),
        }
        for g in grants
    ]
