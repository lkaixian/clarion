"""P2.12 -- data-quality batch validators (`app/data_quality.py`) + admin API.

Rule / scan tests run against an isolated throwaway migrated SQLite DB (they
write clinical rows). The admin-endpoint test uses the shared conftest
fixtures with hand-built alert rows it cleans up.
"""
import contextlib
import os
import pathlib
import subprocess
import sys
import tempfile
import time
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from conftest import drop_patient
from app.data_quality import (
    RULES, _FINDING_RULE_TO_KEY,
    run_scan,
    _parse_iso_date, _normalize_name,
)


# --------------------------------------------------------------------------
# isolated throwaway DB
# --------------------------------------------------------------------------

@contextlib.contextmanager
def _throwaway_db(target: str = "head"):
    from alembic import command
    from alembic.config import Config

    fd, path = tempfile.mkstemp(suffix=".db", prefix="clarion_dq_")
    os.close(fd)
    url = "sqlite:///" + path.replace("\\", "/")
    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    engine = None
    try:
        cfg = Config(str(pathlib.Path(models.__file__).resolve().parent.parent / "alembic.ini"))
        command.upgrade(cfg, target)
        engine = create_engine(url)
        db = sessionmaker(bind=engine)()
        try:
            yield db, url
        finally:
            db.close()
    finally:
        if engine is not None:
            engine.dispose()
        if prev is not None:
            os.environ["DATABASE_URL"] = prev
        else:
            os.environ.pop("DATABASE_URL", None)
        with contextlib.suppress(OSError):
            os.remove(path)


@pytest.fixture
def fresh_db():
    with _throwaway_db("head") as (db, _url):
        yield db


def _patient(db, **over):
    kw = {"full_name": "John Clean", "date_of_birth": "1990-01-01", "gender": "male",
          "blood_type": "O+", "national_id": "900101-10-1234"}
    kw.update(over)
    p = models.Patient(**kw)
    db.add(p)
    db.commit()
    return p


def _condition(db, patient_id, **over):
    kw = {"patient_id": patient_id, "name": "Asthma", "status": "active", "diagnosed_at": "2020-01-01"}
    kw.update(over)
    c = models.Condition(**kw)
    db.add(c)
    db.commit()
    return c


def _medication(db, patient_id, **over):
    kw = {"patient_id": patient_id, "drug_name": "Inhaler", "dosage": "1 puff",
          "frequency": "BID", "start_date": "2020-01-01", "active": True}
    kw.update(over)
    m = models.MedicationStatement(**kw)
    db.add(m)
    db.commit()
    return m


def _encounter(db, patient_id, **over):
    kw = {"patient_id": patient_id, "facility_name": "Klinik A", "encounter_type": "outpatient", "reason": "Cough"}
    kw.update(over)
    e = models.Encounter(**kw)
    db.add(e)
    db.commit()
    return e


def _allergy(db, patient_id, **over):
    kw = {"patient_id": patient_id, "substance": "Penicillin", "severity": "mild"}
    kw.update(over)
    a = models.AllergyIntolerance(**kw)
    db.add(a)
    db.commit()
    return a


# --------------------------------------------------------------------------
# clean baseline + one-violation-at-a-time
# --------------------------------------------------------------------------

def test_clean_db_has_no_alerts(fresh_db):
    p = _patient(fresh_db)
    _condition(fresh_db, p.id)
    _medication(fresh_db, p.id)
    _encounter(fresh_db, p.id)
    _allergy(fresh_db, p.id)

    res = run_scan(fresh_db, disabled=set())
    assert res.still_open == 0
    assert fresh_db.query(models.DataQualityAlert).count() == 0


# (finding_rule, entity_type, entity_kind, overrides). "patient" replaces the
# baseline patient; the rest hang off a clean one.
_CASES = [
    ("patient_missing_gender", "patient", "patient", {"gender": None}),
    ("patient_missing_gender", "patient", "patient", {"gender": "   "}),
    ("patient_missing_blood_type", "patient", "patient", {"blood_type": None}),
    ("patient_invalid_gender", "patient", "patient", {"gender": "alien"}),
    ("patient_invalid_blood_type", "patient", "patient", {"blood_type": "Z+"}),
    ("patient_unparseable_dob", "patient", "patient", {"date_of_birth": "not-a-date"}),
    ("patient_dob_in_future", "patient", "patient", {"date_of_birth": "2099-01-01"}),
    ("patient_implausible_age", "patient", "patient", {"date_of_birth": "1890-01-01"}),
    ("condition_blank_name", "condition", "condition", {"name": ""}),
    ("condition_invalid_status", "condition", "condition", {"status": "unknown"}),
    ("condition_unparseable_diagnosed_at", "condition", "condition", {"diagnosed_at": "123"}),
    ("condition_diagnosed_in_future", "condition", "condition", {"diagnosed_at": "2099-01-01"}),
    ("condition_diagnosed_before_birth", "condition", "condition", {"diagnosed_at": "1980-01-01"}),
    ("medication_missing_dosage", "medication", "medication", {"dosage": None}),
    ("medication_missing_frequency", "medication", "medication", {"frequency": None}),
    ("medication_unparseable_start_date", "medication", "medication", {"start_date": "asdf"}),
    ("medication_start_in_future", "medication", "medication", {"start_date": "2099-01-01"}),
    ("allergy_invalid_severity", "allergy", "allergy", {"severity": "deadly"}),
    ("encounter_missing_reason", "encounter", "encounter", {"reason": None}),
    ("encounter_invalid_type", "encounter", "encounter", {"encounter_type": "alien"}),
]


@pytest.mark.parametrize("finding_rule, entity_type, kind, overrides", _CASES)
def test_single_violation_raises_exactly_one_alert(fresh_db, finding_rule, entity_type, kind, overrides):
    if kind == "patient":
        entity = _patient(fresh_db, **overrides)
    else:
        p = _patient(fresh_db)
        entity = {"condition": _condition, "medication": _medication,
                  "encounter": _encounter, "allergy": _allergy}[kind](fresh_db, p.id, **overrides)

    res = run_scan(fresh_db, disabled=set())
    assert res.new_alerts == 1, [a.rule for a in fresh_db.query(models.DataQualityAlert).all()]

    alert = fresh_db.query(models.DataQualityAlert).one()
    assert alert.rule == finding_rule
    assert alert.entity_type == entity_type
    assert alert.entity_id == entity.id
    assert alert.detail
    assert alert.category in {"missing", "coding", "duplicate", "anomaly"}


def test_probable_duplicate_needs_a_missing_nric(fresh_db):
    _patient(fresh_db, full_name="Bob Lim", date_of_birth="1990-01-01", national_id="111")
    _patient(fresh_db, full_name="Bob  LIM", date_of_birth="1990-01-01", national_id=None)
    run_scan(fresh_db, disabled=set())
    dups = fresh_db.query(models.DataQualityAlert).filter_by(rule="patient_probable_duplicate").all()
    assert len(dups) == 2

    fresh_db.query(models.DataQualityAlert).delete()
    fresh_db.query(models.Patient).delete()
    fresh_db.commit()
    _patient(fresh_db, full_name="Bob Lim", date_of_birth="1990-01-01", national_id="111")
    _patient(fresh_db, full_name="Bob Lim", date_of_birth="1990-01-01", national_id="222")
    run_scan(fresh_db, disabled=set())
    assert fresh_db.query(models.DataQualityAlert).filter_by(rule="patient_probable_duplicate").count() == 0


def test_duplicate_active_conditions_on_one_patient(fresh_db):
    p = _patient(fresh_db)
    _condition(fresh_db, p.id, name="Asthma")
    _condition(fresh_db, p.id, name="asthma.")
    run_scan(fresh_db, disabled=set())
    assert fresh_db.query(models.DataQualityAlert).filter_by(rule="condition_duplicate_on_patient").count() == 2


# --------------------------------------------------------------------------
# scan lifecycle: upsert / auto-resolve / reopen / disable
# --------------------------------------------------------------------------

def test_repeat_scan_upserts_not_duplicates(fresh_db):
    _patient(fresh_db, gender=None)

    r1 = run_scan(fresh_db, disabled=set())
    assert r1.new_alerts == 1
    first_seen = fresh_db.query(models.DataQualityAlert).one().last_seen_at
    time.sleep(0.01)

    r2 = run_scan(fresh_db, disabled=set())
    assert r2.new_alerts == 0
    a2 = fresh_db.query(models.DataQualityAlert).one()
    assert a2.times_seen == 2
    assert a2.last_seen_at > first_seen


def test_fixed_data_auto_resolves_then_reopens(fresh_db):
    p = _patient(fresh_db, gender=None)
    run_scan(fresh_db, disabled=set())
    assert not fresh_db.query(models.DataQualityAlert).one().resolved

    p.gender = "male"
    fresh_db.add(p)
    fresh_db.commit()
    r = run_scan(fresh_db, disabled=set())
    assert r.auto_resolved == 1
    row = fresh_db.query(models.DataQualityAlert).one()
    assert row.resolved and row.resolved_by == "system"

    p.gender = None
    fresh_db.add(p)
    fresh_db.commit()
    run_scan(fresh_db, disabled=set())
    row = fresh_db.query(models.DataQualityAlert).one()
    assert not row.resolved and row.resolved_by is None


def test_manual_resolve_is_not_reopened_by_a_scan(fresh_db):
    _patient(fresh_db, gender=None)
    run_scan(fresh_db, disabled=set())
    row = fresh_db.query(models.DataQualityAlert).one()
    row.resolved = True
    row.resolved_by = "some-admin-id"
    fresh_db.add(row)
    fresh_db.commit()

    run_scan(fresh_db, disabled=set())  # the finding still fires
    row = fresh_db.query(models.DataQualityAlert).one()
    assert row.resolved and row.resolved_by == "some-admin-id"


def test_disabled_rule_neither_fires_nor_auto_resolves(fresh_db):
    _patient(fresh_db, gender="alien")

    r = run_scan(fresh_db, disabled={"coding_patient_gender"})
    assert r.new_alerts == 0 and "coding_patient_gender" in r.rules_skipped
    assert fresh_db.query(models.DataQualityAlert).count() == 0

    run_scan(fresh_db, disabled=set())  # now it fires
    assert not fresh_db.query(models.DataQualityAlert).one().resolved

    # re-disable: the existing alert must NOT be auto-resolved
    r = run_scan(fresh_db, disabled={"coding_patient_gender"})
    assert r.auto_resolved == 0
    assert not fresh_db.query(models.DataQualityAlert).one().resolved


def test_disabled_rules_read_from_env(fresh_db, monkeypatch):
    monkeypatch.setenv("DATA_QUALITY_DISABLED_RULES", " coding_patient_gender , anomaly_dates ")
    _patient(fresh_db, gender="alien")
    r = run_scan(fresh_db)  # no explicit disabled= -> env
    assert {"coding_patient_gender", "anomaly_dates"} <= set(r.rules_skipped)
    assert fresh_db.query(models.DataQualityAlert).count() == 0


# --------------------------------------------------------------------------
# registry integrity
# --------------------------------------------------------------------------

def test_a_throwing_rule_does_not_abort_the_whole_scan(fresh_db, monkeypatch):
    _patient(fresh_db, gender=None)  # a clean finding for another rule

    import app.data_quality as dq

    def _boom(_db):
        raise RuntimeError("rule blew up")
        yield  # pragma: no cover

    boom = dq.Rule("boom", _boom, ("boom_finding",))
    monkeypatch.setattr(dq, "RULES", dq.RULES + [boom])
    monkeypatch.setattr(dq, "_FINDING_RULE_TO_KEY", {**dq._FINDING_RULE_TO_KEY, "boom_finding": "boom"})

    res = dq.run_scan(fresh_db, disabled=set())
    assert res.rules_failed and res.rules_failed[0][0] == "boom"
    assert res.new_alerts == 1  # the good rule still ran and committed
    assert fresh_db.query(models.DataQualityAlert).filter_by(rule="patient_missing_gender").count() == 1


def test_anomaly_details_carry_no_raw_dates(fresh_db):
    p = _patient(fresh_db, date_of_birth="1800-01-01")
    _condition(fresh_db, p.id, diagnosed_at="1700-01-01")  # before birth + implausible
    _medication(fresh_db, p.id, start_date="2099-01-01")
    run_scan(fresh_db, disabled=set())
    for a in fresh_db.query(models.DataQualityAlert).filter(models.DataQualityAlert.category == "anomaly").all():
        assert "1800" not in a.detail and "1700" not in a.detail and "2099" not in a.detail, a.detail


def test_registry_emits_map_is_consistent():
    all_case_rules = {c[0] for c in _CASES}
    assert all_case_rules <= set(_FINDING_RULE_TO_KEY), all_case_rules - set(_FINDING_RULE_TO_KEY)
    for r in RULES:
        assert r.emits, r.key
        for fr in r.emits:
            assert _FINDING_RULE_TO_KEY[fr] == r.key
    flat = [fr for r in RULES for fr in r.emits]
    assert len(flat) == len(set(flat))  # no Finding.rule claimed by two config keys


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def test_parse_iso_date():
    assert _parse_iso_date("2020-01-02") == date(2020, 1, 2)
    assert _parse_iso_date("2020-01-02T09:00:00") == date(2020, 1, 2)
    for bad in ("", None, "not-a-date", "2020-13-40", 20200102):
        assert _parse_iso_date(bad) is None


def test_normalize_name():
    assert _normalize_name("  Dr.  Siti   binti  Ali ") == _normalize_name("dr siti binti ali")
    assert _normalize_name(None) == ""


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cli(args, url):
    env = dict(os.environ)
    env["DATABASE_URL"] = url
    env.setdefault("SECRET_KEY", "test-only-secret-key-not-for-any-real-deployment")
    env.setdefault("OTP_HMAC_KEY", "test-only-otp-hmac-key")
    return subprocess.run(
        [sys.executable, "-m"] + args,
        cwd=str(pathlib.Path(models.__file__).resolve().parent.parent),
        env=env, capture_output=True, text=True,
    )


def test_cli_list_rules_and_scan():
    with _throwaway_db("head") as (db, url):
        _patient(db, gender="alien")
        lst = _cli(["db.data_quality_scan", "--list-rules"], url)
        assert lst.returncode == 0 and "coding_patient_gender" in lst.stdout

        run = _cli(["db.data_quality_scan", "--json"], url)
        assert run.returncode == 0, run.stdout + run.stderr
        assert '"findings": 1' in run.stdout


# --------------------------------------------------------------------------
# admin API
# --------------------------------------------------------------------------

_uniq = [0]


def _mk_alert(db, **over):
    _uniq[0] += 1
    kw = dict(
        rule="patient_invalid_gender", category="coding", severity="warning",
        entity_type="patient", entity_id=f"dq-test-{_uniq[0]}", patient_id=None,
        detail="gender not recognised", times_seen=1,
    )
    kw.update(over)
    a = models.DataQualityAlert(**kw)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_admin_data_quality_endpoints(test_client, make_user, auth_headers, db_session):
    admin = make_user(role="admin", facility="Hospital Sejahtera")
    clinician = make_user(role="clinician", facility="Hospital Sejahtera")
    H = auth_headers(admin)

    open_a = _mk_alert(db_session)
    ack_a = _mk_alert(db_session, severity="error")
    created = [open_a.id, ack_a.id]
    try:
        assert test_client.get("/admin/data-quality", headers=auth_headers(clinician)).status_code == 403

        r = test_client.post(f"/admin/data-quality/{ack_a.id}/acknowledge", headers=H)
        assert r.status_code == 200 and r.json()["acknowledged"] is True

        open_ids = {a["id"] for a in test_client.get("/admin/data-quality?status=open", headers=H).json()}
        assert open_a.id in open_ids and ack_a.id not in open_ids

        errs = test_client.get("/admin/data-quality?status=all&severity=error", headers=H).json()
        assert all(a["severity"] == "error" for a in errs) and ack_a.id in {a["id"] for a in errs}

        s = test_client.get("/admin/data-quality/summary", headers=H).json()
        assert set(s) == {"open_total", "acknowledged", "by_category", "by_severity"}

        r = test_client.post(f"/admin/data-quality/{open_a.id}/resolve", headers=H)
        assert r.status_code == 200 and r.json()["resolved"] is True

        assert test_client.post("/admin/data-quality/nope/resolve", headers=H).status_code == 404
        assert test_client.get("/admin/data-quality?status=weird", headers=H).status_code == 400
    finally:
        for aid in created:
            row = db_session.query(models.DataQualityAlert).filter_by(id=aid).first()
            if row is not None:
                db_session.delete(row)
        db_session.commit()


def test_admin_list_is_facility_scoped_with_break_glass(test_client, make_user, auth_headers, db_session):
    admin_a = make_user(role="admin", facility="Facility A")
    H = auth_headers(admin_a)

    # a patient whose only relationship is to Facility B
    pb = models.Patient(full_name="Faridah B", date_of_birth="1970-01-01")
    db_session.add(pb)
    db_session.flush()
    enc = models.Encounter(patient_id=pb.id, facility_name="Facility B", encounter_type="outpatient")
    db_session.add(enc)
    other_facility_alert = _mk_alert(db_session, entity_id=pb.id, patient_id=pb.id,
                                     rule="patient_missing_blood_type", category="missing")
    dup_alert = _mk_alert(db_session, entity_id=pb.id, patient_id=pb.id,
                          rule="patient_probable_duplicate", category="duplicate")
    cleanup = [other_facility_alert.id, dup_alert.id, enc.id, pb.id]
    try:
        scoped = {a["id"] for a in test_client.get("/admin/data-quality?status=all", headers=H).json()}
        assert other_facility_alert.id not in scoped   # B's patient, A can't see it
        assert dup_alert.id in scoped                  # probable-duplicate is cross-facility by design

        allf = {a["id"] for a in test_client.get(
            "/admin/data-quality?status=all&break_glass_reason=merge+review", headers=H).json()}
        assert other_facility_alert.id in allf and dup_alert.id in allf
    finally:
        for aid in cleanup:
            for m in (models.DataQualityAlert, models.Encounter):
                row = db_session.query(m).filter_by(id=aid).first()
                if row is not None:
                    db_session.delete(row)
        db_session.commit()
        drop_patient(db_session, pb.id)


def test_admin_acknowledge_resolve_is_facility_scoped(test_client, make_user, auth_headers, db_session):
    """Security Audit L6: acknowledge/resolve used to look up by id alone,
    letting a facility-scoped admin mutate another facility's alert. Same
    fix (and same 404-not-403 shape) as P4.5's security-alerts review."""
    admin_a = make_user(role="admin", facility="Facility A")
    H = auth_headers(admin_a)

    pb = models.Patient(full_name="Zainal B", date_of_birth="1975-01-01")
    db_session.add(pb)
    db_session.flush()
    enc = models.Encounter(patient_id=pb.id, facility_name="Facility B", encounter_type="outpatient")
    db_session.add(enc)
    other_facility_alert = _mk_alert(db_session, entity_id=pb.id, patient_id=pb.id,
                                     rule="patient_missing_blood_type", category="missing")
    dup_alert = _mk_alert(db_session, entity_id=pb.id, patient_id=pb.id,
                          rule="patient_probable_duplicate", category="duplicate")
    cleanup = [other_facility_alert.id, dup_alert.id, enc.id, pb.id]
    try:
        # Facility A's admin can't touch Facility B's alert -- 404, not 403,
        # so the response doesn't confirm the id even exists.
        r = test_client.post(f"/admin/data-quality/{other_facility_alert.id}/acknowledge", headers=H)
        assert r.status_code == 404
        r = test_client.post(f"/admin/data-quality/{other_facility_alert.id}/resolve", headers=H)
        assert r.status_code == 404
        assert db_session.get(models.DataQualityAlert, other_facility_alert.id).acknowledged is False

        # ...but a cross-facility rule (probable-duplicate) is reviewable by design.
        r = test_client.post(f"/admin/data-quality/{dup_alert.id}/acknowledge", headers=H)
        assert r.status_code == 200 and r.json()["acknowledged"] is True
    finally:
        for aid in cleanup:
            for m in (models.DataQualityAlert, models.Encounter):
                row = db_session.query(m).filter_by(id=aid).first()
                if row is not None:
                    db_session.delete(row)
        db_session.commit()
        drop_patient(db_session, pb.id)
