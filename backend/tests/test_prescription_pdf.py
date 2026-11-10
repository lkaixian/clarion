"""Printable prescription: RBAC, facility scoping, audit row, PDF body."""
import uuid

from app import models
from conftest import _make_patient

FAC = "Rx Clinic"


def _setup(db, make_user):
    p = _make_patient(db, full_name="Rx Patient", national_id=f"90{uuid.uuid4().int % 10**10:010d}")
    db.add_all([
        models.MedicationStatement(patient_id=p.id, drug_name="Amoxicillin", dosage="500mg", frequency="TDS",
                                   recorded_by_facility=FAC, active=True),
        models.MedicationStatement(patient_id=p.id, drug_name="StoppedDrug", recorded_by_facility=FAC, active=False),
    ])
    db.commit()
    return p


def _get(c, h, pid):
    return c.get(f"/pharmacy/patients/{pid}/prescription/pdf", headers=h)


def test_prescription_pdf(test_client, make_user, auth_headers, db_session):
    p = _setup(db_session, make_user)
    pharm = make_user(role="pharmacist", facility=FAC)
    r = _get(test_client, auth_headers(pharm), p.id)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and r.headers["cache-control"] == "no-store"
    assert 'filename="prescription-Rx_Patient.pdf"' in r.headers["content-disposition"]
    audit = db_session.query(models.AuditLog).filter_by(patient_id=p.id, action="prescription_pdf_printed").all()
    assert len(audit) == 1 and audit[0].actor_facility == FAC
    assert "Amoxicillin" not in (audit[0].detail or "")  # no PHI in the audit detail

    clin = make_user(role="clinician", facility=FAC)
    assert _get(test_client, auth_headers(clin), p.id).status_code == 200


def test_prescription_denied_cases(test_client, make_user, auth_headers, db_session):
    p = _setup(db_session, make_user)
    recep = make_user(role="receptionist", facility=FAC)
    assert _get(test_client, auth_headers(recep), p.id).status_code == 403
    other = make_user(role="pharmacist", facility="Some Other Facility")
    assert _get(test_client, auth_headers(other), p.id).status_code == 404
    pharm = make_user(role="pharmacist", facility=FAC)
    assert _get(test_client, auth_headers(pharm), "no-such-id").status_code == 404
    assert db_session.query(models.AuditLog).filter_by(patient_id=p.id, action="prescription_pdf_printed").count() == 0
