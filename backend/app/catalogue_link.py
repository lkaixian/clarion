"""Ties the HIS drug catalogue (`drugs`) to the older free-text records that name a drug:
patient medication statements, pharmacy inventory items, purchase proposals and purchase
order lines. Each of those carries a nullable `drug_code`.

Rules (one place, so the four call sites cannot drift):
  * an explicit drug_code must exist in the catalogue, else 422;
  * with no code, an exact name match (case-insensitive, trimmed) against a drug's generic
    name or trade name links it, but only when exactly one catalogue drug matches;
  * no match leaves it unlinked: free text stays valid (external or unlisted drugs are common).
"""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from . import models


def match_drug_code(db: Session, name: Optional[str]) -> Optional[str]:
    """The catalogue drug_code whose generic or trade name equals `name`, only if unique."""
    key = (name or "").strip().lower()
    if not key:
        return None
    rows = (
        db.query(models.Drug.drug_code)
        .filter(or_(
            func.lower(func.trim(models.Drug.drug_generic_name)) == key,
            func.lower(func.trim(models.Drug.trade_name)) == key,
        ))
        .limit(2).all()
    )
    codes = {r[0] for r in rows}
    return codes.pop() if len(codes) == 1 else None


def relink_on_update(db: Session, fields: dict, current_name: str, current_code: Optional[str]) -> None:
    """For a PATCH's submitted fields: when `drug_code` or `drug_name` is being changed, set
    fields["drug_code"] to the resolved code. A PATCH that only repeats the same name leaves
    the stored link alone (an explicit link under a different name must survive a price edit)."""
    if "drug_name" in fields and (fields["drug_name"] is None or not fields["drug_name"].strip()):
        raise HTTPException(status_code=422, detail="drug_name cannot be empty.")
    name = fields.get("drug_name", current_name)
    renamed = "drug_name" in fields and name.strip().lower() != (current_name or "").strip().lower()
    if "drug_code" in fields or renamed:
        fields["drug_code"] = resolve_drug_code(db, fields.get("drug_code"), name)
    elif "drug_name" in fields and current_code is None:
        fields["drug_code"] = match_drug_code(db, name)  # unlinked item: retry the name match


def resolve_drug_code(db: Session, drug_code: Optional[str], name: Optional[str]) -> Optional[str]:
    """Explicit code (validated) wins; otherwise try the name; otherwise None."""
    code = (drug_code or "").strip()
    if code:
        row = db.query(models.Drug.drug_code).filter(models.Drug.drug_code == code).first()
        if row is None:
            raise HTTPException(status_code=422, detail=f"Unknown catalogue drug code: {code}")
        return row[0]  # the catalogue's own spelling, not the caller's
    return match_drug_code(db, name)
