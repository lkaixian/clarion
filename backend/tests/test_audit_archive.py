from datetime import datetime, timedelta, timezone

from app import audit, models
from app.audit_archive import archive_day, verify_archived_day
from app.storage import LocalObjectStore
from conftest import _make_patient


def test_archive_roundtrip_and_tamper(db_session, tmp_path):
    store = LocalObjectStore(str(tmp_path))
    p = _make_patient(db_session)
    for i in range(3):
        audit.log_access(db_session, p.id, "u1", "clinician", f"view_{i}")
    day = datetime.now(timezone.utc).date()
    man = archive_day(db_session, day, store)
    assert man["row_count"] >= 3
    assert verify_archived_day(day, store) == (True, "ok")
    assert archive_day(db_session, day, store) == man  # idempotent
    # corrupt the stored object -> checksum/verify fails
    obj = tmp_path / "clarion-reports-archive" / man["object_key"]
    obj.write_bytes(obj.read_bytes()[:-5] + b"xxxxx")
    assert verify_archived_day(day, store)[0] is False


def test_audit_log_days_window(test_client, db_session, make_user, auth_headers, monkeypatch):
    staff = make_user("admin")
    p = _make_patient(db_session)
    audit.log_access(db_session, p.id, staff.id, "admin", "view_record")
    h = auth_headers(staff)
    url = f"/patients/{p.id}/audit-log"
    assert len(test_client.get(url + "?days=7", headers=h).json()) >= 1

    class _Later(datetime):  # pretend 30 days have passed
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) + timedelta(days=30)

    monkeypatch.setattr("app.routers.patients.datetime", _Later)
    assert test_client.get(url + "?days=7", headers=h).json() == []
    assert len(test_client.get(url + "?days=60", headers=h).json()) >= 1
