import mimetypes
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select, union
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from ..ai.nric_ocr import dob_from_ic_number
from ..storage import (
    BUCKET_DOCUMENTS,
    BUCKET_SIGNATURES,
    ObjectNotFound,
    ObjectStoreError,
    apply_object_meta,
    get_object_store,
    sanitize_filename,
)
from ..derived import get_or_make_thumbnail
from .auth_router import _resolve_patient_by_nric
from .reception import _malaysia_today
from .profile import save_signature_from_b64, copy_signature_snapshot

router = APIRouter(prefix="/patients", tags=["patients"])

# Content-Types this app actually needs to serve inline/safely from
# GET /patients/{id}/documents/{document_id}/file -- scanned prescriptions,
# lab reports, discharge summaries, X-ray/imaging. Anything guessed outside
# this allowlist (in particular text/html, which a browser will happily
# execute in this app's own origin) is forced to application/octet-stream
# instead, which browsers only ever download, never render/execute. See
# get_document_file below -- deliberately guessed from the sanitized
# object key (ClinicalDocument.file_object_key), never from the
# attacker-controlled ClinicalDocument.original_filename.
SAFE_DOCUMENT_MEDIA_TYPES = {
    "image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf",
}


# ---------------------------------------------------------------------------
# Cross-hospital clinical-record immutability helpers
# ---------------------------------------------------------------------------
# A clinical sub-record (Condition / MedicationStatement / AllergyIntolerance
# / Encounter) may be amended via PATCH ONLY when BOTH hold:
#   1. the acting user's facility == the facility that AUTHORED that row, AND
#   2. the patient is CURRENTLY PRESENT at that facility.
# Otherwise the correction mechanism is to APPEND a new entry (the add_*
# POST endpoints stay open to any facility for any patient). Legacy rows with
# a NULL author facility can never satisfy rule #1 and are therefore
# effectively immutable to everyone via PATCH -- the intended safe default.


def _row_author_facility(row) -> "str | None":
    """The facility that authored a clinical sub-record, whichever column
    holds it for that resource type: Condition/AllergyIntolerance ->
    `authored_by_facility`; MedicationStatement -> `recorded_by_facility`
    (NOT `prescribed_by_facility`, which is the -- often external --
    prescriber); Encounter -> `facility_name`."""
    if isinstance(row, models.MedicationStatement):
        return row.recorded_by_facility
    if isinstance(row, models.Encounter):
        return row.facility_name
    # Condition / AllergyIntolerance
    return getattr(row, "authored_by_facility", None)


def _patient_present_at(db: Session, patient_id: str, facility: str) -> bool:
    """True iff the patient is CURRENTLY at `facility` -- either an active
    (undischarged) Admission there, or a same-day (Malaysia-local) queue
    ticket in a still-open state ('waiting' / 'called'). This is rule #2 of
    the cross-facility PATCH guard."""
    if not facility:
        return False

    active_admission = (
        db.query(models.Admission.id)
        .filter(
            models.Admission.patient_id == patient_id,
            models.Admission.facility_name == facility,
            models.Admission.discharged_at.is_(None),
        )
        .first()
    )
    if active_admission is not None:
        return True

    # Reuse reception's single source of truth for "today" in Malaysia-local
    # terms (Asia/Kuala_Lumpur, UTC+8, no DST) -- see models.QueueTicket's
    # docstring for why the queue day is deliberately not the UTC date.
    _utc_start, queue_date = _malaysia_today()
    open_ticket = (
        db.query(models.QueueTicket.id)
        .filter(
            models.QueueTicket.patient_id == patient_id,
            models.QueueTicket.facility_name == facility,
            models.QueueTicket.status.in_(("waiting", "called")),
            models.QueueTicket.queue_date == queue_date,
        )
        .first()
    )
    return open_ticket is not None


def _record_editable(
    db: Session, patient_id: str, row, current_user,
    present_at_caller_facility: "bool | None" = None,
) -> bool:
    """Rule #1 AND rule #2 combined, for the `editable` flag exposed on every
    serialized clinical sub-record. False whenever there is no user context
    (e.g. the unauthenticated emergency scan) or the acting user has no
    facility assigned.

    `present_at_caller_facility` lets a bulk caller (`_serialize_patient`)
    pass in the rule-#2 result it has already computed once for this
    (patient, caller-facility) pair, instead of this function re-running the
    two `_patient_present_at` queries for every clinical sub-record on the
    patient. When None it is computed here as before (the single-row PATCH
    return serializers)."""
    if current_user is None or not getattr(current_user, "facility", None):
        return False
    owner = _row_author_facility(row)
    if not owner or owner != current_user.facility:
        return False
    if present_at_caller_facility is not None:
        return present_at_caller_facility
    return _patient_present_at(db, patient_id, current_user.facility)


def _hidden_author_facilities(db: Session, caller_facility: "str | None") -> set:
    """Facilities whose authored clinical sub-records must be HIDDEN from
    this caller because that facility has set HospitalSetting.records_shared_publicly
    to False. A facility never hides records from its own staff, so
    `caller_facility` is always excluded from the result. Computed once per
    _serialize_patient call."""
    rows = (
        db.query(models.HospitalSetting.facility_name)
        .filter(models.HospitalSetting.records_shared_publicly.is_(False))
        .all()
    )
    return {f for (f,) in rows if f and f != caller_facility}


# ---------------------------------------------------------------------------
# Clinical-record annotations (append-only sign-off -- models.ClinicalRecordAnnotation)
# ---------------------------------------------------------------------------
# An annotation is an immutability-safe way to mark a (possibly
# cross-facility) clinical sub-record resolved / discontinued / corrected
# WITHOUT touching the row's own columns: the read path folds
# kind=='resolved' / kind=='discontinued' into a COMPUTED effective_status /
# effective_active on the serialized record, and the raw column is left
# exactly as its authoring facility set it.
ANNOTATION_TARGET_TYPE_BY_MODEL = {
    models.Condition: "condition",
    models.MedicationStatement: "medication",
    models.AllergyIntolerance: "allergy",
    models.Encounter: "encounter",
}


def _group_annotations_by_target(db: Session, patient_id: str) -> dict:
    """All of a patient's annotations, grouped `target_id -> [rows]`, newest
    first within each group -- fetched once per _serialize_patient call."""
    grouped: dict = {}
    rows = (
        db.query(models.ClinicalRecordAnnotation)
        .filter(models.ClinicalRecordAnnotation.patient_id == patient_id)
        .order_by(models.ClinicalRecordAnnotation.created_at.desc())
        .all()
    )
    for row in rows:
        grouped.setdefault(row.target_id, []).append(row)
    return grouped


def _annotations_for_target(db: Session, patient_id: str, target_id: str) -> list:
    """The annotation group for one record -- used by the PATCH endpoints'
    return serializers, which don't build the full patient grouping."""
    return (
        db.query(models.ClinicalRecordAnnotation)
        .filter(
            models.ClinicalRecordAnnotation.patient_id == patient_id,
            models.ClinicalRecordAnnotation.target_id == target_id,
        )
        .order_by(models.ClinicalRecordAnnotation.created_at.desc())
        .all()
    )


def _serialize_annotation(a: models.ClinicalRecordAnnotation) -> dict:
    return {
        "id": a.id,
        "target_type": a.target_type,
        "target_id": a.target_id,
        "kind": a.kind,
        "note": a.note,
        "signed_by_name": a.signed_by_name,
        "signed_by_role": a.signed_by_role,
        "facility_name": a.facility_name,
        "created_at": str(a.created_at),
        "signature_url": f"/patients/{a.patient_id}/annotations/{a.id}/signature",
    }


def _annotation_dicts(anns) -> list:
    return [_serialize_annotation(a) for a in (anns or [])]


def _serialize_patient(
    p: models.Patient,
    db: Session,
    current_user,
    bypass_sharing_filter: bool = False,
) -> dict:
    """Serialize a full patient record.

    `db` + `current_user` are threaded through so every embedded clinical
    sub-record can carry `authored_by_facility` + a computed `editable` flag
    (see _record_editable), and so records authored by a facility that has
    opted out of public sharing (HospitalSetting.records_shared_publicly ==
    False) can be filtered out for callers at OTHER facilities.

    `current_user` may be None for a context with no acting user (there is
    none in the current codebase -- the emergency scan path builds its own
    scoped payload and never calls this -- but the parameter is explicit so
    a future caller can't forget it). `bypass_sharing_filter=True` is a
    life-safety override that disables the records_shared_publicly read
    filter entirely; the patient viewing their OWN record also always sees
    everything.
    """
    caller_facility = getattr(current_user, "facility", None) if current_user is not None else None
    caller_is_this_patient = (
        current_user is not None
        and getattr(current_user, "role", None) == "patient"
        and getattr(current_user, "patient_id", None) == p.id
    )
    if bypass_sharing_filter or caller_is_this_patient:
        hidden = set()
    else:
        hidden = _hidden_author_facilities(db, caller_facility)

    def _visible(row) -> bool:
        if not hidden:
            return True
        return _row_author_facility(row) not in hidden

    # One query for every annotation on this patient, grouped by target_id --
    # each clinical sub-record serializer below gets handed just its own
    # group (or []), and folds kind=='resolved'/'discontinued' into a
    # computed effective_status/effective_active without mutating the row.
    ann_groups = _group_annotations_by_target(db, p.id)

    # Rule #2 of the cross-facility immutability guard ("is the patient
    # currently present at the caller's facility") is constant for every
    # sub-record on this patient -- compute it once here instead of letting
    # _record_editable re-run its two queries per condition/medication/
    # allergy/encounter (a 40-record patient was ~80 redundant queries).
    present_here = _patient_present_at(db, p.id, caller_facility) if caller_facility else False

    return {
        "id": p.id, "full_name": p.full_name, "date_of_birth": p.date_of_birth,
        "gender": p.gender, "national_id": p.national_id, "blood_type": p.blood_type,
        "phone": p.phone, "senior_citizen_mode": p.senior_citizen_mode,
        "email": p.email, "emergency_contact_name": p.emergency_contact_name,
        "emergency_contact_phone": p.emergency_contact_phone,
        "emergency_contact_relationship": p.emergency_contact_relationship,
        "conditions": [
            _serialize_condition(c, db, current_user, ann_groups.get(c.id), present_here)
            for c in p.conditions if _visible(c)
        ],
        "medications": [
            _serialize_medication(m, db, current_user, ann_groups.get(m.id), present_here)
            for m in p.medications if _visible(m)
        ],
        "allergies": [
            _serialize_allergy(a, db, current_user, ann_groups.get(a.id), present_here)
            for a in p.allergies if _visible(a)
        ],
        "encounters": [
            _serialize_encounter(e, db, current_user, ann_groups.get(e.id), present_here)
            for e in p.encounters if _visible(e)
        ],
        # Flat list of every annotation on this patient (newest first) --
        # a convenience mirror of what's already embedded per-record above.
        "annotations": [
            _serialize_annotation(a)
            for group in ann_groups.values() for a in group
        ],
        # Summary shape only -- raw_text/ai_summary can be large OCR dumps,
        # fetched on demand via GET /patients/{id}/documents/{document_id}
        # instead so a full patient-record GET stays cheap. Filtered by the
        # same records_shared_publicly rule as the clinical sub-records above:
        # a discharge-summary / prescription scan's OCR text is exactly the
        # diagnoses + drugs the opt-out is meant to hide, so an opted-out
        # facility's documents must drop out of another facility's view too
        # (the detail/file endpoints enforce the same check -- see
        # _document_visible_to).
        "documents": [
            {
                "id": d.id, "doc_type": d.doc_type, "original_filename": d.original_filename,
                "uploaded_by_facility": d.uploaded_by_facility, "uploaded_at": str(d.uploaded_at),
            }
            for d in p.documents
            if not hidden or d.uploaded_by_facility not in hidden
        ],
    }


@router.post("", response_model=schemas.PatientOut)
def create_patient(
    payload: schemas.PatientCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    data = payload.model_dump()

    # An empty-string national_id isn't a real NRIC -- treat it the same as
    # "no NRIC provided" (NULL) rather than a real value. Patient.national_id
    # is a nullable unique column: multiple NULLs are fine (SQLite/most DBs
    # never treat NULL as equal to NULL for a unique constraint), but two
    # patients both stored with national_id="" WOULD collide as a genuine
    # duplicate -- that's a modeling bug, not a real duplicate NRIC.
    if data.get("national_id") == "":
        data["national_id"] = None

    # Pre-insert uniqueness check, dash/case-tolerant (matches the NRIC
    # normalization used everywhere else NRICs are compared -- see
    # nric.normalize_nric / auth_router._resolve_patient_by_nric, reused
    # here as an indexed lookup rather than a fetch-every-patient loop --
    # Security Audit M2), so a request that differs only by dashes or case
    # still gets caught here with a clean message instead of slipping
    # through to a raw DB IntegrityError. (normalized_national_id itself is
    # populated automatically by models.Patient's @validates hook below,
    # once national_id is assigned via **data -- nothing to set here.)
    if data.get("national_id") and _resolve_patient_by_nric(db, data["national_id"]) is not None:
        raise HTTPException(
            status_code=400,
            detail="This NRIC is already registered to another patient.",
        )

    # Derive date_of_birth from the NRIC itself rather than trusting a
    # hand-typed value -- a standard Malaysian NRIC's first 6 digits ALREADY
    # encode the holder's birthdate (see ai/nric_ocr.py::dob_from_ic_number),
    # so when it's present and resolves cleanly, it's treated as the
    # authoritative source and OVERRIDES whatever date_of_birth the client
    # sent (same "never trust a client-supplied identity field the server
    # can derive itself" philosophy self_registration.py already applies to
    # its OCR checks). dob_from_ic_number needs a bare-digits string --
    # national_id here may be dash-formatted ("520314-01-1234") -- so strip
    # non-digits first.
    if data.get("national_id"):
        ic_digits = re.sub(r"\D", "", data["national_id"])
        derived_dob = dob_from_ic_number(ic_digits)
        if derived_dob:
            data["date_of_birth"] = derived_dob

    # Fallback: no national_id at all, or one that doesn't resolve to a
    # plausible date (non-standard/unparseable NRIC) -- fall back to
    # requiring the client-supplied date_of_birth, same as this endpoint's
    # pre-existing behaviour before NRIC-derived DOB was added.
    if not data.get("date_of_birth"):
        raise HTTPException(
            status_code=400,
            detail="Date of birth is required — provide a valid Malaysian NRIC to auto-detect it, or enter date of birth directly.",
        )

    patient = models.Patient(**data)
    db.add(patient)
    try:
        db.commit()
    except IntegrityError:
        # Safety net for the pre-check above (e.g. a concurrent request
        # that snuck in between the check and this commit) -- never let a
        # raw sqlalchemy.exc.IntegrityError escape as a plain-text 500.
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="This NRIC is already registered to another patient.",
        )
    db.refresh(patient)
    log_access(db, patient.id, current_user.id, current_user.role, "create_patient",
               actor_facility=current_user.facility)
    return patient


# Security Audit H2: the set of tables/columns that establish "this
# facility has an actual relationship to this patient" -- an encounter, a
# clinical sub-record it authored, an admission, a queue ticket, or a
# scheduled appointment there. Deliberately broad/inclusive (any one source
# counts) -- the goal is "has this facility ever legitimately touched this
# patient", not a single stricter source of truth. Shared by both helpers
# below so the definition can't drift between the bulk (list) and
# single-patient (detail) forms of the same check.
_FACILITY_RELATIONSHIP_SOURCES = (
    (models.Encounter, models.Encounter.facility_name),
    (models.Condition, models.Condition.authored_by_facility),
    (models.MedicationStatement, models.MedicationStatement.recorded_by_facility),
    (models.AllergyIntolerance, models.AllergyIntolerance.authored_by_facility),
    (models.Admission, models.Admission.facility_name),
    (models.QueueTicket, models.QueueTicket.facility_name),
    (models.Appointment, models.Appointment.facility_name),
)


def _facility_known_patient_ids_select(facility: str):
    """Bulk form: a `SELECT patient_id ...` UNION over every
    _FACILITY_RELATIONSHIP_SOURCES table for `facility`, returned as a
    subquery-able selectable (NOT executed here).

    list_patients composes this straight into `Patient.id.in_(...)` so the
    whole default scope -- filter, ORDER BY, LIMIT/OFFSET -- runs in one
    database round-trip. Previously this ran 7 separate `SELECT DISTINCT`
    queries, unioned them into a Python set, then passed the entire set back
    as a literal `IN (...)` list (thousands of bind params at a large
    facility, and the DISTINCT scans happened in full regardless of the
    page requested). Code-review follow-up 2026-09-07 -- backed by the new
    facility-column indexes in migration d5e8a1c4b6f2."""
    return union(
        *(
            select(model.patient_id).where(facility_col == facility)
            for model, facility_col in _FACILITY_RELATIONSHIP_SOURCES
        )
    ).subquery()


def _patient_known_to_facility(db: Session, patient_id: str, facility: str) -> bool:
    """Single-patient form: cheap existence check (short-circuits on the
    first match) for get_patient_full_record's cross-facility audit flag --
    deliberately NOT built from _facility_known_patient_ids_select and a
    membership test, which would scan the facility's ENTIRE patient set just
    to answer one yes/no question on every detail view."""
    for model, facility_col in _FACILITY_RELATIONSHIP_SOURCES:
        hit = (
            db.query(model.patient_id)
            .filter(model.patient_id == patient_id, facility_col == facility)
            .first()
        )
        if hit is not None:
            return True
    return False


_LIST_PATIENTS_MAX_LIMIT = 200


@router.get("", response_model=List[schemas.PatientOut])
def list_patients(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=_LIST_PATIENTS_MAX_LIMIT),
    break_glass_reason: Optional[str] = Query(
        None,
        description=(
            "Supply a non-blank reason to override the default facility scope "
            "and browse every patient in the system. Logged prominently "
            "(action=list_patients_break_glass) -- use only for a genuine "
            "cross-facility need, not routine browsing."
        ),
    ),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Security Audit H2: default-scoped to patients this user's facility
    actually has a relationship to (see _facility_known_patient_ids_select),
    never the whole system. `break_glass_reason` is the explicit, audited escape
    hatch for a genuine cross-facility need (e.g. a records officer
    tracking down a transferred patient's chart) -- unlike
    get_patient_full_record's allow-and-log design for a single patient
    (no emergency urgency justifies browsing EVERYONE unscoped, so this one
    default-denies instead). No admin override on the scoping itself --
    admin still needs break_glass_reason like anyone else, consistent with
    every other cross-facility guard in this codebase (see
    _guard_cross_facility_amend's docstring)."""
    query = db.query(models.Patient).order_by(models.Patient.full_name)

    if break_glass_reason and break_glass_reason.strip():
        log_access(
            db, None, current_user.id, current_user.role, "list_patients_break_glass",
            detail=break_glass_reason.strip(), actor_facility=current_user.facility,
        )
        return query.offset(skip).limit(limit).all()

    if not current_user.facility:
        return []
    known = _facility_known_patient_ids_select(current_user.facility)
    return (
        query.filter(models.Patient.id.in_(select(known.c.patient_id)))
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{patient_id}")
def get_patient_full_record(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # patients may only view their own record
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's record")

    # Security Audit H2: unlike list_patients (default-denied, no emergency
    # urgency to browsing everyone), a single-patient lookup stays fully
    # open -- CLARION's whole cross-hospital-continuity premise depends on
    # a walk-in/emergency patient's history being reachable at ANY
    # facility, and blocking that here could cost real time. Instead this
    # is the "allow, but log conspicuously" break-glass pattern real EHRs
    # use: a staff caller (not admin/records_officer/clinician viewing
    # their OWN facility's known patient, and not the patient themself)
    # gets a DISTINCT, clearly-labelled audit action so a cross-facility
    # view is fully reviewable after the fact rather than either blocked
    # or indistinguishable from a routine local lookup.
    is_cross_facility = (
        current_user.role != "patient"
        and (not current_user.facility or not _patient_known_to_facility(db, patient_id, current_user.facility))
    )
    log_access(
        db, patient_id, current_user.id, current_user.role,
        "view_full_record_cross_facility" if is_cross_facility else "view_full_record",
        fields=["all"], actor_facility=current_user.facility,
    )
    return _serialize_patient(patient, db, current_user)


# Each of the four per-resource serializers below takes (row, db, current_user)
# so it can attach the two cross-facility-immutability fields:
#   - authored_by_facility: which facility owns (authored) this row, read
#     from whichever column holds it for that resource type
#     (_row_author_facility). NULL for legacy rows.
#   - editable: True iff the acting user's facility == authored_by_facility
#     AND the patient is currently present at that facility (_record_editable).
#     Always False when there is no user context (emergency scan passes
#     current_user=None).
def _serialize_condition(c: models.Condition, db: Session, current_user, anns=(), present_here=None) -> dict:
    ann_list = list(anns or [])
    return {
        "id": c.id, "name": c.name, "status": c.status,
        "diagnosed_at": c.diagnosed_at, "is_chronic": c.is_chronic,
        "critical_for_emergency": c.critical_for_emergency,
        "authored_by_facility": c.authored_by_facility,
        "editable": _record_editable(db, c.patient_id, c, current_user, present_here),
        # Computed, immutability-safe: a `resolved` annotation folds through
        # to effective_status without ever touching the `status` column
        # (which stays whatever its authoring facility set).
        "effective_status": "resolved" if any(a.kind == "resolved" for a in ann_list) else c.status,
        "annotations": _annotation_dicts(ann_list),
    }


def _serialize_medication(m: models.MedicationStatement, db: Session, current_user, anns=(), present_here=None) -> dict:
    ann_list = list(anns or [])
    return {
        "id": m.id, "drug_name": m.drug_name, "dosage": m.dosage,
        "frequency": m.frequency, "prescribed_by_facility": m.prescribed_by_facility,
        "start_date": m.start_date, "active": m.active,
        "critical_for_emergency": m.critical_for_emergency,
        # The recording facility is the author for edit-rights; the prescriber
        # (prescribed_by_facility, above) may be a different / external one.
        "authored_by_facility": m.recorded_by_facility,
        "editable": _record_editable(db, m.patient_id, m, current_user, present_here),
        # Computed, immutability-safe: a `discontinued` annotation folds
        # through to effective_active without touching the `active` column.
        "effective_active": False if any(a.kind == "discontinued" for a in ann_list) else m.active,
        "annotations": _annotation_dicts(ann_list),
    }


def _serialize_allergy(a: models.AllergyIntolerance, db: Session, current_user, anns=(), present_here=None) -> dict:
    ann_list = list(anns or [])
    return {
        "id": a.id, "substance": a.substance, "reaction": a.reaction,
        "severity": a.severity, "critical_for_emergency": a.critical_for_emergency,
        "authored_by_facility": a.authored_by_facility,
        "editable": _record_editable(db, a.patient_id, a, current_user, present_here),
        "annotations": _annotation_dicts(ann_list),
    }


def _serialize_encounter(e: models.Encounter, db: Session, current_user, anns=(), present_here=None) -> dict:
    ann_list = list(anns or [])
    return {
        "id": e.id, "facility_name": e.facility_name, "encounter_type": e.encounter_type,
        "reason": e.reason, "notes": e.notes, "started_at": str(e.started_at),
        # facility_name doubles as the author facility for encounters.
        "authored_by_facility": e.facility_name,
        "editable": _record_editable(db, e.patient_id, e, current_user, present_here),
        # Consultation sign-off metadata (routers/consultation.py) -- all
        # None for an encounter created any other way. signature_url points
        # at the signer's current profile signature for a "signed by Dr X"
        # thumbnail (the per-encounter snapshot copy on disk isn't served).
        "signed_by": e.signed_by,
        "signed_by_name": e.signed_by_name,
        "signed_by_role": e.signed_by_role,
        "signature_url": f"/staff/{e.signed_by}/signature" if e.signed_by else None,
        "annotations": _annotation_dicts(ann_list),
    }


def _guard_cross_facility_amend(db: Session, patient_id: str, row, current_user, record_type: str):
    """Enforce the cross-hospital immutability rule on a PATCH to a clinical
    sub-record: the amend is allowed ONLY when the acting user's facility is
    the row's authoring facility AND the patient is currently present there
    (_record_editable is exactly that AND). Otherwise 403 -- with a message
    that points the caller at the real correction mechanism (append a new
    entry via the still-open POST endpoint).

    Deliberately NO global admin override: an admin at a non-owning facility
    is blocked the same as anyone else (they can add a new entry); an admin
    AT the owning facility with the patient present is already allowed by the
    rule. The existing role gate on the endpoint is unchanged.

    The denied attempt is written to the audit log too -- this codebase
    already logs failed/denied access elsewhere (see the emergency-scan
    'emergency_access_failed' entries), and a blocked cross-facility edit
    attempt is exactly the kind of event a patient's audit trail should show.
    """
    if _record_editable(db, patient_id, row, current_user):
        return
    owner = _row_author_facility(row)
    log_access(
        db, patient_id, current_user.id, current_user.role, f"update_{record_type}_denied",
        detail=f"{record_type} authored by {owner or 'unknown facility'}; "
               f"acting facility {current_user.facility or 'none'}",
        actor_facility=current_user.facility,
    )
    raise HTTPException(
        status_code=403,
        detail=(
            f"This {record_type} was recorded by {owner or 'another facility'} and can only be "
            "amended there while the patient is checked in. Add a new entry to record a change."
        ),
    )


@router.post("/{patient_id}/conditions")
def add_condition(
    patient_id: str, payload: schemas.ConditionCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # Stamp the authoring facility from the acting user (append-a-new-entry is
    # the cross-facility correction mechanism, and each new row records who
    # authored it). Legacy rows keep NULL and stay PATCH-immutable.
    condition = models.Condition(
        patient_id=patient_id, authored_by_facility=current_user.facility, **payload.model_dump()
    )
    db.add(condition)
    db.commit()
    # Security Audit M8: log the new row's id, never the clinical value
    # (diagnosis name) -- the audit store must not become a second, less-
    # controlled copy of clinical data. Same as the update_* endpoints.
    log_access(db, patient_id, current_user.id, current_user.role, "add_condition", detail=condition.id,
               actor_facility=current_user.facility)
    return {"status": "ok"}


@router.patch("/{patient_id}/conditions/{condition_id}")
def update_condition(
    patient_id: str, condition_id: str, payload: schemas.ConditionUpdate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    condition = (
        db.query(models.Condition)
        .filter(models.Condition.id == condition_id, models.Condition.patient_id == patient_id)
        .first()
    )
    if not condition:
        raise HTTPException(status_code=404, detail="Condition not found")

    # Cross-hospital immutability: only the authoring facility may amend, and
    # only while the patient is currently present there (403 otherwise).
    _guard_cross_facility_amend(db, patient_id, condition, current_user, "condition")

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(condition, field, value)

    if submitted_fields:
        db.add(condition)
        db.commit()
        db.refresh(condition)

    log_access(
        db, patient_id, current_user.id, current_user.role, "update_condition",
        fields=sorted(submitted_fields.keys()), detail=condition_id,
        actor_facility=current_user.facility,
    )
    return _serialize_condition(
        condition, db, current_user, _annotations_for_target(db, patient_id, condition.id)
    )


@router.post("/{patient_id}/medications")
def add_medication(
    patient_id: str, payload: schemas.MedicationCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # prescribed_by_facility stays whatever the client sent (it's the -- often
    # external -- prescriber, e.g. a clinic the patient also attends; that's
    # what the cross-facility duplicate-prescription check keys on). The
    # authoring facility for edit-rights is recorded_by_facility, stamped from
    # the acting user and never client-supplied; None when the user has no
    # facility (mirrors add_condition/add_allergy -- an unattributable row is
    # PATCH-immutable to everyone rather than forgeable).
    med_data = payload.model_dump()
    med = models.MedicationStatement(
        patient_id=patient_id,
        recorded_by_facility=current_user.facility or None,
        **med_data,
    )
    db.add(med)
    db.commit()
    # Security Audit M8: log the row id, not the drug name.
    log_access(db, patient_id, current_user.id, current_user.role, "add_medication", detail=med.id,
               actor_facility=current_user.facility)
    return {"status": "ok"}


@router.patch("/{patient_id}/medications/{medication_id}")
def update_medication(
    patient_id: str, medication_id: str, payload: schemas.MedicationUpdate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    med = (
        db.query(models.MedicationStatement)
        .filter(models.MedicationStatement.id == medication_id, models.MedicationStatement.patient_id == patient_id)
        .first()
    )
    if not med:
        raise HTTPException(status_code=404, detail="Medication not found")

    _guard_cross_facility_amend(db, patient_id, med, current_user, "medication")

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(med, field, value)

    if submitted_fields:
        db.add(med)
        db.commit()
        db.refresh(med)

    log_access(
        db, patient_id, current_user.id, current_user.role, "update_medication",
        fields=sorted(submitted_fields.keys()), detail=medication_id,
        actor_facility=current_user.facility,
    )
    return _serialize_medication(
        med, db, current_user, _annotations_for_target(db, patient_id, med.id)
    )


@router.post("/{patient_id}/allergies")
def add_allergy(
    patient_id: str, payload: schemas.AllergyCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    allergy = models.AllergyIntolerance(
        patient_id=patient_id, authored_by_facility=current_user.facility, **payload.model_dump()
    )
    db.add(allergy)
    db.commit()
    # Security Audit M8: log the row id, not the allergen substance.
    log_access(db, patient_id, current_user.id, current_user.role, "add_allergy", detail=allergy.id,
               actor_facility=current_user.facility)
    return {"status": "ok"}


@router.patch("/{patient_id}/allergies/{allergy_id}")
def update_allergy(
    patient_id: str, allergy_id: str, payload: schemas.AllergyUpdate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    allergy = (
        db.query(models.AllergyIntolerance)
        .filter(models.AllergyIntolerance.id == allergy_id, models.AllergyIntolerance.patient_id == patient_id)
        .first()
    )
    if not allergy:
        raise HTTPException(status_code=404, detail="Allergy not found")

    _guard_cross_facility_amend(db, patient_id, allergy, current_user, "allergy")

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(allergy, field, value)

    if submitted_fields:
        db.add(allergy)
        db.commit()
        db.refresh(allergy)

    log_access(
        db, patient_id, current_user.id, current_user.role, "update_allergy",
        fields=sorted(submitted_fields.keys()), detail=allergy_id,
        actor_facility=current_user.facility,
    )
    return _serialize_allergy(
        allergy, db, current_user, _annotations_for_target(db, patient_id, allergy.id)
    )


@router.post("/{patient_id}/encounters")
def add_encounter(
    patient_id: str, payload: schemas.EncounterCreate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Recording a transfer/visit here is what powers the 'what changed since
    last visit' transfer view on the web console."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    # facility_name doubles as the authoring facility -- force it from the
    # acting user (fall back to the client-supplied value only when the user
    # has no facility, since the column is NOT NULL).
    enc_data = payload.model_dump()
    enc_data["facility_name"] = current_user.facility or enc_data["facility_name"]
    encounter = models.Encounter(patient_id=patient_id, **enc_data)
    db.add(encounter)
    db.commit()
    # Security Audit M8: log the row id (the authoring facility is already
    # captured as actor_facility), not free-text pulled from the payload.
    log_access(db, patient_id, current_user.id, current_user.role, "add_encounter", detail=encounter.id,
               actor_facility=current_user.facility)
    return {"status": "ok"}


@router.patch("/{patient_id}/encounters/{encounter_id}")
def update_encounter(
    patient_id: str, encounter_id: str, payload: schemas.EncounterUpdate, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Staff-only edit/correction for an existing encounter (e.g. fixing a
    typo'd reason/notes after the fact) -- the POST above stays create-only,
    this is what backs an eventual 'edit visit' UI action."""
    encounter = (
        db.query(models.Encounter)
        .filter(models.Encounter.id == encounter_id, models.Encounter.patient_id == patient_id)
        .first()
    )
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    _guard_cross_facility_amend(db, patient_id, encounter, current_user, "encounter")

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(encounter, field, value)

    if submitted_fields:
        db.add(encounter)
        db.commit()
        db.refresh(encounter)

    log_access(
        db, patient_id, current_user.id, current_user.role, "update_encounter",
        fields=sorted(submitted_fields.keys()), detail=encounter_id,
        actor_facility=current_user.facility,
    )
    return _serialize_encounter(
        encounter, db, current_user, _annotations_for_target(db, patient_id, encounter.id)
    )


@router.patch("/{patient_id}/profile", response_model=schemas.PatientOut)
def update_own_profile(
    patient_id: str,
    payload: schemas.PatientProfileUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Self-service only, for now: a patient editing their OWN contact
    profile (email/phone/emergency contact). No staff-editing variant here
    by design -- out of scope for this pass.

    full_name / date_of_birth / national_id are immutable via self-service
    identity fields: a request that tries to set any of them is explicitly
    rejected with a clear 400, not silently ignored, so a caller isn't
    misled into thinking an identity-field change actually took effect.
    """
    if current_user.role != "patient" or current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot edit another patient's profile")

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    submitted_fields = payload.model_dump(exclude_unset=True)

    attempted_immutable = sorted(set(submitted_fields) & schemas.PATIENT_IMMUTABLE_FIELDS)
    if attempted_immutable:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot change {', '.join(attempted_immutable)} via profile self-service. "
                "These identity fields are immutable outside of staff-mediated changes."
            ),
        )

    changed_fields = []
    for field in schemas.PATIENT_SELF_EDITABLE_FIELDS:
        if field in submitted_fields:
            setattr(patient, field, submitted_fields[field])
            changed_fields.append(field)

    if changed_fields:
        db.add(patient)
        db.commit()
        db.refresh(patient)

    # Log which fields changed, not their new values -- the values
    # themselves are contact PII that shouldn't end up duplicated in a
    # more exposed place (the audit log) than the field already lives.
    log_access(
        db, patient_id, current_user.id, current_user.role, "update_own_profile",
        fields=changed_fields, actor_facility=current_user.facility,
    )
    return patient


@router.get("/{patient_id}/audit-log")
def get_audit_log(
    patient_id: str, db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Patients (and staff) can review exactly who accessed the record and
    when — this is the transparency half of the PDPA-aligned design.

    `actor_name` is resolved via a LIVE join against `users.full_name`
    (not a value stored/snapshotted on the AuditLog row itself) -- see
    models.AuditLog's class docstring for the reasoning: a later name
    correction (typo fix, legal name change) should be reflected in old
    history too, not stay frozen/wrong. `actor_facility`, in contrast, IS a
    snapshot straight off the row (no join needed) -- same docstring covers
    why those two fields are deliberately handled differently.

    `actor` is only ever a real `users.id` for a staff/patient action --
    the "system" actor and the unauthenticated emergency-scan endpoints'
    "emergency_responder:<name>" actor have no matching `User` row at all,
    so the join is skipped for those (and for a staff `User` account that
    has since been deleted, the lookup just degrades to `actor_name=None`
    rather than a 500 -- "who" for that row is still available via the raw
    `actor` id, just not resolvable to a live display name anymore).
    """
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's audit log")

    # Paginated (code-review follow-up 2026-09-07): a long-lived record's
    # audit trail grows without bound and was returned in full on every
    # PatientDetail open. `limit` defaults to 500 -- well above any
    # demo/clinic patient's real history, so the existing "fetch all" web
    # client is unaffected -- and caps the pathological case.
    logs = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.patient_id == patient_id)
        # id tiebreak: keeps ordering deterministic when two rows share a
        # timestamp (P1.2b -- matters most on MariaDB, and as a floor even with
        # DATETIME(6) precision).
        .order_by(models.AuditLog.timestamp.desc(), models.AuditLog.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    # Batch-resolve actor -> full_name in one query instead of one query per
    # row -- skip "system" and "emergency_responder:*" actors up front since
    # neither is ever a real users.id, so there's no point even trying them
    # against the User table.
    real_user_actor_ids = {
        l.actor for l in logs
        if l.actor != "system" and not l.actor.startswith("emergency_responder:")
    }
    actor_names = {}
    if real_user_actor_ids:
        for user_id, full_name in (
            db.query(models.User.id, models.User.full_name)
            .filter(models.User.id.in_(real_user_actor_ids))
            .all()
        ):
            actor_names[user_id] = full_name

    return [
        {
            "actor": l.actor, "actor_role": l.actor_role, "action": l.action,
            "fields_accessed": l.fields_accessed, "timestamp": str(l.timestamp),
            "detail": l.detail,
            # Additive fields -- existing web/mobile clients that only read
            # the keys above keep working unchanged.
            "actor_name": actor_names.get(l.actor),  # None if unresolvable (system/emergency/deleted account)
            "actor_facility": l.actor_facility,
        }
        for l in logs
    ]


def _assert_document_visible_or_404(db: Session, document: models.ClinicalDocument, current_user) -> None:
    """Apply the same records_shared_publicly rule to a single document as
    _serialize_patient applies to its embedded 'documents' list: if the
    uploading facility has opted out of public sharing, a caller at any
    OTHER facility gets the same non-leaking 404 as 'document does not
    exist'. The uploading facility's own staff, and (future) a patient
    viewing their own record, are never filtered."""
    caller_facility = getattr(current_user, "facility", None)
    hidden = _hidden_author_facilities(db, caller_facility)
    if document.uploaded_by_facility in hidden:
        raise HTTPException(status_code=404, detail="Document not found")


def _get_document_or_404(db: Session, patient_id: str, document_id: str) -> models.ClinicalDocument:
    # Check the patient exists first -- there's no FK enforcement between
    # ClinicalDocument.patient_id and Patient.id (SQLite foreign_keys pragma
    # is off), so a bogus patient_id must not silently succeed just because
    # a matching (possibly orphaned) document row happens to exist. Mirrors
    # how the rest of the API treats a nonexistent patient_id (see
    # get_patient_full_record above).
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    document = (
        db.query(models.ClinicalDocument)
        .filter(models.ClinicalDocument.id == document_id, models.ClinicalDocument.patient_id == patient_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/{patient_id}/documents/{document_id}")
def get_document_detail(
    patient_id: str, document_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Full document detail, including the (potentially large) raw_text OCR
    dump and ai_summary -- deliberately NOT part of _serialize_patient's
    'documents' summary list, fetched here on demand instead. Staff-only,
    same roles as the AI handover-brief/interaction-check endpoints -- a
    patient viewing their own record does not get document detail access in
    this pass."""
    document = _get_document_or_404(db, patient_id, document_id)
    _assert_document_visible_or_404(db, document, current_user)

    log_access(db, patient_id, current_user.id, current_user.role, "view_document", detail=document_id,
               actor_facility=current_user.facility)
    return {
        "id": document.id,
        "doc_type": document.doc_type,
        "original_filename": document.original_filename,
        "uploaded_by_facility": document.uploaded_by_facility,
        "uploaded_at": str(document.uploaded_at),
        "raw_text": document.raw_text,
        "ai_summary": document.ai_summary,
        # Whether the ORIGINAL uploaded file (not just its OCR'd text) can be
        # fetched from GET .../documents/{document_id}/file below. False for
        # any document uploaded before file persistence existed, or if the
        # object write failed at upload time.
        "file_available": bool(document.file_object_key),
        # Whether GET .../thumbnail can return a preview -- true only for a
        # stored original whose recorded mime is a raster image (never a PDF).
        "thumbnail_available": bool(document.file_object_key)
        and (document.file_mime or "").startswith("image/"),
    }


@router.get("/{patient_id}/documents/{document_id}/file")
def get_document_file(
    patient_id: str, document_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Serves back the original uploaded file (X-ray image, scanned lab
    report, etc.) as persisted by POST /ai/digitise/{patient_id}. 404 if no
    file was ever persisted for this document (e.g. uploaded before this
    endpoint existed) -- only the OCR'd raw_text is available in that case,
    via GET /patients/{patient_id}/documents/{document_id} above."""
    document = _get_document_or_404(db, patient_id, document_id)
    _assert_document_visible_or_404(db, document, current_user)

    if not document.file_object_key:
        raise HTTPException(status_code=404, detail="Original file not available for this document")

    try:
        stream = get_object_store().open_stream(BUCKET_DOCUMENTS, document.file_object_key)
    except (ObjectNotFound, ValueError):
        raise HTTPException(status_code=404, detail="Original file not available for this document")
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="Document storage is temporarily unavailable.")

    # If anything below fails before the StreamingResponse is handed back,
    # close the iterator so the backend connection/handle it opened is
    # released (a created-but-never-consumed generator would otherwise leak).
    try:
        log_access(db, patient_id, current_user.id, current_user.role, "view_document_file", detail=document_id,
                   actor_facility=current_user.facility)
    except Exception:
        stream.close()
        raise

    # Content-Type is guessed from the sanitized object key
    # (document.file_object_key ends "{document_id}_{safe_basename}", built
    # server-side by POST /ai/digitise/{patient_id}), NEVER from the
    # attacker-controlled document.original_filename -- otherwise a file
    # uploaded as e.g. "evil.html" would be served back with Content-Type:
    # text/html and execute in this app's own origin when opened by staff
    # (stored XSS). Anything outside the small allowlist of types this app
    # actually needs falls back to application/octet-stream, which browsers
    # only download.
    guessed_type, _ = mimetypes.guess_type(document.file_object_key)
    media_type = guessed_type if guessed_type in SAFE_DOCUMENT_MEDIA_TYPES else "application/octet-stream"

    safe_download_name = sanitize_filename(
        document.original_filename, fallback=f"document_{document_id}"
    )
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_download_name}"',
        "X-Content-Type-Options": "nosniff",
    }
    if document.file_bytes:
        headers["Content-Length"] = str(document.file_bytes)
    return StreamingResponse(stream, media_type=media_type, headers=headers)


@router.get("/{patient_id}/documents/{document_id}/thumbnail")
def get_document_thumbnail(
    patient_id: str, document_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """A 300px JPEG preview of an image document (P1.7). Same roles +
    cross-facility visibility gate as GET .../file. 404 when the document has
    no stored original, or the original is a PDF / not a decodable raster
    image. The preview is regenerated from the original on a cache miss, so it
    is never authoritative and the WORM original is never touched."""
    document = _get_document_or_404(db, patient_id, document_id)
    _assert_document_visible_or_404(db, document, current_user)

    if not document.file_object_key:
        raise HTTPException(status_code=404, detail="No preview available for this document")
    try:
        thumb = get_or_make_thumbnail(
            BUCKET_DOCUMENTS, document.file_object_key, sha256=document.file_sha256
        )
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="Document storage is temporarily unavailable.")
    if thumb is None:
        raise HTTPException(status_code=404, detail="No preview available for this document")

    log_access(db, patient_id, current_user.id, current_user.role, "view_document_thumbnail",
               detail=document_id, actor_facility=current_user.facility)
    return Response(
        content=thumb, media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


# ---------------------------------------------------------------------------
# Clinical-record annotations (append-only sign-off) -- see
# models.ClinicalRecordAnnotation + the serializer helpers near the top.
# ---------------------------------------------------------------------------
_ANNOTATION_MODEL = {
    "condition": models.Condition,
    "medication": models.MedicationStatement,
    "allergy": models.AllergyIntolerance,
    "encounter": models.Encounter,
}

# kind -> the one target_type it is valid for (kinds not listed here --
# 'correction', 'note' -- are valid against any target).
_ANNOTATION_KIND_REQUIRES_TARGET = {
    "resolved": "condition",
    "discontinued": "medication",
}


@router.post("/{patient_id}/annotations")
def add_record_annotation(
    patient_id: str,
    payload: schemas.RecordAnnotationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Append a signed annotation to one of the patient's clinical
    sub-records. Append-only -- there is no update/delete. REQUIRES a saved
    digital signature (routers/profile.py); pass `signature_b64` to save one
    on the spot if you have none yet.

    `resolved` is only valid against a condition and `discontinued` only
    against a medication (400 otherwise) -- those two kinds are what the
    read path folds into a computed effective_status / effective_active."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    required_target = _ANNOTATION_KIND_REQUIRES_TARGET.get(payload.kind)
    if required_target and payload.target_type != required_target:
        raise HTTPException(
            status_code=400,
            detail=f"kind '{payload.kind}' is only valid for a {required_target} record.",
        )

    model = _ANNOTATION_MODEL[payload.target_type]
    target = db.query(model).filter(model.id == payload.target_id).first()
    if target is None or target.patient_id != patient_id:
        raise HTTPException(status_code=404, detail="Target record not found for this patient.")

    if not current_user.signature_object_key and not payload.signature_b64:
        raise HTTPException(
            status_code=409,
            detail="Save your signature in your profile before signing off a record annotation.",
        )
    if payload.signature_b64 and not current_user.signature_object_key:
        save_signature_from_b64(db, current_user, payload.signature_b64)

    annotation = models.ClinicalRecordAnnotation(
        patient_id=patient_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        kind=payload.kind,
        note=payload.note,
        signed_by=current_user.id,
        signed_by_name=current_user.full_name,
        signed_by_role=current_user.role,
        facility_name=current_user.facility,
    )
    db.add(annotation)
    db.flush()  # need annotation.id for the per-row signature snapshot key

    apply_object_meta(
        annotation,
        copy_signature_snapshot(current_user, f"annotations/{annotation.id}.png"),
        "signature",
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)

    log_access(
        db, patient_id, current_user.id, current_user.role, "add_record_annotation",
        detail=f"{payload.target_type}:{payload.kind}", actor_facility=current_user.facility,
    )
    return _serialize_annotation(annotation)


@router.get("/{patient_id}/annotations")
def list_record_annotations(
    patient_id: str,
    db: Session = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """Every annotation on this patient's records, newest first. Paginated
    (code-review follow-up 2026-09-07) with a generous default so the
    existing "fetch all" client is unaffected."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    rows = (
        db.query(models.ClinicalRecordAnnotation)
        .filter(models.ClinicalRecordAnnotation.patient_id == patient_id)
        .order_by(models.ClinicalRecordAnnotation.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_serialize_annotation(a) for a in rows]


@router.get("/{patient_id}/annotations/{annotation_id}/signature")
def get_annotation_signature(
    patient_id: str,
    annotation_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """The signature PNG snapshotted onto this annotation at signing time.
    The object key is read from the DB column only; served with nosniff. 404
    if the annotation isn't this patient's or has no snapshot stored."""
    annotation = (
        db.query(models.ClinicalRecordAnnotation)
        .filter(
            models.ClinicalRecordAnnotation.id == annotation_id,
            models.ClinicalRecordAnnotation.patient_id == patient_id,
        )
        .first()
    )
    if annotation is None or not annotation.signature_object_key:
        raise HTTPException(status_code=404, detail="Signature not found.")
    try:
        data = get_object_store().get_checked(
            BUCKET_SIGNATURES, annotation.signature_object_key, annotation.signature_sha256
        )
    except (ObjectNotFound, ValueError):
        raise HTTPException(status_code=404, detail="Signature not found.")
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="Signature storage is temporarily unavailable.")

    return Response(
        content=data, media_type="image/png",
        headers={"X-Content-Type-Options": "nosniff"},
    )
