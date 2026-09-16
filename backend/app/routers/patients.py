import hashlib
import mimetypes
import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_, select
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
from ..derived import ALLOWED_THUMBNAIL_SIZES, get_or_make_thumbnail
from ..document_generation import render_document
from ..campus_registry import check_eligibility
from ..clinical_access import (
    _facility_known_patient_ids_select,
    _hidden_author_facilities,
    _patient_known_to_facility,
    _patient_present_at,
    _record_editable,
    _row_author_facility,
)
from .auth_router import _resolve_patient_by_nric
from .appointments import _booked_times_for_clinician, _clinicians_for
from ..appointments import compute_available_slots
from .profile import save_signature_from_b64, copy_signature_snapshot, photo_response

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


# Cross-hospital clinical-record immutability helpers (_row_author_facility,
# _patient_present_at, _record_editable, _hidden_author_facilities) now live
# in ..clinical_access -- imported above, shared with every other clinical
# router instead of being reached into here as "private" functions.

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

    # P3.10: one batched query for every signed-off ConsultationNote
    # (vitals + SOAP text) on this patient's encounters, keyed by
    # encounter_id -- same "one query, not one per row" discipline as
    # ann_groups above, rather than letting _serialize_encounter lazy-load
    # Encounter.consultation_note per encounter (an N+1 the P3.1 review
    # round already flagged this codebase for elsewhere).
    encounter_ids = [e.id for e in p.encounters]
    notes_by_encounter = (
        {
            n.encounter_id: n
            for n in db.query(models.ConsultationNote)
            .filter(models.ConsultationNote.encounter_id.in_(encounter_ids))
            .all()
        }
        if encounter_ids else {}
    )

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
            _serialize_encounter(e, db, current_user, ann_groups.get(e.id), present_here, notes_by_encounter.get(e.id))
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


@router.get("/announcements", response_model=List[schemas.AnnouncementOut])
def list_announcements(
    facility_name: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """P3.10: currently-live announcements for one facility
    (`starts_at` already passed, `expires_at` NULL or still in the future).
    Any authenticated caller may query this -- same "publicly-relevant, not
    patient-specific" posture as GET /patients/appointment-slots; management
    (unfiltered, admin-only) is GET /admin/announcements."""
    now = datetime.now(timezone.utc)
    rows = (
        db.query(models.Announcement)
        .filter(
            models.Announcement.facility_name == facility_name,
            models.Announcement.starts_at <= now,
            or_(models.Announcement.expires_at.is_(None), models.Announcement.expires_at >= now),
        )
        .order_by(models.Announcement.starts_at.desc())
        .all()
    )
    return [schemas.AnnouncementOut.model_validate(r) for r in rows]


@router.get("/appointment-slots", response_model=List[schemas.AppointmentSlotOut])
def list_appointment_slots(
    facility_name: str,
    date: str,
    department: Optional[str] = None,
    clinician_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """P3.10: bookable slots for a given day (Malaysia-local
    `date`, "YYYY-MM-DD"). Any authenticated caller may query this -- it
    discloses only which times are free, the same "publicly-relevant
    scheduling info" posture as GET /display/{token}. Union of every
    matching clinician's free slots (see appointments.py's _clinicians_for)
    when clinician_id isn't pinned, so a patient picking "any doctor" still
    sees a real, bookable time per row.

    Deliberately defined HERE, not on appointments.router (which also
    mounts under the "/patients" prefix) -- appointments.router is included
    into the app AFTER this router (see main.py), so a literal route
    registered there would be shadowed by GET /{patient_id} below matching
    "appointment-slots" as a patient_id first. Every literal top-level
    /patients/... route (this one, /announcements, /booking-options) must
    stay in THIS router, ahead of /{patient_id}, for the same reason."""
    try:
        local_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    clinicians = _clinicians_for(db, facility_name, department, clinician_id)
    if clinician_id and not clinicians:
        raise HTTPException(status_code=404, detail="Clinician not found for that facility/department")

    results: list[schemas.AppointmentSlotOut] = []
    for clinician in clinicians:
        booked = _booked_times_for_clinician(db, clinician.id)
        for slot in compute_available_slots(local_date, booked):
            results.append(schemas.AppointmentSlotOut(
                scheduled_at=slot, clinician_id=clinician.id, clinician_name=clinician.full_name,
            ))
    results.sort(key=lambda s: (s.scheduled_at, s.clinician_name or ""))
    return results


@router.get("/booking-options", response_model=schemas.BookingOptionsOut)
def list_booking_options(
    facility_name: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """P3.10: the department + clinician pickers a patient's
    self-booking flow needs, at one facility. Same visibility posture as
    list_appointment_slots above (and same reason this lives here, not on
    appointments.router)."""
    departments = [
        name for (name,) in db.query(models.FacilitySection.name)
        .filter(models.FacilitySection.facility_name == facility_name, models.FacilitySection.active.is_(True))
        .order_by(models.FacilitySection.name.asc())
        .all()
    ]
    clinicians = (
        db.query(models.User)
        .filter(models.User.role == "clinician", models.User.facility == facility_name)
        .order_by(models.User.full_name.asc())
        .all()
    )
    return schemas.BookingOptionsOut(
        departments=departments,
        clinicians=[
            schemas.BookingClinicianOut(
                id=c.id, full_name=c.full_name, department=c.section,
                bio=c.bio, has_photo=bool(c.photo_object_key),
            )
            for c in clinicians
        ],
    )


@router.get("/clinicians/{clinician_id}/photo")
def get_clinician_photo(
    clinician_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """A clinician's profile photo for the self-booking picker (P3.10).
    Deliberately as open as GET /booking-options above (any authenticated
    user, patients included) -- this is the PUBLIC half of the profile
    photo feature; see routers/profile.py::get_staff_photo for the
    facility-scoped colleague-only version. Only ever serves a role="clinician"
    row -- never leaks another staff member's photo through this path."""
    target = (
        db.query(models.User)
        .filter(models.User.id == clinician_id, models.User.role == "clinician")
        .first()
    )
    if target is None or not target.photo_object_key:
        raise HTTPException(status_code=404, detail="Photo not found.")

    return photo_response(
        target.photo_object_key,
        sha256=target.photo_sha256,
        not_found_detail="Photo not found.",
    )


@router.get("/campus-eligibility/{nric}")
async def check_campus_eligibility(
    nric: str,
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """New-patient eligibility check against the University's SMP/SMS/e-klinik panel /
    Registrar system -- called from the "New Patient"
    intake form before/while filling it in. Same role list as create_patient
    (this router isn't reachable by `receptionist` by default -- see
    permissions.py::DEFAULT_ROLE_PAGES -- and patient creation itself is
    already admin/records_officer/clinician only; this check follows that
    existing design rather than opening a new carve-out). Advisory only --
    see app/campus_registry.py, which this app knows nothing real about, is a
    documented mock (2026-09-15), and never blocks patient creation on its
    own."""
    return await check_eligibility(nric)


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
# _FACILITY_RELATIONSHIP_SOURCES / _facility_known_patient_ids_select /
# _patient_known_to_facility now live in ..clinical_access (imported above) --
# register a new clinical module's table there, not here.


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


def _serialize_encounter(
    e: models.Encounter, db: Session, current_user, anns=(), present_here=None, note: "models.ConsultationNote | None" = None,
) -> dict:
    ann_list = list(anns or [])
    return {
        "id": e.id, "facility_name": e.facility_name, "encounter_type": e.encounter_type,
        "reason": e.reason, "notes": e.notes, "started_at": str(e.started_at),
        "department": e.department,
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
        # P3.10: diagnosis/treatment notes + vitals for this
        # visit -- was previously staff-only via GET /consultation/encounters/
        # {id}/note (see that endpoint's docstring: "cross-facility clinical
        # sharing stays centralised in patients.py"). None when the sign-off
        # never recorded structured data (legacy free-text-only encounters).
        "consultation_note": (
            {
                "assessment": note.assessment, "plan": note.plan, "treatment_plan": note.treatment_plan,
                "bp_systolic": note.bp_systolic, "bp_diastolic": note.bp_diastolic,
                "temperature_c": note.temperature_c, "pulse_bpm": note.pulse_bpm,
            }
            if note else None
        ),
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
        # NULL for an uploaded/OCR'd scan -- only set for a P3.5 GENERATED
        # document (Digital MC / Referral Letter / Timeslip).
        "signed_by_name": document.signed_by_name,
        "signed_at": str(document.signed_at) if document.signed_at else None,
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
    request: Request, patient_id: str, document_id: str,
    size: int = Query(300, description="300 = list thumbnail, 1400 = web preview"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """A JPEG preview of a document (P1.7/P1.7b) -- ``size=300`` (default) for
    a list thumbnail, ``size=1400`` for a readable "web preview" that avoids
    pulling a possibly-15MB original over a slow link. Same roles +
    cross-facility visibility gate as GET .../file. An image document is
    downscaled; a PDF gets page 1 rendered. 404 when the document has no
    stored original or neither applies. The preview is regenerated from the
    original on a cache miss, so it is never authoritative and the WORM
    original is never touched. Content-addressed (the derived key folds in
    the source sha256), so a strong ETag + If-None-Match 304 is safe."""
    if size not in ALLOWED_THUMBNAIL_SIZES:
        raise HTTPException(
            status_code=422,
            detail=f"size must be one of: {', '.join(str(s) for s in ALLOWED_THUMBNAIL_SIZES)}",
        )
    document = _get_document_or_404(db, patient_id, document_id)
    _assert_document_visible_or_404(db, document, current_user)

    if not document.file_object_key:
        raise HTTPException(status_code=404, detail="No preview available for this document")
    try:
        thumb = get_or_make_thumbnail(
            BUCKET_DOCUMENTS, document.file_object_key, size=size, sha256=document.file_sha256
        )
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="Document storage is temporarily unavailable.")
    if thumb is None:
        raise HTTPException(status_code=404, detail="No preview available for this document")

    log_access(db, patient_id, current_user.id, current_user.role, "view_document_thumbnail",
               detail=document_id, actor_facility=current_user.facility)

    etag = f'"{hashlib.sha1(thumb, usedforsecurity=False).hexdigest()}"'  # cache-freshness tag only, not a security use
    headers = {
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=300",
    }
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=thumb, media_type="image/jpeg", headers=headers)


@router.get("/{patient_id}/encounters/{encounter_id}/visit-summary.pdf")
def get_visit_summary_pdf(
    patient_id: str,
    encounter_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """P3.10: a read-only PDF rendered on the fly from an
    already-signed Encounter + its ConsultationNote. Deliberately NOT stored
    as a ClinicalDocument the way POST /documents/generate's 3 doc_types
    are -- there is no free-text/staff-entered content being issued here,
    it's fully derived from records that are themselves already immutable,
    so regenerating on every request is simpler than a second WORM copy that
    could drift from the source encounter. The signature drawn on the page
    is the EXISTING per-encounter snapshot taken at sign-off time
    (Encounter.signature_object_key -- see models.Encounter's docstring),
    not a signature belonging to whoever is downloading -- a patient has no
    clinical signature of their own to substitute.

    The patient may fetch their own; staff get the same cross-facility
    visibility rule as get_patient_full_record (a facility that opted out
    of records_shared_publicly can't pull another facility's visit as a PDF
    either)."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    is_own_record = current_user.role == "patient" and current_user.patient_id == patient_id
    if not is_own_record and current_user.role not in ("admin", "records_officer", "clinician"):
        raise HTTPException(status_code=403, detail="Not authorized to view this visit summary")

    encounter = (
        db.query(models.Encounter)
        .filter(models.Encounter.id == encounter_id, models.Encounter.patient_id == patient_id)
        .first()
    )
    # Only a SIGNED encounter is a "visit" worth summarising -- an unsigned/
    # legacy row has no doctor or signature to render.
    if not encounter or not encounter.signed_by:
        raise HTTPException(status_code=404, detail="Visit summary not available")

    if not is_own_record:
        hidden = _hidden_author_facilities(db, current_user.facility)
        if encounter.facility_name in hidden:
            raise HTTPException(status_code=404, detail="Visit summary not available")

    note = (
        db.query(models.ConsultationNote)
        .filter(models.ConsultationNote.encounter_id == encounter_id)
        .first()
    )

    vitals_parts = []
    if note and note.bp_systolic is not None and note.bp_diastolic is not None:
        vitals_parts.append(f"BP {note.bp_systolic}/{note.bp_diastolic} mmHg")
    if note and note.temperature_c is not None:
        vitals_parts.append(f"Temp {note.temperature_c:.1f} °C")
    if note and note.pulse_bpm is not None:
        vitals_parts.append(f"Pulse {note.pulse_bpm} bpm")

    fields = {
        "visit_date": str(encounter.started_at),
        "doctor_name": encounter.signed_by_name,
        "department": encounter.department,
        "vitals_line": ", ".join(vitals_parts) or None,
        "assessment": note.assessment if note else None,
        "plan": note.plan if note else None,
        "treatment_plan": note.treatment_plan if note else None,
    }

    signature_png = None
    if encounter.signature_object_key:
        try:
            signature_png = get_object_store().get_checked(
                BUCKET_SIGNATURES, encounter.signature_object_key, encounter.signature_sha256
            )
        except ObjectStoreError:
            pass  # render without the image rather than failing the whole download

    signed_at = encounter.started_at if isinstance(encounter.started_at, datetime) else datetime.now(timezone.utc)
    pdf_bytes, _plain_text = render_document(
        "visit_summary", patient, fields,
        facility_name=encounter.facility_name,
        signer_name=encounter.signed_by_name or "-",
        signer_role=encounter.signed_by_role,
        signed_at=signed_at,
        signature_png=signature_png,
    )

    log_access(
        db, patient_id, current_user.id, current_user.role, "view_visit_summary_pdf",
        detail=encounter_id, actor_facility=current_user.facility,
    )
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="visit_summary_{encounter_id}.pdf"'},
    )


@router.post("/{patient_id}/documents/generate")
def generate_document(
    patient_id: str,
    payload: schemas.GenerateDocumentRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer", "clinician")),
):
    """P3.5: render a signed Digital Medical Certificate /
    Referral Letter / Timeslip as a PDF and file it as a ClinicalDocument --
    same WORM bucket, same GET .../file /.../thumbnail serving, same
    cross-facility visibility rule as an uploaded scan. REQUIRES a saved
    digital signature, same convention as every other sign-off endpoint
    here; pass `signature_b64` to save one on the spot.

    Unlike the OCR upload path (POST /ai/digitise), a storage failure here
    is NOT best-effort -- there is no independently-already-successful OCR
    result to preserve, so if the PDF can't be persisted the whole issuance
    is rolled back rather than leaving a document row with no file behind
    it (same "never store a half-done write" rule imaging.py's medicine-
    photo path follows)."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    if not current_user.signature_object_key and not payload.signature_b64:
        raise HTTPException(
            status_code=409,
            detail="Save your signature in your profile before generating a signed document.",
        )
    if payload.signature_b64 and not current_user.signature_object_key:
        save_signature_from_b64(db, current_user, payload.signature_b64)

    signature_png = None
    try:
        signature_png = get_object_store().get_checked(
            BUCKET_SIGNATURES, current_user.signature_object_key, current_user.signature_sha256
        )
    except ObjectStoreError:
        pass  # rendered without the image rather than blocking issuance over a storage hiccup

    now = datetime.now(timezone.utc)
    fields = payload.model_dump(exclude={"doc_type", "signature_b64"}, exclude_none=True)
    pdf_bytes, plain_text = render_document(
        payload.doc_type, patient, fields,
        facility_name=current_user.facility,
        signer_name=current_user.full_name,
        signer_role=current_user.role,
        signed_at=now,
        signature_png=signature_png,
    )

    safe_name = sanitize_filename(f"{payload.doc_type}_{now.date().isoformat()}.pdf", fallback="document.pdf")
    doc = models.ClinicalDocument(
        patient_id=patient_id, doc_type=payload.doc_type, original_filename=safe_name,
        raw_text=plain_text, uploaded_by_facility=current_user.facility,
        signed_by=current_user.id, signed_by_name=current_user.full_name, signed_at=now,
    )
    db.add(doc)
    db.flush()  # need doc.id for the object key

    try:
        meta = get_object_store().put(
            BUCKET_DOCUMENTS, f"{patient_id}/{doc.id}_{safe_name}", pdf_bytes, mime="application/pdf",
        )
    except (OSError, ObjectStoreError):
        db.rollback()
        raise HTTPException(status_code=503, detail="Could not store the generated document. Try again.")
    apply_object_meta(doc, meta, "file")
    db.add(doc)
    db.commit()
    db.refresh(doc)

    log_access(
        db, patient_id, current_user.id, current_user.role, "generate_document",
        detail=payload.doc_type, actor_facility=current_user.facility,
    )
    return {"document_id": doc.id, "doc_type": doc.doc_type}


# ---------------------------------------------------------------------------
# Clinical-record annotations (append-only sign-off) -- see
# models.ClinicalRecordAnnotation + the serializer helpers near the top.
# ---------------------------------------------------------------------------
_ANNOTATION_MODEL = {
    "condition": models.Condition,
    "medication": models.MedicationStatement,
    "allergy": models.AllergyIntolerance,
    "encounter": models.Encounter,
    "service_result": models.ServiceResult,
    "dental_chart_entry": models.DentalChartEntry,
    "consultation_note": models.ConsultationNote,
}

# kind -> the one target_type it is valid for (kinds not listed here --
# 'correction', 'note' -- are valid against any target).
_ANNOTATION_KIND_REQUIRES_TARGET = {
    "resolved": "condition",
    "discontinued": "medication",
}

# target_type -> its model's authoring-facility column, for the subset of
# annotation targets whose facility-opt-out this router actually enforces
# (see _exclude_hidden_facility_scoped_annotations below). Both happen to be
# named `facility_name` on their model today; kept as an explicit map rather
# than assuming that, since it's not true of every _ANNOTATION_MODEL entry
# (Condition/AllergyIntolerance use `authored_by_facility`,
# MedicationStatement uses `recorded_by_facility`).
_ANNOTATION_FACILITY_SCOPED_TARGETS = {
    "service_result": (models.ServiceResult, models.ServiceResult.facility_name),
    "dental_chart_entry": (models.DentalChartEntry, models.DentalChartEntry.facility_name),
}


def _exclude_hidden_facility_scoped_annotations(query, db: Session, caller_facility: Optional[str]):
    """Filter OUT ClinicalRecordAnnotation rows targeting a
    _ANNOTATION_FACILITY_SCOPED_TARGETS record whose authoring facility has
    opted out of cross-facility sharing (HospitalSetting.records_shared_publicly)
    -- same opt-out ancillary.py's own reads already respect for the
    underlying ServiceResult (routers/ancillary.py::get_service_request /
    list_service_requests), and dental.py for DentalChartEntry. Fixed
    2026-09-12 (voltagent security audit, P3.1): list_record_annotations had
    no facility scoping at all, so a 'correction' annotation quoting a hidden
    facility's lab/X-ray result was readable here even though the result
    itself is hidden through the ancillary endpoints. Extended to
    dental_chart_entry (P3.2) at the same time it was introduced, rather than
    recreating the same gap for a second type.

    Applied to `query` BEFORE offset/limit -- a first version of this fix
    fetched the page first and filtered hidden rows out in Python, which
    reintroduced the exact under-filled-page/misaligned-offset bug that
    ancillary.py::list_service_requests' own hidden-facility filter was
    fixed for in the same diff this was first written in (caught in review).
    A correlated subquery per target type keeps this a bounded number of
    round trips regardless of page size.

    Deliberately scoped to _ANNOTATION_FACILITY_SCOPED_TARGETS only. The
    other _ANNOTATION_MODEL types (condition/medication/allergy/encounter)
    have no facility scoping here either, but that is a wider PRE-EXISTING
    gap this doesn't touch (tracked in healthcare/Implementation Roadmap.md
    rather than fixed blind, since those endpoints' own direct reads have
    their own established scoping rules this would need to mirror one at a
    time)."""
    hidden = _hidden_author_facilities(db, caller_facility)
    if not hidden:
        return query
    clauses = [models.ClinicalRecordAnnotation.target_type.notin_(list(_ANNOTATION_FACILITY_SCOPED_TARGETS.keys()))]
    for target_type, (model, facility_col) in _ANNOTATION_FACILITY_SCOPED_TARGETS.items():
        hidden_ids = select(model.id).where(facility_col.in_(hidden))
        clauses.append(
            and_(
                models.ClinicalRecordAnnotation.target_type == target_type,
                models.ClinicalRecordAnnotation.target_id.notin_(hidden_ids),
            )
        )
    return query.filter(or_(*clauses))


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
    # ConsultationNote is the one _ANNOTATION_MODEL target with NO cross-
    # facility read at all (consultation.py::get_consultation_note: "no
    # broader read mode"), unlike condition/medication/allergy/encounter,
    # which are already universally cross-facility readable elsewhere in
    # this router -- so, unlike those, annotating one must not be open to
    # every facility either, or a facility with zero read access to the
    # note could still attach a signed "correction" to it. 404, not 403,
    # so this never confirms the note's existence to the wrong facility
    # (same non-leaking shape as get_consultation_note's own 404).
    if payload.target_type == "consultation_note" and target.facility_name != current_user.facility:
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

    q = db.query(models.ClinicalRecordAnnotation).filter(
        models.ClinicalRecordAnnotation.patient_id == patient_id
    )
    q = _exclude_hidden_facility_scoped_annotations(q, db, current_user.facility)
    rows = q.order_by(models.ClinicalRecordAnnotation.created_at.desc()).offset(skip).limit(limit).all()
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
