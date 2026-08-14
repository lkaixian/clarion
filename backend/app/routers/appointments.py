from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from ..appointments import compute_reminder_offsets

router = APIRouter(prefix="/patients", tags=["appointments"])


def _serialize_appointment(a: models.Appointment) -> dict:
    # reminders is computed on every read (never persisted) -- see
    # appointments.compute_reminder_offsets's docstring for why. This is the
    # one place both the create and list/patch responses funnel through, so
    # every AppointmentOut-shaped response includes it consistently.
    return {
        "id": a.id,
        "patient_id": a.patient_id,
        "facility_name": a.facility_name,
        "venue": a.venue,
        "scheduled_at": a.scheduled_at,
        "reason": a.reason,
        "fasting_required": a.fasting_required,
        "fasting_hours": a.fasting_hours,
        "precaution_notes": a.precaution_notes,
        "extra_reminder_hours_before": a.extra_reminder_hours_before,
        "status": a.status,
        "created_by": a.created_by,
        "created_at": a.created_at,
        "reminders": compute_reminder_offsets(a),
    }


def _get_appointment_or_404(db: Session, patient_id: str, appointment_id: str) -> models.Appointment:
    # Scoped to patient_id too, not just appointment_id -- mirrors
    # patients.py::_get_document_or_404's reasoning: there's no FK
    # enforcement between Appointment.patient_id and Patient.id (SQLite
    # foreign_keys pragma is off), so a caller can't be trusted to have the
    # right patient_id/appointment_id pairing just because both individually
    # resolve to *some* row.
    appointment = (
        db.query(models.Appointment)
        .filter(models.Appointment.id == appointment_id, models.Appointment.patient_id == patient_id)
        .first()
    )
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appointment


@router.post("/{patient_id}/appointments", response_model=schemas.AppointmentOut)
def create_appointment(
    patient_id: str,
    payload: schemas.AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer")),
):
    """Doctor/staff-published appointment (follow-up visit, procedure, etc.).
    Reminder timing is never stored -- see compute_reminder_offsets."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    appointment = models.Appointment(
        patient_id=patient_id, created_by=current_user.id, **payload.model_dump()
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)

    log_access(
        db, patient_id, current_user.id, current_user.role, "create_appointment",
        detail=payload.facility_name, actor_facility=current_user.facility,
    )
    return _serialize_appointment(appointment)


@router.get("/{patient_id}/appointments", response_model=List[schemas.AppointmentOut])
def list_appointments(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Patient (own record only) + staff. Cancelled/completed appointments
    are included, not hidden -- the client filters/styles by status, this
    endpoint stays the full history (same "don't hide history server-side"
    stance as get_audit_log)."""
    if current_user.role == "patient" and current_user.patient_id != patient_id:
        raise HTTPException(status_code=403, detail="Cannot view another patient's appointments")

    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    appointments = (
        db.query(models.Appointment)
        .filter(models.Appointment.patient_id == patient_id)
        .order_by(models.Appointment.scheduled_at.asc())
        .all()
    )

    log_access(
        db, patient_id, current_user.id, current_user.role, "view_appointments",
        actor_facility=current_user.facility,
    )
    return [_serialize_appointment(a) for a in appointments]


@router.patch("/{patient_id}/appointments/{appointment_id}", response_model=schemas.AppointmentOut)
def update_appointment(
    patient_id: str,
    appointment_id: str,
    payload: schemas.AppointmentUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles("admin", "clinician", "records_officer")),
):
    """Staff-only partial update, including the status transition (e.g. to
    "cancelled" -- soft-cancel only, matches EmergencyToken.revoked's
    pattern; this never hard-deletes a row)."""
    appointment = _get_appointment_or_404(db, patient_id, appointment_id)

    submitted_fields = payload.model_dump(exclude_unset=True)
    for field, value in submitted_fields.items():
        setattr(appointment, field, value)

    # Re-validate fasting_hours/fasting_required against the MERGED row, not
    # just the raw PATCH payload -- schemas.AppointmentUpdate deliberately
    # skips this check itself (see its docstring) because a PATCH containing
    # only fasting_hours, against a row that ALREADY has
    # fasting_required=True, must stay valid. But a PATCH that sets
    # fasting_hours on a row where fasting_required is (and stays) False
    # must still be rejected here, after the merge.
    if appointment.fasting_hours is not None and not appointment.fasting_required:
        raise HTTPException(
            status_code=400,
            detail="fasting_hours can only be set when fasting_required is true.",
        )

    if submitted_fields:
        db.add(appointment)
        db.commit()
        db.refresh(appointment)

    log_access(
        db, patient_id, current_user.id, current_user.role, "update_appointment",
        fields=sorted(submitted_fields.keys()), detail=appointment_id,
        actor_facility=current_user.facility,
    )
    return _serialize_appointment(appointment)
