"""Read-only HIS catalogues: GET /drugs, /drugs/{code}, /products, /products/{code},
/fee-schedules.

Search is a case-insensitive substring match (`q`) with limit/offset paging. Drug detail
resolves its dictionary codes (route, frequency, instruction, indication...) to names via
reference_codes so clients need no second lookup. Any staff account; no PHI."""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db

router = APIRouter(tags=["catalogue"])
_AUTH = Depends(auth.get_staff_user)


class _Row(BaseModel):
    class Config:
        from_attributes = True


class DrugOut(_Row):
    drug_code: str
    drug_generic_name: str
    drug_label: Optional[str] = None
    active_ingredient: Optional[str] = None
    drug_category: Optional[str] = None
    drug_schedule: Optional[str] = None
    drug_formulary: Optional[str] = None
    drug_type: Optional[str] = None
    item_subgroup: Optional[str] = None
    trade_name: Optional[str] = None
    strength: Optional[str] = None
    uom_strength: Optional[str] = None
    dosage_form: Optional[str] = None
    sku_uom: Optional[str] = None


class PrescriptionOut(_Row):
    drug_dosage: Optional[float] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    route: Optional[str] = None
    drug_duration: Optional[float] = None
    period: Optional[str] = None
    instruction: Optional[str] = None


class DrugDetail(DrugOut):
    category_name: Optional[str] = None
    special_instruction: Optional[str] = None
    instruction: Optional[str] = None
    caution: Optional[str] = None
    indications: List[str] = []
    prescriptions: List[PrescriptionOut] = []


class ProductOut(_Row):
    product_code: str
    product_name: str
    product_name_other: Optional[str] = None
    category_code: Optional[str] = None
    unit_code: Optional[str] = None
    product_unit_charge: Optional[float] = None
    product_stocked: Optional[int] = None
    product_average_cost: Optional[float] = None
    product_on_hand: Optional[float] = None
    status_code: Optional[str] = None


class UomOut(_Row):
    unit_code: Optional[str] = None
    uom_rate: Optional[float] = None
    uom_price: Optional[float] = None
    uom_cost: Optional[float] = None
    uom_default_price: Optional[int] = None


class TierOut(_Row):
    charge_code: str
    tier_min: Optional[float] = None
    tier_max: Optional[float] = None
    rates: Optional[dict] = None


class ProductDetail(ProductOut):
    category_name: Optional[str] = None
    uoms: List[UomOut] = []


class FeeOut(_Row):
    fee_code: str
    part: Optional[str] = None
    header: Optional[str] = None
    sub_header: Optional[str] = None
    description: Optional[str] = None
    value: Optional[str] = None
    value2: Optional[str] = None


def _names(db: Session, kind: str, codes) -> Dict[str, str]:
    codes = {c for c in codes if c}
    if not codes:
        return {}
    r = models.ReferenceCode
    return {c.code: c.name for c in db.query(r).filter(r.kind == kind, r.code.in_(codes))}


@router.get("/drugs", response_model=List[DrugOut])
def list_drugs(
    q: Optional[str] = Query(default=None, max_length=64),
    category: Optional[str] = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), _: models.User = _AUTH,
):
    d = models.Drug
    qry = db.query(d)
    if category:
        qry = qry.filter(d.drug_code.like(f"{category}%"))  # ATC prefix, e.g. A01
    if q:
        like = f"%{q}%"
        conds = [d.drug_generic_name.ilike(like), d.trade_name.ilike(like),
                 d.active_ingredient.ilike(like), d.drug_code.ilike(like)]
        # The therapeutic class is the drug's parent: typing "antibiotic" finds its members.
        # drug_categories codes are the 3-character ATC prefix of drug_code.
        cats = db.query(models.ReferenceCode.code).filter(
            models.ReferenceCode.kind == "drug_categories", models.ReferenceCode.name.ilike(like)).limit(50).all()
        conds += [d.drug_code.like(f"{c}%") for (c,) in cats]
        qry = qry.filter(or_(*conds))
    return qry.order_by(d.drug_generic_name, d.drug_code).offset(offset).limit(limit).all()


@router.get("/drugs/{drug_code}", response_model=DrugDetail)
def get_drug(drug_code: str, db: Session = Depends(get_db), _: models.User = _AUTH):
    drug = db.get(models.Drug, drug_code)
    if not drug:
        raise HTTPException(status_code=404, detail="Drug not found")
    rx = (db.query(models.DrugPrescription).filter_by(drug_code=drug_code)
          .order_by(models.DrugPrescription.prescription_id).all())
    ind = [i for (i,) in db.query(models.DrugDisease.indication_code).filter_by(drug_code=drug_code)]
    out = DrugOut.model_validate(drug).model_dump()
    atc = drug.drug_code[:3]  # drug_categories are ATC level-2 codes, the drug_code prefix
    out["category_name"] = _names(db, "drug_categories", [atc]).get(atc)
    for field, kind, code in (("special_instruction", "drug_special_instructions", drug.special_code),
                              ("instruction", "drug_instructions", drug.instruction_code),
                              ("caution", "drug_cautions", drug.caution_code)):
        out[field] = _names(db, kind, [code]).get(code)
    out["indications"] = sorted(_names(db, "drug_indications", ind).values())
    dosages = _names(db, "drug_dosages", [r.dosage_code for r in rx])
    freqs = _names(db, "drug_frequencies", [r.frequency_code for r in rx])
    routes = _names(db, "drug_routes", [r.route_code for r in rx])
    periods = _names(db, "periods", [r.period_code for r in rx])
    instr = _names(db, "drug_instructions", [r.instruction_code for r in rx])
    out["prescriptions"] = [
        dict(drug_dosage=r.drug_dosage, dosage=dosages.get(r.dosage_code) or r.dosage_code,
             frequency=freqs.get(r.frequency_code) or r.frequency_code,
             route=routes.get(r.route_code) or r.route_code, drug_duration=r.drug_duration,
             period=periods.get(r.period_code) or r.period_code,
             instruction=instr.get(r.instruction_code))
        for r in rx
    ]
    return out


@router.get("/products", response_model=List[ProductOut])
def list_products(
    q: Optional[str] = Query(default=None, max_length=64),
    category: Optional[str] = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), _: models.User = _AUTH,
):
    p = models.Product
    qry = db.query(p)
    if category:
        qry = qry.filter(p.category_code == category)
    if q:
        like = f"%{q}%"
        conds = [p.product_name.ilike(like), p.product_code.ilike(like)]
        # Category (and the category's own parent, e.g. "Hospital") name also matches.
        R = models.ReferenceCode
        cats = {c for (c,) in db.query(R.code).filter(R.kind == "product_categories", R.name.ilike(like))}
        parents = {c for (c,) in db.query(R.code).filter(R.kind == "product_category_parents", R.name.ilike(like))}
        if parents:
            cats |= {c for (c,) in db.query(R.code).filter(R.kind == "product_categories", R.parent.in_(parents))}
        if cats:
            conds.append(p.category_code.in_(cats))
        qry = qry.filter(or_(*conds))
    return qry.order_by(p.product_name, p.product_code).offset(offset).limit(limit).all()


@router.get("/products/{product_code}", response_model=ProductDetail)
def get_product(product_code: str, db: Session = Depends(get_db), _: models.User = _AUTH):
    prod = db.get(models.Product, product_code)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    out = ProductOut.model_validate(prod).model_dump()
    out["category_name"] = _names(db, "product_categories", [prod.category_code]).get(prod.category_code)
    out["uoms"] = db.query(models.ProductUom).filter_by(product_code=product_code).order_by(models.ProductUom.id).all()
    return out


@router.get("/price-tiers", response_model=List[TierOut])
def list_price_tiers(
    charge_code: Optional[str] = Query(default=None, max_length=64),
    db: Session = Depends(get_db), _: models.User = _AUTH,
):
    """Price bands, optionally for one charge_code (a reference_codes product_charges code).
    The source has no product -> charge_code link, so this is looked up by code, not per product."""
    t = models.ProductPriceTier
    qry = db.query(t)
    if charge_code:
        qry = qry.filter(t.charge_code == charge_code)
    return qry.order_by(t.charge_code, t.tier_min, t.tier_id).all()


@router.get("/fee-schedules", response_model=List[FeeOut])
def list_fee_schedules(
    q: Optional[str] = Query(default=None, max_length=64),
    part: Optional[str] = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db), _: models.User = _AUTH,
):
    f = models.FeeSchedule
    qry = db.query(f)
    if part:
        qry = qry.filter(f.part == part)
    if q:
        like = f"%{q}%"
        qry = qry.filter(or_(f.description.ilike(like), f.header.ilike(like),
                             f.sub_header.ilike(like), f.fee_code.ilike(like)))
    return qry.order_by(f.fee_code).offset(offset).limit(limit).all()





