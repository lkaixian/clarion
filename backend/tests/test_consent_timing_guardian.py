"""Sharing consent: asked at registration, recorded by clinicians, back-filled /
withdrawn at central when it changes, and given by a guardian for a minor."""
from datetime import datetime, timedelta, timezone

from app import models, mpi_client


def _patient(db, name="Consent Pat", dob="1990-01-01", nric=None):
    p = models.Patient(full_name=name, date_of_birth=dob, national_id=nric)
    db.add(p)
    db.commit()
    return p


def _ledger(db, pid):
    return db.query(models.ConsentRecord).filter_by(patient_id=pid).order_by(models.ConsentRecord.created_at).all()


def _post(test_client, headers, pid, purpose="cross_facility_sharing", granted=True):
    return test_client.post("/pdpa/consent", headers=headers,
                            json={"patient_id": pid, "purpose": purpose, "granted": granted})


def test_registration_can_record_sharing_consent(test_client, make_user, auth_headers, db_session):
    clinician = make_user(role="clinician", facility="Reg Hospital")
    ok = test_client.post("/patients", headers=auth_headers(clinician), json={
        "full_name": "Asked At Desk", "date_of_birth": "1985-05-05", "share_across_facilities": True})
    assert ok.status_code == 200, ok.text
    row, = _ledger(db_session, ok.json()["id"])
    assert (row.purpose, row.granted, row.source) == ("cross_facility_sharing", True, "registration")

    no = test_client.post("/patients", headers=auth_headers(clinician), json={
        "full_name": "Not Asked", "date_of_birth": "1985-05-05"})
    assert _ledger(db_session, no.json()["id"]) == []  # opt-in: silence is not consent


def test_clinician_may_record_sharing_consent_but_nothing_else(test_client, make_user, auth_headers, db_session):
    clinician = make_user(role="clinician", facility="Desk Hospital")
    p = _patient(db_session)
    db_session.add(models.Encounter(patient_id=p.id, facility_name="Desk Hospital", encounter_type="outpatient"))
    db_session.commit()
    assert _post(test_client, auth_headers(clinician), p.id).status_code == 200
    assert _post(test_client, auth_headers(clinician), p.id, purpose="research").status_code == 403


def test_grant_backfills_and_withdrawal_retracts_at_central(
        test_client, make_user, auth_headers, db_session, monkeypatch):
    admin = make_user(role="admin", facility="Sync Hospital")
    p = _patient(db_session, nric="880808-08-8888")
    signer = make_user(role="clinician", facility="Sync Hospital")
    ids = []
    for days in (5, 4, 3, 2, 1):  # five signed visits: only the newest three are worth publishing
        e = models.Encounter(patient_id=p.id, facility_name="Sync Hospital", encounter_type="outpatient",
                             started_at=datetime.now(timezone.utc) - timedelta(days=days),
                             signed_by=signer.id, signed_by_name="Dr S", signed_by_role="clinician")
        db_session.add(e)
        db_session.commit()
        ids.append(e.id)
    published, withdrawn = [], []
    monkeypatch.setattr(mpi_client, "enabled", lambda: True)
    monkeypatch.setattr(mpi_client, "facility_name", lambda: "Sync Hospital")
    monkeypatch.setattr(mpi_client, "enqueue_publish", lambda db, eid: published.append(eid))
    monkeypatch.setattr(mpi_client.jobs, "enqueue", lambda db, kind, payload: withdrawn.append((kind, payload)))

    assert _post(test_client, auth_headers(admin), p.id, granted=True).status_code == 200
    assert published == ids[:1:-1]  # newest three, newest first

    assert _post(test_client, auth_headers(admin), p.id, granted=False).status_code == 200
    assert withdrawn == [(mpi_client.WITHDRAW_KIND, {"patient_id": p.id})]


def _guardian(db_session, make_user, child_dob, linked=True):
    parent = _patient(db_session, "Parent", "1980-01-01")
    child = _patient(db_session, "Child", child_dob)
    if linked:
        db_session.add(models.PatientDependant(patient_id=parent.id, dependant_id=child.id, relation_code="child"))
        db_session.commit()
    return make_user(role="patient", patient_id=parent.id), parent, child


def test_guardian_gives_consent_for_a_minor(test_client, make_user, auth_headers, db_session):
    young = (datetime.now(timezone.utc) - timedelta(days=365 * 6)).strftime("%Y-%m-%d")
    guardian, parent, child = _guardian(db_session, make_user, young)
    H = auth_headers(guardian)

    assert _post(test_client, H, child.id).status_code == 200
    row, = _ledger(db_session, child.id)
    assert row.source == "guardian" and row.recorded_by == guardian.id
    eff = test_client.get("/pdpa/consent", headers=H, params={"patient_id": child.id}).json()["effective"]
    assert eff["cross_facility_sharing"] is True
    audit = [a for a in db_session.query(models.AuditLog).filter_by(patient_id=child.id) if a.action == "consent_granted"]
    assert audit and "on_behalf_of_minor" in audit[-1].detail

    # A guardian still cannot open a data-subject request for the child through this path.
    dsr = test_client.post("/pdpa/requests", headers=H, json={"patient_id": child.id, "kind": "access"})
    assert dsr.status_code == 403


def test_guardian_cannot_act_for_an_adult_or_an_unlinked_child(test_client, make_user, auth_headers, db_session):
    adult_guardian, _, adult = _guardian(db_session, make_user, "1990-01-01")
    assert _post(test_client, auth_headers(adult_guardian), adult.id).status_code == 403

    young = (datetime.now(timezone.utc) - timedelta(days=365 * 6)).strftime("%Y-%m-%d")
    stranger, _, other_child = _guardian(db_session, make_user, young, linked=False)
    assert _post(test_client, auth_headers(stranger), other_child.id).status_code == 403
    assert _ledger(db_session, other_child.id) == []


def test_a_queued_withdrawal_does_nothing_if_consent_was_granted_again(db_session, monkeypatch):
    p = _patient(db_session, nric="770707-07-7777")
    db_session.add(models.ConsentRecord(patient_id=p.id, purpose="cross_facility_sharing", granted=True,
                                        source="staff", created_at=datetime.now(timezone.utc)))
    db_session.commit()
    calls = []
    monkeypatch.setattr(mpi_client, "_cfg", lambda: {"facility_id": "x", "seed": "x", "base": "https://c"})
    monkeypatch.setattr(mpi_client, "_call", lambda *a, **k: calls.append(a))
    mpi_client._withdraw_job({"patient_id": p.id})
    assert calls == []


def test_a_spouse_link_is_not_a_guardian_link(test_client, make_user, auth_headers, db_session):
    young = (datetime.now(timezone.utc) - timedelta(days=365 * 17)).strftime("%Y-%m-%d")
    partner, parent, minor = _guardian(db_session, make_user, young)
    link = db_session.query(models.PatientDependant).filter_by(patient_id=parent.id).first()
    link.relation_code = "spouse"
    db_session.commit()
    assert _post(test_client, auth_headers(partner), minor.id).status_code == 403
