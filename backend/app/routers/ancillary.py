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
(added to patients.py::_FACILITY_RELATIONSHIP_SOURCES), and this build
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

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

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


def _request_or_404(
    db: Session, request_id: str, current_user: models.User, *, require_same_facility: bool = False
) -> models.ServiceRequest:
    req = db.query(models.ServiceRequest).filter(models.ServiceRequest.id == request_id).first()
    if req is None:
        raise HTTPException(status_code=404, detail="Service request not found")
    if require_same_facility and current_user.role != "admin" and req.ordering_facility_name != current_user.facility:
        raise HTTPException(status_code=404, detail="Service request not found")
    return req


def _serialize_request(req: models.ServiceRequest) -> schemas.ServiceRequestOut:
    out = schemas.ServiceRequestOut.model_validate(req)
    out.catalog_item_name = req.catalog_item.name if req.catalog_item else None
    if req.result is not None:
        result_out = schemas.ServiceResultOut.model_validate(req.result)
        result_out.has_document = bool(req.result.file_object_key)
        out.result = result_out
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
    shared/global item by explicitly sending `facility_name=null`."""
    facility_name = payload.facility_name
    if current_user.role != "admin":
        if not current_user.facility:
            raise HTTPException(status_code=400, detail="Your account has no facility assigned.")
        facility_name = current_user.facility

    item = models.ServiceCatalogItem(
        module=payload.module, name=payload.name, code=payload.code,
        unit_price_cents=payload.unit_price_cents, facility_name=facility_name,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/catalog/{item_id}", response_model=schemas.ServiceCatalogItemOut)
def update_catalog_item(
    item_id: str,
    payload: schemas.ServiceCatalogItemUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer")),
):
    """No delete endpoint -- toggle `active` off instead (see
    models.ServiceCatalogItem's docstring)."""
    item = db.query(models.ServiceCatalogItem).filter(models.ServiceCatalogItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Service catalog item not found")
    if current_user.role != "admin" and item.facility_name != current_user.facility:
        # Covers global (facility_name IS NULL) items too -- a non-admin may
        # SEE them (list_catalog) but only an admin may edit the shared catalog.
        raise HTTPException(status_code=404, detail="Service catalog item not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
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
    db.refresh(req)

    log_access(
        db, patient.id, current_user.id, current_user.role, "ancillary_request_created",
        detail=f"module={req.module} catalog_item={item.name} request_id={req.id}",
        actor_facility=current_user.facility,
    )
    return _serialize_request(req)


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

    q = db.query(models.ServiceRequest)
    if patient_id:
        if current_user.role == "receptionist":
            raise HTTPException(status_code=403, detail="Not permitted to view cross-facility patient history")
        patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
        if patient is None:
            raise HTTPException(status_code=404, detail="Patient not found")
        q = q.filter(models.ServiceRequest.patient_id == patient_id)
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

    rows = q.order_by(models.ServiceRequest.created_at.desc()).offset(offset).limit(limit).all()
    return [_serialize_request(r) for r in rows]


@router.get("/requests/{request_id}", response_model=schemas.ServiceRequestOut)
def get_service_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*ORDER_ROLES)),
):
    # A receptionist only sees their own facility's orders; every other
    # ORDER_ROLES role gets the same universal cross-facility clinical read
    # as get_patient_full_record.
    require_same_facility = current_user.role == "receptionist"
    req = _request_or_404(db, request_id, current_user, require_same_facility=require_same_facility)
    return _serialize_request(req)


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
    db.refresh(req)

    log_access(
        db, req.patient_id, current_user.id, current_user.role, "ancillary_request_cancelled",
        detail=f"request_id={req.id}", actor_facility=current_user.facility,
    )
    return _serialize_request(req)


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
    db.flush()  # need result.id for the per-row signature snapshot key

    apply_object_meta(
        result,
        copy_signature_snapshot(current_user, f"service-results/{result.id}.png"),
        "signature",
    )
    req.status = "signed_off"
    db.add(result)
    db.commit()
    db.refresh(req)

    flags = " ".join(f for f, on in (("critical", result.flag_critical), ("abnormal", result.flag_abnormal)) if on)
    log_access(
        db, req.patient_id, current_user.id, current_user.role, "ancillary_result_signed_off",
        detail=f"module={req.module} request_id={req.id} result_id={result.id}" + (f" flags={flags}" if flags else ""),
        actor_facility=current_user.facility,
    )
    return _serialize_request(req)


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

    enforce_upload_size(file, MAX_RESULT_UPLOAD_BYTES, "File")
    raw = await file.read()
    if len(raw) > MAX_RESULT_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail=f"File too large — max {MAX_RESULT_UPLOAD_BYTES // (1024 * 1024)}MB"
        )

    mime = sniff_document_mime(raw)
    safe_name = sanitize_filename(file.filename, fallback="result")
    key = f"service-results/{req.result.id}_{safe_name}"
    try:
        meta = get_object_store().put(BUCKET_DOCUMENTS, key, raw, mime=mime)
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="Document storage is temporarily unavailable.")

    apply_object_meta(req.result, meta, "file")
    db.add(req.result)
    db.commit()
    db.refresh(req)

    log_access(
        db, req.patient_id, current_user.id, current_user.role, "ancillary_result_document_uploaded",
        detail=f"request_id={req.id}", actor_facility=current_user.facility,
    )
    return _serialize_request(req)


@router.get("/requests/{request_id}/result/document")
def get_result_document(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*ORDER_ROLES)),
):
    require_same_facility = current_user.role == "receptionist"
    req = _request_or_404(db, request_id, current_user, require_same_facility=require_same_facility)
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
    headers = {
        "Content-Disposition": f'attachment; filename="{sanitize_filename(result.file_object_key.rsplit("_", 1)[-1], fallback=f"result_{result.id}")}"',
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
