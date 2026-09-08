"""P2.10 -- PDPA consent ledger, data-subject requests, DPO register,
retention schedule + scan.

Malaysia's PDPA has no right to erasure -- these tests assert that (a DSR
`kind` of "erasure" is rejected; withdraw_consent only appends to the
ledger; the retention scan flags, never deletes).
"""
import contextlib
import os
import pathlib
import tempfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.retention import run_retention_scan


# --------------------------------------------------------------------------
# consent ledger
# --------------------------------------------------------------------------

def _patient_user(db_session, make_user):
    p = models.Patient(full_name="Aminah Test", date_of_birth="1990-01-01",
                       national_id=f"9001{os.getpid() % 100:02d}-01-{id(db_session) % 10000:04d}")
    db_session.add(p)
    db_session.flush()
    u = make_user(role="patient", patient_id=p.id)
    db_session.commit()
    return p, u


def test_consent_ledger_is_append_only_newest_wins(test_client, make_user, auth_headers, db_session):
    p, u = _patient_user(db_session, make_user)
    H = auth_headers(u)
    try:
        assert test_client.post("/pdpa/consent", json={"purpose": "research", "granted": True}, headers=H).status_code == 200
        assert test_client.get("/pdpa/consent", headers=H).json()["effective"] == {"research": True}

        assert test_client.post("/pdpa/consent", json={"purpose": "research", "granted": False}, headers=H).status_code == 200
        assert test_client.get("/pdpa/consent", headers=H).json()["effective"] == {"research": False}

        # both rows survive -- nothing was updated/deleted
        assert db_session.query(models.ConsentRecord).filter_by(patient_id=p.id, purpose="research").count() == 2

        bad = test_client.post("/pdpa/consent", json={"purpose": "not_a_purpose", "granted": True}, headers=H)
        assert bad.status_code == 400
    finally:
        db_session.query(models.ConsentRecord).filter_by(patient_id=p.id).delete()
        db_session.query(models.Patient).filter_by(id=p.id).delete()
        db_session.commit()


def test_patient_cannot_touch_another_patients_consent(test_client, make_user, auth_headers, db_session):
    p, u = _patient_user(db_session, make_user)
    H = auth_headers(u)
    try:
        r = test_client.post("/pdpa/consent",
                             json={"purpose": "research", "granted": True, "patient_id": "someone-else"},
                             headers=H)
        assert r.status_code == 403
    finally:
        db_session.query(models.Patient).filter_by(id=p.id).delete()
        db_session.commit()


# --------------------------------------------------------------------------
# data-subject requests
# --------------------------------------------------------------------------

def test_dsr_workflow_and_export(test_client, make_user, auth_headers, db_session):
    p, u = _patient_user(db_session, make_user)
    # give the patient a relationship to the RO's facility (P2.2 scope)
    enc = models.Encounter(patient_id=p.id, facility_name="Hospital Sejahtera", encounter_type="outpatient")
    db_session.add(enc)
    db_session.commit()
    ro = make_user(role="records_officer", facility="Hospital Sejahtera")
    HP, HR = auth_headers(u), auth_headers(ro)
    made = []
    try:
        filed = test_client.post("/pdpa/requests", json={"kind": "access", "detail": "my data please"}, headers=HP)
        assert filed.status_code == 200
        dsr = filed.json()
        made.append(dsr["id"])
        assert dsr["status"] == "open"
        due = datetime.fromisoformat(dsr["due_at"])
        assert 20 <= (due - datetime.fromisoformat(dsr["requested_at"])).days <= 22   # 21-day SLA

        # erasure is not a valid kind (no right to erasure in Malaysian PDPA)
        assert test_client.post("/pdpa/requests", json={"kind": "erasure"}, headers=HP).status_code == 400

        assert dsr["id"] in {d["id"] for d in test_client.get("/pdpa/requests", headers=HP).json()}
        assert dsr["id"] in {d["id"] for d in test_client.get("/pdpa/requests", headers=HR).json()}

        # the subject can export their own record any time
        assert test_client.get(f"/pdpa/requests/{dsr['id']}/export", headers=HP).status_code == 200
        # a staff handler cannot until the request is assigned to them + in_progress
        assert test_client.get(f"/pdpa/requests/{dsr['id']}/export", headers=HR).status_code == 409

        assert test_client.post(f"/pdpa/requests/{dsr['id']}/assign", json={}, headers=HR).json()["status"] == "in_progress"

        exp = test_client.get(f"/pdpa/requests/{dsr['id']}/export", headers=HR)
        assert exp.status_code == 200
        body = exp.json()
        assert body["format"] == "clarion-patient-record/v1"
        assert body["record"]["id"] == p.id
        assert "consent_history" in body

        # +14 extension
        ext = test_client.post(f"/pdpa/requests/{dsr['id']}/extend", json={"note": "waiting on the patient"}, headers=HR)
        assert ext.status_code == 200
        assert datetime.fromisoformat(ext.json()["due_at"]) > due
        assert test_client.post(f"/pdpa/requests/{dsr['id']}/extend", json={"note": "again"}, headers=HR).status_code == 409

        assert test_client.post(f"/pdpa/requests/{dsr['id']}/complete", json={"note": "emailed a PDF"}, headers=HR).json()["status"] == "completed"

        # a plain clinician cannot drive the workflow, and a records officer at
        # an unrelated facility cannot see it at all
        clin = make_user(role="clinician", facility="Hospital Sejahtera")
        assert test_client.post(f"/pdpa/requests/{dsr['id']}/complete", json={}, headers=auth_headers(clin)).status_code == 403
        other_ro = make_user(role="records_officer", facility="Klinik Elsewhere")
        assert test_client.get(f"/pdpa/requests/{dsr['id']}", headers=auth_headers(other_ro)).status_code == 404
    finally:
        for did in made:
            db_session.query(models.DataSubjectRequest).filter_by(id=did).delete()
        db_session.query(models.ConsentRecord).filter_by(patient_id=p.id).delete()
        db_session.query(models.Encounter).filter_by(id=enc.id).delete()
        db_session.query(models.Patient).filter_by(id=p.id).delete()
        db_session.commit()


def test_export_rejects_a_non_access_request(test_client, make_user, auth_headers, db_session):
    p, u = _patient_user(db_session, make_user)
    H = auth_headers(u)
    made = []
    try:
        dsr = test_client.post("/pdpa/requests", json={"kind": "correction", "detail": "fix my dob"}, headers=H).json()
        made.append(dsr["id"])
        assert test_client.get(f"/pdpa/requests/{dsr['id']}/export", headers=H).status_code == 400
    finally:
        for did in made:
            db_session.query(models.DataSubjectRequest).filter_by(id=did).delete()
        db_session.query(models.Patient).filter_by(id=p.id).delete()
        db_session.commit()


# --------------------------------------------------------------------------
# admin: DPO register + retention policies
# --------------------------------------------------------------------------

def test_dpo_register_create_on_read_and_update(test_client, make_user, auth_headers, db_session):
    admin = make_user(role="admin", facility="Facility DPO Test")
    H = auth_headers(admin)
    try:
        got = test_client.get("/admin/dpo-register", headers=H)
        assert got.status_code == 200 and got.json()["facility_name"] == "Facility DPO Test"

        upd = test_client.put("/admin/dpo-register",
                              json={"dpo_name": "Dr Siti", "dpo_email": "dpo@example.edu.my",
                                    "jpdp_registration_ref": "JPDP/2025/00123"}, headers=H)
        assert upd.status_code == 200 and upd.json()["dpo_name"] == "Dr Siti"

        clin = make_user(role="clinician", facility="Facility DPO Test")
        assert test_client.get("/admin/dpo-register", headers=auth_headers(clin)).status_code == 403
    finally:
        db_session.query(models.DpoRegister).filter_by(facility_name="Facility DPO Test").delete()
        db_session.commit()


def test_retention_policies_seed_and_edit(test_client, make_user, auth_headers, db_session):
    fac_admin = make_user(role="admin", facility="Hospital Sejahtera")
    plat_admin = make_user(role="admin", facility=None)   # platform admin
    HF, HP = auth_headers(fac_admin), auth_headers(plat_admin)

    pols = {p["category"]: p for p in test_client.get("/admin/retention-policies", headers=HF).json()}
    assert pols["patient"]["retain_years"] == 7
    assert pols["medicolegal"]["retain_years"] is None   # indefinite

    # a single-facility admin cannot change the platform-wide schedule
    assert test_client.put("/admin/retention-policies/patient",
                           json={"category": "patient", "retain_years": 10}, headers=HF).status_code == 403
    assert test_client.post("/admin/retention/scan", headers=HF).status_code == 403

    upd = test_client.put("/admin/retention-policies/patient",
                          json={"category": "patient", "retain_years": 10}, headers=HP)
    assert upd.status_code == 200 and upd.json()["retain_years"] == 10
    # 0 is rejected (would flag everything)
    assert test_client.put("/admin/retention-policies/patient",
                           json={"category": "patient", "retain_years": 0}, headers=HP).status_code == 422
    test_client.put("/admin/retention-policies/patient",
                    json={"category": "patient", "retain_years": 7}, headers=HP)   # restore default


# --------------------------------------------------------------------------
# retention scan -- FLAG ONLY
# --------------------------------------------------------------------------

@contextlib.contextmanager
def _fresh_db():
    from alembic import command
    from alembic.config import Config
    fd, path = tempfile.mkstemp(suffix=".db", prefix="clarion_ret_")
    os.close(fd)
    url = "sqlite:///" + path.replace("\\", "/")
    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    eng = None
    try:
        command.upgrade(Config(str(pathlib.Path(models.__file__).resolve().parent.parent / "alembic.ini")), "head")
        eng = create_engine(url)
        db = sessionmaker(bind=eng)()
        try:
            yield db
        finally:
            db.close()
    finally:
        if eng is not None:
            eng.dispose()
        if prev is not None:
            os.environ["DATABASE_URL"] = prev
        else:
            os.environ.pop("DATABASE_URL", None)
        with contextlib.suppress(OSError):
            os.remove(path)


def test_retention_scan_flags_old_records_only_and_never_deletes():
    with _fresh_db() as db:
        db.add(models.RetentionPolicy(category="encounter", retain_years=7))
        db.add(models.RetentionPolicy(category="patient", retain_years=7))
        db.add(models.RetentionPolicy(category="document", retain_years=7))
        db.add(models.RetentionPolicy(category="medicolegal", retain_years=None))
        p = models.Patient(full_name="Old Record", date_of_birth="1950-01-01")
        db.add(p)
        db.flush()
        old = models.Encounter(patient_id=p.id, facility_name="H", encounter_type="outpatient",
                               started_at=datetime.now(timezone.utc) - timedelta(days=365 * 9))
        recent = models.Encounter(patient_id=p.id, facility_name="H", encounter_type="outpatient",
                                  started_at=datetime.now(timezone.utc) - timedelta(days=30))
        db.add_all([old, recent])
        db.commit()

        res = run_retention_scan(db)
        assert res.flagged_new >= 1
        flagged = {(i.entity_type, i.entity_id) for i in db.query(models.RetentionReviewItem).all()}
        assert ("encounter", old.id) in flagged
        assert ("encounter", recent.id) not in flagged

        # the records are all still there -- FLAG ONLY
        assert db.query(models.Encounter).count() == 2
        assert db.query(models.Patient).count() == 1

        # re-scan is idempotent (upsert), and a dispositioned item is left alone
        item = db.query(models.RetentionReviewItem).filter_by(entity_id=old.id).first()
        item.disposed = True
        db.commit()
        before = db.query(models.RetentionReviewItem).count()
        run_retention_scan(db)
        assert db.query(models.RetentionReviewItem).count() == before
        assert db.query(models.RetentionReviewItem).filter_by(entity_id=old.id).first().disposed is True
