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
):
    entry = models.AuditLog(
        patient_id=patient_id,
        actor=actor,
        actor_role=actor_role,
        action=action,
        fields_accessed=fields,
        detail=detail,
    )
    db.add(entry)
    db.commit()
