"""P1.12 — backend pytest suite scaffold, first real coverage.

Uses the shared fixtures in conftest.py (test_client / db_session /
make_user / auth_headers). Covers, per the roadmap's stated priority order:
  1. Role-based access control (require_roles) on a real endpoint.
  2. Router-level page-access gating (require_page_access).
  3. Cross-facility clinical-record immutability (_guard_cross_facility_amend
     in app/routers/patients.py) -- the feature this codebase treats as its
     core data-integrity guarantee (a hospital can never silently edit
     another hospital's entry in a shared patient record).
"""
from app import models


def _make_patient(db_session, **overrides):
    patient = models.Patient(
        full_name=overrides.pop("full_name", "Test Patient"),
        date_of_birth=overrides.pop("date_of_birth", "1990-01-01"),
        **overrides,
    )
    db_session.add(patient)
    db_session.commit()
    db_session.refresh(patient)
    return patient


def _make_ward(db_session, facility_name: str):
    ward = models.Ward(facility_name=facility_name, ward_name="General", total_beds=10)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)
    return ward


def _admit(db_session, patient, facility_name: str, ward, bed_number: int = 1):
    admission = models.Admission(
        facility_name=facility_name, patient_id=patient.id, ward_id=ward.id, bed_number=bed_number,
    )
    db_session.add(admission)
    db_session.commit()
    db_session.refresh(admission)
    return admission


# --------------------------------------------------------------------------
# 1. RBAC (auth.require_roles)
# --------------------------------------------------------------------------
def test_pharmacist_cannot_create_patient(test_client, make_user, auth_headers):
    pharmacist = make_user(role="pharmacist", facility="Main Hospital")
    resp = test_client.post(
        "/patients",
        headers=auth_headers(pharmacist),
        json={"full_name": "New Patient", "date_of_birth": "1985-05-05"},
    )
    assert resp.status_code == 403


def test_clinician_can_create_patient(test_client, make_user, auth_headers):
    clinician = make_user(role="clinician", facility="Main Hospital")
    resp = test_client.post(
        "/patients",
        headers=auth_headers(clinician),
        json={"full_name": "New Patient", "date_of_birth": "1985-05-05"},
    )
    assert resp.status_code == 200, resp.text


# --------------------------------------------------------------------------
# 2. Router-level page-access gating (auth.require_page_access, wired at
#    app.include_router(patients.router, dependencies=[...]) in main.py)
# --------------------------------------------------------------------------
def test_receptionist_blocked_from_patients_page_by_default(test_client, make_user, auth_headers):
    # DEFAULT_ROLE_PAGES gives receptionist only ["reception"] until an
    # admin widens it via PUT /admin/role-permissions (see app/permissions.py).
    receptionist = make_user(role="receptionist", facility="Main Hospital")
    resp = test_client.get("/patients", headers=auth_headers(receptionist))
    assert resp.status_code == 403


def test_clinician_allowed_on_patients_page_by_default(test_client, make_user, auth_headers):
    clinician = make_user(role="clinician", facility="Main Hospital")
    resp = test_client.get("/patients", headers=auth_headers(clinician))
    assert resp.status_code == 200


# --------------------------------------------------------------------------
# 3. Cross-facility clinical-record immutability
# --------------------------------------------------------------------------
def test_cross_facility_edit_denied(test_client, db_session, make_user, auth_headers):
    """A condition authored at Facility A can never be amended by staff at
    Facility B -- 403, with the audit trail recording the denial."""
    author = make_user(role="clinician", facility="Facility A")
    other = make_user(role="clinician", facility="Facility B")
    patient = _make_patient(db_session)

    add_resp = test_client.post(
        f"/patients/{patient.id}/conditions",
        headers=auth_headers(author),
        json={"name": "Hypertension"},
    )
    assert add_resp.status_code == 200, add_resp.text

    condition = db_session.query(models.Condition).filter_by(patient_id=patient.id).first()
    assert condition.authored_by_facility == "Facility A"

    resp = test_client.patch(
        f"/patients/{patient.id}/conditions/{condition.id}",
        headers=auth_headers(other),
        json={"status": "resolved"},
    )
    assert resp.status_code == 403
    assert "Facility A" in resp.json()["detail"]

    db_session.expire_all()
    unchanged = db_session.query(models.Condition).filter_by(id=condition.id).first()
    assert unchanged.status == "active"  # the denied PATCH must not have applied

    denial = (
        db_session.query(models.AuditLog)
        .filter_by(patient_id=patient.id, action="update_condition_denied")
        .first()
    )
    assert denial is not None
    assert denial.actor_facility == "Facility B"


def test_same_facility_edit_denied_when_patient_not_present(test_client, db_session, make_user, auth_headers):
    """Same facility as the author is necessary but NOT sufficient -- the
    patient must also be currently present there (rule #2). No Admission /
    open QueueTicket exists here, so this must still be denied."""
    author = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)

    add_resp = test_client.post(
        f"/patients/{patient.id}/conditions",
        headers=auth_headers(author),
        json={"name": "Diabetes"},
    )
    assert add_resp.status_code == 200
    condition = db_session.query(models.Condition).filter_by(patient_id=patient.id).first()

    same_facility_colleague = make_user(role="clinician", facility="Facility A")
    resp = test_client.patch(
        f"/patients/{patient.id}/conditions/{condition.id}",
        headers=auth_headers(same_facility_colleague),
        json={"status": "resolved"},
    )
    assert resp.status_code == 403


def test_same_facility_edit_allowed_when_patient_present(test_client, db_session, make_user, auth_headers):
    """Both rules satisfied (same authoring facility AND an active
    Admission there) -- the amend must be allowed."""
    author = make_user(role="clinician", facility="Facility A")
    patient = _make_patient(db_session)
    ward = _make_ward(db_session, "Facility A")
    _admit(db_session, patient, "Facility A", ward)

    add_resp = test_client.post(
        f"/patients/{patient.id}/conditions",
        headers=auth_headers(author),
        json={"name": "Asthma"},
    )
    assert add_resp.status_code == 200
    condition = db_session.query(models.Condition).filter_by(patient_id=patient.id).first()

    resp = test_client.patch(
        f"/patients/{patient.id}/conditions/{condition.id}",
        headers=auth_headers(author),
        json={"status": "resolved"},
    )
    assert resp.status_code == 200, resp.text

    db_session.expire_all()
    updated = db_session.query(models.Condition).filter_by(id=condition.id).first()
    assert updated.status == "resolved"
