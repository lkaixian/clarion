"""P3.6/P3.7: Reporting (canned operational reports +
Custom Report Builder + notifiable-disease reporting). The
query/filter/group/sort logic lives in app/reporting_engine.py (dataset
registry -- see its docstring for why this is deliberately NOT a generic
SQL builder); PDF/Excel rendering lives in app/report_export.py. This file
is just the HTTP surface + RBAC + template CRUD + the notifiable-disease
notification workflow (bottom of the file).

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
from .. import predictive_analytics
from ..ai.report_narrative import generate_report_narrative

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
            group_by=payload.group_by, sort=payload.sort, anonymize=payload.anonymize,
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


@router.post("/narrative", response_model=schemas.ReportNarrativeOut)
def narrate_report(
    payload: schemas.ReportRunRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    """P4.3c NL report narrative: the same selection /reports/run accepts,
    turned into a short prose summary by the local LLM -- see
    ai/report_narrative.py. Advisory only, nothing persisted."""
    facility = _require_facility(current_user)
    result = _run(db, facility, payload)
    datasets = {d["key"]: d["label"] for d in reporting_engine.dataset_specs(db)}
    label = datasets.get(payload.dataset, payload.dataset)
    out = generate_report_narrative(label, result)
    log_access(
        db, patient_id=None, actor=current_user.id, actor_role=current_user.role,
        action="report_narrative_generated", detail=f"dataset={payload.dataset} rows={result['row_count']}",
        actor_facility=facility,
    )
    return out


# ---------- Predictive analytics (P4.6, +) ----------
# See app/predictive_analytics.py's docstring for the EWMA-forecast /
# rule-based-stratification approach and why. Same facility-local rule,
# read-only/compute-on-demand (no persisted rows -- these are dashboard
# views, not an alert workflow like data_quality.py/security_analytics.py).

@router.get("/predictive/visit-volume")
def predictive_visit_volume(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    facility = _require_facility(current_user)
    result = predictive_analytics.forecast_visit_volume(db, facility)
    log_access(db, patient_id=None, actor=current_user.id, actor_role=current_user.role,
               action="predictive_visit_volume", actor_facility=facility)
    return result


@router.get("/predictive/disease-burden")
def predictive_disease_burden(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    facility = _require_facility(current_user)
    result = predictive_analytics.forecast_disease_burden(db, facility)
    log_access(db, patient_id=None, actor=current_user.id, actor_role=current_user.role,
               action="predictive_disease_burden", actor_facility=facility)
    return result


@router.get("/predictive/stock-depletion")
def predictive_stock_depletion(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    facility = _require_facility(current_user)
    result = predictive_analytics.forecast_stock_depletion(db, facility)
    log_access(db, patient_id=None, actor=current_user.id, actor_role=current_user.role,
               action="predictive_stock_depletion", actor_facility=facility)
    return result


@router.get("/predictive/risk-stratification")
def predictive_risk_stratification(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    """Surfaces real patient names/ids for the high-risk cohort --
    deliberately not run through reporting_engine's anonymize option
: this is a clinical worklist meant to be acted on, not an
    exportable statistical report."""
    facility = _require_facility(current_user)
    result = predictive_analytics.population_risk_stratification(db, facility)
    log_access(db, patient_id=None, actor=current_user.id, actor_role=current_user.role,
               action="predictive_risk_stratification",
               detail=f"cohort_size={result['cohort_size']} high={result['by_band']['high']}",
               actor_facility=facility)
    return result


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


# ---------- Notifiable disease reporting ----------
# No public e-Notifikasi API exists (see models.NotifiableDiseaseReport's
# docstring) -- these endpoints generate the notification record + a PDF
# for a human to file at enotifikasi.moh.gov.my, and track whether that's
# been done. `candidates` only SUGGESTS cases (Condition.name matched
# against models.NOTIFIABLE_DISEASES); `disease_name` on create is always
# free text, so filing isn't gated on the suggestion list.

_NOTIFIABLE_LOWER = [d.lower() for d in models.NOTIFIABLE_DISEASES]


def _serialize_notification(row: models.NotifiableDiseaseReport) -> schemas.NotifiableDiseaseReportOut:
    return schemas.NotifiableDiseaseReportOut(
        id=row.id, facility_name=row.facility_name, patient_id=row.patient_id,
        patient_name=row.patient.full_name if row.patient else None,
        condition_id=row.condition_id, disease_name=row.disease_name, onset_date=row.onset_date,
        notes=row.notes, status=row.status, reported_by=row.reported_by, reported_by_name=row.reported_by_name,
        reported_at=row.reported_at, submitted_by=row.submitted_by, submitted_at=row.submitted_at,
    )


def _matches_notifiable(condition_name: str) -> Optional[str]:
    name = (condition_name or "").strip().lower()
    for i, candidate in enumerate(_NOTIFIABLE_LOWER):
        if candidate == name or candidate in name:
            return models.NOTIFIABLE_DISEASES[i]
    return None


@router.get("/notifiable-diseases/candidates")
def list_notifiable_disease_candidates(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    facility = _require_facility(current_user)
    already_filed = {
        row.condition_id
        for row in db.query(models.NotifiableDiseaseReport.condition_id)
        .filter(models.NotifiableDiseaseReport.facility_name == facility, models.NotifiableDiseaseReport.condition_id.isnot(None))
        .all()
    }
    conditions = db.query(models.Condition).filter(models.Condition.authored_by_facility == facility).all()
    out = []
    for cond in conditions:
        if cond.id in already_filed:
            continue
        matched = _matches_notifiable(cond.name)
        if not matched:
            continue
        patient = db.query(models.Patient).filter(models.Patient.id == cond.patient_id).first()
        out.append({
            "condition_id": cond.id, "patient_id": cond.patient_id,
            "patient_name": patient.full_name if patient else None,
            "matched_disease": matched, "condition_name": cond.name, "diagnosed_at": cond.diagnosed_at,
        })
    return out


@router.get("/notifiable-diseases", response_model=list[schemas.NotifiableDiseaseReportOut])
def list_notifiable_disease_reports(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    q = db.query(models.NotifiableDiseaseReport).filter(models.NotifiableDiseaseReport.facility_name == current_user.facility)
    if status:
        q = q.filter(models.NotifiableDiseaseReport.status == status)
    rows = q.order_by(models.NotifiableDiseaseReport.reported_at.desc()).all()
    return [_serialize_notification(r) for r in rows]


@router.post("/notifiable-diseases", response_model=schemas.NotifiableDiseaseReportOut, status_code=201)
def create_notifiable_disease_report(
    payload: schemas.NotifiableDiseaseReportCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    facility = _require_facility(current_user)
    patient = db.query(models.Patient).filter(models.Patient.id == payload.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    if payload.condition_id:
        condition = db.query(models.Condition).filter(models.Condition.id == payload.condition_id).first()
        if not condition or condition.patient_id != payload.patient_id:
            raise HTTPException(status_code=404, detail="Condition not found for this patient")
        dup = (
            db.query(models.NotifiableDiseaseReport)
            .filter(models.NotifiableDiseaseReport.condition_id == payload.condition_id)
            .first()
        )
        if dup:
            raise HTTPException(status_code=409, detail="A notification already exists for this condition")

    row = models.NotifiableDiseaseReport(
        facility_name=facility, patient_id=payload.patient_id, condition_id=payload.condition_id,
        disease_name=payload.disease_name, onset_date=payload.onset_date, notes=payload.notes,
        reported_by=current_user.id, reported_by_name=current_user.full_name,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    log_access(
        db, patient_id=payload.patient_id, actor=current_user.id, actor_role=current_user.role,
        action="notifiable_disease_reported", detail=f"report_id={row.id} disease={row.disease_name!r}",
        actor_facility=facility,
    )
    return _serialize_notification(row)


def _notification_or_404(db: Session, report_id: str, current_user: models.User) -> models.NotifiableDiseaseReport:
    row = db.query(models.NotifiableDiseaseReport).filter(models.NotifiableDiseaseReport.id == report_id).first()
    if row is None or row.facility_name != current_user.facility:
        raise HTTPException(status_code=404, detail="Notification not found")
    return row


@router.post("/notifiable-diseases/{report_id}/submitted", response_model=schemas.NotifiableDiseaseReportOut)
def mark_notifiable_disease_submitted(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    row = _notification_or_404(db, report_id, current_user)
    if row.status == "submitted":
        raise HTTPException(status_code=409, detail="Already marked submitted")
    row.status = "submitted"
    row.submitted_by = current_user.id
    row.submitted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    log_access(
        db, patient_id=row.patient_id, actor=current_user.id, actor_role=current_user.role,
        action="notifiable_disease_marked_submitted", detail=f"report_id={row.id}",
        actor_facility=current_user.facility,
    )
    return _serialize_notification(row)


@router.get("/notifiable-diseases/{report_id}/document")
def get_notifiable_disease_document(
    report_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*REPORTING_ROLES)),
):
    row = _notification_or_404(db, report_id, current_user)
    patient = db.query(models.Patient).filter(models.Patient.id == row.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    body = report_export.render_notifiable_disease_pdf(row, patient)
    filename = f"notifiable-disease-{row.id}.pdf"
    return Response(
        content=body, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
