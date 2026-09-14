"""
Ancillary engine: Procedure / Laboratory / X-ray / Physiotherapy (P3.1,
the tender).

The four modules' clause text is near-identical (register a patient
straight from Frontdesk OR off a physician's order; clinical indication;
sign off; add/update/delete the module's own tests/procedures/treatments +
charges; store results/reports; visit-history reporting), so this is ONE
shared engine -- `ServiceCatalogItem` (the "Parameter Management" surface),
`ServiceRequest` (the order) and `ServiceResult` (the perform + sign-off,
same one-atomic-action shape as routers/consultation.py::complete_ticket) --
with `module` as just a value, not four separate schemas. See
models.py's "Ancillary engine" section comment for the full column-level
rationale.

RBAC: everyone in ORDER_ROLES (admin/records_officer/clinician/
receptionist) can place and cancel an order -- every module clause
explicitly allows Frontdesk-direct registration. Only SIGNOFF_ROLES
(admin/records_officer/clinician) may perform + sign a result, or manage
the catalog -- a receptionist orders but never clinically signs.
Cross-facility scoping mirrors patients.py's cross-hospital immutability
pattern: ServiceRequest.ordering_facility_name is the authoring facility
(added to clinical_access.py::_FACILITY_RELATIONSHIP_SOURCES), and this build
confines perform/sign/cancel to that facility -- no cross-facility referral
routing yet (a real deployment sending e.g. a lab sample to an external
reference lab is out of scope for this pass). A signed ServiceResult is
immutable; a correction is a new ClinicalRecordAnnotation with
target_type='service_result' (routers/patients.py::_ANNOTATION_MODEL),
never an edit here.
"""
import mimetypes
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from ..storage import (
    BUCKET_DOCUMENTS,
    ObjectNotFound,
    ObjectStoreError,
    apply_object_meta,
    get_object_store,
    sanitize_filename,
)
from ._uploads import enforce_upload_size, sniff_document_mime
from ..clinical_access import _hidden_author_facilities
from ..printing import build_sample_label_png
from .patients import SAFE_DOCUMENT_MEDIA_TYPES
from .profile import save_signature_from_b64, copy_signature_snapshot

router = APIRouter(prefix="/ancillary", tags=["ancillary"])

ORDER_ROLES = ("admin", "records_officer", "clinician", "receptionist")
SIGNOFF_ROLES = ("admin", "records_officer", "clinician")

MAX_RESULT_UPLOAD_BYTES = 15 * 1024 * 1024  # 15MB, same ceiling as ai_router.py::digitise_document


# ---------------------------------------------------------------------------
# Shared lookups
# ---------------------------------------------------------------------------
def _check_module(module: Optional[str]) -> None:
    if module is not None and module not in schemas.ANCILLARY_MODULES:
        raise HTTPException(
            status_code=422,
            detail=f"module must be one of: {', '.join(sorted(schemas.ANCILLARY_MODULES))}",
        )


def _visible_catalog_item_or_404(db: Session, catalog_item_id: str, current_user: models.User) -> models.ServiceCatalogItem:
    """A catalog item is visible to a caller if it's global (facility_name
    IS NULL) or belongs to their own facility -- same 404-not-403 leak
    avoidance as the rest of the app."""
    item = db.query(models.ServiceCatalogItem).filter(models.ServiceCatalogItem.id == catalog_item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Service catalog item not found")
    if item.facility_name is not None and item.facility_name != current_user.facility:
        raise HTTPException(status_code=404, detail="Service catalog item not found")
    return item


def _load_request_with_relations(db: Session, request_id: str) -> Optional[models.ServiceRequest]:
    """The one place that fetches a ServiceRequest with catalog_item/result/
    patient eagerly joinedloaded -- used both for the initial lookup and to
    re-load after a write, so `_serialize_request` never triggers a lazy
    (N+1) query. Fixed 2026-09-12 (review follow-up): cancel/sign-off/
    upload used to call `db.commit(); db.refresh(req)` and then serialize --
    `refresh()` expires relationship attributes without reloading them, so
    every subsequent `req.result`/`req.catalog_item`/`req.patient` access
    issued its own extra SELECT."""
    return (
        db.query(models.ServiceRequest)
        .options(
            joinedload(models.ServiceRequest.catalog_item),
            joinedload(models.ServiceRequest.result),
            joinedload(models.ServiceRequest.patient),
            joinedload(models.ServiceRequest.dicom_study),
        )
        .filter(models.ServiceRequest.id == request_id)
        .first()
    )


def _request_or_404(
    db: Session, request_id: str, current_user: models.User, *, require_same_facility: bool = False
) -> models.ServiceRequest:
    """`require_same_facility=True` is the WRITE-path guard (cancel/sign-off/
    document-upload) -- deliberately NO admin override, matching
    patients.py::_guard_cross_facility_amend's documented "no global admin
    override" invariant (a normal admin has a facility and is walled inside
    it, same as anyone else; a platform/bootstrap admin has no facility to
    begin with, so `current_user.facility` is None and this still denies
    correctly). Fixed 2026-09-12 (voltagent + /code-review): this used to
    exempt role=='admin', letting any facility's admin cancel or forge a
    signed result at any OTHER facility.

    A NULL `ordering_facility_name` (never produced by create_service_request
    today, but the column is nullable -- e.g. a future data import) is
    immutable to EVERYONE, including a facility-less platform/bootstrap
    admin: `None != None` would otherwise silently evaluate to False and
    skip this guard entirely. Fixed 2026-09-12 (voltagent security audit):
    matches clinical_access.py::_record_editable's `not owner or owner != caller`
    idiom rather than a bare `!=`."""
    req = _load_request_with_relations(db, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Service request not found")
    if require_same_facility and (
        not req.ordering_facility_name or req.ordering_facility_name != current_user.facility
    ):
        raise HTTPException(status_code=404, detail="Service request not found")
    return req


def _serialize_request(req: models.ServiceRequest, current_user: models.User) -> schemas.ServiceRequestOut:
    out = schemas.ServiceRequestOut.model_validate(req)
    out.catalog_item_name = req.catalog_item.name if req.catalog_item else None
    out.patient_full_name = req.patient.full_name if req.patient else None
    # A receptionist places/cancels orders but is not a clinical reader --
    # same "front-desk role, not a clinical reader" line this module's
    # docstring already draws elsewhere (list_service_requests' patient_id
    # branch). Fixed 2026-09-12 (/code-review): this used to leak full
    # result_text/flags/attachment-availability to a receptionist through
    # their own facility's default worklist view, which no endpoint's role
    # gate was actually blocking.
    if req.result is not None and current_user.role != "receptionist":
        result_out = schemas.ServiceResultOut.model_validate(req.result)
        result_out.has_document = bool(req.result.file_object_key)
        out.result = result_out
    else:
        # model_validate(req) above already auto-populated `out.result` by
        # reading the ORM relationship straight off `req` (pydantic's
        # from_attributes nested validation) -- for a receptionist, or a
        # not-yet-resulted request, that population must be explicitly
        # undone here, not just skipped, or the stripped branch above is a
        # no-op and the full result leaks through anyway.
        out.result = None
    out.has_dicom_study = req.dicom_study is not None
    return out


# ---------------------------------------------------------------------------
# Catalog ("Parameter Management" --)
# ---------------------------------------------------------------------------
@router.get("/catalog", response_model=List[schemas.ServiceCatalogItemOut])
def list_catalog(
    module: Optional[str] = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*ORDER_ROLES)),
):
    """Every catalog item visible to the caller: global (facility_name IS
    NULL, demo-seeded) items plus their own facility's additions."""
    _check_module(module)
    q = db.query(models.ServiceCatalogItem).filter(
        (models.ServiceCatalogItem.facility_name.is_(None))
        | (models.ServiceCatalogItem.facility_name == current_user.facility)
    )
    if module:
        q = q.filter(models.ServiceCatalogItem.module == module)
    if not include_inactive:
        q = q.filter(models.ServiceCatalogItem.active.is_(True))
    return q.order_by(models.ServiceCatalogItem.module, models.ServiceCatalogItem.name).all()


@router.post("/catalog", response_model=schemas.ServiceCatalogItemOut, status_code=201)
def create_catalog_item(
    payload: schemas.ServiceCatalogItemCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer")),
):
    """A non-admin's item is always scoped to their own facility regardless
    of what `facility_name` they send -- only an admin may publish a
    shared/global item by explicitly sending `facility_name=null`.

    An admin may ALSO only target their own facility or null (global) --
    never an arbitrary other facility's name (fixed 2026-09-12, /code-review:
    this used to trust an admin's `facility_name` verbatim, letting any
    admin plant/contaminate a catalog item under a facility they have no
    relationship to). Same "facility must be omitted or match your own"
    rule as admin.py::_check_mapping_authz."""
    facility_name = payload.facility_name
    if current_user.role != "admin":
        if not current_user.facility:
            raise HTTPException(status_code=400, detail="Your account has no facility assigned.")
        facility_name = current_user.facility
    elif facility_name is not None and facility_name != current_user.facility:
        raise HTTPException(
            status_code=403,
            detail="facility_name must be omitted (global) or match your own facility.",
        )

    item = models.ServiceCatalogItem(
        module=payload.module, name=payload.name, code=payload.code,
        unit_price_cents=payload.unit_price_cents, facility_name=facility_name,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    # Fixed 2026-09-12 (voltagent security audit): catalog writes are
    # billing-relevant (unit_price_cents is snapshotted onto every
    # subsequent order, feeding P3.3) but had no audit trail at all, unlike
    # every patient-scoped write in this file.
    log_access(
        db, None, current_user.id, current_user.role, "ancillary_catalog_item_created",
        detail=f"module={item.module} name={item.name!r} item_id={item.id}",
        actor_facility=current_user.facility,
    )
    return item


@router.patch("/catalog/{item_id}", response_model=schemas.ServiceCatalogItemOut)
def update_catalog_item(
    item_id: str,
    payload: schemas.ServiceCatalogItemUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer")),
):
    """No delete endpoint -- toggle `active` off instead (see
    models.ServiceCatalogItem's docstring).

    No admin override: an admin may edit a global item (facility_name IS
    NULL) or their OWN facility's item, exactly like everyone else -- never
    another facility's private item (fixed 2026-09-12, /code-review: this
    used to skip the ownership check entirely for role=='admin')."""
    item = db.query(models.ServiceCatalogItem).filter(models.ServiceCatalogItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Service catalog item not found")
    if item.facility_name is not None and item.facility_name != current_user.facility:
        raise HTTPException(status_code=404, detail="Service catalog item not found")
    changed_fields = sorted(payload.model_dump(exclude_unset=True).keys())
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)

    log_access(
        db, None, current_user.id, current_user.role, "ancillary_catalog_item_updated",
        detail=f"item_id={item.id} fields={','.join(changed_fields)}",
        actor_facility=current_user.facility,
    )
    return item


# ---------------------------------------------------------------------------
# Requests (the "order")
# ---------------------------------------------------------------------------
@router.post("/requests", response_model=schemas.ServiceRequestOut, status_code=201)
def create_service_request(
    payload: schemas.ServiceRequestCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*ORDER_ROLES)),
):
    if not current_user.facility:
        raise HTTPException(status_code=400, detail="Your account has no facility assigned.")

    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    item = _visible_catalog_item_or_404(db, payload.catalog_item_id, current_user)
    if item.module != payload.module:
        raise HTTPException(status_code=400, detail="catalog_item_id does not belong to this module")
    if not item.active:
        raise HTTPException(status_code=400, detail="This catalog item is no longer active")

    if payload.source_encounter_id:
        encounter = db.query(models.Encounter).filter(models.Encounter.id == payload.source_encounter_id).first()
        if encounter is None or encounter.patient_id != payload.patient_id:
            raise HTTPException(status_code=404, detail="source_encounter_id not found for this patient")

    req = models.ServiceRequest(
        patient_id=payload.patient_id,
        module=payload.module,
        catalog_item_id=item.id,
        source=payload.source,
        source_encounter_id=payload.source_encounter_id,
        clinical_indication=payload.clinical_indication,
        priority=payload.priority,
        unit_price_cents=item.unit_price_cents,
        requested_by=current_user.id,
        requested_by_name=current_user.full_name,
        requested_by_role=current_user.role,
        ordering_facility_name=current_user.facility,
    )
    db.add(req)
    db.commit()
    req = _load_request_with_relations(db, req.id)

    log_access(
        db, patient.id, current_user.id, current_user.role, "ancillary_request_created",
        detail=f"module={req.module} catalog_item={item.name} request_id={req.id}",
        actor_facility=current_user.facility,
    )
    return _serialize_request(req, current_user)


@router.get("/requests", response_model=List[schemas.ServiceRequestOut])
def list_service_requests(
    module: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    patient_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*ORDER_ROLES)),
):
    """Default: the caller's OWN facility's worklist (same own-facility-only
    scope as Reception's queue). `patient_id` instead opens that one
    patient's ancillary history across every facility that has ever ordered
    for them -- same universal cross-facility clinical read as
    patients.py::get_patient_full_record, so restricted to the same
    clinical-reader roles (receptionist excluded: front-desk role, not a
    clinical reader)."""
    _check_module(module)
    if status is not None and status not in models.SERVICE_REQUEST_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"status must be one of: {', '.join(models.SERVICE_REQUEST_STATUSES)}",
        )

    q = db.query(models.ServiceRequest).options(
        joinedload(models.ServiceRequest.catalog_item),
        joinedload(models.ServiceRequest.result),
        joinedload(models.ServiceRequest.patient),
        joinedload(models.ServiceRequest.dicom_study),
    )
    cross_facility = False
    if patient_id:
        if current_user.role == "receptionist":
            raise HTTPException(status_code=403, detail="Not permitted to view cross-facility patient history")
        patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
        if patient is None:
            raise HTTPException(status_code=404, detail="Patient not found")
        q = q.filter(models.ServiceRequest.patient_id == patient_id)
        cross_facility = True
        log_access(
            db, patient_id, current_user.id, current_user.role, "view_ancillary_history",
            actor_facility=current_user.facility,
        )
    else:
        if not current_user.facility:
            return []
        q = q.filter(models.ServiceRequest.ordering_facility_name == current_user.facility)

    if module:
        q = q.filter(models.ServiceRequest.module == module)
    if status:
        q = q.filter(models.ServiceRequest.status == status)

    if cross_facility:
        # Same records_shared_publicly opt-out as patients.py's other
        # cross-facility clinical reads (_hidden_author_facilities) --
        # never hides the caller's OWN facility's rows. Applied in SQL
        # BEFORE offset/limit (fixed 2026-09-12, review follow-up: this used
        # to filter hidden rows out of the already-paginated Python list,
        # so a page could silently come back under-filled, and successive
        # offset-based pages would skip/misalign rows once hidden rows were
        # stripped out from under a fixed offset). A NULL
        # ordering_facility_name (never actually produced by
        # create_service_request, but the column is nullable) is explicitly
        # kept rather than risking SQL's NULL-vs-NOT IN(...) three-valued
        # logic silently dropping it.
        hidden = _hidden_author_facilities(db, current_user.facility)
        if hidden:
            q = q.filter(
                or_(
                    models.ServiceRequest.ordering_facility_name.is_(None),
                    models.ServiceRequest.ordering_facility_name.notin_(hidden),
                )
            )

    rows = q.order_by(models.ServiceRequest.created_at.desc()).offset(offset).limit(limit).all()
    return [_serialize_request(r, current_user) for r in rows]


@router.get("/requests/{request_id}", response_model=schemas.ServiceRequestOut)
def get_service_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*ORDER_ROLES)),
):
    # A receptionist only sees their own facility's orders; every other
    # ORDER_ROLES role gets the same universal cross-facility clinical read
    # as get_patient_full_record -- MINUS whatever the ordering facility has
    # opted out of public sharing (HospitalSetting.records_shared_publicly),
    # same as patients.py's other cross-facility clinical reads.
    require_same_facility = current_user.role == "receptionist"
    req = _request_or_404(db, request_id, current_user, require_same_facility=require_same_facility)
    if not require_same_facility and req.ordering_facility_name != current_user.facility:
        if req.ordering_facility_name in _hidden_author_facilities(db, current_user.facility):
            raise HTTPException(status_code=404, detail="Service request not found")
    return _serialize_request(req, current_user)


@router.get("/requests/{request_id}/label")
def get_service_request_label(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*ORDER_ROLES)),
):
    """P3.9: a printable sample-label image (patient name, IC,
    item, scannable code) for this order -- own-facility only, same as every
    other write/print action against a request (a label is only ever
    printed where the sample is physically taken). See app/printing.py's
    module docstring for why this returns image bytes rather than talking to
    a label printer directly."""
    req = _request_or_404(db, request_id, current_user, require_same_facility=True)
    png_bytes = build_sample_label_png(
        patient_name=req.patient.full_name,
        national_id=req.patient.national_id,
        item_name=req.catalog_item.name,
        request_id=req.id,
    )
    return Response(content=png_bytes, media_type="image/png")


@router.post("/requests/{request_id}/cancel", response_model=schemas.ServiceRequestOut)
def cancel_service_request(
    request_id: str,
    payload: schemas.ServiceRequestCancel,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*ORDER_ROLES)),
):
    req = _request_or_404(db, request_id, current_user, require_same_facility=True)
    if req.status != "ordered":
        raise HTTPException(status_code=400, detail=f"Cannot cancel a request that is already '{req.status}'")

    req.status = "cancelled"
    req.cancelled_at = datetime.now(timezone.utc)
    req.cancelled_reason = payload.reason
    db.commit()
    req = _load_request_with_relations(db, req.id)

    log_access(
        db, req.patient_id, current_user.id, current_user.role, "ancillary_request_cancelled",
        detail=f"request_id={req.id}", actor_facility=current_user.facility,
    )
    return _serialize_request(req, current_user)


# ---------------------------------------------------------------------------
# Result + sign-off
# ---------------------------------------------------------------------------
@router.post("/requests/{request_id}/result", response_model=schemas.ServiceRequestOut)
def sign_off_service_request(
    request_id: str,
    payload: schemas.ServiceResultCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*SIGNOFF_ROLES)),
):
    """Perform AND sign off in one atomic action -- same shape as
    routers/consultation.py::complete_ticket. Confined to the request's own
    ordering facility (see module docstring). REQUIRES a saved digital
    signature; pass `signature_b64` to save one on the spot."""
    req = _request_or_404(db, request_id, current_user, require_same_facility=True)
    if req.status != "ordered":
        raise HTTPException(status_code=400, detail=f"Request is already '{req.status}'")

    if not current_user.signature_object_key and not payload.signature_b64:
        raise HTTPException(
            status_code=409,
            detail="Save your signature in your profile before signing off a result.",
        )
    if payload.signature_b64 and not current_user.signature_object_key:
        save_signature_from_b64(db, current_user, payload.signature_b64)

    now = datetime.now(timezone.utc)
    result = models.ServiceResult(
        service_request_id=req.id,
        patient_id=req.patient_id,
        result_text=payload.result_text,
        flag_abnormal=payload.flag_abnormal,
        flag_critical=payload.flag_critical,
        performed_by=current_user.id,
        performed_by_name=current_user.full_name,
        performed_by_role=current_user.role,
        performed_at=now,
        facility_name=current_user.facility,
        signed_by=current_user.id,
        signed_by_name=current_user.full_name,
        signed_by_role=current_user.role,
    )
    db.add(result)
    try:
        # need result.id for the per-row signature snapshot key below.
        # ServiceResult.service_request_id is UNIQUE -- a concurrent
        # double sign-off (double-click, or two staff racing the same
        # order) hits that constraint here rather than silently creating
        # two results. Same race-to-409 discipline as
        # consultation.py::start_session's claim race (code-review
        # follow-up 2026-09-12: this used to have no handling at all,
        # so a race would surface as an unhandled 500).
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="This request already has a result.")

    apply_object_meta(
        result,
        copy_signature_snapshot(current_user, f"service-results/{result.id}.png"),
        "signature",
    )
    req.status = "signed_off"
    db.add(result)
    db.commit()
    req = _load_request_with_relations(db, req.id)

    flags = " ".join(f for f, on in (("critical", result.flag_critical), ("abnormal", result.flag_abnormal)) if on)
    log_access(
        db, req.patient_id, current_user.id, current_user.role, "ancillary_result_signed_off",
        detail=f"module={req.module} request_id={req.id} result_id={result.id}" + (f" flags={flags}" if flags else ""),
        actor_facility=current_user.facility,
    )
    return _serialize_request(req, current_user)


@router.post("/requests/{request_id}/result/document", response_model=schemas.ServiceRequestOut)
async def upload_result_document(
    request_id: str,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.require_roles(*SIGNOFF_ROLES)),
):
    """Attach a softcopy (scanned lab/X-ray report, etc.) to an
    ALREADY-signed result -- a separate step from sign-off itself so a
    failed/retried upload never blocks the sign-off from landing. Same
    upload-safety discipline as ai_router.py::digitise_document (size
    ceiling enforced before `.read()`, server-side mime sniff, sanitized
    filename in the object key -- never the client's raw filename)."""
    req = _request_or_404(db, request_id, current_user, require_same_facility=True)
    if req.result is None:
        raise HTTPException(status_code=400, detail="Sign off the result before attaching a document")
    if req.result.file_object_key:
        # Fixed 2026-09-12 (review follow-up): this endpoint had no guard
        # against a second upload, which silently replaced the object-store
        # pointer -- overwriting an already-attached document's metadata on
        # this immutable, signed-off result and orphaning the original
        # object in MinIO (never deleted, never reachable again). A genuine
        # replacement is a records_officer/admin action from Admin, not a
        # second call to this endpoint.
        raise HTTPException(status_code=409, detail="A document is already attached to this result.")

    enforce_upload_size(file, MAX_RESULT_UPLOAD_BYTES, "File")
    raw = await file.read()
    if len(raw) > MAX_RESULT_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail=f"File too large — max {MAX_RESULT_UPLOAD_BYTES // (1024 * 1024)}MB"
        )

    mime = sniff_document_mime(raw)
    safe_name = sanitize_filename(file.filename, fallback="result")
    # "/" as the id/filename separator, not "_" (fixed 2026-09-12, review
    # follow-up): get_result_document below recovers the download filename
    # by splitting the key, and "_" is a character sanitize_filename allows
    # THROUGH -- an original name like "blood_test_results.pdf" corrupted
    # the recovered name to "results.pdf". "/" can't appear in safe_name
    # (sanitize_filename strips any path separators), so it's an
    # unambiguous split point; storage.validate_key already allows "/" as a
    # segment separator (see the existing "service-results/" prefix).
    key = f"service-results/{req.result.id}/{safe_name}"
    try:
        # .put() does blocking file/network I/O -- this endpoint is `async
        # def` (needed for `await file.read()`), so a direct call here would
        # stall the whole event loop for the write. run_in_threadpool is the
        # same fix ai_router.py::digitise_document already applies to the
        # identical call (code-review follow-up 2026-09-12: this endpoint
        # was the one place that copy-pasted the pattern without it).
        meta = await run_in_threadpool(get_object_store().put, BUCKET_DOCUMENTS, key, raw, mime=mime)
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="Document storage is temporarily unavailable.")

    apply_object_meta(req.result, meta, "file")
    db.add(req.result)
    db.commit()
    req = _load_request_with_relations(db, req.id)

    log_access(
        db, req.patient_id, current_user.id, current_user.role, "ancillary_result_document_uploaded",
        detail=f"request_id={req.id}", actor_facility=current_user.facility,
    )
    return _serialize_request(req, current_user)


@router.get("/requests/{request_id}/result/document")
def get_result_document(
    request_id: str,
    db: Session = Depends(get_db),
    # SIGNOFF_ROLES, not ORDER_ROLES -- a result document is clinical
    # content (a scanned lab/X-ray report), same "receptionist is
    # front-desk, not a clinical reader" line as _serialize_request's
    # result-stripping above. Fixed 2026-09-12 (/code-review): this used to
    # sit on ORDER_ROLES, so a receptionist who knew/guessed a request_id
    # could fetch the raw attachment even though the JSON payload already
    # hides it from them.
    current_user: models.User = Depends(auth.require_roles(*SIGNOFF_ROLES)),
):
    req = _request_or_404(db, request_id, current_user, require_same_facility=False)
    if req.ordering_facility_name != current_user.facility:
        if req.ordering_facility_name in _hidden_author_facilities(db, current_user.facility):
            raise HTTPException(status_code=404, detail="No result document available")
    if req.result is None or not req.result.file_object_key:
        raise HTTPException(status_code=404, detail="No result document available")
    result = req.result

    try:
        stream = get_object_store().open_stream(BUCKET_DOCUMENTS, result.file_object_key)
    except (ObjectNotFound, ValueError):
        raise HTTPException(status_code=404, detail="No result document available")
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="Document storage is temporarily unavailable.")

    try:
        log_access(
            db, req.patient_id, current_user.id, current_user.role, "view_ancillary_result_document",
            detail=req.id, actor_facility=current_user.facility,
        )
    except Exception:
        stream.close()
        raise

    # Content-Type guessed from the sanitized object key, never the
    # attacker-controlled original filename -- same stored-XSS guard as
    # patients.py::get_document_file.
    guessed_type, _ = mimetypes.guess_type(result.file_object_key)
    media_type = guessed_type if guessed_type in SAFE_DOCUMENT_MEDIA_TYPES else "application/octet-stream"
    # Split on "/" (the id/filename separator upload_result_document writes),
    # not "_" (fixed 2026-09-12, review follow-up: rsplit("_", 1) corrupted
    # any original filename that itself contained an underscore, e.g.
    # "blood_test_results.pdf" downloaded as "results.pdf").
    original_name = result.file_object_key.rsplit("/", 1)[-1]
    headers = {
        "Content-Disposition": f'attachment; filename="{sanitize_filename(original_name, fallback=f"result_{result.id}")}"',
        "X-Content-Type-Options": "nosniff",
    }
    if result.file_bytes:
        headers["Content-Length"] = str(result.file_bytes)
    return StreamingResponse(stream, media_type=media_type, headers=headers)


# ---------------------------------------------------------------------------
# Reporting ("Reporting Management ... data & statistics" --
#)
# ---------------------------------------------------------------------------
@router.get("/stats", response_model=schemas.AncillaryStatsOut)
def ancillary_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*SIGNOFF_ROLES)),
):
    """Minimal per-facility 'data & statistics' surface: open orders +
    signed-off count over the trailing 30 days, grouped by module. A fuller
    Custom Report Builder is P3.6."""
    facility = current_user.facility
    open_by_module = {m: 0 for m in schemas.ANCILLARY_MODULES}
    signed_off_by_module = {m: 0 for m in schemas.ANCILLARY_MODULES}

    if facility:
        for module, count in (
            db.query(models.ServiceRequest.module, func.count(models.ServiceRequest.id))
            .filter(models.ServiceRequest.ordering_facility_name == facility, models.ServiceRequest.status == "ordered")
            .group_by(models.ServiceRequest.module)
            .all()
        ):
            open_by_module[module] = count

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        for module, count in (
            db.query(models.ServiceRequest.module, func.count(models.ServiceRequest.id))
            .filter(
                models.ServiceRequest.ordering_facility_name == facility,
                models.ServiceRequest.status == "signed_off",
                models.ServiceRequest.created_at >= cutoff,
            )
            .group_by(models.ServiceRequest.module)
            .all()
        ):
            signed_off_by_module[module] = count

    return schemas.AncillaryStatsOut(
        facility_name=facility, open_by_module=open_by_module, signed_off_last_30d_by_module=signed_off_by_module,
    )
