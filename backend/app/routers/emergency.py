import base64
import hashlib
import hmac
import io
import os
import secrets
from urllib.parse import urlsplit
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, NamedTuple

import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas, auth, tag_crypto, contact_notify
from ..database import get_db
from ..audit import log_access
from ..rate_limit import limiter
from ..clinical_access import _patient_present_at
from .notifications import notify

router = APIRouter(prefix="/emergency", tags=["emergency"])

# Who may see what. A scan returns grant.scope (what the patient agreed to expose
# at all) intersected with the ceiling for the scanner's tier. The tier comes only
# from the account behind the bearer token, never from anything the caller types.
# "identity" = name + age; "emergency_contact" = the family contact's name, relationship and phone.
_TIER_CEILING = {
    "public": frozenset({"allergies", "conditions"}),
    "responder": frozenset({"allergies", "conditions", "blood_type", "identity", "emergency_contact"}),
    "clinical": frozenset({"allergies", "conditions", "blood_type", "medications", "identity", "emergency_contact"}),
    # An enrolled paramedic crew (User.responder_tier == "paramedic"): what a responder sees plus the
    # active medications they need before treating. No other clinical access comes with it.
    "paramedic": frozenset({"allergies", "conditions", "blood_type", "medications", "identity", "emergency_contact"}),
}
_TIER_BY_ROLE = {
    "emergency_responder": "responder", "receptionist": "responder",
    "clinician": "clinical", "admin": "clinical", "records_officer": "clinical", "pharmacist": "clinical",
}
# The paramedic tier is not a role of its own: it is an emergency_responder account whose admin set
# responder_tier="paramedic" (POST /admin/responders, or a role grant), so every responder restriction
# (allowed routes, expiry window, audit) applies to it unchanged.


def _tier_for(current_user) -> str:
    tier = _TIER_BY_ROLE.get(current_user.role, "public") if current_user else "public"
    if current_user and current_user.role == "emergency_responder" and current_user.responder_tier == "paramedic":
        tier = "paramedic"
    return tier


def _effective_scope(grant, current_user) -> "tuple[str, set]":
    tier = _tier_for(current_user)
    return tier, (set(grant.scope or []) | {"identity", "emergency_contact"}) & _TIER_CEILING[tier]


# What the patient's contact is told about the scanner: a role, never a name.
_WHO = {"public": "an unidentified person (position unverified)", "responder": "a responder",
        "paramedic": "a paramedic", "clinical": "a clinician"}
_LOCATION_TOKEN_MINUTES = 15
_APPROX_ABOVE_M = 500  # a fix worse than this (or with no accuracy) is shown as approximate
_MAX_LOCATIONS_PER_PATIENT_PER_10_MIN = 20
_NOTE_DEDUP_MINUTES = 15          # an unread "card scanned" notice hides repeats this long ...
_LOCATED_NOTE_DEDUP_MINUTES = 2   # ... but a located scan by an identified responder only this long
_PUBLIC_LOCATION_SMS_WINDOW = timedelta(minutes=30)


def _who(tier: str, facility: "str | None") -> str:
    return _WHO.get(tier, "someone") + (f" ({facility})" if facility else "")


def _loc_hash(token: str) -> str:
    return hmac.new(auth.SECRET_KEY.encode(), b"scan-loc:" + token.encode(), hashlib.sha256).hexdigest()


def _location_token(db: Session, patient, grant, tier: str, ident, current_user) -> str:
    """Returned with every scan so the scanner's device can send its position LATER (a GPS fix that
    was slow, or one that needed the user to tap "share"). An opaque random value (only its hash is
    stored): it carries nothing readable, works ONCE, only for the scan it came from, only while that
    card is still valid, and only for the same signed-in scanner when the scan was identified."""
    token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    db.query(models.ScanLocationGrant).filter(
        models.ScanLocationGrant.expires_at < now - timedelta(days=1)).delete(synchronize_session=False)
    db.add(models.ScanLocationGrant(
        token_hash=_loc_hash(token), patient_id=patient.id, emergency_token_id=grant.id, tier=tier,
        actor_user_id=current_user.id if current_user else None,
        actor_role=ident.actor_role, actor_facility=ident.actor_facility,
        expires_at=now + timedelta(minutes=_LOCATION_TOKEN_MINUTES)))
    db.commit()
    return token


def _purge_old(db: Session) -> None:
    """Retention, for EVERY patient (not only the one being written): scan positions, the contact
    alert jobs that carry coordinates in their payload, and the notices that carry the map link."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=models.SCAN_LOCATION_KEEP_DAYS)
    db.query(models.ScanLocation).filter(models.ScanLocation.created_at < cutoff).delete(synchronize_session=False)
    db.query(models.Notification).filter(
        models.Notification.kind.in_(("card_scanned", "contact_card_scanned")),
        models.Notification.created_at < cutoff).delete(synchronize_session=False)
    db.query(models.Job).filter(
        models.Job.kind == contact_notify.JOB_KIND, models.Job.status.in_(("done", "failed")),
        models.Job.created_at < datetime.now(timezone.utc) - timedelta(days=1)).delete(synchronize_session=False)


def _record_location(db: Session, patient, tier: str, ident, loc) -> "dict | None":
    """Store the scanner's reported position. None = not stored (this patient already got a burst of
    them in the last 10 minutes), so a flood of fake rows can't push a genuine one out of the list."""
    _purge_old(db)
    burst = db.query(models.ScanLocation).filter(
        models.ScanLocation.patient_id == patient.id,
        models.ScanLocation.created_at >= datetime.now(timezone.utc) - timedelta(minutes=10)).count()
    if burst >= _MAX_LOCATIONS_PER_PATIENT_PER_10_MIN:
        db.commit()
        return None
    db.add(models.ScanLocation(
        patient_id=patient.id, lat=loc.lat, lng=loc.lng, accuracy_m=loc.accuracy_m, tier=tier,
        actor_role=ident.actor_role, actor_facility=ident.actor_facility))
    db.commit()
    return {"lat": loc.lat, "lng": loc.lng,
            "approx": loc.accuracy_m is None or loc.accuracy_m > _APPROX_ABOVE_M}


def _recent_public_location_sms(db: Session, patient_id: str) -> bool:
    """True if a location text for this patient already went out recently (a public scanner's late
    fix may only add one per window; an identified responder is not limited this way)."""
    return db.query(models.Job).filter(
        models.Job.kind == contact_notify.JOB_KIND,
        models.Job.created_at >= datetime.now(timezone.utc) - _PUBLIC_LOCATION_SMS_WINDOW,
        models.Job.payload.like(f'%"patient_id": "{patient_id}"%'), models.Job.payload.like('%"loc"%')).count() > 0


def _notify_patient_of_scan(db: Session, patient, tier: str, ident, loc: "dict | None" = None) -> None:
    """Tell the patient's own account when anything above the public view was opened, or when a
    scanner's position came with the scan. A located scan by an identified responder is de-duplicated
    over a much shorter window (2 min, not 15) so it is not hidden behind a bystander's earlier notice.
    ponytail: the patient's own login(s) only; guardians of a minor need a PatientDependant lookup."""
    if tier == "public" and not loc:
        return
    accounts = db.query(models.User).filter(
        models.User.patient_id == patient.id, models.user_has_role("patient")).all()
    minutes = _LOCATED_NOTE_DEDUP_MINUTES if (loc and tier != "public") else _NOTE_DEDUP_MINUTES
    where = f" at {ident.actor_facility}" if ident.actor_facility else ""
    url = contact_notify.maps_url(loc["lat"], loc["lng"]) if loc else None
    approx = ", approximate" if loc and loc.get("approx") else ""
    for account in accounts:
        recent = db.query(models.Notification).filter(
            models.Notification.user_id == account.id, models.Notification.kind == "card_scanned",
            models.Notification.read_at.is_(None),
            models.Notification.created_at >= datetime.now(timezone.utc) - timedelta(minutes=minutes)).first()
        if recent:
            continue
        notify(db, account.id, "card_scanned", "Your emergency card was scanned",
               body=f"Opened with {tier} access{where}."
               + (f" Where (reported by the scanner's phone{approx}): {url}" if url else ""),
               link=url, urgent=True)


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


def _public_base() -> str:
    """Where the public emergency page lives (the SPA's /e/... route): CLARION_PUBLIC_URL, default
    https://clarion.larmkx.com. A value that is set but not a plain https origin (http is allowed only for
    localhost) is refused loudly -- printing cards that point somewhere else would be worse than failing."""
    raw = os.environ.get("CLARION_PUBLIC_URL")
    if raw is None or not raw.strip():
        return "https://clarion.larmkx.com"
    parts = urlsplit(raw.strip())
    local = parts.hostname in ("localhost", "127.0.0.1")
    if (parts.scheme != "https" and not (parts.scheme == "http" and local)) or not parts.hostname \
            or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise RuntimeError("CLARION_PUBLIC_URL must be a plain https origin such as https://clarion.example.org")
    return f"{parts.scheme}://{parts.netloc}"


_public_base()  # a bad CLARION_PUBLIC_URL stops the app at startup, not when the first card is printed


def _render_qr_base64(card_reference: str) -> str:
    """Render the emergency QR PNG for a given card_reference and return it
    as a `data:image/png;base64,...` string.

    The QR content is a link, `{public base}/e/{card_reference}`: any phone camera opens the
    public emergency page (public tier only), and the CLARION app recognises the same link.
    Cards printed before this change carry the older `CLARION-EMERGENCY:{card_reference}` text,
    which the app still understands. Deterministic, so it can be rendered as often as needed —
    nothing about the image is persisted, only the card_reference it's derived from."""
    qr_payload = f"{_public_base()}/e/{card_reference}"
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
      before -- `actor="public_unverified:<name>"`,
      `actor_role="public_unverified"`. That role value *means*
      "self-asserted, unverified" (a verified responder account keeps
      `emergency_responder`) and every audit-trail consumer
      (web `PatientDetail.jsx`, `mobile_flutter/.../audit_log_screen.dart`)
      keys on it; a reviewer filtering `actor_role == "public_unverified"`
      gets precisely the unverified accesses. Rows written before the rename
      carry `emergency_responder:` and are still recognised by prefix.
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
        actor=f"public_unverified:{said or 'unidentified'}",
        actor_role="public_unverified",
        actor_facility=None,
        detail_suffix=f"org={org}",
    )


def _scan_detail(ident: _ResponderAudit, tier: str) -> str:
    """Unverified rows keep the bare `org=...` shape the audit UIs parse (their tier is
    always public); verified rows record the tier the account got."""
    return ident.detail_suffix if ident.actor_role == "public_unverified" else f"{ident.detail_suffix} tier={tier}"


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
    identity: bool = True,
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
    result = (
        {"full_name": patient.full_name, "age": _age_from_dob(patient.date_of_birth)}
        if identity else {"full_name": None, "age": None}
    )
    if "emergency_contact" in scope:
        result["emergency_contact"] = (
            {"name": patient.emergency_contact_name, "relationship": patient.emergency_contact_relationship,
             "phone": patient.emergency_contact_phone}
            if patient.emergency_contact_phone else None
        )
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
        .filter(or_(models.EmergencyToken.card_reference == payload.card_reference,
                    models.EmergencyToken.public_ref == payload.card_reference))
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

    tier, scope = _effective_scope(grant, current_user)
    resolved_cond_ids, discontinued_med_ids = _resolved_discontinued_ids(db, patient.id)
    result = _scoped_fields(patient, scope, resolved_cond_ids, discontinued_med_ids,
                            identity="identity" in scope)
    result["tier"] = tier
    if tier == "public":
        result["omitted_non_critical"] = {}

    loc = _record_location(db, patient, tier, ident, payload.location) if payload.location else None
    _notify_patient_of_scan(db, patient, tier, ident, loc)
    # Every successful scan alerts the emergency contact (queued, never blocks or fails the scan).
    family = contact_notify.safe_queue(
        db, patient, location=loc, who=_who(tier, ident.actor_facility),
        priority=bool(loc) and tier != "public", pub=tier == "public")
    if family == "throttled" and loc:  # a dropped location text must not be silent
        log_access(db, patient.id, ident.actor, ident.actor_role, "emergency_contact_alert_throttled",
                   detail=f"tier={tier} located=1", actor_facility=ident.actor_facility)
    result["location_token"] = _location_token(db, patient, grant, tier, ident, current_user)
    if tier != "public":  # the public tier must not learn whether a contact exists or was alerted recently
        result["family_notification"] = family
    log_access(
        db, patient.id,
        actor=ident.actor, actor_role=ident.actor_role,
        action="emergency_access",
        fields=sorted(scope),
        detail=_scan_detail(ident, tier),
        actor_facility=ident.actor_facility,
    )
    _audit_sharing_bypass_if_any(db, patient, ident)

    return result


@router.post("/location")
@limiter.limit("10/minute")  # per-IP; the real bounds are one use per token and the per-number SMS caps
def share_scan_location(
    request: Request,
    payload: schemas.ScanLocationSend,
    db: Session = Depends(get_db),
    current_user: "models.User | None" = Depends(auth.get_optional_current_user),
):
    """A scanner's position that arrived AFTER the scan (slow GPS fix, or the user tapped "share").
    Authorised by the one-use `location_token` that scan returned: it only ever reaches the patient
    that scan was of, only while the card is still valid, and for an identified scan only from the
    same signed-in scanner. Who it is attributed to (tier, role, facility) is what was recorded at
    scan time, never what this request claims. The contact gets a "new location" text."""
    gone = HTTPException(status_code=400, detail="This location link has expired. Scan the card again.")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    row = db.query(models.ScanLocationGrant).filter(
        models.ScanLocationGrant.token_hash == _loc_hash(payload.token)).first()
    if row is None or row.used_at is not None or row.expires_at.replace(tzinfo=None) < now:
        raise gone
    card = db.get(models.EmergencyToken, row.emergency_token_id)
    if card is None or card.revoked or card.expires_at < now:
        raise gone
    if row.actor_user_id and (current_user is None or current_user.id != row.actor_user_id):
        raise gone
    patient = db.get(models.Patient, row.patient_id)
    won = db.query(models.ScanLocationGrant).filter(
        models.ScanLocationGrant.id == row.id, models.ScanLocationGrant.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)
    db.commit()
    if patient is None or won != 1:
        raise gone
    tier = row.tier
    ident = _ResponderAudit(
        actor=row.actor_user_id or "public_unverified:location", actor_role=row.actor_role or "public_unverified",
        actor_facility=row.actor_facility, detail_suffix="")
    loc = _record_location(db, patient, tier, ident, payload.location)
    if loc is None:  # a burst: stored nothing, told nobody
        return {"status": "ok"}
    _notify_patient_of_scan(db, patient, tier, ident, loc)
    identified = row.actor_user_id is not None
    if identified or not _recent_public_location_sms(db, patient.id):
        family = contact_notify.safe_queue(db, patient, location=loc, who=_who(tier, ident.actor_facility),
                                           priority=True, update=True, pub=not identified)
        if family == "throttled":
            log_access(db, patient.id, ident.actor, ident.actor_role, "emergency_contact_alert_throttled",
                       detail=f"tier={tier} located=1 update=1", actor_facility=ident.actor_facility)
    log_access(db, patient.id, ident.actor, ident.actor_role, "emergency_location_shared",
               detail=f"tier={tier}", actor_facility=ident.actor_facility)
    return {"status": "ok"}


@router.get("/locations/{patient_id}", response_model=List[schemas.ScanLocationOut])
def list_scan_locations(
    patient_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_page_access("patients")),
):
    """Where this patient's card was recently scanned (as reported by the scanners' devices), newest
    first. The patient (or a guardian acting for them), or staff at a facility the patient is at."""
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's scan locations")
    _require_patient_present_for_staff(db, current_user, patient_id)
    rows = (
        db.query(models.ScanLocation).filter(models.ScanLocation.patient_id == patient_id)
        .order_by(models.ScanLocation.created_at.desc()).limit(50).all()
    )
    log_access(db, patient_id, current_user.id, current_user.role, "view_scan_locations",
               detail=f"rows={len(rows)}", actor_facility=current_user.facility)
    return rows


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


# The sealed record leads with "X:<yyyymmdd>|"; below this many plaintext
# bytes left over, there is no room for even a blood type plus one allergy.
_SEALED_EXPIRY_LEN = len("X:YYYYMMDD")
# A tag this big (NTAG215/216) also carries a URL record so a phone without the app opens the
# public page; the URL record's bytes come out of the sealed record's budget.
_URL_ON_TAG_MIN_CAPACITY = 400
_URL_RECORD_OVERHEAD = 6
_MIN_SEALED_BUDGET = 24


def _sealed_budget(max_bytes: int) -> int:
    """Plaintext bytes available for the data once the expiry prefix is paid for."""
    return tag_crypto.plaintext_budget(max_bytes) - _SEALED_EXPIRY_LEN - 1


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

    # Refuse before anything is persisted: a tag too small for the sealed
    # record must never fall back to writing readable plaintext.
    capacity = payload.tag_max_bytes or _TAG_TEXT_MAX_BYTES_DEFAULT
    public_ref = secrets.token_urlsafe(8)  # new at every registration; the link never contains the UID
    public_url = f"{_public_base()}/e/{public_ref}"
    url_on_tag = capacity >= _URL_ON_TAG_MIN_CAPACITY
    budget = _sealed_budget(capacity - (len(public_url) + _URL_RECORD_OVERHEAD if url_on_tag else 0))
    if budget < _MIN_SEALED_BUDGET:
        raise HTTPException(
            status_code=422,
            detail="This tag is too small for an encrypted emergency record. "
                   "Use a larger tag (NTAG215 or NTAG216).",
        )

    if existing:
        existing.scope = payload.scope
        existing.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=payload.valid_minutes)
        existing.revoked = False
        existing.registered_by = current_user.id
        existing.nfc_uid_last4 = auth.nfc_uid_last4(payload.nfc_uid)
        existing.nfc_revocation_id = tag_crypto.revocation_id(auth.canonical_nfc_uid(payload.nfc_uid))
        existing.nfc_tag_type = payload.tag_type
        existing.public_ref = public_ref
        grant = existing
        action = "update_nfc_card"
    else:
        grant = models.EmergencyToken(
            patient_id=payload.patient_id,
            token=secrets.token_urlsafe(32),
            nfc_uid=uid_hash,
            nfc_uid_last4=auth.nfc_uid_last4(payload.nfc_uid),
            nfc_revocation_id=tag_crypto.revocation_id(auth.canonical_nfc_uid(payload.nfc_uid)),
            nfc_tag_type=payload.tag_type,
            public_ref=public_ref,
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

    # tag_blob: the compact on-tag record (see _build_compact_tag_text's
    # docstring for why it exists alongside the UID pointer above), AES-GCM
    # sealed to this physical tag's UID and computed with the SAME scope just
    # granted, so the tag never carries more than the patient consented to
    # share. Staff write it onto the tag's NDEF memory after this returns.
    # It is the only form ever returned: plaintext tags are read-only legacy.
    # None means the patient has no emergency-critical data yet (nothing to
    # write; the card still works online).
    resolved_cond_ids, discontinued_med_ids = _resolved_discontinued_ids(db, payload.patient_id)
    tag_blob = None
    # X:<yyyymmdd> = the grant's own expiry, sealed in so an offline reader
    # refuses a lapsed tag. (A revoked-but-unexpired tag is refused offline
    # once the device has synced the revoked list from /emergency/tag-keys.)
    expiry = f"X:{grant.expires_at:%Y%m%d}"
    blob_plain, tag_blob_truncated = _build_compact_tag_text(
        patient, set(payload.scope or []), resolved_cond_ids, discontinued_med_ids, budget,
    )
    if blob_plain:
        tag_blob = tag_crypto.seal(f"{expiry}|{blob_plain}", auth.canonical_nfc_uid(payload.nfc_uid))
    grant.tag_digest = _tag_digest(blob_plain)  # of "" too: a card written empty goes stale once data appears
    grant.tag_budget = budget
    db.commit()

    return {
        "id": grant.id,
        "nfc_uid_last4": grant.nfc_uid_last4,
        "scope": grant.scope,
        "tag_blob": tag_blob,
        "tag_blob_key_id": tag_crypto.current_key_id() if tag_blob else None,
        "tag_blob_truncated": tag_blob_truncated,
        "tag_security": _tag_security(payload.tag_type),
        "grant_valid_until": grant.expires_at.isoformat(),
        "revoked": grant.revoked,
        # Written as the FIRST NDEF record when url_on_tag, so a phone without the app opens the page.
        "public_url": public_url,
        "url_on_tag": url_on_tag,
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

    tier, scope = _effective_scope(grant, current_user)
    resolved_cond_ids, discontinued_med_ids = _resolved_discontinued_ids(db, patient.id)
    result = _scoped_fields(patient, scope, resolved_cond_ids, discontinued_med_ids,
                            identity="identity" in scope)
    result["tier"] = tier
    if tier == "public":
        result["omitted_non_critical"] = {}

    loc = _record_location(db, patient, tier, ident, payload.location) if payload.location else None
    _notify_patient_of_scan(db, patient, tier, ident, loc)
    # Every successful scan alerts the emergency contact (queued, never blocks or fails the scan).
    family = contact_notify.safe_queue(
        db, patient, location=loc, who=_who(tier, ident.actor_facility),
        priority=bool(loc) and tier != "public", pub=tier == "public")
    if family == "throttled" and loc:  # a dropped location text must not be silent
        log_access(db, patient.id, ident.actor, ident.actor_role, "emergency_contact_alert_throttled",
                   detail=f"tier={tier} located=1", actor_facility=ident.actor_facility)
    result["location_token"] = _location_token(db, patient, grant, tier, ident, current_user)
    if tier != "public":  # the public tier must not learn whether a contact exists or was alerted recently
        result["family_notification"] = family
    log_access(
        db, patient.id,
        actor=ident.actor, actor_role=ident.actor_role,
        action="emergency_access_nfc",
        fields=sorted(scope),
        detail=f"{hash_marker} {_scan_detail(ident, tier)}",
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
    network, plus what it needs to refuse a revoked card offline: the
    revocation key and the ids of cards revoked while still unexpired (an
    expired card is already refused by the expiry sealed into its record, so
    the list stays short). `key_max_age_hours` is how long the device may keep
    all of this without a successful refresh. Every fetch is audited."""
    keys = tag_crypto.active_keys()
    # The sealed expiry is date-only and a device treats a record as valid until
    # 23:59:59 UTC that day, so keep a card listed for a day past expires_at.
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    revoked_ids = [
        r[0] for r in db.query(models.EmergencyToken.nfc_revocation_id)
        .filter(models.EmergencyToken.revoked.is_(True),
                models.EmergencyToken.nfc_revocation_id.isnot(None),
                models.EmergencyToken.expires_at > cutoff)
        .all()
    ]
    # A time-boxed account (community responder) must not outlive its window
    # on a phone that is offline: the device treats `valid_until` as a hard stop
    # on top of key_max_age_hours.
    valid_until = None
    if "emergency_responder" in auth.all_roles(auth.real_user(current_user)) and current_user.access_expires_at is not None:
        exp = current_user.access_expires_at
        if exp.tzinfo is not None:
            exp = exp.astimezone(timezone.utc).replace(tzinfo=None)
        valid_until = exp.isoformat() + "Z"
    response.headers["Cache-Control"] = "no-store"
    log_access(db, None, current_user.id, current_user.role, "tag_keys_fetch",
               detail=f"key_ids={','.join(keys)} revoked={len(revoked_ids)}", actor_facility=current_user.facility)
    return {
        "current_key_id": tag_crypto.current_key_id(),
        "keys": keys,
        "revocation_key": base64.b64encode(tag_crypto.revocation_key()).decode(),
        "revoked_card_ids": revoked_ids,
        "key_max_age_hours": tag_crypto.key_max_age_hours(),
        "valid_until": valid_until,
    }


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
        if patient_id and e.outcome == "decrypted":  # a tap made with no network: alert the contact now
            contact_notify.safe_queue(db, db.get(models.Patient, patient_id), when=read_at, late=True)

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
    # A card registered before nfc_revocation_id existed cannot be listed for
    # offline devices (the raw UID is not stored): say so, so staff re-register
    # and revoke again, or retire the key set.
    offline_revocable = grant.nfc_revocation_id is not None
    log_access(db, grant.patient_id, current_user.id, current_user.role, "revoke_nfc_card",
               detail=f"card_id={grant.id} last4={grant.nfc_uid_last4} offline_revocable={offline_revocable}",
               actor_facility=current_user.facility)
    return {"status": "revoked", "offline_revocable": offline_revocable}


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
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    patient = db.query(models.Patient).filter_by(id=patient_id).first() if grants else None
    resolved, discontinued = _resolved_discontinued_ids(db, patient_id) if grants else (set(), set())
    out = []
    for g in grants:
        card = _nfc_card_out(g, now)
        # None = unknown (card registered before this check, or nothing was written).
        card["tag_stale"] = None if not (g.tag_digest and g.tag_budget and patient) else (
            _tag_digest(_build_compact_tag_text(patient, set(g.scope or []), resolved, discontinued, g.tag_budget)[0])
            != g.tag_digest)
        out.append(card)
    return out


def _tag_digest(plain: str) -> str:
    return hashlib.sha256(plain.encode()).hexdigest()[:16]


def _nfc_card_out(g: "models.EmergencyToken", now: datetime) -> dict:
    tag_type = g.nfc_tag_type or "unknown"
    expired = g.expires_at < now
    status = "revoked" if g.revoked else ("expired" if expired else "active")
    return {
        "id": g.id,
        "nfc_uid_last4": g.nfc_uid_last4,
        "scope": g.scope,
        "grant_valid_until": g.expires_at.isoformat(),
        "revoked": g.revoked,
        "registered_by": g.registered_by,
        "created_at": g.created_at.isoformat(),
        "tag_type": tag_type,
        # Anything but an NTAG 424 DNA has no tamper-proof read counter.
        "outdated": tag_type != "ntag424",
        "status": status,
        "valid_days_left": None if status != "active" else max(0, (g.expires_at - now).days),
    }


_NFC_HISTORY_EVENTS = {
    "register_nfc_card": "registered",
    "update_nfc_card": "renewed",
    "revoke_nfc_card": "revoked",
    "emergency_access_nfc": "scanned",
}


@router.get("/nfc/{patient_id}/{card_id}/history")
def nfc_card_history(
    patient_id: str, card_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_page_access("patients")),
):
    """Timeline for one card, newest first, from the audit log. Shows role / organisation /
    facility only: a responder's typed name is not repeated here."""
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's NFC cards")
    _require_patient_present_for_staff(db, current_user, patient_id)
    grant = (
        db.query(models.EmergencyToken)
        .filter(models.EmergencyToken.id == card_id, models.EmergencyToken.patient_id == patient_id,
                models.EmergencyToken.nfc_uid.isnot(None))
        .first()
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="NFC card not found")
    rows = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.patient_id == patient_id,
                models.AuditLog.action.in_(list(_NFC_HISTORY_EVENTS)),
                or_(models.AuditLog.detail.like(f"%card_id={grant.id}%"),
                    models.AuditLog.detail.like(f"%nfc_hash={grant.nfc_uid[:16]}%")))
        .order_by(models.AuditLog.timestamp.desc())
        .limit(50)
        .all()
    )
    out = []
    for r in rows:
        m = re.search(r"org=(.*?)(?: self_asserted=| tier=|$)", r.detail or "")
        org = m.group(1).strip() if m and m.group(1).strip() not in ("", "None") else None
        out.append({
            "at": (r.timestamp.replace(tzinfo=timezone.utc) if r.timestamp.tzinfo is None else r.timestamp).isoformat(),
            "event": _NFC_HISTORY_EVENTS[r.action],
            "by_role": r.actor_role,
            "by_org": org,
            "facility": r.actor_facility,
        })
    return out
