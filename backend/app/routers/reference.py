"""Read-only HIS lookup lists: GET /reference (kinds + counts),
GET /reference/{kind}?parent=&q= (e.g. kind=postcodes&parent=batu_pahat).
Any staff account; the data is public reference material, no PHI."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db

router = APIRouter(prefix="/reference", tags=["reference"])


class ReferenceOut(BaseModel):
    code: str
    name: str
    parent: Optional[str] = None
    parent_name: Optional[str] = None  # resolved name of `parent` (e.g. the city of a postcode)
    state_name: Optional[str] = None   # resolved extra.state_code (postcodes)
    extra: Optional[dict] = None

    class Config:
        from_attributes = True


@router.get("")
def list_kinds(db: Session = Depends(get_db), _: models.User = Depends(auth.get_staff_user)):
    rows = db.query(models.ReferenceCode.kind, func.count()).group_by(models.ReferenceCode.kind).all()
    return {k: n for k, n in sorted(rows)}


@router.get("/{kind}", response_model=List[ReferenceOut])
def get_kind(
    kind: str,
    parent: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
    _: models.User = Depends(auth.get_staff_user),
):
    r = models.ReferenceCode
    qry = db.query(r).filter(r.kind == kind)
    if parent:
        qry = qry.filter(r.parent == parent)
    rows = qry.order_by(r.name, r.code).all()
    if not rows and not db.query(r.id).filter(r.kind == kind).first():
        raise HTTPException(status_code=404, detail="Unknown reference list")

    # Parent and state are stored as codes; resolve them to names so the list can show them and
    # the filter can match them (typing "Johor" finds its cities and postcodes).
    wanted = {x.parent for x in rows if x.parent} | {
        (x.extra or {}).get("state_code") for x in rows if (x.extra or {}).get("state_code")}
    names: dict = {}
    if wanted:
        for p in db.query(r).filter(r.code.in_(wanted), r.kind != kind):
            names.setdefault(p.code, p.name)
    out = []
    for x in rows:
        state = (x.extra or {}).get("state_code")
        out.append({
            "code": x.code, "name": x.name, "parent": x.parent, "extra": x.extra,
            "parent_name": names.get(x.parent) if x.parent else None,
            "state_name": names.get(state) if state else None,
        })
    if q:
        words = q.lower().split()
        out = [
            o for o in out
            if all(any(w in (o[f] or "").lower() for f in ("code", "name", "parent", "parent_name", "state_name"))
                   or w in str((o["extra"] or {}).get("state_code") or "").lower() for w in words)
        ]
    return out
