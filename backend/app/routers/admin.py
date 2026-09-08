"""
Facility-scoped admin console endpoints: medicine inventory, ward/bed
capacity, and a facility-wide appointments dashboard.

The `admin` role is NOT being renamed or promoted here -- it is being
redefined in SCOPE: an admin manages their own hospital (`User.facility`)
only, not the whole platform. Every endpoint below is auto-scoped to
`current_user.facility` -- that facility is NEVER taken from client input on
create (always forced server-side from the authenticated admin's own row),
and every list/read is filtered to `facility_name == current_user.facility`.
THIS SCOPING IS THE ACTUAL SECURITY BOUNDARY this router exists to add
("manager admin, not super admin") -- every new endpoint here must keep
following it; don't add one that trusts a client-supplied facility_name.

An admin `User` row with `facility is None` (a pre-existing account, or one
created via /auth/register without a facility) is treated as "this admin
has no assigned hospital yet": every list endpoint below returns an empty
list for such a user (never a crash, never "sees everything"), and every
create endpoint 400s with a clear message rather than silently writing a
facility_name=None row.

Patient record visibility is explicitly untouched by this router -- see
routers/patients.py, which keeps its existing (broader) admin/clinician/
records_officer access as-is.
"""
import secrets
from datetime import datetime, timezone
from typing import List, Optional, Union

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from .. import models, schemas, auth, permissions
from ..database import get_db
from ..audit import log_access
from ..appointments import compute_reminder_offsets
from ..inventory import (
    _get_inventory_item_or_404,
    _serialize_inventory_item,
    _pending_delete_item_ids,
    _serialize_delete_request,
    _apply_inventory_search,
    _apply_restock,
    _serialize_purchase_proposal,
    _low_stock_count,
    save_medicine_image,
)
from .staff import _get_clock_status, batch_clock_status
from .reception import _malaysia_today
from ..directory import resolve_user_names

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_facility(current_user: models.User) -> str:
    """Every admin CREATE endpoint routes through this -- 400s instead of
    silently writing a facility_name=None row for an admin account that has
    no assigned hospital yet (see module docstring's edge-case rule)."""
    if not current_user.facility:
        raise HTTPException(
            status_code=400,
            detail="Your account has no facility assigned — contact a system administrator.",
        )
    return current_user.facility


def _serialize_ward(ward: models.Ward) -> dict:
    available_beds = ward.total_beds - ward.occupied_beds
    occupancy_pct = round((ward.occupied_beds / ward.total_beds) * 100, 1) if ward.total_beds else 0.0
    return {
        "id": ward.id,
        "facility_name": ward.facility_name,
        "ward_name": ward.ward_name,
        "ward_type": ward.ward_type,
        "total_beds": ward.total_beds,
        "occupied_beds": ward.occupied_beds,
        "updated_by": ward.updated_by,
        "updated_at": ward.updated_at,
        "created_at": ward.created_at,
        "available_beds": available_beds,
        "occupancy_pct": occupancy_pct,
    }


def _get_ward_or_404(db: Session, ward_id: str, facility: str) -> models.Ward:
    ward = (
        db.query(models.Ward)
        .filter(models.Ward.id == ward_id, models.Ward.facility_name == facility)
        .first()
    )
    if not ward:
        raise HTTPException(status_code=404, detail="Ward not found")
    return ward


# ---------- Appointments dashboard ----------
@router.get("/appointments", response_model=List[schemas.AdminAppointmentOut])
def list_admin_appointments(
    include_all: bool = Query(False, description="Include cancelled/completed appointments, not just scheduled ones."),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Facility-wide "what's coming up" view across ALL patients at this
    admin's own hospital -- distinct from GET /patients/{id}/appointments,
    which is one patient's own history. Defaults to status="scheduled" only
    (staff dashboards usually want the upcoming queue, not cancelled/
    completed clutter) -- pass ?include_all=true to see full history."""
    if not current_user.facility:
        # No crash, no "sees everything" -- see module docstring's edge-case
        # rule.
        return []

    query = db.query(models.Appointment).filter(models.Appointment.facility_name == current_user.facility)
    if not include_all:
        query = query.filter(models.Appointment.status == "scheduled")
    appointments = query.order_by(models.Appointment.scheduled_at.asc()).all()

    # Batch-resolve patient_id -> patient_name and created_by -> staff name
    # in two queries total, not one query per row (same "batch, don't
    # N+1" discipline as patients.py::get_audit_log's actor_name resolution).
    patient_ids = {a.patient_id for a in appointments}
    patient_names = {}
    if patient_ids:
        for pid, full_name in (
            db.query(models.Patient.id, models.Patient.full_name)
            .filter(models.Patient.id.in_(patient_ids))
            .all()
        ):
            patient_names[pid] = full_name

    creator_names = resolve_user_names(db, {a.created_by for a in appointments})

    log_access(
        db, None, current_user.id, current_user.role, "view_admin_appointments",
        actor_facility=current_user.facility,
    )

    results = []
    for a in appointments:
        results.append({
            "id": a.id,
            "patient_id": a.patient_id,
            "facility_name": a.facility_name,
            "venue": a.venue,
            "scheduled_at": a.scheduled_at,
            "reason": a.reason,
            "fasting_required": a.fasting_required,
            "fasting_hours": a.fasting_hours,
            "precaution_notes": a.precaution_notes,
            "extra_reminder_hours_before": a.extra_reminder_hours_before,
            "status": a.status,
            "created_by": a.created_by,
            "created_at": a.created_at,
            "previous_scheduled_at": a.previous_scheduled_at,
            "reschedule_reason_code": a.reschedule_reason_code,
            "reschedule_reason_other": a.reschedule_reason_other,
            "reminders": compute_reminder_offsets(a),
            # latest_reschedule_request deliberately omitted here (left at
            # AppointmentOut's default None) -- this is a read-only,
            # facility-wide monitoring list (see this endpoint's docstring),
            # not the accept/reject action surface (that's
            # PatientDetail.jsx, via GET /patients/{id}/appointments), so
            # it's not worth an extra per-row query in a bulk listing.
            "patient_name": patient_names.get(a.patient_id, "Unknown patient"),
            # None if the creating staff account has since been deleted --
            # see AdminAppointmentOut's docstring.
            "created_by_name": creator_names.get(a.created_by),
        })
    return results


# ---------- Medicine inventory ----------
@router.get("/inventory", response_model=List[schemas.MedicineInventoryOut])
def list_inventory(
    low_stock_only: bool = Query(False),
    q: Optional[str] = Query(None, description="Case-insensitive substring match on drug_name, or exact/prefix match on barcode (e.g. a scanned code)."),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    if not current_user.facility:
        return []

    query = db.query(models.MedicineInventoryItem).filter(
        models.MedicineInventoryItem.facility_name == current_user.facility
    )
    if low_stock_only:
        query = query.filter(
            models.MedicineInventoryItem.reorder_threshold.isnot(None),
            models.MedicineInventoryItem.quantity_on_hand <= models.MedicineInventoryItem.reorder_threshold,
        )
    query = _apply_inventory_search(query, q)
    items = query.order_by(models.MedicineInventoryItem.drug_name.asc()).all()
    pending = _pending_delete_item_ids(db, [i.id for i in items])
    return [_serialize_inventory_item(db, i, pending) for i in items]


@router.post("/inventory/{item_id}/image", response_model=schemas.MedicineInventoryOut)
def upload_inventory_image_admin(
    item_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Attach/replace a photo of the medicine or its packaging. Multipart
    `file`; max 2MB; PNG/JPEG/WebP only (content-type + extension + magic
    bytes must all agree). Same action is available to pharmacists via
    POST /pharmacy/inventory/{id}/image."""
    facility = _require_facility(current_user)
    item = _get_inventory_item_or_404(db, item_id, facility)
    save_medicine_image(db, item, file, current_user, facility)
    return _serialize_inventory_item(db, item)


@router.post("/inventory", response_model=schemas.MedicineInventoryOut)
def create_inventory_item(
    payload: schemas.MedicineInventoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """facility_name is FORCED to current_user.facility -- MedicineInventoryCreate
    has no facility_name field at all, so there's nothing for a client to
    override even if it tries to send one in the request body (FastAPI/
    pydantic simply ignores unknown keys here, since this schema has no
    extra="forbid"). This is the actual security boundary the whole admin
    scoping rests on -- see module docstring."""
    facility = _require_facility(current_user)

    item = models.MedicineInventoryItem(
        facility_name=facility, updated_by=current_user.id, **payload.model_dump()
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    log_access(
        db, None, current_user.id, current_user.role, "create_inventory_item",
        detail=item.drug_name, actor_facility=current_user.facility,
    )
    return _serialize_inventory_item(db, item)


@router.patch("/inventory/{item_id}", response_model=schemas.MedicineInventoryOut)
def update_inventory_item(
    item_id: str,
    payload: schemas.MedicineInventoryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _require_facility(current_user)
    item = _get_inventory_item_or_404(db, item_id, facility)

    submitted_fields = payload.model_dump(exclude_unset=True)
    previous_quantity = item.quantity_on_hand
    for field, value in submitted_fields.items():
        setattr(item, field, value)

    # A RAISE in quantity_on_hand is a genuine restock -- stamp
    # last_restocked_at. A lower/unchanged quantity is consumption or a
    # correction, not a restock, so that timestamp is deliberately left
    # untouched -- matters for anyone later auditing "when did we last
    # actually get more stock" (see module-level task spec for the exact
    # reasoning this preserves).
    if "quantity_on_hand" in submitted_fields and item.quantity_on_hand > previous_quantity:
        item.last_restocked_at = datetime.utcnow()

    if submitted_fields:
        item.updated_by = current_user.id
        db.add(item)
        db.commit()
        db.refresh(item)

    log_access(
        db, None, current_user.id, current_user.role, "update_inventory_item",
        fields=sorted(submitted_fields.keys()), detail=item.drug_name,
        actor_facility=current_user.facility,
    )
    return _serialize_inventory_item(db, item)


@router.delete("/inventory/{item_id}")
def delete_inventory_item(
    item_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Hard delete -- unlike patient-facing resources this isn't clinical
    history worth soft-preserving (an EmergencyToken-style revoked flag
    would be pointless here): a discontinued inventory item should just go
    away."""
    facility = _require_facility(current_user)
    item = _get_inventory_item_or_404(db, item_id, facility)
    drug_name = item.drug_name

    db.delete(item)
    db.commit()

    log_access(
        db, None, current_user.id, current_user.role, "delete_inventory_item",
        detail=drug_name, actor_facility=current_user.facility,
    )
    return {"detail": "Inventory item deleted"}


# ---------- Inventory: pharmacist deletion requests (admin approval) ----------
# Declared right after the inventory CRUD above and BEFORE any of the
# `/inventory/{item_id}` style routes matter for GET (there is no GET on
# `/inventory/{item_id}`, so `/inventory/delete-requests` can't be swallowed
# -- but keeping them adjacent makes the ordering obvious).


def _get_delete_request_or_404(db: Session, request_id: str, facility: str) -> models.InventoryDeleteRequest:
    req = (
        db.query(models.InventoryDeleteRequest)
        .filter(
            models.InventoryDeleteRequest.id == request_id,
            models.InventoryDeleteRequest.facility_name == facility,
        )
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Delete request not found")
    return req


@router.get("/inventory/delete-requests", response_model=List[schemas.InventoryDeleteRequestOut])
def list_inventory_delete_requests(
    status: str = Query("pending", description='Filter by status: "pending" (default), "approved", "rejected", or "all".'),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    if not current_user.facility:
        return []

    query = db.query(models.InventoryDeleteRequest).filter(
        models.InventoryDeleteRequest.facility_name == current_user.facility
    )
    if status != "all":
        query = query.filter(models.InventoryDeleteRequest.status == status)
    requests = query.order_by(models.InventoryDeleteRequest.created_at.desc()).all()

    requester_names = resolve_user_names(db, {r.requested_by for r in requests})

    return [_serialize_delete_request(r, requester_names.get(r.requested_by)) for r in requests]


@router.post("/inventory/delete-requests/{request_id}/approve", response_model=schemas.InventoryDeleteRequestOut)
def approve_inventory_delete_request(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Marks the request approved and performs the hard delete of the item.
    The item may already be gone (a direct admin DELETE, or a prior
    approval) -- that's handled gracefully, the request still resolves."""
    facility = _require_facility(current_user)
    req = _get_delete_request_or_404(db, request_id, facility)
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request already {req.status}.")

    item = (
        db.query(models.MedicineInventoryItem)
        .filter(
            models.MedicineInventoryItem.id == req.item_id,
            models.MedicineInventoryItem.facility_name == facility,
        )
        .first()
    )
    if item is not None:
        db.delete(item)

    req.status = "approved"
    req.resolved_by = current_user.id
    req.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(req)

    log_access(
        db, None, current_user.id, current_user.role, "approve_inventory_delete_request",
        detail=req.item_name, actor_facility=facility,
    )
    requester_name = (
        db.query(models.User.full_name).filter(models.User.id == req.requested_by).scalar()
    )
    return _serialize_delete_request(req, requester_name)


@router.post("/inventory/delete-requests/{request_id}/reject", response_model=schemas.InventoryDeleteRequestOut)
def reject_inventory_delete_request(
    request_id: str,
    payload: schemas.DeleteRequestResolve,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _require_facility(current_user)
    req = _get_delete_request_or_404(db, request_id, facility)
    if req.status != "pending":
        raise HTTPException(status_code=409, detail=f"Request already {req.status}.")

    req.status = "rejected"
    req.admin_note = payload.admin_note
    req.resolved_by = current_user.id
    req.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(req)

    log_access(
        db, None, current_user.id, current_user.role, "reject_inventory_delete_request",
        detail=req.item_name, actor_facility=facility,
    )
    requester_name = (
        db.query(models.User.full_name).filter(models.User.id == req.requested_by).scalar()
    )
    return _serialize_delete_request(req, requester_name)


# ---------- Inventory: pharmacist purchase proposals (admin approval) ----------
# The procurement counterpart to the delete-request flow directly above --
# same facility-scoped, non-leaking 404 and same "pending -> approve/reject"
# shape. A proposal with item_id set restocks an existing item; item_id NULL
# creates a brand-new catalogue item then stocks it. Approval runs the
# shared _apply_restock primitive (see its docstring) so it is byte-for-byte
# the same stock/budget movement as an auto-approved pharmacist restock.


def _get_purchase_proposal_or_404(
    db: Session, proposal_id: str, facility: str,
) -> models.MedicinePurchaseProposal:
    proposal = (
        db.query(models.MedicinePurchaseProposal)
        .filter(
            models.MedicinePurchaseProposal.id == proposal_id,
            models.MedicinePurchaseProposal.facility_name == facility,
        )
        .first()
    )
    if not proposal:
        raise HTTPException(status_code=404, detail="Purchase proposal not found")
    return proposal


def _purchase_proposals_with_names(
    db: Session, proposals: List[models.MedicinePurchaseProposal],
) -> list:
    """Batch-resolve requester display names in one query, same
    "batch, don't N+1" discipline as list_inventory_delete_requests."""
    names = resolve_user_names(db, {p.requested_by for p in proposals})
    return [_serialize_purchase_proposal(p, names.get(p.requested_by)) for p in proposals]


@router.get("/purchase-proposals", response_model=List[schemas.PurchaseProposalOut])
def list_purchase_proposals(
    status: str = Query("pending", description='Filter by status: "pending" (default), "approved", "rejected", or "all".'),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """The admin approval queue for this admin's own facility, newest first."""
    if not current_user.facility:
        return []

    query = db.query(models.MedicinePurchaseProposal).filter(
        models.MedicinePurchaseProposal.facility_name == current_user.facility
    )
    if status != "all":
        query = query.filter(models.MedicinePurchaseProposal.status == status)
    proposals = query.order_by(models.MedicinePurchaseProposal.created_at.desc()).all()
    return _purchase_proposals_with_names(db, proposals)


@router.post("/purchase-proposals/{proposal_id}/approve", response_model=schemas.PurchaseProposalOut)
def approve_purchase_proposal(
    proposal_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Approve a pharmacist's purchase proposal and apply it.

    - existing item (item_id set): restock it by `quantity` via the shared
      _apply_restock primitive. 409 if the catalogue item has since been
      hard-deleted (a dangling ref -- nothing to restock).
    - new item (item_id NULL): create the MedicineInventoryItem
      (quantity_on_hand=0, unit_cost = proposal.unit_cost, barcode =
      proposal.proposed_barcode) then run the same restock for `quantity`.
    """
    facility = _require_facility(current_user)
    proposal = _get_purchase_proposal_or_404(db, proposal_id, facility)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal already {proposal.status}.")

    # Atomically CLAIM the proposal before doing any stock/budget work, so a
    # double-click or client retry can't run _apply_restock twice for one
    # proposal (each would otherwise both read status='pending' first). The
    # conditional UPDATE flips pending->approved in a single statement; a
    # concurrent caller's identical UPDATE then matches zero rows. If anything
    # below raises, the surrounding request transaction is never committed and
    # this claim rolls back with it.
    claimed = (
        db.query(models.MedicinePurchaseProposal)
        .filter(
            models.MedicinePurchaseProposal.id == proposal.id,
            models.MedicinePurchaseProposal.status == "pending",
        )
        .update(
            {
                "status": "approved",
                "reviewed_by": current_user.id,
                "reviewed_at": datetime.utcnow(),
            },
            synchronize_session=False,
        )
    )
    if not claimed:
        db.rollback()
        raise HTTPException(status_code=409, detail="Proposal was already handled by another request.")
    db.refresh(proposal)

    if proposal.item_id is not None:
        item = (
            db.query(models.MedicineInventoryItem)
            .filter(
                models.MedicineInventoryItem.id == proposal.item_id,
                models.MedicineInventoryItem.facility_name == facility,
            )
            .first()
        )
        if item is None:
            raise HTTPException(
                status_code=409,
                detail="The catalogue item this proposal targets no longer exists — reject it instead.",
            )
        detail = f"approve restock +{proposal.quantity} {item.drug_name}"
    else:
        item = models.MedicineInventoryItem(
            facility_name=facility,
            drug_name=proposal.proposed_drug_name,
            unit=proposal.proposed_unit,
            barcode=proposal.proposed_barcode,
            quantity_on_hand=0,
            unit_cost=proposal.unit_cost,
            updated_by=current_user.id,
        )
        db.add(item)
        db.flush()  # assign item.id before the restock event references it
        detail = f"approve new item {item.drug_name} (+{proposal.quantity})"

    cost = _apply_restock(db, item, proposal.quantity, proposal.unit_cost, current_user, facility)

    # status / reviewed_by / reviewed_at were already set by the atomic claim
    # above; just persist the restock + any new-item row.
    db.commit()
    db.refresh(proposal)

    log_access(
        db, None, current_user.id, current_user.role, "approve_purchase_proposal",
        detail=f"{detail} (cost {cost:.2f})", actor_facility=facility,
    )
    requester_name = (
        db.query(models.User.full_name).filter(models.User.id == proposal.requested_by).scalar()
    )
    return _serialize_purchase_proposal(proposal, requester_name)


@router.post("/purchase-proposals/{proposal_id}/reject", response_model=schemas.PurchaseProposalOut)
def reject_purchase_proposal(
    proposal_id: str,
    payload: schemas.PurchaseProposalReject,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _require_facility(current_user)
    proposal = _get_purchase_proposal_or_404(db, proposal_id, facility)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal already {proposal.status}.")

    proposal.status = "rejected"
    proposal.admin_note = payload.reason
    proposal.reviewed_by = current_user.id
    proposal.reviewed_at = datetime.utcnow()
    db.commit()
    db.refresh(proposal)

    log_access(
        db, None, current_user.id, current_user.role, "reject_purchase_proposal",
        detail=proposal.proposed_drug_name, actor_facility=facility,
    )
    requester_name = (
        db.query(models.User.full_name).filter(models.User.id == proposal.requested_by).scalar()
    )
    return _serialize_purchase_proposal(proposal, requester_name)


# ---------- Medicine procurement budget ----------
def _current_stock_value(db: Session, facility: str) -> float:
    total = (
        db.query(
            func.sum(
                func.coalesce(models.MedicineInventoryItem.unit_cost, 0.0)
                * models.MedicineInventoryItem.quantity_on_hand
            )
        )
        .filter(models.MedicineInventoryItem.facility_name == facility)
        .scalar()
    )
    return float(total or 0.0)


@router.get("/budget", response_model=schemas.BudgetOut)
def get_budget(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    if not current_user.facility:
        return schemas.BudgetOut(
            allocated_amount=0.0, procurement_spend=0.0,
            current_stock_value=0.0, remaining=0.0, low_stock_count=0,
        )

    facility = current_user.facility
    budget = (
        db.query(models.MedicineBudget)
        .filter(models.MedicineBudget.facility_name == facility)
        .first()
    )
    allocated = float(budget.allocated_amount) if budget else 0.0
    spend = float(budget.procurement_spend) if budget else 0.0
    return schemas.BudgetOut(
        allocated_amount=allocated,
        procurement_spend=spend,
        current_stock_value=_current_stock_value(db, facility),
        remaining=allocated - spend,
        low_stock_count=_low_stock_count(db, facility),
    )


@router.put("/budget", response_model=schemas.BudgetOut)
def set_budget(
    payload: schemas.BudgetUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _require_facility(current_user)
    budget = (
        db.query(models.MedicineBudget)
        .filter(models.MedicineBudget.facility_name == facility)
        .first()
    )
    if budget is None:
        budget = models.MedicineBudget(facility_name=facility, procurement_spend=0.0)
        db.add(budget)
    budget.allocated_amount = payload.allocated_amount
    budget.updated_by = current_user.id
    db.commit()
    db.refresh(budget)

    log_access(
        db, None, current_user.id, current_user.role, "set_medicine_budget",
        detail=f"allocated={budget.allocated_amount}", actor_facility=facility,
    )
    return schemas.BudgetOut(
        allocated_amount=float(budget.allocated_amount),
        procurement_spend=float(budget.procurement_spend),
        current_stock_value=_current_stock_value(db, facility),
        remaining=float(budget.allocated_amount) - float(budget.procurement_spend),
    )


# ---------- Hospital settings (per-facility admin config) ----------
# One HospitalSetting row per facility_name, lazily created with documented
# defaults on first read -- the exact same create-on-read pattern as
# get_budget / MedicineBudget above. Same forced-facility boundary as every
# other endpoint in this router: the row is always keyed on
# current_user.facility, never a client-supplied name.
def _get_or_create_hospital_setting(db: Session, facility: str) -> models.HospitalSetting:
    setting = (
        db.query(models.HospitalSetting)
        .filter(models.HospitalSetting.facility_name == facility)
        .first()
    )
    if setting is None:
        setting = models.HospitalSetting(
            facility_name=facility,
            # display_name defaults to the facility_name itself so the row is
            # immediately usable on a console without a mandatory first edit.
            display_name=facility,
        )
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


@router.get("/hospital-settings", response_model=schemas.HospitalSettingOut)
def get_hospital_settings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """This admin's own facility's settings row, created-on-read with
    defaults (records_shared_publicly=True, timezone=Asia/Kuala_Lumpur)."""
    facility = _require_facility(current_user)
    return _get_or_create_hospital_setting(db, facility)


@router.put("/hospital-settings", response_model=schemas.HospitalSettingOut)
def update_hospital_settings(
    payload: schemas.HospitalSettingUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Update display_name / address / contact_phone / timezone /
    records_shared_publicly for the caller's own facility. Flipping
    records_shared_publicly to False immediately hides this facility's
    authored clinical sub-records from staff at other facilities (see
    routers/patients.py::_serialize_patient); the emergency-scan path and the
    patient's own view are never affected."""
    facility = _require_facility(current_user)
    setting = _get_or_create_hospital_setting(db, facility)

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(setting, field, value)

    if submitted_fields:
        setting.updated_by = current_user.id
        db.add(setting)
        db.commit()
        db.refresh(setting)

    log_access(
        db, None, current_user.id, current_user.role, "update_hospital_settings",
        fields=sorted(submitted_fields.keys()), detail=facility,
        actor_facility=facility,
    )
    return setting


# ---------- Role -> page access (per-facility, admin-configurable) ----------
# Which console pages each staff role may reach AT THIS ADMIN'S FACILITY.
# Same forced-facility boundary as every other endpoint in this router (the
# row is always keyed on current_user.facility, never client input) and the
# same lazy create-on-read pattern as hospital-settings above -- the actual
# model + defaults live in app/permissions.py; enforcement is
# auth.require_page_access, wired at router level in app/main.py.
def _role_permissions_payload(db: Session, facility: str) -> List[schemas.RolePagePermissionOut]:
    rows = [
        schemas.RolePagePermissionOut(
            role=role,
            allowed_pages=list(
                permissions.get_or_create_role_permission(db, facility, role).allowed_pages or []
            ),
            configurable_pages=list(permissions.CONFIGURABLE_PAGES),
            editable=True,
        )
        for role in permissions.CONFIGURABLE_STAFF_ROLES
    ]
    # A read-only `admin` row so the matrix UI can render it greyed --
    # admin always holds every page and is never a configurable checkbox.
    rows.append(
        schemas.RolePagePermissionOut(
            role="admin",
            allowed_pages=list(permissions.ADMIN_PAGES),
            configurable_pages=list(permissions.CONFIGURABLE_PAGES),
            editable=False,
        )
    )
    return rows


@router.get("/role-permissions", response_model=List[schemas.RolePagePermissionOut])
def get_role_permissions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """One row per configurable staff role (clinician / records_officer /
    receptionist / pharmacist), lazily created with the documented defaults
    on first read, plus a read-only `admin` row. `configurable_pages` is the
    fixed full column set (["patients","reception","pharmacy"]) so the UI
    knows every checkbox that exists."""
    facility = _require_facility(current_user)
    return _role_permissions_payload(db, facility)


@router.put("/role-permissions", response_model=List[schemas.RolePagePermissionOut])
def update_role_permissions(
    body: Union[schemas.RolePagePermissionUpdate, List[schemas.RolePagePermissionUpdate]] = Body(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Upsert page access for one role ({role, allowed_pages}) or several at
    once (a list -- nicer for a matrix save). Validates that every `role` is
    a configurable staff role (admin / patient / emergency_responder are
    rejected outright) and every page is in
    ["patients","reception","pharmacy"] (the `admin` page is never
    assignable to another role). Always scoped to the acting admin's own
    facility."""
    facility = _require_facility(current_user)
    items = body if isinstance(body, list) else [body]
    if not items:
        raise HTTPException(status_code=400, detail="No role permissions supplied.")

    seen: set = set()
    for item in items:
        if item.role not in permissions.CONFIGURABLE_STAFF_ROLES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"role must be one of: {', '.join(permissions.CONFIGURABLE_STAFF_ROLES)} "
                    f"(got {item.role!r})."
                ),
            )
        if item.role in seen:
            raise HTTPException(status_code=400, detail=f"Duplicate role in request: {item.role}.")
        seen.add(item.role)
        unknown = [p for p in item.allowed_pages if p not in permissions.CONFIGURABLE_PAGES]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown page(s): {', '.join(unknown)}. "
                    f"Valid pages: {', '.join(permissions.CONFIGURABLE_PAGES)}."
                ),
            )

    for item in items:
        row = permissions.get_or_create_role_permission(db, facility, item.role)
        row.allowed_pages = permissions._canonical_order(item.allowed_pages)
        row.updated_by = current_user.id
        db.add(row)
    db.commit()

    log_access(
        db, None, current_user.id, current_user.role, "update_role_permissions",
        fields=sorted(seen), detail=facility, actor_facility=facility,
    )
    return _role_permissions_payload(db, facility)


# ---------- Wards ----------
@router.get("/wards", response_model=List[schemas.WardOut])
def list_wards(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    if not current_user.facility:
        return []

    wards = (
        db.query(models.Ward)
        .filter(models.Ward.facility_name == current_user.facility)
        .order_by(models.Ward.ward_name.asc())
        .all()
    )
    return [_serialize_ward(w) for w in wards]


@router.post("/wards", response_model=schemas.WardOut)
def create_ward(
    payload: schemas.WardCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Same forced-facility pattern as create_inventory_item -- see that
    function's docstring; the exact same boundary applies here."""
    facility = _require_facility(current_user)

    ward = models.Ward(facility_name=facility, updated_by=current_user.id, **payload.model_dump())
    db.add(ward)
    db.commit()
    db.refresh(ward)

    log_access(
        db, None, current_user.id, current_user.role, "create_ward",
        detail=ward.ward_name, actor_facility=current_user.facility,
    )
    return _serialize_ward(ward)


@router.patch("/wards/{ward_id}", response_model=schemas.WardOut)
def update_ward(
    ward_id: str,
    payload: schemas.WardUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _require_facility(current_user)
    ward = _get_ward_or_404(db, ward_id, facility)

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(ward, field, value)

    # Re-validate total_beds/occupied_beds against the MERGED row, not just
    # the raw PATCH payload -- schemas.WardUpdate deliberately skips this
    # check itself (see its docstring), same technique (and same "inline
    # in the router, not a schema-internal call" style) as
    # appointments.py::update_appointment's fasting_hours/fasting_required
    # re-check.
    if not (0 <= ward.occupied_beds <= ward.total_beds):
        raise HTTPException(
            status_code=400,
            detail="occupied_beds must be between 0 and total_beds.",
        )

    if submitted_fields:
        ward.updated_by = current_user.id
        db.add(ward)
        db.commit()
        db.refresh(ward)

    log_access(
        db, None, current_user.id, current_user.role, "update_ward",
        fields=sorted(submitted_fields.keys()), detail=ward.ward_name,
        actor_facility=current_user.facility,
    )
    return _serialize_ward(ward)


@router.delete("/wards/{ward_id}")
def delete_ward(
    ward_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _require_facility(current_user)
    ward = _get_ward_or_404(db, ward_id, facility)
    ward_name = ward.ward_name

    db.delete(ward)
    db.commit()

    log_access(
        db, None, current_user.id, current_user.role, "delete_ward",
        detail=ward_name, actor_facility=current_user.facility,
    )
    return {"detail": "Ward deleted"}


# ---------- Floors (auto-generated wards) ----------
# Same forced-facility / scoped-404 boundary as wards/inventory above (see
# this module's docstring). A Floor owns a uniform block of general Ward
# rows: the admin sets ward_count + beds_per_ward as numbers, the backend
# creates/adjusts that many identical Ward rows. Per-bed occupancy lives on
# models.Admission (routers/reception.py), NOT on Ward.occupied_beds -- the
# legacy aggregate counter is deliberately left alone here.
def _ward_name_for_floor(floor_label: str, index: int) -> str:
    return f"{floor_label} — Ward {index}"


def _build_floor_wards(floor: models.Floor, facility: str, user_id: str, start_index: int, count: int) -> list:
    """`count` fresh general Ward rows numbered `start_index .. start_index+count-1`,
    each sized to `floor.beds_per_ward` and pointing back at `floor`. Shared
    with seed.py so the seed and the endpoint build identical rows."""
    return [
        models.Ward(
            facility_name=facility,
            ward_name=_ward_name_for_floor(floor.floor_label, i),
            ward_type="general",
            total_beds=floor.beds_per_ward,
            occupied_beds=0,
            floor_id=floor.id,
            updated_by=user_id,
        )
        for i in range(start_index, start_index + count)
    ]


def _floor_child_wards(db: Session, floor_id: str) -> list:
    # Ordered by creation so "the trailing wards" (the ones a ward_count
    # decrease removes) are unambiguously the most recently added.
    return (
        db.query(models.Ward)
        .filter(models.Ward.floor_id == floor_id)
        .order_by(models.Ward.created_at.asc(), models.Ward.id.asc())
        .all()
    )


def _ward_has_active_admission(db: Session, ward_id: str) -> bool:
    return (
        db.query(models.Admission.id)
        .filter(models.Admission.ward_id == ward_id, models.Admission.discharged_at.is_(None))
        .first()
        is not None
    )


def _serialize_floor(db: Session, floor: models.Floor) -> dict:
    wards = _floor_child_wards(db, floor.id)
    ward_ids = [w.id for w in wards]
    occupied = 0
    if ward_ids:
        occupied = (
            db.query(func.count(models.Admission.id))
            .filter(
                models.Admission.ward_id.in_(ward_ids),
                models.Admission.discharged_at.is_(None),
            )
            .scalar()
        ) or 0
    return {
        "id": floor.id,
        "facility_name": floor.facility_name,
        "floor_label": floor.floor_label,
        "gender_restriction": floor.gender_restriction,
        "ward_count": floor.ward_count,
        "beds_per_ward": floor.beds_per_ward,
        "created_by": floor.created_by,
        "created_at": floor.created_at,
        "updated_by": floor.updated_by,
        "updated_at": floor.updated_at,
        "ward_ids": ward_ids,
        "total_beds": sum(w.total_beds for w in wards),
        "occupied_beds": occupied,
    }


def _get_floor_or_404(db: Session, floor_id: str, facility: str) -> models.Floor:
    floor = (
        db.query(models.Floor)
        .filter(models.Floor.id == floor_id, models.Floor.facility_name == facility)
        .first()
    )
    if not floor:
        raise HTTPException(status_code=404, detail="Floor not found")
    return floor


@router.get("/floors", response_model=List[schemas.FloorOut])
def list_floors(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    if not current_user.facility:
        return []
    floors = (
        db.query(models.Floor)
        .filter(models.Floor.facility_name == current_user.facility)
        .order_by(models.Floor.floor_label.asc())
        .all()
    )
    return [_serialize_floor(db, f) for f in floors]


@router.post("/floors", response_model=schemas.FloorOut)
def create_floor(
    payload: schemas.FloorCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Same forced-facility pattern as create_ward -- plus it materialises
    `ward_count` child Ward rows in the same transaction."""
    facility = _require_facility(current_user)

    floor = models.Floor(
        facility_name=facility,
        created_by=current_user.id,
        updated_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(floor)
    db.flush()  # assign floor.id before building child wards
    for ward in _build_floor_wards(floor, facility, current_user.id, 1, floor.ward_count):
        db.add(ward)
    db.commit()
    db.refresh(floor)

    log_access(
        db, None, current_user.id, current_user.role, "create_floor",
        detail=f"{floor.floor_label} ({floor.ward_count} wards x {floor.beds_per_ward} beds)",
        actor_facility=facility,
    )
    return _serialize_floor(db, floor)


@router.patch("/floors/{floor_id}", response_model=schemas.FloorOut)
def update_floor(
    floor_id: str,
    payload: schemas.FloorUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _require_facility(current_user)
    floor = _get_floor_or_404(db, floor_id, facility)

    submitted_fields = payload.model_dump(exclude_unset=True)
    child_wards = _floor_child_wards(db, floor.id)

    # floor_label / gender_restriction: always allowed. Deliberately does NOT
    # rename existing child wards or move already-admitted patients -- a bed
    # assignment is a point-in-time fact (same reasoning as the plan's
    # "changing gender_restriction doesn't move existing patients").
    if "floor_label" in submitted_fields:
        floor.floor_label = submitted_fields["floor_label"]
    if "gender_restriction" in submitted_fields:
        floor.gender_restriction = submitted_fields["gender_restriction"]

    # beds_per_ward: resize every child ward. 400 if a patient is currently
    # in a bed number that would fall outside the new range.
    if "beds_per_ward" in submitted_fields:
        new_bpw = submitted_fields["beds_per_ward"]
        stranded = (
            db.query(models.Admission)
            .filter(
                models.Admission.ward_id.in_([w.id for w in child_wards] or ["__none__"]),
                models.Admission.discharged_at.is_(None),
                models.Admission.bed_number > new_bpw,
            )
            .first()
        )
        if stranded:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot reduce beds_per_ward: a patient is admitted to a bed number "
                    "above the new limit. Discharge or move them first."
                ),
            )
        floor.beds_per_ward = new_bpw
        for w in child_wards:
            w.total_beds = new_bpw

    # ward_count: raising adds trailing wards; lowering removes trailing
    # wards, but only if they have NO active admission.
    if "ward_count" in submitted_fields:
        new_count = submitted_fields["ward_count"]
        current_count = len(child_wards)
        if new_count > current_count:
            for w in _build_floor_wards(
                floor, facility, current_user.id, current_count + 1, new_count - current_count
            ):
                db.add(w)
        elif new_count < current_count:
            trailing = child_wards[new_count:]
            for w in trailing:
                if _ward_has_active_admission(db, w.id):
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Cannot reduce ward_count: '{w.ward_name}' still has an admitted "
                            "patient. Discharge or move them first."
                        ),
                    )
            for w in trailing:
                db.delete(w)
        floor.ward_count = new_count

    if submitted_fields:
        floor.updated_by = current_user.id
        db.commit()
        db.refresh(floor)

    log_access(
        db, None, current_user.id, current_user.role, "update_floor",
        fields=sorted(submitted_fields.keys()), detail=floor.floor_label,
        actor_facility=facility,
    )
    return _serialize_floor(db, floor)


@router.delete("/floors/{floor_id}")
def delete_floor(
    floor_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """400 if any child ward has an active admission; otherwise deletes the
    child wards then the floor."""
    facility = _require_facility(current_user)
    floor = _get_floor_or_404(db, floor_id, facility)
    child_wards = _floor_child_wards(db, floor.id)

    for w in child_wards:
        if _ward_has_active_admission(db, w.id):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot delete this floor: one of its wards still has an admitted "
                    "patient. Discharge everyone on the floor first."
                ),
            )
    for w in child_wards:
        db.delete(w)
    db.delete(floor)
    db.commit()

    log_access(
        db, None, current_user.id, current_user.role, "delete_floor",
        detail=floor.floor_label, actor_facility=facility,
    )
    return {"detail": "Floor deleted"}


# ---------- Consultation rooms ("Bilik") ----------
# Same forced-facility / scoped-404 boundary as wards and inventory above --
# see this module's docstring. These rooms feed reception's round-robin
# check-in assignment (routers/reception.py::_assign_room) and the
# clinician "My Room" worklist.
def _room_waiting_today(db: Session, room_id: str) -> int:
    _utc_start, queue_date = _malaysia_today()
    return (
        db.query(func.count(models.QueueTicket.id))
        .filter(
            models.QueueTicket.room_id == room_id,
            models.QueueTicket.queue_date == queue_date,
            models.QueueTicket.status != "cancelled",
        )
        .scalar()
    ) or 0


def _serialize_room(db: Session, room: models.ConsultationRoom) -> dict:
    return {
        "id": room.id,
        "facility_name": room.facility_name,
        "room_name": room.room_name,
        "department": room.department,
        "active": room.active,
        "updated_by": room.updated_by,
        "updated_at": room.updated_at,
        "created_at": room.created_at,
        "waiting_today": _room_waiting_today(db, room.id),
    }


def _get_room_or_404(db: Session, room_id: str, facility: str) -> models.ConsultationRoom:
    room = (
        db.query(models.ConsultationRoom)
        .filter(
            models.ConsultationRoom.id == room_id,
            models.ConsultationRoom.facility_name == facility,
        )
        .first()
    )
    if not room:
        raise HTTPException(status_code=404, detail="Consultation room not found")
    return room


@router.get("/rooms", response_model=List[schemas.ConsultationRoomOut])
def list_rooms(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    if not current_user.facility:
        return []
    rooms = (
        db.query(models.ConsultationRoom)
        .filter(models.ConsultationRoom.facility_name == current_user.facility)
        .order_by(models.ConsultationRoom.room_name.asc())
        .all()
    )
    return [_serialize_room(db, r) for r in rooms]


@router.post("/rooms", response_model=schemas.ConsultationRoomOut)
def create_room(
    payload: schemas.ConsultationRoomCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _require_facility(current_user)
    room = models.ConsultationRoom(
        facility_name=facility, created_by=current_user.id, updated_by=current_user.id,
        **payload.model_dump(),
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    log_access(
        db, None, current_user.id, current_user.role, "create_room",
        detail=room.room_name, actor_facility=current_user.facility,
    )
    return _serialize_room(db, room)


@router.patch("/rooms/{room_id}", response_model=schemas.ConsultationRoomOut)
def update_room(
    room_id: str,
    payload: schemas.ConsultationRoomUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _require_facility(current_user)
    room = _get_room_or_404(db, room_id, facility)

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(room, field, value)
    if submitted_fields:
        room.updated_by = current_user.id
        db.add(room)
        db.commit()
        db.refresh(room)

    log_access(
        db, None, current_user.id, current_user.role, "update_room",
        fields=sorted(submitted_fields.keys()), detail=room.room_name,
        actor_facility=current_user.facility,
    )
    return _serialize_room(db, room)


@router.delete("/rooms/{room_id}")
def delete_room(
    room_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Hard delete. Any active RoomClaim on this room is released first so a
    clinician isn't left "in" a room that no longer exists; past QueueTickets
    keep their room_name snapshot (room_id becomes a dangling ref, tolerated
    the same way a deleted staff account is on old audit rows)."""
    facility = _require_facility(current_user)
    room = _get_room_or_404(db, room_id, facility)
    room_name = room.room_name

    now = datetime.utcnow()
    for claim in (
        db.query(models.RoomClaim)
        .filter(models.RoomClaim.room_id == room_id, models.RoomClaim.released_at.is_(None))
        .all()
    ):
        claim.released_at = now

    db.delete(room)
    db.commit()

    log_access(
        db, None, current_user.id, current_user.role, "delete_room",
        detail=room_name, actor_facility=current_user.facility,
    )
    return {"detail": "Consultation room deleted"}


# ---------- Facility sections (per-counter reception scoping) ----------
# An admin defines the front-desk registration counters for their own
# hospital ("General Registration", "Emergency", "O&G", "Orthopaedics",
# "ICU") and pins each receptionist/clinician to one (see
# assign_staff_section below + models.User.section). Same "manager admin,
# not super admin" boundary as the /admin/rooms block above: facility is
# NEVER taken from client input, every read/write is forced to
# current_user.facility, and lookups use the non-leaking scoped-404.
def _serialize_section(db: Session, section: models.FacilitySection) -> dict:
    assigned = (
        db.query(func.count(models.User.id))
        .filter(
            models.User.facility == section.facility_name,
            models.User.section == section.name,
        )
        .scalar()
    ) or 0
    return {
        "id": section.id,
        "facility_name": section.facility_name,
        "name": section.name,
        "active": section.active,
        "updated_by": section.updated_by,
        "updated_at": section.updated_at,
        "created_at": section.created_at,
        "assigned_staff_count": assigned,
    }


def _get_section_or_404(db: Session, section_id: str, facility: str) -> models.FacilitySection:
    section = (
        db.query(models.FacilitySection)
        .filter(
            models.FacilitySection.id == section_id,
            models.FacilitySection.facility_name == facility,
        )
        .first()
    )
    if not section:
        raise HTTPException(status_code=404, detail="Facility section not found")
    return section


@router.get("/sections", response_model=List[schemas.FacilitySectionOut])
def list_sections(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Every section (active AND inactive) for the admin's own facility,
    ordered by name. An admin with no facility assigned gets [] (module
    docstring's edge-case rule)."""
    if not current_user.facility:
        return []
    sections = (
        db.query(models.FacilitySection)
        .filter(models.FacilitySection.facility_name == current_user.facility)
        .order_by(models.FacilitySection.name.asc())
        .all()
    )
    return [_serialize_section(db, s) for s in sections]


@router.post("/sections", response_model=schemas.FacilitySectionOut)
def create_section(
    payload: schemas.FacilitySectionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _require_facility(current_user)
    existing = (
        db.query(models.FacilitySection)
        .filter(
            models.FacilitySection.facility_name == facility,
            models.FacilitySection.name == payload.name,
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A section with that name already exists at this facility.")

    section = models.FacilitySection(
        facility_name=facility, name=payload.name,
        created_by=current_user.id, updated_by=current_user.id,
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    log_access(
        db, None, current_user.id, current_user.role, "create_section",
        detail=section.name, actor_facility=current_user.facility,
    )
    return _serialize_section(db, section)


@router.patch("/sections/{section_id}", response_model=schemas.FacilitySectionOut)
def update_section(
    section_id: str,
    payload: schemas.FacilitySectionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Rename and/or (de)activate a section. On a RENAME, staff currently
    pinned to the old name are moved to the new name in the same
    transaction -- `User.section` is a denormalised string, so a rename that
    didn't fix it up would silently orphan every assigned receptionist.
    Historical QueueTicket.department strings are point-in-time and are
    deliberately left untouched."""
    facility = _require_facility(current_user)
    section = _get_section_or_404(db, section_id, facility)

    submitted_fields = payload.model_dump(exclude_unset=True)
    new_name = submitted_fields.get("name")
    if new_name is not None and new_name != section.name:
        clash = (
            db.query(models.FacilitySection)
            .filter(
                models.FacilitySection.facility_name == facility,
                models.FacilitySection.name == new_name,
                models.FacilitySection.id != section.id,
            )
            .first()
        )
        if clash:
            raise HTTPException(status_code=409, detail="A section with that name already exists at this facility.")
        old_name = section.name
        db.query(models.User).filter(
            models.User.facility == facility,
            models.User.section == old_name,
        ).update({models.User.section: new_name}, synchronize_session=False)

    for field, value in submitted_fields.items():
        setattr(section, field, value)
    if submitted_fields:
        section.updated_by = current_user.id
        db.add(section)
        db.commit()
        db.refresh(section)

    log_access(
        db, None, current_user.id, current_user.role, "update_section",
        fields=sorted(submitted_fields.keys()), detail=section.name,
        actor_facility=current_user.facility,
    )
    return _serialize_section(db, section)


@router.delete("/sections/{section_id}")
def delete_section(
    section_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Hard delete. Any receptionist/clinician pinned to this section is
    un-scoped first (`User.section` -> NULL) so nobody is left pointing at a
    section that no longer exists -- same "release dependents first" idea as
    delete_room releasing RoomClaims. Historical QueueTickets keep their
    point-in-time `department` string."""
    facility = _require_facility(current_user)
    section = _get_section_or_404(db, section_id, facility)
    section_name = section.name

    released = db.query(models.User).filter(
        models.User.facility == facility,
        models.User.section == section_name,
    ).update({models.User.section: None}, synchronize_session=False)

    db.delete(section)
    db.commit()

    log_access(
        db, None, current_user.id, current_user.role, "delete_section",
        detail=f"{section_name} unassigned_staff={released}",
        actor_facility=current_user.facility,
    )
    return {"detail": "Facility section deleted"}


# ---------- Staff roster (read-only) ----------
# Deliberately READ-ONLY: no admin-initiated clock actions and no account
# editing/deactivation here -- staff clock themselves in/out via
# routers/staff.py only. This section exists purely to give an admin
# visibility into "who's currently on shift at my facility", not control
# over it (see routers/staff.py's module docstring for the full split).
def _get_roster_user_or_404(db: Session, user_id: str, facility: str) -> models.User:
    # Same non-leaking scoped-404 pattern as _get_inventory_item_or_404 /
    # _get_ward_or_404 above: "doesn't exist", "isn't a roster staff role
    # (clinician / records_officer / receptionist)", and "belongs to a
    # different facility" are all the SAME generic 404, so an admin can
    # never distinguish which condition failed.
    user = (
        db.query(models.User)
        .filter(
            models.User.id == user_id,
            models.User.role.in_(["clinician", "records_officer", "receptionist"]),
            models.User.facility == facility,
        )
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="Staff member not found")
    return user


@router.get("/staff", response_model=List[schemas.StaffRosterEntryOut])
def list_staff_roster(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    if not current_user.facility:
        # No crash, no "sees everything" -- see module docstring's edge-case
        # rule.
        return []

    staff = (
        db.query(models.User)
        .filter(
            models.User.role.in_(["clinician", "records_officer", "receptionist"]),
            models.User.facility == current_user.facility,
        )
        .order_by(models.User.full_name.asc())
        .all()
    )

    clock = batch_clock_status(db, [u.id for u in staff])
    results = []
    for u in staff:
        # staff.py's shared status-derivation logic, batched for the roster
        # (2 queries total instead of 2 per row).
        status = clock[u.id]
        results.append(
            schemas.StaffRosterEntryOut(
                id=u.id,
                full_name=u.full_name,
                email=u.email,
                role=u.role,
                facility=u.facility,
                section=u.section,
                must_change_password=u.must_change_password,
                clocked_in=status.clocked_in,
                since=status.since,
                last_clock_out_at=status.last_clock_out_at,
            )
        )
    return results


@router.patch("/staff/{user_id}", response_model=schemas.StaffRosterEntryOut)
def assign_staff_section(
    user_id: str,
    payload: schemas.StaffSectionAssign,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Pin a receptionist/clinician at the admin's own facility to a
    FacilitySection (per-counter reception scoping -- see
    models.User.section + routers/reception.py), or send `section: null` to
    un-scope them.

    Same non-leaking scoped-404 as the rest of this router for "wrong
    facility / not a roster role". Only `receptionist` and `clinician`
    accounts can carry a section (a records_officer never works the front
    desk queue) -- a 400, not a 404, since the caller legitimately found the
    user in their roster. The target section must be an ACTIVE
    FacilitySection at this facility."""
    facility = _require_facility(current_user)
    user = _get_roster_user_or_404(db, user_id, facility)

    if user.role not in ("receptionist", "clinician"):
        raise HTTPException(
            status_code=400,
            detail="Only receptionists and clinicians can be assigned a section.",
        )

    section_name = payload.section
    if section_name is not None:
        section = (
            db.query(models.FacilitySection)
            .filter(
                models.FacilitySection.facility_name == facility,
                models.FacilitySection.name == section_name,
                models.FacilitySection.active.is_(True),
            )
            .first()
        )
        if not section:
            raise HTTPException(
                status_code=400,
                detail="That section does not exist (or is inactive) at this facility.",
            )

    user.section = section_name
    db.add(user)
    db.commit()
    db.refresh(user)

    log_access(
        db, None, current_user.id, current_user.role, "assign_staff_section",
        detail=f"user={user.email} section={section_name or ''}",
        actor_facility=current_user.facility,
    )

    status = _get_clock_status(db, user.id)
    return schemas.StaffRosterEntryOut(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        facility=user.facility,
        section=user.section,
        must_change_password=user.must_change_password,
        clocked_in=status.clocked_in,
        since=status.since,
        last_clock_out_at=status.last_clock_out_at,
    )


@router.get("/staff/{user_id}/clock-history", response_model=List[schemas.ClockEventOut])
def get_staff_clock_history(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    facility = _require_facility(current_user)
    _get_roster_user_or_404(db, user_id, facility)

    events = (
        db.query(models.StaffClockEvent)
        .filter(models.StaffClockEvent.user_id == user_id)
        .order_by(models.StaffClockEvent.clock_in_at.desc())
        .limit(30)
        .all()
    )

    results = []
    for e in events:
        duration_minutes = None
        if e.clock_out_at is not None:
            duration_minutes = int((e.clock_out_at - e.clock_in_at).total_seconds() // 60)
        results.append(
            schemas.ClockEventOut(
                id=e.id,
                clock_in_at=e.clock_in_at,
                clock_out_at=e.clock_out_at,
                duration_minutes=duration_minutes,
            )
        )
    return results


# ---------- Waiting-room displays (public unauthenticated feed tokens) ----------
# An admin mints one long-lived token per waiting-area screen (see
# models.WaitingRoomDisplay + routers/display.py). Same forced-facility /
# non-leaking scoped-404 boundary as every other endpoint in this router;
# unlike the reception self-check-in station, MULTIPLE active rows per
# facility are allowed on purpose (one screen per waiting area).
def _get_waiting_room_display_or_404(db: Session, display_id: str, facility: str) -> models.WaitingRoomDisplay:
    row = (
        db.query(models.WaitingRoomDisplay)
        .filter(
            models.WaitingRoomDisplay.id == display_id,
            models.WaitingRoomDisplay.facility_name == facility,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Waiting-room display not found")
    return row


@router.get("/waiting-room-displays", response_model=List[schemas.WaitingRoomDisplayOut])
def list_waiting_room_displays(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Every waiting-room display token for this admin's own facility,
    including revoked ones (so the console can show history), newest first."""
    if not current_user.facility:
        return []
    return (
        db.query(models.WaitingRoomDisplay)
        .filter(models.WaitingRoomDisplay.facility_name == current_user.facility)
        .order_by(models.WaitingRoomDisplay.created_at.desc())
        .all()
    )


@router.post("/waiting-room-displays", response_model=schemas.WaitingRoomDisplayOut)
def create_waiting_room_display(
    payload: schemas.WaitingRoomDisplayCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Mint a new display token for this facility (optionally scoped to one
    section). The response includes `token` -- put it in the screen device's
    URL as /display/{token}."""
    facility = _require_facility(current_user)
    row = models.WaitingRoomDisplay(
        facility_name=facility,
        token=secrets.token_urlsafe(16),
        section=payload.section,
        show_full_names=payload.show_full_names,
        created_by=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    log_access(
        db, None, current_user.id, current_user.role, "create_waiting_room_display",
        detail=f"section={payload.section or ''} show_full_names={payload.show_full_names}",
        actor_facility=facility,
    )
    return row


@router.post("/waiting-room-displays/{display_id}/revoke", response_model=schemas.WaitingRoomDisplayOut)
def revoke_waiting_room_display(
    display_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Soft-retire a display token (GET /display/{token} 404s afterwards).
    Never deleted -- same soft-invalidate pattern as ReceptionStation.revoked."""
    facility = _require_facility(current_user)
    row = _get_waiting_room_display_or_404(db, display_id, facility)
    row.revoked = True
    db.add(row)
    db.commit()
    db.refresh(row)

    log_access(
        db, None, current_user.id, current_user.role, "revoke_waiting_room_display",
        detail=display_id, actor_facility=facility,
    )
    return row


# ---------- LDAP/AD role mapping (P1.10, the tender) ----------
# Deliberately NOT facility-scoped for READS, unlike every other endpoint in
# this router (see this file's module docstring on "manager admin, not
# super admin") -- which AD groups exist and what they map to is a
# platform-level identity-provider setting, so every admin, at any
# facility, sees the same global table.
#
# WRITES are a different story (voltagent security review finding H3): the
# `facility` value on a row is what a JIT-provisioned member of that group
# lands at, and letting it be an arbitrary client-supplied string would let
# any single-facility admin mint a mapping that provisions (or resyncs) a
# user at a DIFFERENT facility -- exactly the cross-tenant escalation
# `auth_router.register()` is already hardened against elsewhere in this
# codebase. `_check_mapping_authz` below enforces the same rule this
# router applies everywhere else: a `facility` value must be either absent
# (a facility-agnostic mapping) or equal to the ACTING admin's own
# `current_user.facility` -- never client-chosen independently of that.
#
# It ALSO blocks a facility-scoped admin from pointing ANY mapping at
# `role="admin"` (code-review follow-up 2026-09-07). A facility admin who
# could map an AD group to `admin` -- and, via a facility-omitted mapping,
# to a `facility=None` GLOBAL admin -- would be a facility-admin ->
# platform-admin privilege-escalation path. Only a platform/bootstrap admin
# (no facility of their own) may create an admin-granting mapping. This is a
# deliberate tightening of the earlier "an IT/Helpdesk AD group -> admin is
# a normal use" stance; the normal use is still available, it just has to be
# configured by a platform admin. Reverse by deleting the `role == "admin"`
# check if the University decides facility admins should self-provision admins.
def _check_mapping_authz(
    current_user: models.User, facility: Optional[str], role: str
) -> None:
    if facility is not None and facility != current_user.facility:
        raise HTTPException(
            status_code=403,
            detail=(
                "facility must be omitted or match your own facility "
                f"({current_user.facility or 'none assigned'}) -- an admin cannot "
                "assign an LDAP role mapping's facility to a hospital other than their own."
            ),
        )
    if role == "admin" and current_user.facility:
        raise HTTPException(
            status_code=403,
            detail=(
                "Only a platform admin (one with no facility assigned) may create an "
                "LDAP role mapping that grants the admin role."
            ),
        )


@router.get("/ldap-role-mappings", response_model=List[schemas.LdapRoleMappingOut])
def list_ldap_role_mappings(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    return (
        db.query(models.LdapRoleMapping)
        .order_by(models.LdapRoleMapping.priority.desc())
        .all()
    )


@router.post("/ldap-role-mappings", response_model=schemas.LdapRoleMappingOut, status_code=201)
def create_ldap_role_mapping(
    payload: schemas.LdapRoleMappingCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    _check_mapping_authz(current_user, payload.facility, payload.role)

    existing = (
        db.query(models.LdapRoleMapping)
        .filter(func.lower(models.LdapRoleMapping.group_dn) == payload.group_dn.lower())
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="A mapping for this group_dn already exists.")

    row = models.LdapRoleMapping(
        group_dn=payload.group_dn,
        role=payload.role,
        facility=payload.facility,
        priority=payload.priority,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Race: two concurrent creates for the same group_dn (case variants
        # included -- MariaDB's ci collation and the pre-check above can
        # disagree on SQLite's case-sensitive default collation).
        db.rollback()
        raise HTTPException(status_code=409, detail="A mapping for this group_dn already exists.")
    db.refresh(row)

    log_access(
        db, None, current_user.id, current_user.role, "create_ldap_role_mapping",
        detail=f"group_dn={payload.group_dn} role={payload.role}",
    )
    return row


def _get_ldap_role_mapping_or_404(db: Session, mapping_id: str) -> models.LdapRoleMapping:
    row = db.query(models.LdapRoleMapping).filter(models.LdapRoleMapping.id == mapping_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="LDAP role mapping not found.")
    return row


@router.put("/ldap-role-mappings/{mapping_id}", response_model=schemas.LdapRoleMappingOut)
def update_ldap_role_mapping(
    mapping_id: str,
    payload: schemas.LdapRoleMappingUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    _check_mapping_authz(current_user, payload.facility, payload.role)
    row = _get_ldap_role_mapping_or_404(db, mapping_id)

    duplicate = (
        db.query(models.LdapRoleMapping)
        .filter(
            func.lower(models.LdapRoleMapping.group_dn) == payload.group_dn.lower(),
            models.LdapRoleMapping.id != mapping_id,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="A mapping for this group_dn already exists.")

    row.group_dn = payload.group_dn
    row.role = payload.role
    row.facility = payload.facility
    row.priority = payload.priority
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A mapping for this group_dn already exists.")
    db.refresh(row)

    log_access(
        db, None, current_user.id, current_user.role, "update_ldap_role_mapping",
        detail=f"id={mapping_id} group_dn={payload.group_dn} role={payload.role}",
    )
    return row


@router.delete("/ldap-role-mappings/{mapping_id}")
def delete_ldap_role_mapping(
    mapping_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    row = _get_ldap_role_mapping_or_404(db, mapping_id)
    group_dn = row.group_dn
    db.delete(row)
    db.commit()

    log_access(
        db, None, current_user.id, current_user.role, "delete_ldap_role_mapping",
        detail=f"id={mapping_id} group_dn={group_dn}",
    )
    return {"detail": "LDAP role mapping deleted"}


# --------------------------------------------------------------------------
# Audit hash-chain integrity (P2.9)
# --------------------------------------------------------------------------

@router.get("/audit/chain-status")
def get_audit_chain_status(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Walk the whole `audit_logs` hash chain and report whether it is
    intact. Deliberately platform-global, not facility-scoped: chain
    integrity is a system-health signal, and the response carries only
    counts + hash digests -- no patient data, no per-facility records. The
    full recompute is O(rows) but read-only; run it from an integrity
    dashboard / a nightly check, not on a hot path.

    `db/verify_audit_chain.py` is the same check as a CLI (for cron / CI).
    """
    from ..audit import verify_chain

    report = verify_chain(db)
    log_access(
        db, None, current_user.id, current_user.role, "verify_audit_chain",
        detail=f"ok={report.ok} rows={report.total_rows} last_seq={report.last_seq}",
        actor_facility=current_user.facility,
    )
    return report.as_dict()


# --------------------------------------------------------------------------
# Data-quality alerts (P2.12, the tender)
# --------------------------------------------------------------------------
# Facility-scoped like the rest of this router: an admin sees alerts for
# patients their facility has a relationship to (the P2.2
# `_facility_known_patient_ids_select` scope), plus the inherently
# cross-facility `patient_probable_duplicate` alerts (those exist precisely
# to be reviewed for a merge), plus non-patient alerts. A platform admin
# (`facility is None`) or an explicit `break_glass_reason` sees everything,
# audit-logged -- same escape hatch, and same wording, as `list_patients`.
# Every read is `log_access`-ed. `detail` never carries a clinical value.

_DQ_STATUS = {"open", "acknowledged", "resolved", "all"}
_DQ_CROSS_FACILITY_RULES = ("patient_probable_duplicate",)


def _dq_facility_filter(current_user: models.User):
    """The WHERE clause that scopes DataQualityAlert to `current_user`'s
    facility, or None if the caller may see everything (platform admin)."""
    from .patients import _facility_known_patient_ids_select

    if not current_user.facility:
        return None
    known = _facility_known_patient_ids_select(current_user.facility)
    return or_(
        models.DataQualityAlert.patient_id.is_(None),
        models.DataQualityAlert.patient_id.in_(select(known.c.patient_id)),
        models.DataQualityAlert.rule.in_(_DQ_CROSS_FACILITY_RULES),
    )


@router.get("/data-quality", response_model=List[schemas.DataQualityAlertOut])
def list_data_quality_alerts(
    db: Session = Depends(get_db),
    status: str = Query("open", description="open | acknowledged | resolved | all"),
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    patient_id: Optional[str] = Query(None),
    break_glass_reason: Optional[str] = Query(
        None, description="see EVERY facility's alerts, not just your own -- "
                          "audited (action=list_data_quality_break_glass)"),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    if status not in _DQ_STATUS:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(_DQ_STATUS)}")

    q = db.query(models.DataQualityAlert)
    if status == "open":
        q = q.filter(models.DataQualityAlert.resolved.is_(False),
                     models.DataQualityAlert.acknowledged.is_(False))
    elif status == "acknowledged":
        q = q.filter(models.DataQualityAlert.acknowledged.is_(True),
                     models.DataQualityAlert.resolved.is_(False))
    elif status == "resolved":
        q = q.filter(models.DataQualityAlert.resolved.is_(True))
    if category:
        q = q.filter(models.DataQualityAlert.category == category)
    if severity:
        q = q.filter(models.DataQualityAlert.severity == severity)
    if patient_id:
        q = q.filter(models.DataQualityAlert.patient_id == patient_id)

    broke_glass = bool(break_glass_reason and break_glass_reason.strip())
    scope = _dq_facility_filter(current_user)
    if broke_glass or scope is None:
        log_access(db, None, current_user.id, current_user.role,
                   "list_data_quality_break_glass" if broke_glass else "list_data_quality",
                   detail=(break_glass_reason or "").strip()[:200] or None,
                   actor_facility=current_user.facility)
    else:
        q = q.filter(scope)
        log_access(db, None, current_user.id, current_user.role, "list_data_quality",
                   actor_facility=current_user.facility)

    # Resolved rows sort by when they were resolved (a manually-resolved
    # alert whose finding keeps recurring still gets its last_seen_at bumped
    # by every scan -- ordering that view by last_seen_at would float dead
    # rows to the top forever). Everything else sorts by recency of the issue.
    order_col = (models.DataQualityAlert.resolved_at if status == "resolved"
                 else models.DataQualityAlert.last_seen_at)
    return (
        q.order_by(order_col.desc(), models.DataQualityAlert.id.desc())
        .offset(skip).limit(limit).all()
    )


@router.get("/data-quality/summary")
def data_quality_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    open_unack = and_(
        models.DataQualityAlert.resolved.is_(False),
        models.DataQualityAlert.acknowledged.is_(False),
    )
    scope = _dq_facility_filter(current_user)
    base = db.query(models.DataQualityAlert)
    if scope is not None:
        base = base.filter(scope)

    rows = (
        base.with_entities(
            models.DataQualityAlert.category,
            models.DataQualityAlert.severity,
            func.count(models.DataQualityAlert.id),
        )
        .filter(open_unack)
        .group_by(models.DataQualityAlert.category, models.DataQualityAlert.severity)
        .all()
    )
    by_category: dict = {}
    by_severity: dict = {}
    open_total = 0
    for category, severity, n in rows:
        by_category[category] = by_category.get(category, 0) + n
        by_severity[severity] = by_severity.get(severity, 0) + n
        open_total += n
    acknowledged = (
        base.with_entities(func.count(models.DataQualityAlert.id))
        .filter(models.DataQualityAlert.resolved.is_(False),
                models.DataQualityAlert.acknowledged.is_(True))
        .scalar()
    )
    log_access(db, None, current_user.id, current_user.role, "data_quality_summary",
               actor_facility=current_user.facility)
    return {
        "open_total": open_total,
        "acknowledged": acknowledged or 0,
        "by_category": by_category,
        "by_severity": by_severity,
    }


@router.post("/data-quality/scan")
def run_data_quality_scan(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Trigger a scan on demand (the cron job `db/data_quality_scan.py` is the
    routine path). The scan is platform-wide regardless of the acting admin's
    facility -- it re-derives every alert. `run_scan` catches the
    concurrent-run IntegrityError, so this racing the cron is safe."""
    from ..data_quality import run_scan

    result = run_scan(db)
    log_access(
        db, None, current_user.id, current_user.role, "run_data_quality_scan",
        detail=f"findings={result.findings} new={result.new_alerts} "
               f"resolved={result.auto_resolved} open={result.still_open} "
               f"failed={len(result.rules_failed)}",
        actor_facility=current_user.facility,
    )
    return result.as_dict()


def _get_dq_alert_or_404(db: Session, alert_id: str) -> models.DataQualityAlert:
    row = db.query(models.DataQualityAlert).filter(models.DataQualityAlert.id == alert_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Data-quality alert not found")
    return row


@router.post("/data-quality/{alert_id}/acknowledge", response_model=schemas.DataQualityAlertOut)
def acknowledge_data_quality_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Mark a known/accepted issue as acknowledged -- it stays listed but
    drops out of the 'open' count. A future scan that still sees the finding
    leaves the acknowledgement in place."""
    row = _get_dq_alert_or_404(db, alert_id)
    row.acknowledged = True
    row.acknowledged_by = current_user.id
    row.acknowledged_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(db, row.patient_id, current_user.id, current_user.role,
               "acknowledge_data_quality_alert", detail=f"id={alert_id} rule={row.rule}",
               actor_facility=current_user.facility)
    return row


@router.post("/data-quality/{alert_id}/resolve", response_model=schemas.DataQualityAlertOut)
def resolve_data_quality_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Manually resolve an alert (the underlying data was fixed, or it's a
    false positive). A manual resolve is NOT reopened by a later scan the way
    a system auto-resolve is -- `resolved_by` is the acting admin, not
    'system'."""
    row = _get_dq_alert_or_404(db, alert_id)
    row.resolved = True
    row.resolved_by = current_user.id
    row.resolved_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(db, row.patient_id, current_user.id, current_user.role,
               "resolve_data_quality_alert", detail=f"id={alert_id} rule={row.rule}",
               actor_facility=current_user.facility)
    return row


# --------------------------------------------------------------------------
# PDPA -- DPO register + retention schedule + retention review (P2.10)
# --------------------------------------------------------------------------

@router.get("/dpo-register", response_model=schemas.DpoRegisterOut)
def get_dpo_register(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """The DPO contact registered with the Commissioner (JPDP) for this
    admin's facility. Lazily created (same create-on-read pattern as
    hospital-settings). PDPA 2024 makes a DPO mandatory for the University."""
    if not current_user.facility:
        raise HTTPException(status_code=400, detail="This admin has no assigned facility")
    row = (
        db.query(models.DpoRegister)
        .filter(models.DpoRegister.facility_name == current_user.facility)
        .first()
    )
    if row is None:
        row = models.DpoRegister(facility_name=current_user.facility)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


@router.put("/dpo-register", response_model=schemas.DpoRegisterOut)
def update_dpo_register(
    payload: schemas.DpoRegisterIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    if not current_user.facility:
        raise HTTPException(status_code=400, detail="This admin has no assigned facility")
    row = (
        db.query(models.DpoRegister)
        .filter(models.DpoRegister.facility_name == current_user.facility)
        .first()
    ) or models.DpoRegister(facility_name=current_user.facility)
    for f in ("dpo_name", "dpo_email", "dpo_phone", "jpdp_registration_ref"):
        setattr(row, f, getattr(payload, f))
    row.updated_by = current_user.id
    row.updated_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(db, None, current_user.id, current_user.role, "update_dpo_register",
               actor_facility=current_user.facility)
    return row


def _require_platform_admin(current_user: models.User) -> None:
    """The retention schedule + scan + disposition act platform-wide (the
    scan walks every facility's records; a bad `retain_years` could put the
    whole system's history in the disposal queue). Same rule as
    `_check_mapping_authz` for admin-granting LDAP mappings: only an admin
    with no facility assigned."""
    if current_user.facility:
        raise HTTPException(
            status_code=403,
            detail="Only a platform admin (no facility assigned) may change the "
                   "retention schedule or run / act on the retention review.")


@router.get("/retention-policies", response_model=List[schemas.RetentionPolicyOut])
def list_retention_policies(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """The retention schedule (one row per record category). Platform-global:
    it's a legal/config table, not facility data. Seeded from the Malaysian
    defaults by seed.py; lazily topped-up here if a default is missing."""
    from ..retention import DEFAULT_RETENTION_POLICIES

    have = {p.category for p in db.query(models.RetentionPolicy).all()}
    added = False
    for cat, years, basis in DEFAULT_RETENTION_POLICIES:
        if cat not in have:
            db.add(models.RetentionPolicy(category=cat, retain_years=years, basis=basis))
            added = True
    if added:
        db.commit()
    return db.query(models.RetentionPolicy).order_by(models.RetentionPolicy.category).all()


@router.put("/retention-policies/{category}", response_model=schemas.RetentionPolicyOut)
def update_retention_policy(
    category: str,
    payload: schemas.RetentionPolicyIn,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    row = (
        db.query(models.RetentionPolicy)
        .filter(models.RetentionPolicy.category == category)
        .first()
    ) or models.RetentionPolicy(category=category)
    _require_platform_admin(current_user)
    row.retain_years = payload.retain_years
    if payload.basis is not None:
        row.basis = payload.basis
    row.updated_by = current_user.id
    row.updated_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(db, None, current_user.id, current_user.role, "update_retention_policy",
               detail=f"category={category} retain_years={payload.retain_years}",
               actor_facility=current_user.facility)
    return row


@router.post("/retention/scan")
def run_retention_scan_now(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Trigger the retention scan (the cron `db/retention_scan.py` is the
    routine path). FLAGS records past their window -- never deletes."""
    _require_platform_admin(current_user)
    from ..retention import run_retention_scan

    res = run_retention_scan(db)
    log_access(db, None, current_user.id, current_user.role, "run_retention_scan",
               detail=f"scanned={res.scanned} new={res.flagged_new} open={res.flagged_total}",
               actor_facility=current_user.facility)
    return res.as_dict()


@router.get("/retention/review")
def list_retention_review(
    db: Session = Depends(get_db),
    include_disposed: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    _require_platform_admin(current_user)
    q = db.query(models.RetentionReviewItem)
    if not include_disposed:
        q = q.filter(models.RetentionReviewItem.disposed.is_(False))
    rows = (
        q.order_by(models.RetentionReviewItem.retain_until.asc())
        .offset(skip).limit(limit).all()
    )
    return [
        {
            "id": r.id, "entity_type": r.entity_type, "entity_id": r.entity_id,
            "patient_id": r.patient_id, "category": r.category,
            "last_activity_at": str(r.last_activity_at) if r.last_activity_at else None,
            "retain_until": str(r.retain_until) if r.retain_until else None,
            "first_flagged_at": str(r.first_flagged_at),
            "disposed": r.disposed,
        }
        for r in rows
    ]


@router.post("/retention/review/{item_id}/disposition")
def disposition_retention_item(
    item_id: str,
    note: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin")),
):
    """Mark a flagged record as dispositioned (archived / partition-dropped
    by the DBA). The scan then leaves it alone. This does NOT delete the
    record -- that is a MariaDB DDL job outside the app."""
    _require_platform_admin(current_user)
    row = db.query(models.RetentionReviewItem).filter(models.RetentionReviewItem.id == item_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Retention review item not found")
    row.disposed = True
    row.disposed_by = current_user.id
    row.disposed_at = datetime.now(timezone.utc)
    row.disposition_note = note.strip()
    db.add(row)
    db.commit()
    log_access(db, row.patient_id, current_user.id, current_user.role,
               "disposition_retention_item",
               detail=f"id={item_id} {row.entity_type}:{row.entity_id}",
               actor_facility=current_user.facility)
    return {"detail": "dispositioned"}
