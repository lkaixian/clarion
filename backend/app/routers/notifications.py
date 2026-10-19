"""In-app inbox: GET /notifications, GET /notifications/unread-count,
POST /notifications/read-all, POST /notifications/{id}/read.

Every row belongs to exactly one user and is only ever read or marked by that
user. `notify()` is the one writer other routers call; it only adds the row
(the caller's own commit makes it atomic with the event that caused it)."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/notifications", tags=["notifications"])


def notify(
    db: Session, user_id: str, kind: str, title: str, *,
    body: Optional[str] = None, link: Optional[str] = None,
    urgent: bool = False, facility: Optional[str] = None,
) -> None:
    db.add(models.Notification(
        user_id=user_id, kind=kind, title=title[:255], body=body[:500] if body else None,
        link=link, urgent=urgent, facility_name=facility,
    ))


def _mine(db: Session, user: models.User):
    return db.query(models.Notification).filter(models.Notification.user_id == user.id)


@router.get("", response_model=List[schemas.NotificationOut])
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    q = _mine(db, current_user)
    if unread_only:
        q = q.filter(models.Notification.read_at.is_(None))
    return q.order_by(models.Notification.created_at.desc()).limit(limit).all()


@router.get("/unread-count")
def unread_count(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    n = (
        db.query(func.count(models.Notification.id))
        .filter(models.Notification.user_id == current_user.id, models.Notification.read_at.is_(None))
        .scalar()
    )
    return {"unread": n or 0}


@router.post("/read-all")
def mark_all_read(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    now = datetime.now(timezone.utc)
    n = (
        _mine(db, current_user)
        .filter(models.Notification.read_at.is_(None))
        .update({models.Notification.read_at: now}, synchronize_session=False)
    )
    db.commit()
    return {"marked": n}


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    row = _mine(db, current_user).filter(models.Notification.id == notification_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        db.commit()
    return {"status": "ok"}
