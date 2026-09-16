"""Shared medicine-inventory service for the admin + pharmacy routers.

Extracted verbatim from ``app/routers/admin.py`` (code-review follow-up
2026-09-07) so that ``routers/admin.py`` and ``routers/pharmacy.py`` can both
depend on it, instead of ``pharmacy.py`` importing service helpers straight
from another router module.
"""
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import models
from .audit import log_access
from .storage import BUCKET_MEDICINE, ObjectStoreError, apply_object_meta, get_object_store, sanitize_filename
from .imaging import ImageProcessingError, normalise_image, sniff_image_mime
from .derived import enqueue_prime_thumbnail
from .routers._uploads import enforce_upload_size


# ---------- Medicine photo upload/serve (shared with routers/pharmacy.py) ----------
# Photos go through the ObjectStore (app/storage.py), `clarion-medicine`
# bucket, key `{item_id}_{sanitized_basename}` -- built server-side, never
# from the raw multipart filename. Served back by GET
# /pharmacy/inventory/{item_id}/image.

# Deliberately much tighter than ai_router's 15MB scan cap -- a medicine
# packaging photo is a single phone snapshot, not a multi-page high-res
# clinical scan.
MAX_MEDICINE_IMAGE_BYTES = 2 * 1024 * 1024

# content-type -> canonical extension. The upload path checks BOTH the
# declared content-type AND the filename extension AND sniffs magic bytes
# (see _validate_medicine_image) -- a client controls all three of the
# first two, so none is trusted alone.
_MEDICINE_IMAGE_TYPES = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/webp": {".webp"},
    # P1.7b: an iPhone camera's default format -- normalise_image always
    # re-encodes to JPEG below, so this never reaches _MEDICINE_IMAGE_MEDIA_TYPES.
    "image/heic": {".heic", ".heif"},
}
# Same allowlist, keyed by the type mimetypes.guess_type() derives from the
# sanitized on-disk name when serving the file back -- anything else falls
# back to application/octet-stream (download-only), never served with a
# guessed executable type (same stored-XSS guard as
# patients.py::get_document_file). Deliberately NOT extended with HEIC --
# the stored file is always the normalise_image JPEG output, never the
# original bytes.
_MEDICINE_IMAGE_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp"}


_MEDICINE_SNIFF_OK = {"image/png", "image/jpeg", "image/webp", "image/heic"}


def _sniff_image_bytes(raw: bytes) -> Optional[str]:
    """The sniffed content-type from the file's magic bytes if it is one of the
    three formats the medicine-photo path accepts, else None. Delegates to the
    single sniffer in app.imaging; the client can't spoof it by renaming or by
    setting a Content-Type header."""
    mime = sniff_image_mime(raw)
    return mime if mime in _MEDICINE_SNIFF_OK else None


def save_medicine_image(
    db: Session, item: models.MedicineInventoryItem, file: UploadFile,
    current_user: models.User, facility: str,
) -> None:
    """Validate + persist an uploaded medicine photo, best-effort replacing
    any existing one. Shared by POST /admin/inventory/{id}/image and
    POST /pharmacy/inventory/{id}/image. Commits the row.

    Security: the object key is built server-side from item.id + a
    sanitized basename (never the raw multipart filename), and only that
    DB-stored key is ever used on read -- identical to
    ClinicalDocument.file_object_key / patients.py::get_document_file.
    """
    enforce_upload_size(file, MAX_MEDICINE_IMAGE_BYTES, "Image")
    raw = file.file.read()
    if len(raw) > MAX_MEDICINE_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large — max {MAX_MEDICINE_IMAGE_BYTES // (1024 * 1024)}MB",
        )
    if not raw:
        raise HTTPException(status_code=422, detail="Empty file.")

    declared_type = (file.content_type or "").split(";")[0].strip().lower()
    ext = os.path.splitext(file.filename or "")[1].lower()
    sniffed_type = _sniff_image_bytes(raw)

    allowed_exts = _MEDICINE_IMAGE_TYPES.get(declared_type)
    if (
        allowed_exts is None
        or ext not in allowed_exts
        or sniffed_type is None
        or sniffed_type != declared_type
    ):
        raise HTTPException(
            status_code=422,
            detail="Image must be a PNG, JPEG or WebP file (content-type, extension and contents must all agree).",
        )

    # P1.7: normalise before storing -- strips EXIF/GPS (a phone photo of
    # packaging carries the pharmacist's location), auto-orients, caps the long
    # edge, re-encodes as a progressive JPEG to cut storage.
    # A medicine photo is NOT a legal record, so replacing the stored bytes is
    # fine (unlike a clinical document). The magic-byte + extension + declared-
    # type triple-check above already passed, so a decode failure here means a
    # hostile / corrupt file -- reject it rather than persist un-stripped bytes.
    try:
        processed = normalise_image(raw)
    except ImageProcessingError:
        raise HTTPException(status_code=422, detail="Could not process that image. Try a different file.")

    stem = os.path.splitext(sanitize_filename(file.filename, fallback="image"))[0] or "image"
    key = f"{item.id}_{stem}.jpg"  # normalise_image always emits JPEG

    old_key = item.image_object_key
    try:
        meta = get_object_store().put(BUCKET_MEDICINE, key, processed.data, mime=processed.mime)
    except (OSError, ValueError, ObjectStoreError):
        raise HTTPException(status_code=500, detail="Could not store the image. Try again.")

    apply_object_meta(item, meta, "image")
    item.updated_by = current_user.id
    db.add(item)
    db.commit()
    db.refresh(item)

    # Drop the previous object if the key changed. The derived thumbnail is
    # keyed by the new sha256, so a stale one just expires under ILM -- no
    # explicit purge needed. Never let cleanup failure surface as an error.
    if old_key and old_key != key:
        try:
            get_object_store().delete(BUCKET_MEDICINE, old_key)
        except (OSError, ValueError, ObjectStoreError):
            pass
    enqueue_prime_thumbnail(db, BUCKET_MEDICINE, key, meta.sha256)

    log_access(
        db, None, current_user.id, current_user.role, "upload_medicine_image",
        detail=item.drug_name, actor_facility=facility,
    )


def _has_pending_delete_request(db: Session, item_id: str) -> bool:
    return (
        db.query(models.InventoryDeleteRequest.id)
        .filter(
            models.InventoryDeleteRequest.item_id == item_id,
            models.InventoryDeleteRequest.status == "pending",
        )
        .first()
        is not None
    )


def _pending_delete_item_ids(db: Session, item_ids) -> set:
    """Batch form for the list serializers -- one query for "which of these
    items have a pending delete request", instead of _has_pending_delete_request
    per row (code-review follow-up 2026-09-07)."""
    ids = [i for i in item_ids if i]
    if not ids:
        return set()
    return {
        r for (r,) in db.query(models.InventoryDeleteRequest.item_id)
        .filter(
            models.InventoryDeleteRequest.item_id.in_(ids),
            models.InventoryDeleteRequest.status == "pending",
        )
        .all()
    }


def _serialize_inventory_item(
    db: Session, item: models.MedicineInventoryItem, pending_delete_ids=None
) -> dict:
    has_image = bool(item.image_object_key)
    return {
        "id": item.id,
        "facility_name": item.facility_name,
        "drug_name": item.drug_name,
        "quantity_on_hand": item.quantity_on_hand,
        "unit": item.unit,
        "reorder_threshold": item.reorder_threshold,
        "notes": item.notes,
        "last_restocked_at": item.last_restocked_at,
        "unit_cost": item.unit_cost,
        "barcode": item.barcode,
        "auto_approved": bool(item.auto_approved),
        "updated_by": item.updated_by,
        "updated_at": item.updated_at,
        "created_at": item.created_at,
        "is_low_stock": item.reorder_threshold is not None and item.quantity_on_hand <= item.reorder_threshold,
        "pending_delete_request": (
            item.id in pending_delete_ids if pending_delete_ids is not None
            else _has_pending_delete_request(db, item.id)
        ),
        "has_image": has_image,
        # Points at the pharmacy GET endpoint (admins are in _PHARMACY_ROLES,
        # so one endpoint serves both consoles). Never exposes the raw
        # object key.
        "image_url": f"/pharmacy/inventory/{item.id}/image" if has_image else None,
        # P1.7: 300px preview (regenerated on demand). Same endpoint for both consoles.
        "thumbnail_url": f"/pharmacy/inventory/{item.id}/image/thumbnail" if has_image else None,
    }


def _low_stock_count(db: Session, facility: str) -> int:
    """Items at/below their reorder_threshold for this facility -- the same
    predicate GET /pharmacy/inventory/low-stock filters on, reused for the
    budget/summary badge counters."""
    return (
        db.query(func.count(models.MedicineInventoryItem.id))
        .filter(
            models.MedicineInventoryItem.facility_name == facility,
            models.MedicineInventoryItem.reorder_threshold.isnot(None),
            models.MedicineInventoryItem.quantity_on_hand <= models.MedicineInventoryItem.reorder_threshold,
        )
        .scalar()
    ) or 0


def _apply_inventory_search(query, q: Optional[str]):
    """Shared ?q= filter for GET /admin/inventory and GET /pharmacy/inventory:
    case-insensitive substring on drug_name, OR exact / prefix match on
    barcode (a scanner hands over a full code and expects the exact row;
    a human typing the first few digits still gets a hit)."""
    if not q or not q.strip():
        return query
    term = q.strip()
    like = f"%{term.lower()}%"
    return query.filter(
        or_(
            func.lower(models.MedicineInventoryItem.drug_name).like(like),
            models.MedicineInventoryItem.barcode == term,
            models.MedicineInventoryItem.barcode.like(f"{term}%"),
        )
    )


def _apply_restock(
    db: Session, item: models.MedicineInventoryItem, quantity: int,
    unit_cost_paid: Optional[float], current_user: models.User, facility: str,
    now: Optional[datetime] = None,
) -> float:
    """The one restock primitive, shared by the immediate auto-approved
    pharmacist path (routers/pharmacy.py::adjust_stock) AND admin
    purchase-proposal approval (approve_purchase_proposal below), so the two
    can never diverge: bump quantity_on_hand, stamp last_restocked_at, write
    a `restock` MedicineStockEvent, and accrue MedicineBudget.procurement_spend
    (creating the budget row lazily). Does NOT commit -- the caller owns the
    transaction boundary. Returns the accrued cost.

    `unit_cost_paid` is the price on THIS purchase (payload value or the
    item's stored unit_cost); like the adjust endpoint it is recorded on the
    stock event only and never overwrites the catalogue item.unit_cost.
    """
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    effective_unit_cost = unit_cost_paid if unit_cost_paid is not None else item.unit_cost
    cost = float(effective_unit_cost or 0.0) * quantity

    item.quantity_on_hand += quantity
    item.last_restocked_at = now
    item.updated_by = current_user.id

    db.add(models.MedicineStockEvent(
        facility_name=facility, item_id=item.id, delta=quantity,
        unit_cost_at_time=effective_unit_cost, cost=cost, kind="restock",
        by=current_user.id, at=now,
    ))

    budget = (
        db.query(models.MedicineBudget)
        .filter(models.MedicineBudget.facility_name == facility)
        .first()
    )
    if budget is None:
        budget = models.MedicineBudget(
            facility_name=facility, allocated_amount=0.0, procurement_spend=0.0,
        )
        db.add(budget)
    budget.procurement_spend = float(budget.procurement_spend or 0.0) + cost
    budget.updated_by = current_user.id
    return cost


def _get_inventory_item_or_404(db: Session, item_id: str, facility: str) -> models.MedicineInventoryItem:
    # Scoped to facility too, not just item_id -- a facility-A admin must get
    # the exact same 404 for "doesn't exist" and "exists but belongs to
    # facility B", never a 403 that would leak the row's existence (mirrors
    # patients.py::_get_document_or_404 / appointments.py's patient-scoped
    # 404 reasoning).
    item = (
        db.query(models.MedicineInventoryItem)
        .filter(models.MedicineInventoryItem.id == item_id, models.MedicineInventoryItem.facility_name == facility)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    return item


def _serialize_delete_request(req: models.InventoryDeleteRequest, requester_name) -> dict:
    return {
        "id": req.id,
        "item_id": req.item_id,
        "item_name": req.item_name,
        "requested_by": req.requested_by,
        "requested_by_name": requester_name,
        "reason": req.reason,
        "status": req.status,
        "created_at": req.created_at,
        "resolved_by": req.resolved_by,
        "resolved_at": req.resolved_at,
        "admin_note": req.admin_note,
    }


def _serialize_purchase_proposal(
    proposal: models.MedicinePurchaseProposal, requester_name=None,
) -> dict:
    return {
        "id": proposal.id,
        "facility_name": proposal.facility_name,
        "item_id": proposal.item_id,
        "is_new_item": proposal.item_id is None,
        "proposed_drug_name": proposal.proposed_drug_name,
        "proposed_unit": proposal.proposed_unit,
        "proposed_barcode": proposal.proposed_barcode,
        "quantity": proposal.quantity,
        "unit_cost": proposal.unit_cost,
        "reason": proposal.reason,
        "requested_by": proposal.requested_by,
        "requested_by_name": requester_name,
        "status": proposal.status,
        "reviewed_by": proposal.reviewed_by,
        "reviewed_at": proposal.reviewed_at,
        "admin_note": proposal.admin_note,
        "created_at": proposal.created_at,
    }


def _pending_proposal_count(db: Session, facility: str) -> int:
    return (
        db.query(func.count(models.MedicinePurchaseProposal.id))
        .filter(
            models.MedicinePurchaseProposal.facility_name == facility,
            models.MedicinePurchaseProposal.status == "pending",
        )
        .scalar()
    ) or 0
