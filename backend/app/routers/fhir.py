"""P4.2: thin, READ-ONLY FHIR façade over CLARION's own tables.

Not a FHIR server and not the system of record -- see
healthcare/FHIR Schema Readiness.md. Every route here re-projects an
existing row into FHIR JSON; there is no new data path and no write
capability. Reuses the exact same access policy as GET /patients/{id}
(routers/patients.py::get_patient_full_record): open to any authenticated
staff member with the `patients` page (see main.py's require_page_access
gate on this router), a cross-facility read is logged distinctly rather
than blocked (CLARION's cross-hospital-continuity premise), and a `patient`
role may only reach their own record. No `patient`-role access to the
façade at all for now -- nothing consumes it as a self-service API yet, and
that keeps the per-request identity check to one case instead of two.

Each `_to_fhir_<Resource>` mapper takes just the row (no db/current_user --
unlike patients.py's serializers, the façade never renders the `editable`/
immutability flag; that is a CLARION-internal UI concept the FHIR field
model doesn't have room for) and returns a plain dict shaped like the real
FHIR R4 resource. `_bundle()` wraps a list of them as a `searchset` Bundle.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, auth
from ..database import get_db
from ..audit import log_access
from ..clinical_access import _patient_known_to_facility

router = APIRouter(prefix="/fhir", tags=["fhir"])

_BASE_URL = "https://clarion.local/fhir"  # façade's own base -- no public DNS yet, see docs/deployment.md


def _require_patient_readable(db: Session, patient_id: str, current_user: models.User) -> models.Patient:
    """Same policy as GET /patients/{id} -- see this module's docstring.
    Raises 404 (never 403) for both "doesn't exist" and "patient role,
    someone else's record", same not-confirming-existence posture as
    get_patient_full_record."""
    patient = db.query(models.Patient).filter(models.Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    if current_user.role == "patient":
        raise HTTPException(status_code=404, detail="Patient not found")

    is_cross_facility = not current_user.facility or not _patient_known_to_facility(db, patient_id, current_user.facility)
    log_access(
        db, patient_id, current_user.id, current_user.role,
        "fhir_view_cross_facility" if is_cross_facility else "fhir_view",
        fields=["all"], actor_facility=current_user.facility,
    )
    return patient


def _coding(system: Optional[str], code: Optional[str], display: Optional[str], text: Optional[str] = None) -> Optional[dict]:
    """A FHIR CodeableConcept -- `text` (the free-text label CLARION always
    has) alongside a `coding` array entry only once a system/code exists.
    Never omits `text` just because the coding triple is unset: an uncoded
    row is still valid FHIR (`code` is [0..1]) and still worth a label."""
    if not system and not code and not display and not text:
        return None
    out: dict = {}
    if text:
        out["text"] = text
    if system or code or display:
        coding: dict = {}
        if system:
            coding["system"] = system
        if code:
            coding["code"] = code
        if display:
            coding["display"] = display
        out["coding"] = [coding]
    return out


def _bundle(resource_type: str, resources: List[dict]) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(resources),
        "entry": [{"fullUrl": f"{_BASE_URL}/{resource_type}/{r['id']}", "resource": r} for r in resources],
    }


@router.get("/metadata")
def capability_statement():
    """Static CapabilityStatement -- read + patient-scoped search-type on
    each resource this façade actually serves. No write interactions
    (create/update/delete) are listed because none exist."""
    resources = [
        "Patient", "Condition", "MedicationStatement", "AllergyIntolerance",
        "Encounter", "ServiceRequest", "DiagnosticReport", "DocumentReference",
    ]
    return {
        "resourceType": "CapabilityStatement",
        "status": "active",
        "kind": "instance",
        "fhirVersion": "4.0.1",
        "format": ["json"],
        "software": {"name": "CLARION FHIR façade"},
        "implementation": {"description": "CLARION HealthCare read-only FHIR façade (readiness)"},
        "rest": [{
            "mode": "server",
            "resource": [
                {
                    "type": rt,
                    "interaction": [{"code": "read"}] + ([{"code": "search-type"}] if rt != "Patient" else []),
                }
                for rt in resources
            ],
        }],
    }


def _to_fhir_patient(p: models.Patient) -> dict:
    identifiers = [{"system": "https://fhir.moh.gov.my/NamingSystem/mykad", "value": p.national_id}] if p.national_id else []
    for ident in p.resource_identifiers:
        identifiers.append({"system": ident.system, "value": ident.value})
    return {
        "resourceType": "Patient",
        "id": p.id,
        "identifier": identifiers,
        "name": [{"text": p.full_name}],
        "gender": (p.gender or "").lower() or None,
        "birthDate": p.date_of_birth or None,
        "telecom": [t for t in [
            {"system": "phone", "value": p.phone} if p.phone else None,
            {"system": "email", "value": p.email} if p.email else None,
        ] if t],
    }


@router.get("/Patient/{patient_id}")
def get_fhir_patient(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    patient = _require_patient_readable(db, patient_id, current_user)
    return _to_fhir_patient(patient)


def _to_fhir_condition(c: models.Condition) -> dict:
    return {
        "resourceType": "Condition",
        "id": c.id,
        "subject": {"reference": f"Patient/{c.patient_id}"},
        "clinicalStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "code": "resolved" if c.status == "resolved" else "active",
        }]},
        "code": _coding(c.code_system, c.code_code, c.code_display, text=c.name),
        "onsetString": c.diagnosed_at or None,
        "recorder": {"display": c.authored_by_facility} if c.authored_by_facility else None,
    }


@router.get("/Condition/{condition_id}")
def get_fhir_condition(
    condition_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    row = db.query(models.Condition).filter(models.Condition.id == condition_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Condition not found")
    _require_patient_readable(db, row.patient_id, current_user)
    return _to_fhir_condition(row)


@router.get("/Condition")
def search_fhir_condition(
    patient: str = Query(..., description="Patient id"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _require_patient_readable(db, patient, current_user)
    rows = db.query(models.Condition).filter(models.Condition.patient_id == patient).all()
    return _bundle("Condition", [_to_fhir_condition(r) for r in rows])


def _to_fhir_medication_statement(m: models.MedicationStatement) -> dict:
    return {
        "resourceType": "MedicationStatement",
        "id": m.id,
        "subject": {"reference": f"Patient/{m.patient_id}"},
        "status": "active" if m.active else "stopped",
        "medicationCodeableConcept": _coding(m.code_system, m.code_code, m.code_display, text=m.drug_name),
        "dosage": [{"text": " ".join(x for x in [m.dosage, m.frequency] if x) or None}] if (m.dosage or m.frequency) else [],
        "effectiveDateTime": m.start_date or None,
        "informationSource": {"display": m.prescribed_by_facility} if m.prescribed_by_facility else None,
    }


@router.get("/MedicationStatement/{medication_statement_id}")
def get_fhir_medication_statement(
    medication_statement_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    row = db.query(models.MedicationStatement).filter(models.MedicationStatement.id == medication_statement_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="MedicationStatement not found")
    _require_patient_readable(db, row.patient_id, current_user)
    return _to_fhir_medication_statement(row)


@router.get("/MedicationStatement")
def search_fhir_medication_statement(
    patient: str = Query(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _require_patient_readable(db, patient, current_user)
    rows = db.query(models.MedicationStatement).filter(models.MedicationStatement.patient_id == patient).all()
    return _bundle("MedicationStatement", [_to_fhir_medication_statement(r) for r in rows])


_SEVERITY_MAP = {"mild": "mild", "moderate": "moderate", "severe": "severe"}


def _to_fhir_allergy_intolerance(a: models.AllergyIntolerance) -> dict:
    return {
        "resourceType": "AllergyIntolerance",
        "id": a.id,
        "patient": {"reference": f"Patient/{a.patient_id}"},
        "code": _coding(a.code_system, a.code_code, a.code_display, text=a.substance),
        "criticality": "high" if a.critical_for_emergency else "low",
        "reaction": [{
            "manifestation": [{"text": a.reaction}] if a.reaction else [],
            "severity": _SEVERITY_MAP.get(a.severity),
        }] if (a.reaction or a.severity in _SEVERITY_MAP) else [],
        "recorder": {"display": a.authored_by_facility} if a.authored_by_facility else None,
    }


@router.get("/AllergyIntolerance/{allergy_id}")
def get_fhir_allergy_intolerance(
    allergy_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    row = db.query(models.AllergyIntolerance).filter(models.AllergyIntolerance.id == allergy_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="AllergyIntolerance not found")
    _require_patient_readable(db, row.patient_id, current_user)
    return _to_fhir_allergy_intolerance(row)


@router.get("/AllergyIntolerance")
def search_fhir_allergy_intolerance(
    patient: str = Query(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _require_patient_readable(db, patient, current_user)
    rows = db.query(models.AllergyIntolerance).filter(models.AllergyIntolerance.patient_id == patient).all()
    return _bundle("AllergyIntolerance", [_to_fhir_allergy_intolerance(r) for r in rows])


# v3 ActEncounterCode -- encounter_type is a closed, small free-text enum
# (see models.Encounter), so this is a static lookup, not a stored column.
_ENCOUNTER_CLASS = {
    "outpatient": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "AMB", "display": "ambulatory"},
    "inpatient": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP", "display": "inpatient encounter"},
    "emergency": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "EMER", "display": "emergency"},
    "transfer": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "ACUTE", "display": "inpatient acute"},
}


def _to_fhir_encounter(e: models.Encounter) -> dict:
    return {
        "resourceType": "Encounter",
        "id": e.id,
        "subject": {"reference": f"Patient/{e.patient_id}"},
        "status": "finished" if e.signed_by else "in-progress",
        "class": _ENCOUNTER_CLASS.get(e.encounter_type, {"code": e.encounter_type}),
        "serviceProvider": {"display": e.facility_name},
        "period": {"start": e.started_at.isoformat()} if e.started_at else None,
        "reasonCode": [{"text": e.reason}] if e.reason else [],
    }


@router.get("/Encounter/{encounter_id}")
def get_fhir_encounter(
    encounter_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    row = db.query(models.Encounter).filter(models.Encounter.id == encounter_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Encounter not found")
    _require_patient_readable(db, row.patient_id, current_user)
    return _to_fhir_encounter(row)


@router.get("/Encounter")
def search_fhir_encounter(
    patient: str = Query(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _require_patient_readable(db, patient, current_user)
    rows = db.query(models.Encounter).filter(models.Encounter.patient_id == patient).all()
    return _bundle("Encounter", [_to_fhir_encounter(r) for r in rows])


_SERVICE_REQUEST_STATUS = {"ordered": "active", "cancelled": "revoked", "completed": "completed"}


def _to_fhir_service_request(sr: models.ServiceRequest) -> dict:
    item = sr.catalog_item
    return {
        "resourceType": "ServiceRequest",
        "id": sr.id,
        "subject": {"reference": f"Patient/{sr.patient_id}"},
        "status": _SERVICE_REQUEST_STATUS.get(sr.status, "unknown"),
        "intent": "order",
        "priority": sr.priority or "routine",
        "code": _coding(item.code_system if item else None, item.code if item else None, item.code_display if item else None, text=item.name if item else None),
        "encounter": {"reference": f"Encounter/{sr.source_encounter_id}"} if sr.source_encounter_id else None,
        "reasonCode": [{"text": sr.clinical_indication}] if sr.clinical_indication else [],
        "requester": {"display": sr.requested_by_name} if sr.requested_by_name else None,
        "authoredOn": sr.created_at.isoformat() if sr.created_at else None,
    }


@router.get("/ServiceRequest/{service_request_id}")
def get_fhir_service_request(
    service_request_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    row = db.query(models.ServiceRequest).filter(models.ServiceRequest.id == service_request_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="ServiceRequest not found")
    _require_patient_readable(db, row.patient_id, current_user)
    return _to_fhir_service_request(row)


@router.get("/ServiceRequest")
def search_fhir_service_request(
    patient: str = Query(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _require_patient_readable(db, patient, current_user)
    rows = db.query(models.ServiceRequest).filter(models.ServiceRequest.patient_id == patient).all()
    return _bundle("ServiceRequest", [_to_fhir_service_request(r) for r in rows])


def _to_fhir_diagnostic_report(sres: models.ServiceResult) -> dict:
    req = sres.request
    item = req.catalog_item if req else None
    return {
        "resourceType": "DiagnosticReport",
        "id": sres.id,
        "subject": {"reference": f"Patient/{sres.patient_id}"},
        "status": "final" if sres.signed_by else "preliminary",
        "code": _coding(item.code_system if item else None, item.code if item else None, item.code_display if item else None, text=item.name if item else None),
        "basedOn": [{"reference": f"ServiceRequest/{sres.service_request_id}"}],
        "conclusion": sres.result_text or None,
        "conclusionCode": [{"text": "Abnormal"}] if sres.flag_abnormal else [],
        "effectiveDateTime": sres.performed_at.isoformat() if sres.performed_at else None,
        "issued": sres.created_at.isoformat() if sres.created_at else None,
        "performer": [{"display": sres.performed_by_name}] if sres.performed_by_name else [],
        "presentedForm": [{"contentType": sres.file_mime, "size": sres.file_bytes}] if sres.file_object_key else [],
    }


@router.get("/DiagnosticReport/{service_result_id}")
def get_fhir_diagnostic_report(
    service_result_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    row = db.query(models.ServiceResult).filter(models.ServiceResult.id == service_result_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="DiagnosticReport not found")
    _require_patient_readable(db, row.patient_id, current_user)
    return _to_fhir_diagnostic_report(row)


@router.get("/DiagnosticReport")
def search_fhir_diagnostic_report(
    patient: str = Query(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _require_patient_readable(db, patient, current_user)
    rows = db.query(models.ServiceResult).filter(models.ServiceResult.patient_id == patient).all()
    return _bundle("DiagnosticReport", [_to_fhir_diagnostic_report(r) for r in rows])


_DOC_TYPE_LOINC = {
    # LOINC document-type codes -- well-known, verifiable values (unlike a
    # fabricated ICD-10/MyDrug subset, these four are load-bearing FHIR
    # examples reused across implementation guides).
    "discharge_summary": {"system": "http://loinc.org", "code": "18842-5", "display": "Discharge summary"},
    "prescription": {"system": "http://loinc.org", "code": "57833-6", "display": "Prescription record"},
    "lab_report": {"system": "http://loinc.org", "code": "11502-2", "display": "Laboratory report"},
    "imaging": {"system": "http://loinc.org", "code": "18748-4", "display": "Diagnostic imaging report"},
}


def _to_fhir_document_reference(d: models.ClinicalDocument) -> dict:
    return {
        "resourceType": "DocumentReference",
        "id": d.id,
        "subject": {"reference": f"Patient/{d.patient_id}"},
        "status": "current",
        "docStatus": "final" if d.signed_by else "preliminary",
        "type": {"coding": [_DOC_TYPE_LOINC[d.doc_type]]} if d.doc_type in _DOC_TYPE_LOINC else {"text": d.doc_type},
        "date": (d.signed_at or d.uploaded_at).isoformat() if (d.signed_at or d.uploaded_at) else None,
        "author": [{"display": d.uploaded_by_facility}] if d.uploaded_by_facility else [],
        "content": [{"attachment": {
            "contentType": d.file_mime,
            "size": d.file_bytes,
            "title": d.original_filename,
        }}] if d.file_object_key else [],
    }


@router.get("/DocumentReference/{document_id}")
def get_fhir_document_reference(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    row = db.query(models.ClinicalDocument).filter(models.ClinicalDocument.id == document_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="DocumentReference not found")
    _require_patient_readable(db, row.patient_id, current_user)
    return _to_fhir_document_reference(row)


@router.get("/DocumentReference")
def search_fhir_document_reference(
    patient: str = Query(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    _require_patient_readable(db, patient, current_user)
    rows = db.query(models.ClinicalDocument).filter(models.ClinicalDocument.patient_id == patient).all()
    return _bundle("DocumentReference", [_to_fhir_document_reference(r) for r in rows])
