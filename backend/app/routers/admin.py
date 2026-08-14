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
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from ..appointments import compute_reminder_offsets
from .staff import _get_clock_status

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


def _serialize_inventory_item(item: models.MedicineInventoryItem) -> dict:
    return {
        "id": item.id,
        "facility_name": item.facility_name,
        "drug_name": item.drug_name,
        "quantity_on_hand": item.quantity_on_hand,
        "unit": item.unit,
        "reorder_threshold": item.reorder_threshold,
        "notes": item.notes,
        "last_restocked_at": item.last_restocked_at,
        "updated_by": item.updated_by,
        "updated_at": item.updated_at,
        "created_at": item.created_at,
        "is_low_stock": item.reorder_threshold is not None and item.quantity_on_hand <= item.reorder_threshold,
    }


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

    creator_ids = {a.created_by for a in appointments}
    creator_names = {}
    if creator_ids:
        for uid, full_name in (
            db.query(models.User.id, models.User.full_name)
            .filter(models.User.id.in_(creator_ids))
            .all()
        ):
            creator_names[uid] = full_name

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
            "reminders": compute_reminder_offsets(a),
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
    items = query.order_by(models.MedicineInventoryItem.drug_name.asc()).all()
    return [_serialize_inventory_item(i) for i in items]


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
    return _serialize_inventory_item(item)


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
    return _serialize_inventory_item(item)


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


# ---------- Staff roster (read-only) ----------
# Deliberately READ-ONLY: no admin-initiated clock actions and no account
# editing/deactivation here -- staff clock themselves in/out via
# routers/staff.py only. This section exists purely to give an admin
# visibility into "who's currently on shift at my facility", not control
# over it (see routers/staff.py's module docstring for the full split).
def _get_roster_user_or_404(db: Session, user_id: str, facility: str) -> models.User:
    # Same non-leaking scoped-404 pattern as _get_inventory_item_or_404 /
    # _get_ward_or_404 above: "doesn't exist", "isn't clinician/records_officer",
    # and "belongs to a different facility" are all the SAME generic 404, so
    # an admin can never distinguish which condition failed.
    user = (
        db.query(models.User)
        .filter(
            models.User.id == user_id,
            models.User.role.in_(["clinician", "records_officer"]),
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
            models.User.role.in_(["clinician", "records_officer"]),
            models.User.facility == current_user.facility,
        )
        .order_by(models.User.full_name.asc())
        .all()
    )

    results = []
    for u in staff:
        # Reuse staff.py's shared status-derivation logic rather than
        # re-querying StaffClockEvent inline here -- see this router's
        # import of _get_clock_status and staff.py's module docstring for
        # why.
        status = _get_clock_status(db, u.id)
        results.append(
            schemas.StaffRosterEntryOut(
                id=u.id,
                full_name=u.full_name,
                email=u.email,
                role=u.role,
                facility=u.facility,
                must_change_password=u.must_change_password,
                clocked_in=status.clocked_in,
                since=status.since,
                last_clock_out_at=status.last_clock_out_at,
            )
        )
    return results


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
