"""
Billing (P3.3, the tender + per-module billing).

`bills` / `bill_items` / `payments` / `claims` plus a `charge_master_items`
catalog -- see models.py's "Billing engine" section comment for the full
column-level rationale and Design decisions 1-8 in the P3.3 plan for why
this module is shaped the way it is. The two decisions that most affect
this file:

  - Billing is FACILITY-LOCAL ONLY (Design decision 1) -- unlike
    ancillary.py/dental.py there is no cross-facility read mode, no
    records_shared_publicly opt-out, and therefore none of the
    pagination-before-filter bug class that bit Ancillary twice. Every
    bill/payment/claim lookup is gated by ONE helper, `_bill_or_404`.
  - Every BillItem price is server-derived, never client-supplied (Design
    decision 2) -- `_resolve_bill_item_source` is the one place that reads
    a price off a ChargeMasterItem / signed-off ServiceRequest /
    MedicineInventoryItem and snapshots it onto the new row.

RBAC: BILLING_WRITE_ROLES (admin/records_officer/receptionist) can create
bills, add/void items, finalize/void bills, and record/void payments --
matches the tender ("frontdesk billing"). BILLING_READ_ROLES adds
clinician/pharmacist ("physician views... fees",
pharmacy billing visibility) for read-only access. CLAIM_ROLES
(admin/records_officer only) is narrower still -- insurance/panel claim
administration.
"""
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload, selectinload

from .. import models, schemas, auth, payment_providers
from ..database import get_db
from ..audit import log_access
from .. import charge_master_import as cm_import
from ._uploads import enforce_upload_size

router = APIRouter(prefix="/billing", tags=["billing"])

BILLING_WRITE_ROLES = ("admin", "records_officer", "receptionist")
BILLING_READ_ROLES = BILLING_WRITE_ROLES + ("clinician", "pharmacist")
CLAIM_ROLES = ("admin", "records_officer")


# ---------------------------------------------------------------------------
# Shared lookups
# ---------------------------------------------------------------------------
def _load_bill_with_relations(db: Session, bill_id: str) -> Optional[models.Bill]:
    """The one place that fetches a Bill with patient/items/payments/claims
    eagerly loaded, used for the initial lookup and to re-load after every
    write (never `db.commit(); db.refresh(bill)` then serialize -- same
    N+1 trap ancillary.py's module docstring already documents fixing).
    `selectinload` for the three one-to-many collections, not `joinedload`
    -- joinedload-ing multiple collections on one query multiplies rows
    (items x payments x claims), which `joinedload` alone would on a bill
    that has more than one of each; `patient` is many-to-one so joinedload
    is correct there."""
    return (
        db.query(models.Bill)
        .options(
            joinedload(models.Bill.patient),
            selectinload(models.Bill.items),
            selectinload(models.Bill.payments),
            selectinload(models.Bill.claims),
            selectinload(models.Bill.refunds),
        )
        .filter(models.Bill.id == bill_id)
        .first()
    )


def cancel_open_intents(db: Session, bill_id: str) -> None:
    """A counter payment or deposit changes what is due, so any online attempt opened
    for the old amount is closed (the patient starts a fresh one). Caller commits.
    A gateway success that still arrives later is booked anyway (see settle_intent)."""
    pending = db.query(models.PaymentIntent).filter(
        models.PaymentIntent.bill_id == bill_id, models.PaymentIntent.status == "pending").all()
    for i in pending:
        i.status, i.completed_at = "cancelled", datetime.now(timezone.utc)
        payment_providers.expire_open_session(i)  # the gateway page must stop taking money too


def _bill_or_404(db: Session, bill_id: str, current_user: models.User) -> models.Bill:
    """Billing is facility-local ONLY (Design decision 1) -- unlike
    ancillary/dental there is no cross-facility read mode at all, so this
    is the single 404-not-403 gate for every billing endpoint, read or
    write. `not owner or owner != caller` idiom matches
    clinical_access.py::_record_editable / ancillary.py::_request_or_404 -- a
    facility-less caller is denied rather than risking a `None != None`
    false pass (Bill.facility_name is NOT NULL in practice, but the guard
    is written the same defensive way regardless)."""
    bill = _load_bill_with_relations(db, bill_id)
    if bill is None:
        raise HTTPException(status_code=404, detail="Bill not found")
    if not bill.facility_name or bill.facility_name != current_user.facility:
        raise HTTPException(status_code=404, detail="Bill not found")
    return bill


def _serialize_bill(bill: models.Bill) -> schemas.BillOut:
    """Computes the five money fields from Design decision 6 -- see
    models.py's Bill docstring for why these are derived here, never
    stored. `claimed_pending_cents` sums every claim in submitted/approved
    (money expected but not yet received); `patient_due_cents` is what
    front-desk should actually collect right now, excluding that pending
    amount (the copay/split model)."""
    out = schemas.BillOut.model_validate(bill)
    out.patient_full_name = bill.patient.full_name if bill.patient else None

    total_cents = sum(i.amount_cents for i in bill.items if not i.voided_at)
    refunded_cents = sum(r.amount_cents for r in bill.refunds if r.status == "approved")
    paid_cents = sum(p.amount_cents for p in bill.payments if not p.voided_at) - refunded_cents
    claimed_pending_cents = sum(c.claim_amount_cents for c in bill.claims if c.status in ("submitted", "approved"))
    amount_due_cents = max(0, total_cents - paid_cents)
    patient_due_cents = max(0, amount_due_cents - claimed_pending_cents)

    out.total_cents = total_cents
    out.paid_cents = paid_cents
    out.refunded_cents = refunded_cents
    out.claimed_pending_cents = claimed_pending_cents
    out.amount_due_cents = amount_due_cents
    out.patient_due_cents = patient_due_cents
    return out


def _claim_or_404(db: Session, claim_id: str, current_user: models.User) -> Tuple[models.Claim, models.Bill]:
    claim = db.query(models.Claim).filter(models.Claim.id == claim_id).first()
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    bill = _bill_or_404(db, claim.bill_id, current_user)  # the real facility 404 gate
    return claim, bill


def _check_claim_amount_cap(bill: models.Bill, claim_amount_cents: int) -> None:
    """Shared by create_claim and update_claim -- quality-review finding:
    this rule was duplicated at both call sites, which is exactly how the
    original bug (capping against raw `amount_due_cents` instead of
    `patient_due_cents`) could get fixed in one place and silently missed
    in the other. Caps against `patient_due_cents` (amount_due_cents net of
    every OTHER submitted/approved claim's claimed_pending_cents), not raw
    amount_due_cents -- capping against the latter alone let two
    full-amount claims be created against the same bill (e.g. one $50 bill
    claimed in full to both AIA and Prudential simultaneously). A draft
    claim being edited isn't itself counted in claimed_pending_cents (only
    submitted/approved are), so its own OLD amount never needs to be added
    back before comparing here -- only other claims' amounts matter."""
    unclaimed_cents = _serialize_bill(bill).patient_due_cents
    if claim_amount_cents > unclaimed_cents:
        raise HTTPException(
            status_code=400,
            detail=f"claim_amount_cents cannot exceed the bill's current unclaimed balance ({unclaimed_cents})",
        )


def _resolve_bill_item_source(
    db: Session, payload: schemas.BillItemCreate, current_user: models.User, bill: models.Bill
) -> Tuple[str, int]:
    """Server-derives (description, unit_price_cents) from EXACTLY the one
    source `payload.source_type` names -- Design decision 2: no
    client-supplied price anywhere on BillItemCreate. Every branch 404s on
    a source outside the caller's own facility (same 404-not-403 leak
    avoidance as the rest of the app), never a 403 that would confirm the
    id exists elsewhere."""
    if payload.source_type == "charge_master":
        item = (
            db.query(models.ChargeMasterItem)
            .filter(models.ChargeMasterItem.id == payload.charge_master_item_id)
            .first()
        )
        if item is None:
            raise HTTPException(status_code=404, detail="Charge master item not found")
        if item.facility_name is not None and item.facility_name != current_user.facility:
            raise HTTPException(status_code=404, detail="Charge master item not found")
        if not item.active:
            raise HTTPException(status_code=400, detail="This charge master item is no longer active")
        return item.name, item.unit_price_cents

    if payload.source_type == "service_request":
        req = (
            db.query(models.ServiceRequest)
            .filter(models.ServiceRequest.id == payload.service_request_id)
            .first()
        )
        if req is None:
            raise HTTPException(status_code=404, detail="Service request not found")
        if req.patient_id != bill.patient_id:
            raise HTTPException(status_code=400, detail="service_request_id does not belong to this bill's patient")
        # Same facility-ownership requirement as ancillary.py's write-path
        # guard -- stricter than the encounter-linkage check below, because
        # here real money is being billed for another facility's clinical
        # work, not just a provenance link (Design decision 8 draws this
        # exact line).
        if not req.ordering_facility_name or req.ordering_facility_name != current_user.facility:
            raise HTTPException(status_code=404, detail="Service request not found")
        if req.status != "signed_off":
            raise HTTPException(status_code=400, detail="Only a signed-off service request can be billed")
        # Soft duplicate-billing guard, not a DB unique constraint -- same
        # "partial-unique dropped to a Python guard" call as
        # models.RoomClaim (a genuine but narrow race window between two
        # staff billing the same request at once is an acceptable risk
        # here: worst case is two line items for one service, easily
        # spotted and voided, not a security issue).
        already_billed = (
            db.query(models.BillItem)
            .filter(models.BillItem.service_request_id == req.id, models.BillItem.voided_at.is_(None))
            .first()
        )
        if already_billed is not None:
            raise HTTPException(status_code=409, detail="This service request is already on a bill")
        return (req.catalog_item.name if req.catalog_item else req.module), req.unit_price_cents

    # source_type == "pharmacy_item" (schemas.BillItemCreate's validator
    # guarantees it's one of these three by this point)
    item = (
        db.query(models.MedicineInventoryItem)
        .filter(models.MedicineInventoryItem.id == payload.medicine_inventory_item_id)
        .first()
    )
    if item is None or item.facility_name != current_user.facility:
        raise HTTPException(status_code=404, detail="Inventory item not found")
    if item.unit_cost is None:
        raise HTTPException(status_code=400, detail="This inventory item has no price set")
    # Procurement-cost passthrough -- there is no separate patient-facing
    # sale price on MedicineInventoryItem yet (pharmacy has no markup
    # field). A PATCH-able sale price is a natural follow-up, out of scope
    # here (see the P3.3 plan's Design decision 2).
    #
    # Decimal(str(...)) before scaling, not a plain `round(unit_cost * 100)`
    # -- quality-review finding: `unit_cost` is a Float column, and binary
    # float multiplication (e.g. 12.50 * 100 in raw float arithmetic) plus
    # Python's round() can misconvert a specific decimal price by a cent.
    # Once written, BillItem.unit_price_cents is an immutable snapshot (no
    # PATCH) -- the only recovery from a bad conversion would be void-and-
    # recreate, so this is worth getting exactly right at write time.
    price_cents = int((Decimal(str(item.unit_cost)) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    return item.drug_name, price_cents


# ---------------------------------------------------------------------------
# Charge master ("Parameter Management" for consultation fees + generic
# front-desk/admin charges -- Ancillary/Pharmacy already have their own
# priced catalogs, see models.py's ChargeMasterItem docstring)
# ---------------------------------------------------------------------------
@router.get("/charge-master", response_model=List[schemas.ChargeMasterItemOut])
def list_charge_master(
    category: Optional[str] = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*BILLING_READ_ROLES)),
):
    if category is not None and category not in schemas.CHARGE_MASTER_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=f"category must be one of: {', '.join(sorted(schemas.CHARGE_MASTER_CATEGORIES))}",
        )
    q = db.query(models.ChargeMasterItem).filter(
        (models.ChargeMasterItem.facility_name.is_(None))
        | (models.ChargeMasterItem.facility_name == current_user.facility)
    )
    if category:
        q = q.filter(models.ChargeMasterItem.category == category)
    if not include_inactive:
        q = q.filter(models.ChargeMasterItem.active.is_(True))
    return q.order_by(models.ChargeMasterItem.category, models.ChargeMasterItem.name).all()


@router.post("/charge-master", response_model=schemas.ChargeMasterItemOut, status_code=201)
def create_charge_master_item(
    payload: schemas.ChargeMasterItemCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer")),
):
    """Same facility-scoping rule as ancillary.py::create_catalog_item: a
    non-admin's item is always forced to their own facility; an admin may
    additionally publish a global item (`facility_name=null`) but never
    target an arbitrary OTHER facility."""
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

    item = models.ChargeMasterItem(
        category=payload.category, code=payload.code, name=payload.name,
        unit_price_cents=payload.unit_price_cents, facility_name=facility_name,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    log_access(
        db, None, current_user.id, current_user.role, "charge_master_item_created",
        detail=f"category={item.category} name={item.name!r} item_id={item.id}",
        actor_facility=current_user.facility,
    )
    return item


@router.get("/charge-master/import-template")
def charge_master_import_template(
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer")),
):
    return Response(
        cm_import.template_bytes(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="charge-master-template.xlsx"'},
    )


@router.post("/charge-master/import")
def import_charge_master(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer")),
):
    """Append-only, all-or-nothing Excel import into the caller's OWN facility (a global item
    still goes through the single-item POST, which keeps that admin-only decision explicit).
    `dry_run` defaults to true so a stray call previews instead of writing. Row problems come
    back in `errors` with HTTP 200 and nothing is written."""
    if not current_user.facility:
        raise HTTPException(status_code=400, detail="Your account has no facility assigned.")
    enforce_upload_size(file, cm_import.MAX_BYTES, "Workbook")
    raw = file.file.read(cm_import.MAX_BYTES + 1)
    try:
        rows, errors = cm_import.parse_workbook(raw, schemas.CHARGE_MASTER_CATEGORIES)
    except cm_import.ImportFileError as e:
        raise HTTPException(status_code=422, detail=str(e))

    existing = [
        {"category": i.category, "code": i.code, "name": i.name}
        for i in db.query(models.ChargeMasterItem).filter(
            (models.ChargeMasterItem.facility_name.is_(None))
            | (models.ChargeMasterItem.facility_name == current_user.facility)
        )
    ]
    new, dups = cm_import.split_new_and_duplicates(rows, existing)
    committed = bool(new) and not errors and not dry_run
    if committed:
        db.add_all(
            models.ChargeMasterItem(
                category=r["category"], code=r["code"], name=r["name"],
                unit_price_cents=r["unit_price_cents"], active=r["active"],
                facility_name=current_user.facility,
            )
            for r in new
        )
        db.commit()
        log_access(
            db, None, current_user.id, current_user.role, "charge_master_imported",
            detail=f"added={len(new)} skipped={len(dups)} file={file.filename!r}",
            actor_facility=current_user.facility,
        )
    return {
        "dry_run": dry_run,
        "committed": committed,
        "would_add": len(new),
        "added": len(new) if committed else 0,
        "skipped_duplicates": len(dups),
        "error_count": len(errors),
        "errors": errors[:cm_import.MAX_ERRORS],
        "preview": [
            {k: r[k] for k in ("row", "category", "code", "name", "unit_price_cents", "active")}
            for r in new[:20]
        ],
    }


@router.patch("/charge-master/{item_id}", response_model=schemas.ChargeMasterItemOut)
def update_charge_master_item(
    item_id: str,
    payload: schemas.ChargeMasterItemUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "records_officer")),
):
    """No delete endpoint -- toggle `active` off instead (existing BillItems
    FK to this row and must never be orphaned). No admin override: an admin
    may edit a global item or their OWN facility's item, never another
    facility's private item -- same rule as ancillary.py::update_catalog_item."""
    item = db.query(models.ChargeMasterItem).filter(models.ChargeMasterItem.id == item_id).first()
    if item is None:
        raise HTTPException(status_code=404, detail="Charge master item not found")
    if item.facility_name is not None and item.facility_name != current_user.facility:
        raise HTTPException(status_code=404, detail="Charge master item not found")

    changed_fields = sorted(payload.model_dump(exclude_unset=True).keys())
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)

    log_access(
        db, None, current_user.id, current_user.role, "charge_master_item_updated",
        detail=f"item_id={item.id} fields={','.join(changed_fields)}",
        actor_facility=current_user.facility,
    )
    return item


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------
@router.post("/bills", response_model=schemas.BillOut, status_code=201)
def create_bill(
    payload: schemas.BillCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    if not current_user.facility:
        raise HTTPException(status_code=400, detail="Your account has no facility assigned.")

    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")

    if payload.encounter_id:
        encounter = db.query(models.Encounter).filter(models.Encounter.id == payload.encounter_id).first()
        if encounter is None or encounter.patient_id != payload.patient_id:
            raise HTTPException(status_code=404, detail="encounter_id not found for this patient")
        # Patient-ownership check only, not a facility-hidden check --
        # deliberately matching the already-reviewed, already-accepted gap
        # in ancillary.py/dental.py's own source_encounter_id checks
        # (Design decision 8), not inventing a new inconsistent rule.

    bill = models.Bill(
        patient_id=payload.patient_id, encounter_id=payload.encounter_id,
        facility_name=current_user.facility, status="open",
        created_by=current_user.id, created_by_name=current_user.full_name, created_by_role=current_user.role,
    )
    db.add(bill)
    db.commit()
    bill = _load_bill_with_relations(db, bill.id)

    log_access(
        db, patient.id, current_user.id, current_user.role, "bill_created",
        detail=f"bill_id={bill.id}" + (f" encounter_id={bill.encounter_id}" if bill.encounter_id else ""),
        actor_facility=current_user.facility,
    )
    return _serialize_bill(bill)


@router.get("/bills", response_model=List[schemas.BillOut])
def list_bills(
    patient_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*BILLING_READ_ROLES)),
):
    """Facility-local ONLY (Design decision 1) -- always the caller's own
    facility's bills, optionally further filtered by patient_id/status.
    There is no cross-facility mode for Billing at all, so unlike
    ancillary.py::list_service_requests there is no hidden-facility filter
    to apply before offset/limit here -- the facility filter below already
    runs before pagination, and it's the only filter that matters."""
    if not current_user.facility:
        return []
    q = (
        db.query(models.Bill)
        .options(
            joinedload(models.Bill.patient),
            selectinload(models.Bill.items),
            selectinload(models.Bill.payments),
            selectinload(models.Bill.claims),
        )
        .filter(models.Bill.facility_name == current_user.facility)
    )
    if patient_id:
        q = q.filter(models.Bill.patient_id == patient_id)
    if status:
        if status not in models.BILL_STATUSES:
            raise HTTPException(status_code=422, detail=f"status must be one of: {', '.join(models.BILL_STATUSES)}")
        q = q.filter(models.Bill.status == status)

    rows = q.order_by(models.Bill.created_at.desc()).offset(offset).limit(limit).all()
    return [_serialize_bill(r) for r in rows]


@router.get("/bills/{bill_id}", response_model=schemas.BillOut)
def get_bill(
    bill_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*BILLING_READ_ROLES)),
):
    bill = _bill_or_404(db, bill_id, current_user)
    return _serialize_bill(bill)


@router.post("/bills/{bill_id}/items", response_model=schemas.BillOut, status_code=201)
def add_bill_item(
    bill_id: str,
    payload: schemas.BillItemCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    bill = _bill_or_404(db, bill_id, current_user)
    if bill.status != "open":
        raise HTTPException(status_code=400, detail=f"Cannot add an item to a bill that is '{bill.status}'")

    description, unit_price_cents = _resolve_bill_item_source(db, payload, current_user, bill)
    amount_cents = payload.quantity * unit_price_cents

    item = models.BillItem(
        bill_id=bill.id, source_type=payload.source_type,
        charge_master_item_id=payload.charge_master_item_id,
        service_request_id=payload.service_request_id,
        medicine_inventory_item_id=payload.medicine_inventory_item_id,
        description=description, quantity=payload.quantity,
        unit_price_cents=unit_price_cents, amount_cents=amount_cents,
        created_by=current_user.id, created_by_name=current_user.full_name, created_by_role=current_user.role,
    )
    db.add(item)
    db.commit()
    bill = _load_bill_with_relations(db, bill.id)

    log_access(
        db, bill.patient_id, current_user.id, current_user.role, "bill_item_added",
        detail=f"bill_id={bill.id} source_type={payload.source_type} amount_cents={amount_cents}",
        actor_facility=current_user.facility,
    )
    return _serialize_bill(bill)


@router.post("/bills/{bill_id}/items/{item_id}/void", response_model=schemas.BillOut)
def void_bill_item(
    bill_id: str,
    item_id: str,
    payload: schemas.BillItemVoid,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    """Voiding is allowed at any bill status except `voided` (correcting a
    mistake on an already-finalized bill is legitimate; ADDING a new item
    to a finalized bill is not -- see add_bill_item's status guard)."""
    bill = _bill_or_404(db, bill_id, current_user)
    if bill.status == "voided":
        raise HTTPException(status_code=400, detail="Bill is voided")
    item = next((i for i in bill.items if i.id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Bill item not found")
    if item.voided_at:
        raise HTTPException(status_code=400, detail="Bill item is already voided")

    item.voided_at = datetime.now(timezone.utc)
    item.voided_by = current_user.id
    item.voided_reason = payload.reason
    db.commit()
    bill = _load_bill_with_relations(db, bill.id)

    log_access(
        db, bill.patient_id, current_user.id, current_user.role, "bill_item_voided",
        detail=f"bill_id={bill.id} item_id={item_id} reason={payload.reason!r}",
        actor_facility=current_user.facility,
    )
    return _serialize_bill(bill)


@router.post("/bills/{bill_id}/finalize", response_model=schemas.BillOut)
def finalize_bill(
    bill_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    bill = _bill_or_404(db, bill_id, current_user)
    if bill.status != "open":
        raise HTTPException(status_code=400, detail=f"Bill is already '{bill.status}'")
    if not any(not i.voided_at for i in bill.items):
        raise HTTPException(status_code=400, detail="Cannot finalize a bill with no active line items")

    bill.status = "finalized"
    bill.finalized_at = datetime.now(timezone.utc)
    bill.finalized_by = current_user.id
    db.commit()
    bill = _load_bill_with_relations(db, bill.id)

    log_access(
        db, bill.patient_id, current_user.id, current_user.role, "bill_finalized",
        detail=f"bill_id={bill.id}", actor_facility=current_user.facility,
    )
    return _serialize_bill(bill)


@router.post("/bills/{bill_id}/void", response_model=schemas.BillOut)
def void_bill(
    bill_id: str,
    payload: schemas.BillVoidRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    bill = _bill_or_404(db, bill_id, current_user)
    if bill.status == "voided":
        raise HTTPException(status_code=400, detail="Bill is already voided")

    bill.status = "voided"
    bill.voided_at = datetime.now(timezone.utc)
    bill.voided_by = current_user.id
    bill.voided_reason = payload.reason
    db.commit()
    bill = _load_bill_with_relations(db, bill.id)

    log_access(
        db, bill.patient_id, current_user.id, current_user.role, "bill_voided",
        detail=f"bill_id={bill.id} reason={payload.reason!r}", actor_facility=current_user.facility,
    )
    return _serialize_bill(bill)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@router.post("/bills/{bill_id}/payments", response_model=schemas.BillOut, status_code=201)
def record_payment(
    bill_id: str,
    payload: schemas.PaymentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    bill = _bill_or_404(db, bill_id, current_user)
    if bill.status == "voided":
        raise HTTPException(status_code=400, detail="Cannot record a payment against a voided bill")

    claim = None
    if payload.claim_id:
        claim = next((c for c in bill.claims if c.id == payload.claim_id), None)
        if claim is None:
            raise HTTPException(status_code=404, detail="Claim not found on this bill")
        if claim.status not in ("submitted", "approved"):
            # A claim not yet submitted (or already paid/rejected/void) has
            # nothing to settle -- e.g. attaching a payment to a still-draft
            # claim would silently do nothing (see the status check just
            # below this block) while looking like it settled something.
            raise HTTPException(
                status_code=400,
                detail=f"Claim must be 'submitted' or 'approved' to record a settling payment (it is '{claim.status}')",
            )

    payment = models.Payment(
        bill_id=bill.id, claim_id=payload.claim_id, amount_cents=payload.amount_cents, method=payload.method,
        reference_no=payload.reference_no, received_by=current_user.id,
        received_by_name=current_user.full_name, received_by_role=current_user.role,
        facility_name=current_user.facility,
    )
    db.add(payment)
    cancel_open_intents(db, bill.id)
    # A claim this payment settles moves to 'paid' -- Design decision 6
    # ("a claim moving to paid is expected to be settled via a Payment...").
    if claim is not None and claim.status in ("submitted", "approved"):
        claim.status = "paid"
    db.commit()
    bill = _load_bill_with_relations(db, bill.id)

    log_access(
        db, bill.patient_id, current_user.id, current_user.role, "payment_recorded",
        detail=f"bill_id={bill.id} amount_cents={payload.amount_cents} method={payload.method}",
        actor_facility=current_user.facility,
    )
    return _serialize_bill(bill)


@router.post("/payments/{payment_id}/void", response_model=schemas.BillOut)
def void_payment(
    payment_id: str,
    payload: schemas.PaymentVoid,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*BILLING_WRITE_ROLES)),
):
    payment = db.query(models.Payment).filter(models.Payment.id == payment_id).first()
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    bill = _bill_or_404(db, payment.bill_id, current_user)
    if payment.voided_at:
        raise HTTPException(status_code=400, detail="Payment is already voided")
    if payment.method == "online":
        # Money really moved at the gateway: it goes back through the approved
        # refund flow (which also tells the gateway), never a silent void.
        raise HTTPException(status_code=400, detail="An online payment must be refunded, not voided")
    if payment.method == "deposit":
        # Return the money to the deposit it came from (reference_no = deposit id).
        # SQL-side arithmetic, not read-modify-write: a parallel apply must not be lost.
        D = models.Deposit
        db.query(D).filter(D.id == payment.reference_no).update(
            {D.applied_cents: D.applied_cents - payment.amount_cents}, synchronize_session=False)

    payment.voided_at = datetime.now(timezone.utc)
    payment.voided_by = current_user.id
    payment.voided_reason = payload.reason
    # If this payment had settled a claim, voiding it reverts that claim to
    # 'approved' (still owed, no longer paid) rather than leaving it stuck
    # at 'paid' with no matching money actually received.
    if payment.claim_id:
        claim = db.query(models.Claim).filter(models.Claim.id == payment.claim_id).first()
        if claim is not None and claim.status == "paid":
            claim.status = "approved"
    db.commit()
    bill = _load_bill_with_relations(db, bill.id)

    log_access(
        db, bill.patient_id, current_user.id, current_user.role, "payment_voided",
        detail=f"payment_id={payment_id} reason={payload.reason!r}", actor_facility=current_user.facility,
    )
    return _serialize_bill(bill)


# ---------------------------------------------------------------------------
# Claims ("add/update/delete claims" -- "delete" = void, never a
# DB delete, same never-hard-delete-a-financial-row discipline as the rest
# of this module)
# ---------------------------------------------------------------------------
@router.post("/bills/{bill_id}/claims", response_model=schemas.ClaimOut, status_code=201)
def create_claim(
    bill_id: str,
    payload: schemas.ClaimCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CLAIM_ROLES)),
):
    bill = _bill_or_404(db, bill_id, current_user)
    if bill.status == "voided":
        raise HTTPException(status_code=400, detail="Cannot claim against a voided bill")

    _check_claim_amount_cap(bill, payload.claim_amount_cents)

    claim = models.Claim(
        bill_id=bill.id, payer_name=payload.payer_name, claim_amount_cents=payload.claim_amount_cents,
        status="draft", notes=payload.notes, facility_name=current_user.facility,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    log_access(
        db, bill.patient_id, current_user.id, current_user.role, "claim_created",
        detail=(
            f"bill_id={bill.id} claim_id={claim.id} payer={payload.payer_name!r} "
            f"amount_cents={payload.claim_amount_cents}"
        ),
        actor_facility=current_user.facility,
    )
    return claim


@router.patch("/claims/{claim_id}", response_model=schemas.ClaimOut)
def update_claim(
    claim_id: str,
    payload: schemas.ClaimUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CLAIM_ROLES)),
):
    """Content fields are PATCH-able only while `status == 'draft'` (Design
    decision 4) -- once submitted, further change is a status transition
    only (see the submit/approve/reject/void endpoints below, plus the
    automatic 'paid' transition in record_payment)."""
    claim, bill = _claim_or_404(db, claim_id, current_user)
    if bill.status == "voided":
        raise HTTPException(status_code=400, detail="Cannot edit a claim on a voided bill")
    if claim.status != "draft":
        raise HTTPException(status_code=400, detail="Only a draft claim can be edited")

    updates = payload.model_dump(exclude_unset=True)
    if "claim_amount_cents" in updates:
        _check_claim_amount_cap(bill, updates["claim_amount_cents"])
    for field, value in updates.items():
        setattr(claim, field, value)
    db.commit()
    db.refresh(claim)

    log_access(
        db, bill.patient_id, current_user.id, current_user.role, "claim_updated",
        detail=f"claim_id={claim.id} fields={','.join(sorted(updates.keys()))}",
        actor_facility=current_user.facility,
    )
    return claim


def _transition_claim(
    db: Session, claim_id: str, current_user: models.User, *,
    from_statuses: tuple, to_status: str, action: str, reason: Optional[str] = None,
) -> models.Claim:
    claim, bill = _claim_or_404(db, claim_id, current_user)
    if claim.status not in from_statuses:
        raise HTTPException(status_code=400, detail=f"Cannot {action} a claim that is '{claim.status}'")

    claim.status = to_status
    if to_status == "submitted":
        claim.submitted_at = datetime.now(timezone.utc)
        claim.submitted_by = current_user.id
    if reason:
        claim.notes = f"{claim.notes}\n{reason}" if claim.notes else reason
    db.commit()
    db.refresh(claim)

    log_access(
        db, bill.patient_id, current_user.id, current_user.role, f"claim_{action}",
        detail=f"claim_id={claim.id}", actor_facility=current_user.facility,
    )
    return claim


@router.post("/claims/{claim_id}/submit", response_model=schemas.ClaimOut)
def submit_claim(
    claim_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CLAIM_ROLES)),
):
    return _transition_claim(
        db, claim_id, current_user, from_statuses=("draft",), to_status="submitted", action="submitted",
    )


@router.post("/claims/{claim_id}/approve", response_model=schemas.ClaimOut)
def approve_claim(
    claim_id: str, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CLAIM_ROLES)),
):
    return _transition_claim(
        db, claim_id, current_user, from_statuses=("submitted",), to_status="approved", action="approved",
    )


@router.post("/claims/{claim_id}/reject", response_model=schemas.ClaimOut)
def reject_claim(
    claim_id: str, payload: schemas.ClaimRejectRequest, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CLAIM_ROLES)),
):
    return _transition_claim(
        db, claim_id, current_user, from_statuses=("submitted", "approved"), to_status="rejected",
        action="rejected", reason=payload.reason,
    )


@router.post("/claims/{claim_id}/void", response_model=schemas.ClaimOut)
def void_claim(
    claim_id: str, payload: schemas.ClaimVoidRequest, db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*CLAIM_ROLES)),
):
    """"Delete" per the tender -- never a DB delete (Design
    decision 4). Any non-paid status may be voided."""
    return _transition_claim(
        db, claim_id, current_user, from_statuses=("draft", "submitted", "approved", "rejected"),
        to_status="void", action="voided", reason=payload.reason,
    )


# ---------------------------------------------------------------------------
# Reporting -- a light stand-in; the full "Financial performance reports"
# clause is P3.6's job.
# ---------------------------------------------------------------------------
@router.get("/stats", response_model=schemas.BillingStatsOut)
def billing_stats(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*BILLING_READ_ROLES)),
):
    facility = current_user.facility
    bills_by_status = {s: 0 for s in models.BILL_STATUSES}
    claims_by_status = {s: 0 for s in models.CLAIM_STATUSES}
    total_billed_cents = 0
    total_collected_cents = 0
    total_outstanding_cents = 0

    if facility:
        for status, count in (
            db.query(models.Bill.status, func.count(models.Bill.id))
            .filter(models.Bill.facility_name == facility)
            .group_by(models.Bill.status)
            .all()
        ):
            bills_by_status[status] = count

        for status, count in (
            db.query(models.Claim.status, func.count(models.Claim.id))
            .filter(models.Claim.facility_name == facility)
            .group_by(models.Claim.status)
            .all()
        ):
            claims_by_status[status] = count

        # Reuses _serialize_bill's arithmetic rather than re-deriving the
        # same total/paid/due logic in SQL a second time -- fine at a
        # single facility's bill volume for this demo-scale stats
        # endpoint; a facility with a large bill volume would want a real
        # SQL aggregate, deferred to P3.6's reporting engine.
        bills = (
            db.query(models.Bill)
            .options(
                selectinload(models.Bill.items), selectinload(models.Bill.payments), selectinload(models.Bill.claims),
            )
            .filter(models.Bill.facility_name == facility, models.Bill.status != "voided")
            .all()
        )
        for bill in bills:
            s = _serialize_bill(bill)
            total_billed_cents += s.total_cents
            total_collected_cents += s.paid_cents
            total_outstanding_cents += s.amount_due_cents

    return schemas.BillingStatsOut(
        facility_name=facility, total_billed_cents=total_billed_cents,
        total_collected_cents=total_collected_cents, total_outstanding_cents=total_outstanding_cents,
        bills_by_status=bills_by_status, claims_by_status=claims_by_status,
    )
