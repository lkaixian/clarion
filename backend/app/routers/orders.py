"""CPOE: clinicians order drugs, investigations, imaging and procedures for a patient; the
pharmacist or the performing unit completes them (his_open_1 `orders`, `order_drugs`,
`order_investigations`, `order_imaging`).

  POST /patients/{id}/orders          admin, clinician
  GET  /patients/{id}/orders          admin, clinician, pharmacist, records_officer
  GET  /orders                        same roles: the facility's worklist (?status, ?order_type)
  POST /orders/{id}/complete          drug: pharmacist/admin; other types: clinician/admin
  POST /orders/{id}/cancel            the ordering clinician or an admin, only while `ordered`

Orders are facility-local: a facility sees and acts on its own orders only. Completion is a
conditional UPDATE, so two people finishing the same order cannot both succeed. Drug safety
screening stays the existing GET /ai/prescription-screen/{patient} call, made before ordering.
# ponytail: no pricing/billing hook and no stock decrement on dispense; the order carries the
# product_code so billing and inventory can key off it when that is wanted."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import auth, models
from ..audit import log_access
from ..clinical_access import _patient_known_to_facility
from ..database import get_db

router = APIRouter(tags=["orders"])

ORDER_TYPES = ("drug", "investigation", "imaging", "procedure", "other")
_READ_ROLES = ("admin", "clinician", "pharmacist", "records_officer")
_CODE_KINDS = {  # order column -> reference_codes.kind
    "route_code": "drug_routes", "frequency_code": "drug_frequencies",
    "period_code": "periods", "urgency_code": "urgencies",
}


class OrderCreate(BaseModel):
    order_type: str
    description: Optional[str] = Field(default=None, max_length=500)
    product_code: Optional[str] = Field(default=None, max_length=32)
    encounter_id: Optional[str] = None
    quantity: int = Field(default=1, ge=1, le=10000)
    unit_code: Optional[str] = Field(default=None, max_length=32)
    is_stat: bool = False
    notes: Optional[str] = Field(default=None, max_length=2000)
    strength: Optional[str] = Field(default=None, max_length=64)
    dosage: Optional[str] = Field(default=None, max_length=64)
    route_code: Optional[str] = Field(default=None, max_length=32)
    frequency_code: Optional[str] = Field(default=None, max_length=32)
    duration: Optional[int] = Field(default=None, ge=1, le=3650)
    period_code: Optional[str] = Field(default=None, max_length=32)
    urgency_code: Optional[str] = Field(default=None, max_length=32)
    side: Optional[str] = Field(default=None, max_length=32)
    region: Optional[str] = Field(default=None, max_length=64)
    view: Optional[str] = Field(default=None, max_length=64)


class NoteIn(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def _out(o: models.ClinicalOrder) -> dict:
    return {
        "id": o.id, "patient_id": o.patient_id, "patient_name": o.patient.full_name if o.patient else None,
        "encounter_id": o.encounter_id, "order_type": o.order_type, "product_code": o.product_code,
        "description": o.description, "quantity": o.quantity, "unit_code": o.unit_code, "is_stat": o.is_stat,
        "notes": o.notes, "strength": o.strength, "dosage": o.dosage, "route_code": o.route_code,
        "frequency_code": o.frequency_code, "duration": o.duration, "period_code": o.period_code,
        "urgency_code": o.urgency_code, "side": o.side, "region": o.region, "view": o.view,
        "status": o.status, "ordered_by": o.ordered_by, "ordered_by_name": o.ordered_by_name, "created_at": o.created_at,
        "completed_by_name": o.completed_by_name, "completed_at": o.completed_at,
        "completion_note": o.completion_note, "cancelled_at": o.cancelled_at, "cancel_reason": o.cancel_reason,
    }


def _facility(user: models.User) -> str:
    if not user.facility:
        raise HTTPException(status_code=400, detail="Your account has no facility assigned")
    return user.facility


def _order_or_404(db: Session, user: models.User, order_id: str) -> models.ClinicalOrder:
    o = db.query(models.ClinicalOrder).filter(models.ClinicalOrder.id == order_id).first()
    if o is None or o.facility_name != user.facility:
        raise HTTPException(status_code=404, detail="Order not found")
    return o


@router.post("/patients/{patient_id}/orders", status_code=201)
def create_order(
    patient_id: str, payload: OrderCreate, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin", "clinician")),
):
    facility = _facility(user)
    if payload.order_type not in ORDER_TYPES:
        raise HTTPException(status_code=422, detail=f"order_type must be one of {', '.join(ORDER_TYPES)}")
    # A facility may order only for a patient it already deals with. Orders themselves are
    # deliberately not a "relationship" (clinical_access), or one order would unlock the record.
    if not _patient_known_to_facility(db, patient_id, facility):
        raise HTTPException(status_code=404, detail="Patient not found")
    if payload.order_type != "drug" and any(
        getattr(payload, f) for f in ("strength", "dosage", "route_code", "frequency_code", "duration", "period_code")
    ):
        raise HTTPException(status_code=422, detail="Dosage fields belong on a drug order")

    description = (payload.description or "").strip()
    if payload.product_code:
        product = db.query(models.Product).filter(models.Product.product_code == payload.product_code).first()
        if product is None:
            raise HTTPException(status_code=422, detail=f"Unknown product code: {payload.product_code}")
        description = description or product.product_name
    if not description:
        raise HTTPException(status_code=422, detail="Give a description or a product code")

    for field, kind in _CODE_KINDS.items():
        code = getattr(payload, field)
        if code and db.query(models.ReferenceCode.id).filter_by(kind=kind, code=code).first() is None:
            raise HTTPException(status_code=422, detail=f"Unknown {field}: {code}")

    if payload.encounter_id:
        enc = db.query(models.Encounter.id).filter_by(
            id=payload.encounter_id, patient_id=patient_id, facility_name=facility).first()
        if enc is None:
            raise HTTPException(status_code=422, detail="That encounter does not belong to this patient")

    data = payload.model_dump()
    data["description"] = description
    order = models.ClinicalOrder(
        patient_id=patient_id, facility_name=facility, ordered_by=user.id,
        ordered_by_name=user.full_name, **data,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    log_access(db, patient_id, user.id, user.role, "create_order",
               detail=f"{order.id} {order.order_type}", actor_facility=facility)
    return _out(order)


@router.get("/patients/{patient_id}/orders")
def patient_orders(
    patient_id: str, status: Optional[str] = None, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles(*_READ_ROLES)),
):
    facility = _facility(user)
    q = db.query(models.ClinicalOrder).filter(
        models.ClinicalOrder.patient_id == patient_id, models.ClinicalOrder.facility_name == facility)
    if user.role == "pharmacist":
        q = q.filter(models.ClinicalOrder.order_type == "drug")
    if status:
        q = q.filter(models.ClinicalOrder.status == status)
    rows = q.order_by(models.ClinicalOrder.created_at.desc()).limit(200).all()
    log_access(db, patient_id, user.id, user.role, "list_orders", actor_facility=facility)
    return [_out(o) for o in rows]


@router.get("/orders")
def worklist(
    status: str = "ordered", order_type: Optional[str] = None, limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db), user: models.User = Depends(auth.require_roles(*_READ_ROLES)),
):
    facility = _facility(user)
    q = db.query(models.ClinicalOrder).filter(
        models.ClinicalOrder.facility_name == facility, models.ClinicalOrder.status == status)
    if order_type:
        q = q.filter(models.ClinicalOrder.order_type == order_type)
    if user.role == "pharmacist":  # pharmacists only ever act on drug orders
        q = q.filter(models.ClinicalOrder.order_type == "drug")
    rows = q.order_by(models.ClinicalOrder.is_stat.desc(), models.ClinicalOrder.created_at.asc()).limit(limit).all()
    return [_out(o) for o in rows]


@router.post("/orders/{order_id}/complete")
def complete_order(
    order_id: str, payload: NoteIn, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin", "clinician", "pharmacist")),
):
    _facility(user)
    o = _order_or_404(db, user, order_id)
    is_drug = o.order_type == "drug"
    if user.role == "pharmacist" and not is_drug:
        raise HTTPException(status_code=403, detail="Pharmacists complete drug orders only")
    if user.role == "clinician" and is_drug:
        raise HTTPException(status_code=403, detail="A drug order is completed by the pharmacist")
    if is_drug and o.ordered_by == user.id:
        raise HTTPException(status_code=403, detail="You cannot dispense your own drug order")
    done = db.execute(
        update(models.ClinicalOrder)
        .where(models.ClinicalOrder.id == o.id, models.ClinicalOrder.status == "ordered")
        .values(status="completed", completed_by=user.id, completed_by_name=user.full_name,
                completed_at=datetime.now(timezone.utc), completion_note=payload.note)
    ).rowcount
    db.commit()
    if not done:
        raise HTTPException(status_code=409, detail="This order is no longer open")
    db.refresh(o)
    log_access(db, o.patient_id, user.id, user.role, "complete_order",
               detail=o.id, actor_facility=user.facility)
    return _out(o)


@router.post("/orders/{order_id}/cancel")
def cancel_order(
    order_id: str, payload: ReasonIn, db: Session = Depends(get_db),
    user: models.User = Depends(auth.require_roles("admin", "clinician")),
):
    _facility(user)
    o = _order_or_404(db, user, order_id)
    if user.role != "admin" and o.ordered_by != user.id:
        raise HTTPException(status_code=403, detail="Only the ordering clinician or an admin can cancel")
    done = db.execute(
        update(models.ClinicalOrder)
        .where(models.ClinicalOrder.id == o.id, models.ClinicalOrder.status == "ordered")
        .values(status="cancelled", cancelled_by=user.id, cancelled_at=datetime.now(timezone.utc),
                cancel_reason=payload.reason)
    ).rowcount
    db.commit()
    if not done:
        raise HTTPException(status_code=409, detail="This order is no longer open")
    db.refresh(o)
    log_access(db, o.patient_id, user.id, user.role, "cancel_order", detail=o.id, actor_facility=user.facility)
    return _out(o)
