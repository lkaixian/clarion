"""Who may act for whom, when one patient login manages other people's profiles.

One patient account can add a child or an elderly parent as a *profile* (a Patient row linked
by a PatientDependant row) and switch into it. The link is between patient records, not
logins, so it keeps holding after the dependant later registers a login of their own -- with
one condition: an ADULT who has a login of their own must approve the carer first (a minor, or
an adult with no login of their own, needs no approval). The rule is evaluated on every
request, never cached in a token, so removing a link takes effect immediately. Authority is
not transitive: it is always computed from the signed-in login's own patient record, never
from the profile currently being acted for.
"""
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from . import models

# Dependant links to a partner or ex-partner are never a guardian relationship
# (reference_codes kind `relationships`: Husband, Spouse, Ex-wife, Ex-husband).
NOT_GUARDIAN_CODES = {"2", "spouse", "13", "14"}

# The only relation codes that grant "act as": Child, Mother, Father, Grandmother, Grandfather,
# Guardian (of a ward), Others. A link with no code, or any other code a clinic set for its own
# reasons (sibling, financial dependant...), does not.
SELF_SERVICE_RELATION_CODES = {"1", "3", "4", "9", "10", "12", "99"}

MAX_PROFILES_PER_ACCOUNT = 10
AGE_OF_MAJORITY = 18


def age_of(dob: Optional[str]) -> Optional[int]:
    try:
        born = date.fromisoformat((dob or "")[:10])
    except ValueError:
        return None
    today = date.today()
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def needs_approval(db: Session, link: "models.PatientDependant") -> bool:
    """An adult who has a login of their own has not yet approved this carer."""
    if link.approved_at is not None:
        return False
    dependant = db.get(models.Patient, link.dependant_id)
    age = age_of(dependant.date_of_birth if dependant else None)
    if age is not None and age < AGE_OF_MAJORITY:
        return False
    return db.query(models.User.id).filter(models.User.patient_id == link.dependant_id).first() is not None


def link_for(db: Session, user, patient_id) -> "Optional[models.PatientDependant]":
    home = getattr(user, "patient_id", None)
    if user.role != "patient" or not home or not patient_id or patient_id == home:
        return None
    return db.query(models.PatientDependant).filter_by(patient_id=home, dependant_id=patient_id).first()


def may_act_for(db: Session, user, patient_id) -> bool:
    """True if this patient login may act for `patient_id`: its own record, or a record it is
    linked to as a guardian/carer (and, for an adult with a login, has been approved)."""
    home = getattr(user, "patient_id", None)
    if user.role != "patient" or not home or not patient_id:
        return False
    if patient_id == home:
        return True
    link = link_for(db, user, patient_id)
    return (link is not None and link.relation_code in SELF_SERVICE_RELATION_CODES
            and not needs_approval(db, link))
