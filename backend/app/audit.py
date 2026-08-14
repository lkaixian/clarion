from typing import Optional
from sqlalchemy.orm import Session
from . import models


def log_access(
    db: Session,
    patient_id: Optional[str],
    actor: str,
    actor_role: Optional[str],
    action: str,
    fields: Optional[list] = None,
    detail: Optional[str] = None,
    actor_facility: Optional[str] = None,
):
    # actor_facility is a snapshot of WHERE the actor was based AT THE TIME
    # of this access (see AuditLog's class docstring for why this is a
    # snapshot, unlike the actor's display name which is resolved live at
    # read time instead). Optional/defaulted to None so every pre-existing
    # call site keeps compiling unchanged -- callers that log a staff
    # action should pass current_user.facility; callers with no real
    # `User` row to snapshot from (the "system" actor, or an
    # "emergency_responder:<name>" actor from the unauthenticated
    # emergency-scan endpoints) should just leave this unset.
    entry = models.AuditLog(
        patient_id=patient_id,
        actor=actor,
        actor_role=actor_role,
        action=action,
        fields_accessed=fields,
        detail=detail,
        actor_facility=actor_facility,
    )
    db.add(entry)
    db.commit()
