"""P3.6: Reporting (canned operational reports +
Custom Report Builder). The query/filter/group/sort logic lives in
app/reporting_engine.py (dataset registry -- see its docstring for why this
is deliberately NOT a generic SQL builder); PDF/Excel rendering lives in
app/report_export.py. This file is just the HTTP surface + RBAC + template
CRUD.

RBAC: REPORTING_ROLES (admin/records_officer/clinician) -- a management/
clinical tool, not a frontdesk task, so unlike billing/ancillary it does NOT
reach receptionist/pharmacist by default (permissions.py's DEFAULT_ROLE_PAGES
can still grant it per-facility). Facility-local throughout, same Design
Decision as billing.py: reporting_engine's datasets all filter on the
caller's own `current_user.facility`, and templates never cross facilities.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db
from ..audit import log_access
from .. import reporting_engine
from .. import report_export

router = APIRouter(prefix="/reports", tags=["reports"])

REPORTING_ROLES = ("admin", "records_officer", "clinician")


def _require_facility(current_user: models.User) -> str:
    if not current_user.facility:
        raise HTTPException(status_code=400, detail="Your account has no facility assigned.")
    return current_user.facility


def _run(db: Session, facility: str, payload) -> dict:
    try:
        return reporting_engine.run_report(
            db, facility, payload.dataset,
            fields=payload.fields, filters=payload.filters,
            group_by=payload.group_by, sort=payload.sort,
        )
    except reporting_engine.ReportError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/datasets")
def list_datasets(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    """The field-picker catalogue the Custom Report Builder UI renders
    itself from -- one entry per dataset, each with its typed fields
    (groupable/filterable flags, enum options)."""
    return reporting_engine.dataset_specs(db)


@router.post("/run")
def run_report(
    payload: schemas.ReportRunRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    facility = _require_facility(current_user)
    return _run(db, facility, payload)


@router.post("/export")
def export_report(
    payload: schemas.ReportExportRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    facility = _require_facility(current_user)
    result = _run(db, facility, payload)

    datasets = {d["key"]: d["label"] for d in reporting_engine.dataset_specs(db)}
    title = datasets.get(payload.dataset, payload.dataset)
    now = datetime.now(timezone.utc)

    if payload.format == "pdf":
        body = report_export.render_pdf(title, result, current_user.full_name, now.isoformat())
        media_type, ext = "application/pdf", "pdf"
    else:
        body = report_export.render_excel(title, result)
        media_type, ext = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"

    log_access(
        db, patient_id=None, actor=current_user.id, actor_role=current_user.role,
        action="report_exported", detail=f"dataset={payload.dataset} format={payload.format} rows={result['row_count']}",
        actor_facility=facility,
    )
    filename = f"{payload.dataset}-{now.strftime('%Y%m%d-%H%M%S')}.{ext}"
    return Response(
        content=body, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- Saved report templates ("save & share templates") ----------

def _serialize_template(row: models.ReportTemplate, current_user: models.User) -> schemas.ReportTemplateOut:
    return schemas.ReportTemplateOut(
        id=row.id, facility_name=row.facility_name, name=row.name, dataset=row.dataset,
        fields=row.fields, filters=row.filters or {}, group_by=row.group_by, sort=row.sort,
        is_shared=row.is_shared, created_by=row.created_by, created_by_name=row.created_by_name,
        created_at=row.created_at,
        editable=(row.created_by == current_user.id or current_user.role == "admin"),
    )


def _visible_template_or_404(db: Session, template_id: str, current_user: models.User) -> models.ReportTemplate:
    row = db.query(models.ReportTemplate).filter(models.ReportTemplate.id == template_id).first()
    if (
        row is None
        or row.facility_name != current_user.facility
        or (not row.is_shared and row.created_by != current_user.id and current_user.role != "admin")
    ):
        # Same "404, not 403" shape as every other cross-scope lookup in this
        # codebase -- a private template's existence isn't revealed either.
        raise HTTPException(status_code=404, detail="Report template not found")
    return row


@router.get("/templates", response_model=list[schemas.ReportTemplateOut])
def list_templates(
    dataset: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    q = db.query(models.ReportTemplate).filter(models.ReportTemplate.facility_name == current_user.facility)
    if dataset:
        q = q.filter(models.ReportTemplate.dataset == dataset)
    rows = q.order_by(models.ReportTemplate.created_at.desc()).all()
    visible = [r for r in rows if r.is_shared or r.created_by == current_user.id or current_user.role == "admin"]
    return [_serialize_template(r, current_user) for r in visible]


@router.post("/templates", response_model=schemas.ReportTemplateOut, status_code=201)
def create_template(
    payload: schemas.ReportTemplateCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    facility = _require_facility(current_user)
    # Validate the selection against the engine's own registry up front --
    # a template that can never successfully run is worse than refusing to
    # save it.
    try:
        reporting_engine.run_report(
            db, facility, payload.dataset,
            fields=payload.fields, filters=payload.filters, group_by=payload.group_by, sort=payload.sort,
        )
    except reporting_engine.ReportError as e:
        raise HTTPException(status_code=422, detail=str(e))

    row = models.ReportTemplate(
        facility_name=facility, name=payload.name, dataset=payload.dataset,
        fields=payload.fields, filters=payload.filters, group_by=payload.group_by, sort=payload.sort,
        is_shared=payload.is_shared, created_by=current_user.id, created_by_name=current_user.full_name,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(
        db, patient_id=None, actor=current_user.id, actor_role=current_user.role,
        action="report_template_created", detail=f"template_id={row.id} dataset={row.dataset}",
        actor_facility=facility,
    )
    return _serialize_template(row, current_user)


@router.delete("/templates/{template_id}", status_code=204)
def delete_template(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    row = _visible_template_or_404(db, template_id, current_user)
    if row.created_by != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only the creator or an admin may delete this template")
    db.delete(row)
    db.commit()
    log_access(
        db, patient_id=None, actor=current_user.id, actor_role=current_user.role,
        action="report_template_deleted", detail=f"template_id={template_id}",
        actor_facility=current_user.facility,
    )
