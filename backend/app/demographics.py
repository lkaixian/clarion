"""Coded patient demographics (his_open_1 `patients` code columns).

One place that knows which Patient column is checked against which reference list, shared by
patient creation and the staff demographics edit so the two can never disagree."""
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import models

# Patient column -> reference_codes.kind
DEMOGRAPHIC_KINDS = {
    "title_code": "titles",
    "religion_code": "religions",
    "race_code": "races",
    "nation_code": "nations",
    "marital_code": "marital_statuses",
    "occupation_code": "occupations",
    "state_code": "states",
}
# Free-text / uncoded fields that travel with the coded ones.
DEMOGRAPHIC_PLAIN = ("address_line", "postcode", "city", "sponsor_member_no")
DEMOGRAPHIC_FIELDS = (*DEMOGRAPHIC_KINDS, *DEMOGRAPHIC_PLAIN, "sponsor_code")


def validate_demographics(db: Session, data: dict, facility: Optional[str]) -> dict:
    """Checks every submitted code, then fills city/state from a known postcode when the
    caller did not give them. Returns the cleaned subset of `data` (empty strings become
    None, so a form can clear a field). Raises 422 naming the first bad field."""
    out = {}
    for field in DEMOGRAPHIC_FIELDS:
        if field not in data:
            continue
        value = data[field]
        value = value.strip() if isinstance(value, str) else value
        out[field] = value or None

    for field, kind in DEMOGRAPHIC_KINDS.items():
        code = out.get(field)
        if code is None:
            continue
        ok = db.query(models.ReferenceCode.id).filter_by(kind=kind, code=code).first()
        if ok is None:
            raise HTTPException(status_code=422, detail=f"Unknown {field.replace('_code', '')} code: {code}")

    sponsor = out.get("sponsor_code")
    if sponsor is not None:
        row = db.query(models.Sponsor).filter_by(code=sponsor, facility_name=facility, active=True).first()
        if row is None:
            raise HTTPException(status_code=422, detail=f"Unknown sponsor code: {sponsor}")

    postcode = out.get("postcode")
    if postcode:
        pc = db.query(models.ReferenceCode).filter_by(kind="postcodes", code=postcode).first()
        if pc is not None:
            if "city" not in out:
                city: Optional[models.ReferenceCode] = (
                    db.query(models.ReferenceCode).filter_by(kind="cities", code=pc.parent).first()
                    if pc.parent else None
                )
                if city is not None:
                    out["city"] = city.name
            state = (pc.extra or {}).get("state_code")
            if state and "state_code" not in out:
                out["state_code"] = state
    return out
