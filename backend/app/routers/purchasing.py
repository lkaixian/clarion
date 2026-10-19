"""Purchasing for the pharmacy store: suppliers, purchase orders, goods receipt
(his_open_1 `suppliers`, `purchases`, `purchase_lines`).

  /purchasing/suppliers        list: admin, pharmacist; create/edit: admin
  /purchasing/orders           create (draft): pharmacist, admin
  /purchasing/orders/{id}/place    admin only (the approval step: a pharmacist cannot order
                                   stock on their own, same as the restock-proposal flow)
  /purchasing/orders/{id}/receive  pharmacist, admin: restocks through inventory._apply_restock
  /purchasing/orders/{id}/cancel   admin; only while nothing has been received

Everything is scoped to the caller's facility; another facility's id is a 404. A received
quantity is bumped with a compare-and-set, so two people booking the same delivery cannot
both succeed and double the stock."""
import secrets
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from .. import auth, models
from ..audit import log_access
from ..database import get_db
from ..inventory import _apply_restock

router = APIRouter(prefix="/purchasing", tags=["purchasing"])

_BUYERS = ("admin", "pharmacist")


class SupplierIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    company_number: Optional[str] = Field(default=None, max_length=64)
    tax_number: Optional[str] = Field(default=None, max_length=64)
    street_1: Optional[str] = Field(default=None, max_length=255)
    street_2: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=128)
    postcode: Optional[str] = Field(default=None, max_length=16)
    state_code: Optional[str] = Field(default=None, max_length=32)
    phone: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=255)
    contact_person: Optional[str] = Field(default=None, max_length=255)
    active: bool = True


class SupplierPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    company_number: Optional[str] = Field(default=None, max_length=64)
    tax_number: Optional[str] = Field(default=None, max_length=64)
    street_1: Optional[str] = Field(default=None, max_length=255)
    street_2: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=128)
    postcode: Optional[str] = Field(default=None, max_length=16)
    state_code: Optional[str] = Field(default=None, max_length=32)
    phone: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=255)
    contact_person: Optional[str] = Field(default=None, max_length=255)
    active: Optional[bool] = None

    class Config:
        extra = "forbid"


class LineIn(BaseModel):
    item_id: str
    quantity: int = Field(ge=1, le=1_000_000)
    unit_cost: Optional[float] = Field(default=None, ge=0, le=10_000_000, allow_inf_nan=False)


class OrderIn(BaseModel):
    supplier_id: str
    reference: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = Field(default=None, max_length=2000)
    lines: List[LineIn] = Field(min_length=1, max_length=200)


class ReceiveLine(BaseModel):
    line_id: str
    quantity: int = Field(ge=1, le=1_000_000)
    batch_number: Optional[str] = Field(default=None, max_length=64)
    expiry_date: Optional[str] = None  # ISO date


class ReceiveIn(BaseModel):
    lines: List[ReceiveLine] = Field(min_length=1, max_length=200)


def _facility(user: models.User) -> str:
    if not user.facility:
        raise HTTPException(status_code=400, detail="Your account has no facility assigned")
    return user.facility


def _supplier_out(s: models.Supplier) -> dict:
    return {c: getattr(s, c) for c in (
        "id", "code", "name", "company_number", "tax_number", "street_1", "street_2", "city",
        "postcode", "state_code", "phone", "email", "contact_person", "active")}


def _order_out(o: models.PurchaseOrder) -> dict:
    total = sum((ln.unit_cost or 0.0) * ln.quantity for ln in o.lines)
    return {
        "id": o.id, "po_number": o.po_number, "status": o.status, "reference": o.reference, "notes": o.notes,
        "supplier_id": o.supplier_id, "supplier_name": o.supplier.name if o.supplier else None,
        "created_at": o.created_at, "ordered_at": o.ordered_at, "closed_at": o.closed_at,
        "total_cost": round(total, 2),
        "lines": [
            {"id": ln.id, "item_id": ln.item_id, "item_name": ln.item_name, "quantity": ln.quantity,
             "unit_cost": ln.unit_cost, "received_quantity": ln.received_quantity,
             "batch_number": ln.batch_number, "expiry_date": ln.expiry_date}
            for ln in o.lines
        ],
    }


def _load_order(db: Session, facility: str, order_id: str) -> models.PurchaseOrder:
    o = (
        db.query(models.PurchaseOrder)
        .options(joinedload(models.PurchaseOrder.lines), joinedload(models.PurchaseOrder.supplier))
        .filter(models.PurchaseOrder.id == order_id, models.PurchaseOrder.facility_name == facility)
        .first()
    )
    if o is None:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return o


# ---- suppliers ---------------------------------------------------------------

@router.get("/suppliers")
def list_suppliers(db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles(*_BUYERS))):
    rows = (
        db.query(models.Supplier).filter(models.Supplier.facility_name == _facility(user))
        .order_by(models.Supplier.name.asc()).all()
    )
    return [_supplier_out(s) for s in rows]


@router.post("/suppliers", status_code=201)
def create_supplier(
    payload: SupplierIn, db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("admin")),
):
    s = models.Supplier(facility_name=_facility(user), **{**payload.model_dump(), "code": payload.code.strip()})
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A supplier with that code already exists")
    db.refresh(s)
    return _supplier_out(s)


@router.patch("/suppliers/{supplier_id}")
def update_supplier(
    supplier_id: str, payload: SupplierPatch, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin")),
):
    s = db.query(models.Supplier).filter_by(id=supplier_id, facility_name=_facility(user)).first()
    if s is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        if v is None and k in ("name", "active"):
            continue
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return _supplier_out(s)


# ---- purchase orders -----------------------------------------------------------

@router.get("/orders")
def list_orders(
    status: Optional[str] = None, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*_BUYERS)),
):
    q = (
        db.query(models.PurchaseOrder)
        .options(joinedload(models.PurchaseOrder.lines), joinedload(models.PurchaseOrder.supplier))
        .filter(models.PurchaseOrder.facility_name == _facility(user))
    )
    if status:
        q = q.filter(models.PurchaseOrder.status == status)
    return [_order_out(o) for o in q.order_by(models.PurchaseOrder.created_at.desc()).limit(200).all()]


@router.get("/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles(*_BUYERS))):
    return _order_out(_load_order(db, _facility(user), order_id))


@router.post("/orders", status_code=201)
def create_order(
    payload: OrderIn, db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles(*_BUYERS)),
):
    facility = _facility(user)
    supplier = db.query(models.Supplier).filter_by(id=payload.supplier_id, facility_name=facility).first()
    if supplier is None or not supplier.active:
        raise HTTPException(status_code=422, detail="Unknown or inactive supplier")
    ids = {ln.item_id for ln in payload.lines}
    items = {
        i.id: i for i in db.query(models.MedicineInventoryItem).filter(
            models.MedicineInventoryItem.id.in_(ids), models.MedicineInventoryItem.facility_name == facility)
    }
    if len(items) != len(ids):
        raise HTTPException(status_code=422, detail="One or more items are not in this facility's inventory")
    po = models.PurchaseOrder(
        facility_name=facility, supplier_id=supplier.id, reference=payload.reference, notes=payload.notes,
        created_by=user.id,
        po_number=f"PO-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(5).upper()}",
    )
    for ln in payload.lines:
        item = items[ln.item_id]
        po.lines.append(models.PurchaseOrderLine(
            item_id=item.id, item_name=item.drug_name, quantity=ln.quantity,
            unit_cost=ln.unit_cost if ln.unit_cost is not None else item.unit_cost,
        ))
    db.add(po)
    try:
        db.commit()
    except IntegrityError:  # po_number collision: vanishingly rare, but never a 500
        db.rollback()
        raise HTTPException(status_code=409, detail="Could not number the order; try again")
    log_access(db, None, user.id, user.role, "create_purchase_order", detail=po.po_number, actor_facility=facility)
    return _order_out(_load_order(db, facility, po.id))


def _transition(db: Session, o: models.PurchaseOrder, allowed_from: tuple, to: str, **extra) -> None:
    done = db.execute(
        update(models.PurchaseOrder)
        .where(models.PurchaseOrder.id == o.id, models.PurchaseOrder.status.in_(allowed_from))
        .values(status=to, **extra)
    ).rowcount
    if not done:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"This order is {o.status}; it cannot go to {to}")


@router.post("/orders/{order_id}/place")
def place_order(order_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("admin"))):
    o = _load_order(db, _facility(user), order_id)
    _transition(db, o, ("draft",), "ordered", ordered_at=datetime.now(timezone.utc))
    db.commit()
    log_access(db, None, user.id, user.role, "place_purchase_order", detail=o.po_number, actor_facility=user.facility)
    db.expire_all()
    return _order_out(_load_order(db, user.facility, order_id))


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles("admin"))):
    o = _load_order(db, _facility(user), order_id)
    if any(ln.received_quantity for ln in o.lines):
        raise HTTPException(status_code=409, detail="Goods have already been received against this order")
    _transition(db, o, ("draft", "ordered"), "cancelled", closed_at=datetime.now(timezone.utc))
    # A receipt may have committed between the check above and the status flip.
    db.expire_all()
    if any(ln.received_quantity for ln in _load_order(db, user.facility, order_id).lines):
        db.rollback()
        raise HTTPException(status_code=409, detail="Goods have already been received against this order")
    db.commit()
    log_access(db, None, user.id, user.role, "cancel_purchase_order", detail=o.po_number, actor_facility=user.facility)
    db.expire_all()
    return _order_out(_load_order(db, user.facility, order_id))


@router.post("/orders/{order_id}/receive")
def receive(
    order_id: str, payload: ReceiveIn, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*_BUYERS)),
):
    facility = _facility(user)
    o = _load_order(db, facility, order_id)
    if o.status not in ("ordered", "partially_received"):
        raise HTTPException(status_code=409, detail=f"This order is {o.status}; goods cannot be received")
    lines = {ln.id: ln for ln in o.lines}
    seen = set()
    for r in payload.lines:
        ln = lines.get(r.line_id)
        if ln is None or r.line_id in seen:
            raise HTTPException(status_code=422, detail="Unknown or repeated line")
        seen.add(r.line_id)
        if r.quantity > ln.quantity - ln.received_quantity:
            raise HTTPException(
                status_code=422, detail=f"{ln.item_name}: only {ln.quantity - ln.received_quantity} still outstanding")
        if r.expiry_date:
            try:
                date.fromisoformat(r.expiry_date)
            except ValueError:
                raise HTTPException(status_code=422, detail=f"{ln.item_name}: expiry_date must be YYYY-MM-DD")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for r in payload.lines:
        ln = lines[r.line_id]
        won = db.execute(
            update(models.PurchaseOrderLine)
            .where(models.PurchaseOrderLine.id == ln.id,
                   models.PurchaseOrderLine.received_quantity == ln.received_quantity)
            .values(received_quantity=ln.received_quantity + r.quantity,
                    batch_number=r.batch_number or ln.batch_number, expiry_date=r.expiry_date or ln.expiry_date)
        ).rowcount
        if not won:
            db.rollback()
            raise HTTPException(status_code=409, detail="This delivery was just booked by someone else; reload")
        item = db.query(models.MedicineInventoryItem).filter_by(id=ln.item_id, facility_name=facility).first()
        if item is None:
            db.rollback()
            raise HTTPException(status_code=409, detail=f"{ln.item_name} is no longer in the inventory")
        _apply_restock(db, item, r.quantity, ln.unit_cost, user, facility, now=now)

    db.flush()
    db.expire_all()
    o = _load_order(db, facility, order_id)
    complete = all(ln.received_quantity >= ln.quantity for ln in o.lines)
    # Conditional: if the order was cancelled meanwhile this matches nothing and the
    # whole receipt (stock included) is rolled back.
    won = db.execute(
        update(models.PurchaseOrder)
        .where(models.PurchaseOrder.id == o.id,
               models.PurchaseOrder.status.in_(("ordered", "partially_received")))
        .values(status="received" if complete else "partially_received",
                closed_at=datetime.now(timezone.utc) if complete else None)
    ).rowcount
    if not won:
        db.rollback()
        raise HTTPException(status_code=409, detail="This order changed while goods were being booked; reload")
    db.commit()
    log_access(db, None, user.id, user.role, "receive_purchase_order",
               detail=f"{o.po_number} {o.status}", actor_facility=facility)
    return _order_out(_load_order(db, facility, order_id))
