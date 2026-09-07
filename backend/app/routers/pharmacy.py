"""
Pharmacy stock endpoints -- the pharmacist-facing counterpart to the
admin-only inventory CRUD in routers/admin.py.

Same forced-facility boundary as routers/admin.py (see that module's
docstring): every endpoint here is auto-scoped to the caller's own
`User.facility`, never client-supplied, and every read/write goes through a
scoped-404 helper so a facility-A caller gets the exact same 404 for
"doesn't exist" and "belongs to facility B".

Role split with admin.py:
  - Pharmacists (and admins) adjust STOCK VOLUME here (restock / dispense),
    upload a medicine photo, and can REQUEST a catalogue deletion or a
    purchase (new item, or a restock of an item that isn't auto-approved).
  - Catalogue create / edit / direct delete, delete-request approval, and
    purchase-proposal approval stay admin-only (routers/admin.py).

Purchase-approval workflow (item 6b): a restock (`delta > 0`) on an item
whose `auto_approved` is False does NOT touch stock/budget -- it files a
MedicinePurchaseProposal and returns 202. An admin approves it in
routers/admin.py, which runs the exact same `_apply_restock` primitive the
auto-approved path runs here, so the two can never drift.
"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from ..storage import BUCKET_MEDICINE, ObjectNotFound, ObjectStoreError, get_object_store
from ..derived import get_or_make_thumbnail
from ..directory import resolve_user_names
from .admin import _require_facility
from ..inventory import (
    _get_inventory_item_or_404,
    _serialize_inventory_item,
    _pending_delete_item_ids,
    _serialize_delete_request,
    _apply_inventory_search,
    _apply_restock,
    _serialize_purchase_proposal,
    _low_stock_count,
    _pending_proposal_count,
    save_medicine_image,
    _MEDICINE_IMAGE_MEDIA_TYPES,
)

router = APIRouter(prefix="/pharmacy", tags=["pharmacy"])

logger = logging.getLogger("clarion.pharmacy")

_PHARMACY_ROLES = ("admin", "pharmacist")


@router.get("/inventory", response_model=List[schemas.MedicineInventoryOut])
def list_pharmacy_inventory(
    q: Optional[str] = Query(None, description="Case-insensitive substring match on drug_name, or exact/prefix match on barcode (e.g. a scanned code)."),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_PHARMACY_ROLES)),
):
    if not current_user.facility:
        return []
    query = db.query(models.MedicineInventoryItem).filter(
        models.MedicineInventoryItem.facility_name == current_user.facility
    )
    query = _apply_inventory_search(query, q)
    items = query.order_by(models.MedicineInventoryItem.drug_name.asc()).all()
    log_access(
        db, None, current_user.id, current_user.role, "view_pharmacy_inventory",
        actor_facility=current_user.facility,
    )
    pending = _pending_delete_item_ids(db, [i.id for i in items])
    return [_serialize_inventory_item(db, i, pending) for i in items]


@router.get("/inventory/low-stock", response_model=List[schemas.MedicineInventoryOut])
def list_low_stock(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_PHARMACY_ROLES)),
):
    """Only the items at/below their reorder_threshold for this facility --
    the in-console "reorder reminder" list (item 6a). No email/push: this
    app has no background-job layer, so a low-stock nudge is a screen the
    pharmacist opens, not a notification that's pushed to them."""
    if not current_user.facility:
        return []
    items = (
        db.query(models.MedicineInventoryItem)
        .filter(
            models.MedicineInventoryItem.facility_name == current_user.facility,
            models.MedicineInventoryItem.reorder_threshold.isnot(None),
            models.MedicineInventoryItem.quantity_on_hand <= models.MedicineInventoryItem.reorder_threshold,
        )
        .order_by(models.MedicineInventoryItem.drug_name.asc())
        .all()
    )
    pending = _pending_delete_item_ids(db, [i.id for i in items])
    return [_serialize_inventory_item(db, i, pending) for i in items]


@router.get("/summary", response_model=schemas.PharmacySummaryOut)
def pharmacy_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_PHARMACY_ROLES)),
):
    """The two counters the pharmacy console badges on load: how many items
    are low on stock, and how many purchase proposals are still waiting on
    an admin."""
    if not current_user.facility:
        return schemas.PharmacySummaryOut(low_stock_count=0, pending_proposal_count=0)
    facility = current_user.facility
    return schemas.PharmacySummaryOut(
        low_stock_count=_low_stock_count(db, facility),
        pending_proposal_count=_pending_proposal_count(db, facility),
    )


@router.post(
    "/inventory/{item_id}/adjust",
    response_model=schemas.MedicineInventoryOut,
    responses={202: {"model": schemas.PurchaseProposalOut, "description": "Restock queued for admin approval (item is not auto-approved)."}},
)
def adjust_stock(
    item_id: str,
    payload: schemas.StockAdjustRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_PHARMACY_ROLES)),
):
    """`delta` > 0 (restock):
      - if the item is `auto_approved`: apply immediately via the shared
        _apply_restock primitive (quantity_on_hand += delta, stamp
        last_restocked_at, write a `restock` MedicineStockEvent, accrue
        MedicineBudget.procurement_spend).
      - otherwise: file a MedicinePurchaseProposal (item_id set,
        quantity=delta, unit_cost from payload or the item), touch NOTHING
        on stock/budget, and return HTTP 202 with the serialized proposal.
        A second identical pending proposal (same item, same requester, same
        quantity) is a 409, mirroring the delete-request flow.

    `payload.unit_cost` is the price actually paid on THIS purchase and is
    recorded on the stock event / proposal only -- it deliberately does NOT
    overwrite the catalogue `item.unit_cost` (admin-only via PATCH
    /admin/inventory).

    `delta` < 0 (dispense): always immediate. 400 if it would drive
    quantity_on_hand negative; otherwise decrement and write a `consume`
    event with cost 0 -- no budget change.
    """
    facility = _require_facility(current_user)
    item = _get_inventory_item_or_404(db, item_id, facility)

    now = datetime.utcnow()

    if payload.delta > 0:
        if not item.auto_approved:
            # Block a duplicate identical pending proposal from the same
            # requester (same 409 shape as request_inventory_deletion) --
            # but two DIFFERENT pharmacists, or two different quantities, can
            # each still have one pending.
            existing = (
                db.query(models.MedicinePurchaseProposal)
                .filter(
                    models.MedicinePurchaseProposal.item_id == item.id,
                    models.MedicinePurchaseProposal.requested_by == current_user.id,
                    models.MedicinePurchaseProposal.status == "pending",
                    models.MedicinePurchaseProposal.quantity == payload.delta,
                )
                .first()
            )
            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail="You already have an identical pending purchase proposal for this item.",
                )

            proposal = models.MedicinePurchaseProposal(
                facility_name=facility,
                item_id=item.id,
                proposed_drug_name=item.drug_name,
                proposed_unit=item.unit,
                proposed_barcode=item.barcode,
                quantity=payload.delta,
                unit_cost=payload.unit_cost if payload.unit_cost is not None else item.unit_cost,
                requested_by=current_user.id,
            )
            db.add(proposal)
            db.commit()
            db.refresh(proposal)

            log_access(
                db, None, current_user.id, current_user.role, "propose_restock",
                detail=f"restock +{payload.delta} {item.drug_name} (pending approval)",
                actor_facility=facility,
            )
            return JSONResponse(
                status_code=202,
                content=jsonable_encoder(
                    _serialize_purchase_proposal(proposal, current_user.full_name)
                ),
            )

        cost = _apply_restock(db, item, payload.delta, payload.unit_cost, current_user, facility, now)
        action_detail = f"restock +{payload.delta} {item.drug_name} (cost {cost:.2f})"
        action = "pharmacy_restock"
    else:
        if item.quantity_on_hand + payload.delta < 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot dispense {-payload.delta}: only {item.quantity_on_hand} "
                    f"{item.unit} on hand."
                ),
            )
        item.quantity_on_hand += payload.delta
        item.updated_by = current_user.id
        db.add(models.MedicineStockEvent(
            facility_name=facility, item_id=item.id, delta=payload.delta,
            unit_cost_at_time=item.unit_cost, cost=0.0, kind="consume",
            by=current_user.id, at=now,
        ))
        action_detail = f"dispense {payload.delta} {item.drug_name}"
        action = "pharmacy_dispense"

    db.commit()
    db.refresh(item)

    log_access(
        db, None, current_user.id, current_user.role, action,
        detail=action_detail, actor_facility=facility,
    )
    return _serialize_inventory_item(db, item)


@router.post("/inventory/{item_id}/image", response_model=schemas.MedicineInventoryOut)
def upload_inventory_image(
    item_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_PHARMACY_ROLES)),
):
    """Attach/replace a photo of the medicine or its packaging. Multipart
    `file`; max 2MB; PNG/JPEG/WebP only (declared content-type, filename
    extension and magic bytes must all agree). Replacing an existing image
    deletes the old file best-effort."""
    facility = _require_facility(current_user)
    item = _get_inventory_item_or_404(db, item_id, facility)
    save_medicine_image(db, item, file, current_user, facility)
    return _serialize_inventory_item(db, item)


@router.get("/inventory/{item_id}/image")
def get_inventory_image(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_PHARMACY_ROLES)),
):
    """Returns the medicine photo. Staff-scoped (`_PHARMACY_ROLES`, which
    includes admins), scoped-404, and the object key comes ONLY from the DB
    row -- never the client (identical safeguard to
    patients.py::get_document_file). Content-Type is the magic-byte-sniffed
    type recorded at upload and falls back to application/octet-stream for
    anything outside the image allowlist, so a mis-stored file can never be
    served back with an executable type."""
    facility = _require_facility(current_user)
    item = _get_inventory_item_or_404(db, item_id, facility)

    if not item.image_object_key:
        raise HTTPException(status_code=404, detail="No image for this item")
    try:
        data = get_object_store().get_checked(
            BUCKET_MEDICINE, item.image_object_key, item.image_sha256
        )
    except (ObjectNotFound, ValueError):
        raise HTTPException(status_code=404, detail="No image for this item")
    except ObjectStoreError:
        logger.error(
            "medicine image fetch failed (object store) item=%s key=%s facility=%s",
            item_id, item.image_object_key, facility, exc_info=True,
        )
        raise HTTPException(status_code=503, detail="Image storage is temporarily unavailable.")

    media_type = (
        item.image_mime if item.image_mime in _MEDICINE_IMAGE_MEDIA_TYPES
        else "application/octet-stream"
    )

    log_access(
        db, None, current_user.id, current_user.role, "view_medicine_image",
        detail=item.drug_name, actor_facility=facility,
    )
    # nosniff: defence-in-depth. Upload already enforces declared-type +
    # extension + magic-byte agreement (no SVG), so a stored file is a real
    # raster image, but this stops any browser from ever sniffing it as markup.
    return Response(
        content=data, media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.get("/inventory/{item_id}/image/thumbnail")
def get_inventory_image_thumbnail(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_PHARMACY_ROLES)),
):
    """A 300px JPEG preview of the medicine photo (P1.7). Same auth + facility
    scoping as GET /image; the derived object is regenerated from the original
    on a cache miss. 404 if the item has no photo."""
    facility = _require_facility(current_user)
    item = _get_inventory_item_or_404(db, item_id, facility)
    if not item.image_object_key:
        raise HTTPException(status_code=404, detail="No image for this item")

    try:
        thumb = get_or_make_thumbnail(
            BUCKET_MEDICINE, item.image_object_key, sha256=item.image_sha256
        )
    except ObjectStoreError:
        logger.error(
            "medicine thumbnail generation failed (object store) item=%s key=%s facility=%s",
            item_id, item.image_object_key, facility, exc_info=True,
        )
        raise HTTPException(status_code=503, detail="Image storage is temporarily unavailable.")
    if thumb is None:
        raise HTTPException(status_code=404, detail="No preview available for this item")
    return Response(
        content=thumb, media_type="image/jpeg",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=300"},
    )


@router.post("/inventory/{item_id}/delete-request", response_model=schemas.InventoryDeleteRequestOut)
def request_inventory_deletion(
    item_id: str,
    payload: schemas.InventoryDeleteRequestCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_PHARMACY_ROLES)),
):
    """Files a request for an admin to approve/reject. 409 if a `pending`
    request already exists for this item."""
    facility = _require_facility(current_user)
    item = _get_inventory_item_or_404(db, item_id, facility)

    existing = (
        db.query(models.InventoryDeleteRequest)
        .filter(
            models.InventoryDeleteRequest.item_id == item.id,
            models.InventoryDeleteRequest.status == "pending",
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="A deletion request for this item is already pending admin review.",
        )

    req = models.InventoryDeleteRequest(
        facility_name=facility,
        item_id=item.id,
        item_name=item.drug_name,
        requested_by=current_user.id,
        reason=payload.reason,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    log_access(
        db, None, current_user.id, current_user.role, "request_inventory_deletion",
        detail=item.drug_name, actor_facility=facility,
    )
    return _serialize_delete_request(req, current_user.full_name)


@router.get("/purchase-proposals", response_model=List[schemas.PurchaseProposalOut])
def list_purchase_proposals(
    status: str = Query("pending", description='Filter by status: "pending" (default), "approved", "rejected", or "all".'),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_PHARMACY_ROLES)),
):
    """This pharmacist's facility's purchase proposals, newest first, with
    the requester's display name resolved."""
    if not current_user.facility:
        return []

    query = db.query(models.MedicinePurchaseProposal).filter(
        models.MedicinePurchaseProposal.facility_name == current_user.facility
    )
    if status != "all":
        query = query.filter(models.MedicinePurchaseProposal.status == status)
    proposals = query.order_by(models.MedicinePurchaseProposal.created_at.desc()).all()

    names = resolve_user_names(db, {p.requested_by for p in proposals})
    return [_serialize_purchase_proposal(p, names.get(p.requested_by)) for p in proposals]


@router.post("/purchase-proposals", response_model=schemas.PurchaseProposalOut, status_code=202)
def propose_new_item(
    payload: schemas.PurchaseProposalCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*_PHARMACY_ROLES)),
):
    """Propose a BRAND-NEW catalogue item (item_id NULL on the resulting
    proposal). Approval creates the MedicineInventoryItem then stocks it.
    202 + the serialized proposal. 409 on a duplicate identical pending
    proposal (same drug name, same requester), mirroring the
    delete-request 409."""
    facility = _require_facility(current_user)

    existing = (
        db.query(models.MedicinePurchaseProposal)
        .filter(
            models.MedicinePurchaseProposal.facility_name == facility,
            models.MedicinePurchaseProposal.requested_by == current_user.id,
            models.MedicinePurchaseProposal.status == "pending",
            models.MedicinePurchaseProposal.item_id.is_(None),
            func.lower(models.MedicinePurchaseProposal.proposed_drug_name)
            == payload.proposed_drug_name.lower(),
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="You already have an identical pending proposal for a new item with that name.",
        )

    proposal = models.MedicinePurchaseProposal(
        facility_name=facility,
        item_id=None,
        proposed_drug_name=payload.proposed_drug_name,
        proposed_unit=payload.proposed_unit,
        proposed_barcode=payload.proposed_barcode,
        quantity=payload.quantity,
        unit_cost=payload.unit_cost,
        reason=payload.reason,
        requested_by=current_user.id,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    log_access(
        db, None, current_user.id, current_user.role, "propose_new_medicine",
        detail=proposal.proposed_drug_name, actor_facility=facility,
    )
    return _serialize_purchase_proposal(proposal, current_user.full_name)
