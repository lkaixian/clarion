"""Online booking v2 (routers/booking.py): slot engine, limits, capacity,
profiles, facility discovery and the per-facility admin timetable.

Every test builds its own facility (unique name) because the test DB is
shared for the whole session. Dates are relative to "now" in Kuala Lumpur,
so nothing here depends on the day the suite runs.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import models
from conftest import _facility, _make_patient

KL = ZoneInfo("Asia/Kuala_Lumpur")


# ---------------------------------------------------------------- helpers

def _day(n: int, tz=KL) -> date:
    return (datetime.now(tz) + timedelta(days=n)).date()


def _week(*ranges, weekdays=range(7)):
    return [{"weekday": wd, "start": a, "end": b} for wd in weekdays for a, b in ranges]


def _svc(category="general", hours=None, **kw):
    body = {"category": category, "active": True, "slot_minutes": 30, "capacity": 2,
            "advance_days": 14, "min_notice_minutes": 60,
            "hours": hours if hours is not None else _week(("09:00", "12:00"), ("14:00", "17:00"))}
    body.update(kw)
    return body


class Env:
    """One hospital + its admin, created through the real admin PUT."""

    def __init__(self, client, db, make_user, auth_headers, services=None, enabled=True,
                 lat=None, lng=None, display=None, address=None, tz=None, label="Booking"):
        self.client, self.db, self.make_user, self.auth_headers = client, db, make_user, auth_headers
        self.facility = _facility(label)
        db.add(models.HospitalSetting(
            facility_name=self.facility, display_name=display or f"{self.facility} Clinic",
            address=address, contact_phone="03-1234 5678", **({"timezone": tz} if tz else {}),
        ))
        db.commit()
        self.admin = make_user(role="admin", facility=self.facility)
        self.admin_h = auth_headers(self.admin)
        r = client.put("/booking/admin/settings", headers=self.admin_h, json={
            "online_booking_enabled": enabled, "latitude": lat, "longitude": lng,
            "services": services if services is not None else [_svc()],
        })
        assert r.status_code == 200, r.text

    def patient(self):
        p = _make_patient(self.db)
        u = self.make_user(role="patient", patient_id=p.id)
        u.pid = p.id
        return u, self.auth_headers(u)

    def slots(self, headers, d, category="general"):
        r = self.client.get(f"/booking/facilities/{self.facility}/slots",
                            params={"category": category, "date": d.isoformat()}, headers=headers)
        assert r.status_code == 200, r.text
        return r.json()["slots"]

    def book(self, headers, start, category="general", **extra):
        return self.client.post("/booking/appointments", headers=headers, json={
            "facility_name": self.facility, "category": category, "scheduled_at": start, **extra})


def _env(test_client, db_session, make_user, auth_headers, **kw):
    return Env(test_client, db_session, make_user, auth_headers, **kw)


# ------------------------------------------------------------ categories

def test_categories(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers)
    u, h = e.patient()
    r = test_client.get("/booking/categories", headers=h)
    assert r.status_code == 200
    assert len(r.json()) == 8
    assert {"code": "general", "label": "General consultation"} in r.json()
    assert test_client.get("/booking/categories").status_code == 401


# ------------------------------------------------------- slot generation

def test_slots_lunch_break_and_slot_length(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers, services=[
        _svc("general"),                                                  # 30 min, lunch break
        _svc("dental", _week(("09:00", "12:00")), slot_minutes=45, capacity=1),
        _svc("physio", _week(("09:00", "10:10")), slot_minutes=30),      # 10:00-10:30 would overrun 10:10
    ])
    _, h = e.patient()
    d = _day(2)

    general = e.slots(h, d)
    starts = [s["start"][11:16] for s in general]
    assert starts == ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
                      "14:00", "14:30", "15:00", "15:30", "16:00", "16:30"]
    assert all(s["remaining"] == 2 for s in general)
    assert general[0]["end"][11:16] == "09:30" and general[5]["end"][11:16] == "12:00"
    assert not any(s["start"][11:16] in ("12:00", "12:30", "13:00", "13:30") for s in general)

    dental = e.slots(h, d, "dental")
    assert [s["start"][11:16] for s in dental] == ["09:00", "09:45", "10:30", "11:15"]
    assert dental[-1]["end"][11:16] == "12:00"
    assert all(s["remaining"] == 1 for s in dental)

    assert [s["start"][11:16] for s in e.slots(h, d, "physio")] == ["09:00", "09:30"]


def test_weekday_specific_hours(test_client, make_user, auth_headers, db_session):
    d = _day(3)
    other = (d.weekday() + 1) % 7
    e = _env(test_client, db_session, make_user, auth_headers,
             services=[_svc(hours=_week(("09:00", "10:00"), weekdays=[d.weekday()]))])
    _, h = e.patient()
    assert len(e.slots(h, d)) == 2
    next_other = d + timedelta(days=(other - d.weekday()) % 7 or 7)
    assert e.slots(h, next_other) == []


def test_availability_counts_and_clamps_to_advance_days(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers, services=[_svc(advance_days=7)])
    _, h = e.patient()
    r = test_client.get(f"/booking/facilities/{e.facility}/availability",
                        params={"category": "general", "days": 30}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert (body["slot_minutes"], body["capacity"], body["category"]) == (30, 2, "general")
    assert len(body["days"]) == 7                       # clamped from 30
    assert body["days"][0]["date"] == _day(0).isoformat()
    assert all(x["open_slots"] > 0 for x in body["days"][1:])
    assert [x["open_slots"] for x in body["days"][1:]] == [12] * 6

    # a full slot stops counting as open
    d = _day(2)
    s = e.slots(h, d)[0]
    for _ in range(2):
        u, uh = e.patient()
        assert e.book(uh, s["start"]).status_code == 200
    again = test_client.get(f"/booking/facilities/{e.facility}/availability",
                            params={"category": "general", "days": 7}, headers=h).json()
    assert [x for x in again["days"] if x["date"] == d.isoformat()][0]["open_slots"] == 11


# ---------------------------------------------------- min notice / advance

def test_min_notice_hides_near_slots(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers,
             services=[_svc(min_notice_minutes=7 * 24 * 60, advance_days=30)])
    _, h = e.patient()
    assert e.slots(h, _day(3)) == []                    # inside the 7-day notice window
    assert len(e.slots(h, _day(9))) == 12               # outside it
    # and it is enforced on booking too, not just hidden
    near = datetime.combine(_day(3), datetime.min.time(), KL).replace(hour=9)
    assert e.book(h, near.isoformat()).status_code == 409


def test_min_notice_applies_to_today(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers, services=[
        _svc(hours=_week(("00:00", "23:30")), min_notice_minutes=180, slot_minutes=30)])
    _, h = e.patient()
    now = datetime.now(timezone.utc)
    for s in e.slots(h, _day(0)):
        assert datetime.fromisoformat(s["start"]) >= now + timedelta(minutes=179)


def test_advance_days_limit(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers, services=[_svc(advance_days=2)])
    _, h = e.patient()
    assert len(e.slots(h, _day(1))) > 0
    assert e.slots(h, _day(5)) == []
    far = datetime.combine(_day(5), datetime.min.time(), KL).replace(hour=9)
    assert e.book(h, far.isoformat()).status_code == 409


# ------------------------------------------------------------- capacity

def test_capacity_third_booking_conflicts_and_cancel_frees(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers)
    d = _day(2)
    start = e.slots(e.patient()[1], d)[0]["start"]
    (_, h1), (_, h2), (_, h3) = e.patient(), e.patient(), e.patient()

    r1 = e.book(h1, start)
    assert r1.status_code == 200, r1.text
    assert [s for s in e.slots(h3, d) if s["start"] == start][0]["remaining"] == 1
    r2 = e.book(h2, start)
    assert r2.status_code == 200
    assert [s for s in e.slots(h3, d) if s["start"] == start][0]["remaining"] == 0

    r3 = e.book(h3, start)
    assert r3.status_code == 409

    # the neighbouring slot is independent
    assert e.book(h3, e.slots(h3, d)[1]["start"]).status_code == 200

    # cancelling frees the place
    assert test_client.post(f"/booking/appointments/{r1.json()['id']}/cancel", headers=h1).status_code == 200
    assert e.book(h3, start).status_code == 200


def test_capacity_is_per_category(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers, services=[
        _svc("general", capacity=1), _svc("dental", capacity=1)])
    d = _day(2)
    (_, h1), (_, h2) = e.patient(), e.patient()
    start = e.slots(h1, d)[0]["start"]
    assert e.book(h1, start, "general").status_code == 200
    assert e.book(h2, start, "general").status_code == 409
    assert e.book(h2, start, "dental").status_code == 200


def test_booked_appointment_fields(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers)
    u, h = e.patient()
    start = e.slots(h, _day(2))[0]["start"]
    r = e.book(h, start, reason="Cough for a week")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["self_booked"] is True and b["status"] == "scheduled"
    assert b["booking_category"] == "general"
    assert b["reason"] == "Cough for a week"
    assert b["department"] is None and b["clinician_id"] is None
    assert b["patient_id"] == u.pid and b["created_by"] == u.id
    assert b["facility_name"] == e.facility
    assert b["display_name"] == b["facility_display_name"] == f"{e.facility} Clinic"
    assert b["attendee_name"] is None
    # default reason is the category label
    b2 = e.book(h, e.slots(h, _day(2))[1]["start"]).json()
    assert b2["reason"] == "General consultation"


# ------------------------------------------------- profiles and snapshot

def test_profile_booking_snapshots_attendee(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers)
    u, h = e.patient()
    pr = test_client.post("/booking/profiles", headers=h, json={
        "full_name": "Aiman Hakim", "relationship": "child", "date_of_birth": "2019-03-04",
        "national_id": "190304-01-1234", "gender": "male"})
    assert pr.status_code == 201, pr.text
    pid = pr.json()["id"]

    r = e.book(h, e.slots(h, _day(2))[0]["start"], profile_id=pid)
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["attendee_name"], b["attendee_relationship"], b["attendee_dob"]) == ("Aiman Hakim", "child", "2019-03-04")
    # the booking row belongs to the account's own patient record
    assert b["patient_id"] == u.pid

    # snapshot survives profile edit and delete
    assert test_client.patch(f"/booking/profiles/{pid}", headers=h, json={"full_name": "Changed"}).status_code == 200
    listed = test_client.get(f"/patients/{u.pid}/appointments", headers=h).json()
    row = [a for a in listed if a["id"] == b["id"]][0]
    assert row["attendee_name"] == "Aiman Hakim"
    assert row["booking_category"] == "general" and row["attendee_relationship"] == "child"

    assert test_client.delete(f"/booking/profiles/{pid}", headers=h).status_code == 204
    row = [a for a in test_client.get(f"/patients/{u.pid}/appointments", headers=h).json() if a["id"] == b["id"]][0]
    assert row["attendee_name"] == "Aiman Hakim"
    assert test_client.get("/booking/profiles", headers=h).json() == []
    stored = db_session.query(models.Appointment).filter_by(id=b["id"]).first()
    db_session.refresh(stored)
    assert stored.booked_for_profile_id is None


def test_profile_ownership(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers)
    (_, ha), (_, hb) = e.patient(), e.patient()
    pid = test_client.post("/booking/profiles", headers=ha, json={
        "full_name": "Mum", "relationship": "parent", "national_id": "600101-14-0000"}).json()["id"]

    assert test_client.get("/booking/profiles", headers=hb).json() == []
    assert test_client.patch(f"/booking/profiles/{pid}", headers=hb, json={"full_name": "x"}).status_code == 404
    assert test_client.delete(f"/booking/profiles/{pid}", headers=hb).status_code == 404
    # the owner's copy is untouched
    mine = test_client.get("/booking/profiles", headers=ha).json()
    assert [p["full_name"] for p in mine] == ["Mum"] and mine[0]["national_id"] == "600101-14-0000"
    # and it cannot be used to book
    r = e.book(hb, e.slots(hb, _day(2))[0]["start"], profile_id=pid)
    assert r.status_code == 404


def test_profile_validation_and_limit(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers)
    _, h = e.patient()
    post = lambda body: test_client.post("/booking/profiles", headers=h, json=body)  # noqa: E731
    assert post({"full_name": "A", "relationship": "cousin"}).status_code == 422
    assert post({"full_name": "  ", "relationship": "child"}).status_code == 422
    future = (date.today() + timedelta(days=5)).isoformat()
    assert post({"full_name": "A", "relationship": "child", "date_of_birth": future}).status_code == 422
    for i in range(10):
        assert post({"full_name": f"P{i}", "relationship": "other"}).status_code == 201
    assert post({"full_name": "P11", "relationship": "other"}).status_code == 409


# ------------------------------------------- enablement / visibility

def test_disabled_facility_invisible_and_unbookable(test_client, make_user, auth_headers, db_session):
    tok = uuid.uuid4().hex[:10]
    e = _env(test_client, db_session, make_user, auth_headers, enabled=False, display=f"Zeta {tok}")
    _, h = e.patient()
    names = lambda: [f["facility_name"] for f in test_client.get(  # noqa: E731
        "/booking/facilities", params={"category": "general", "q": tok}, headers=h).json()]
    assert names() == []
    for path in ("slots", "availability"):
        r = test_client.get(f"/booking/facilities/{e.facility}/{path}",
                            params={"category": "general", "date": _day(2).isoformat()}, headers=h)
        assert r.status_code == 404
    start = datetime.combine(_day(2), datetime.min.time(), KL).replace(hour=9).isoformat()
    assert e.book(h, start).status_code == 404

    # turning it on makes it appear and bookable
    body = test_client.get("/booking/admin/settings", headers=e.admin_h).json()
    body["online_booking_enabled"] = True
    assert test_client.put("/booking/admin/settings", headers=e.admin_h, json=body).status_code == 200
    assert names() == [e.facility]
    assert e.book(h, e.slots(h, _day(2))[0]["start"]).status_code == 200


def test_inactive_category_not_listed_or_bookable(test_client, make_user, auth_headers, db_session):
    tok = uuid.uuid4().hex[:10]
    e = _env(test_client, db_session, make_user, auth_headers, display=f"Kappa {tok}",
             services=[_svc("general"), _svc("dental", active=False)])
    _, h = e.patient()
    q = lambda c: [f["facility_name"] for f in test_client.get(  # noqa: E731
        "/booking/facilities", params={"category": c, "q": tok}, headers=h).json()]
    assert q("general") == [e.facility]
    assert q("dental") == []
    assert q("vaccination") == []
    r = test_client.get(f"/booking/facilities/{e.facility}/slots",
                        params={"category": "dental", "date": _day(2).isoformat()}, headers=h)
    assert r.status_code == 404
    assert test_client.get("/booking/facilities", params={"category": "nope"}, headers=h).status_code == 400


# -------------------------------------------------- discovery / ordering

def test_nearest_first_and_text_search(test_client, make_user, auth_headers, db_session):
    tok = uuid.uuid4().hex[:10]
    kl = _env(test_client, db_session, make_user, auth_headers, lat=3.139, lng=101.687,
              display=f"Klinik Bandar {tok}", address="Jalan Ampang, Kuala Lumpur", label="N")
    seremban = _env(test_client, db_session, make_user, auth_headers, lat=2.7258, lng=101.9378,
                    display=f"Klinik Seremban {tok}", address="Jalan Dato Bandar Tunggal, Seremban", label="N")
    jb = _env(test_client, db_session, make_user, auth_headers, lat=1.4927, lng=103.7414,
              display=f"Klinik Johor {tok}", address="Jalan Wong Ah Fook, Johor Bahru", label="N")
    nocoord = _env(test_client, db_session, make_user, auth_headers,
                   display=f"Klinik Tanpa {tok}", address="Alamat tidak diketahui", label="N")
    # a different category only: must not show for "general"
    other = _env(test_client, db_session, make_user, auth_headers, display=f"Klinik Gigi {tok}",
                 lat=3.14, lng=101.69, services=[_svc("dental")], label="N")
    _, h = kl.patient()
    get = lambda **p: test_client.get("/booking/facilities", headers=h, params={  # noqa: E731
        "category": "general", "q": tok, **p})

    # from Putrajaya-ish coordinates: KL < Seremban < JB, no-coordinate last
    r = get(lat=2.9264, lng=101.6964)
    assert r.status_code == 200
    got = r.json()
    assert [f["facility_name"] for f in got] == [kl.facility, seremban.facility, jb.facility, nocoord.facility]
    d = [f["distance_km"] for f in got]
    assert d[3] is None and d[0] < d[1] < d[2]
    assert 20 < d[0] < 30 and 30 < d[1] < 40 and 260 < d[2] < 295

    # known great-circle distance: KL to JB is about 293 km
    far = get(lat=3.139, lng=101.687).json()
    jb_row = [f for f in far if f["facility_name"] == jb.facility][0]
    assert 288 < jb_row["distance_km"] < 297

    # from Johor the order flips
    near_jb = [f["facility_name"] for f in get(lat=1.5, lng=103.7).json()]
    assert near_jb[:3] == [jb.facility, seremban.facility, kl.facility]

    # no coordinates: alphabetical by display name, distance is null
    plain = get().json()
    assert [f["display_name"] for f in plain] == sorted(f["display_name"] for f in plain)
    assert all(f["distance_km"] is None for f in plain) and len(plain) == 4

    # text search: words ANDed, case-insensitive, matches address too
    assert [f["facility_name"] for f in get(q=f"{tok} SEREMBAN").json()] == [seremban.facility]
    assert [f["facility_name"] for f in get(q=f"{tok} wong johor").json()] == [jb.facility]
    assert get(q=f"{tok} seremban johor").json() == []
    assert [f["facility_name"] for f in get(q=f"{tok} tunggal").json()] == [seremban.facility]
    # facility_name is searchable too
    assert [f["facility_name"] for f in get(q=kl.facility.lower()).json()] == [kl.facility]
    assert other.facility not in [f["facility_name"] for f in plain]

    assert len(get(limit=2).json()) == 2
    assert get(lat=2.0).status_code == 422             # lat without lng
    assert get(lat=95, lng=0).status_code == 422
    row = got[0]
    assert set(row) == {"facility_name", "display_name", "address", "contact_phone", "latitude",
                        "longitude", "distance_km", "next_available_at"}


def test_next_available_at(test_client, make_user, auth_headers, db_session):
    tok = uuid.uuid4().hex[:10]
    e = _env(test_client, db_session, make_user, auth_headers, display=f"Omega {tok}",
             services=[_svc(min_notice_minutes=0)])
    _, h = e.patient()
    row = test_client.get("/booking/facilities", headers=h,
                          params={"category": "general", "q": tok}).json()[0]
    assert row["next_available_at"].endswith("+08:00")
    first = datetime.fromisoformat(row["next_available_at"])
    assert first > datetime.now(timezone.utc)
    # nothing bookable -> null
    e2 = _env(test_client, db_session, make_user, auth_headers, display=f"Omega {tok} two",
              services=[_svc(hours=[])])
    rows = test_client.get("/booking/facilities", headers=h, params={"category": "general", "q": f"{tok} two"}).json()
    assert rows[0]["facility_name"] == e2.facility and rows[0]["next_available_at"] is None


# ------------------------------------------------------------ timezone

def test_slots_carry_offset_and_facility_timezone(test_client, make_user, auth_headers, db_session):
    kl = _env(test_client, db_session, make_user, auth_headers)
    jakarta = _env(test_client, db_session, make_user, auth_headers, tz="Asia/Jakarta")
    _, h = kl.patient()
    d = _day(2)

    s = kl.slots(h, d)
    assert all(x["start"].endswith("+08:00") and x["end"].endswith("+08:00") for x in s)
    assert s[0]["start"] == f"{d.isoformat()}T09:00:00+08:00"

    j = jakarta.slots(h, d)
    assert j[0]["start"] == f"{d.isoformat()}T09:00:00+07:00"      # same wall clock, facility's own offset
    assert datetime.fromisoformat(j[0]["start"]) > datetime.fromisoformat(s[0]["start"])

    # a client may send the same instant in UTC and it still matches the slot
    utc = datetime.fromisoformat(s[0]["start"]).astimezone(timezone.utc)
    r = kl.book(h, utc.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert r.status_code == 200, r.text
    got = datetime.fromisoformat(r.json()["scheduled_at"].replace("Z", "+00:00"))
    assert got.tzinfo is not None and got == utc               # never a naive datetime
    assert datetime.fromisoformat(r.json()["created_at"].replace("Z", "+00:00")).tzinfo is not None

    # naive timestamps are refused, an off-grid time is a conflict
    assert kl.book(h, f"{d.isoformat()}T10:00:00").status_code == 422
    assert kl.book(h, f"{d.isoformat()}T10:07:00+08:00").status_code == 409


# ---------------------------------------------------------- who can book

def test_only_linked_patient_can_book(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers)
    _, ph = e.patient()
    start = e.slots(ph, _day(2))[0]["start"]
    clin = make_user(role="clinician", facility=e.facility)
    r = e.book(auth_headers(clin), start)
    assert r.status_code == 403 and "patient" in r.json()["detail"].lower()
    unlinked = make_user(role="patient")
    assert e.book(auth_headers(unlinked), start).status_code == 403
    assert test_client.post("/booking/appointments", json={}).status_code == 401


def test_booking_rate_limit_is_per_user(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers, services=[_svc(capacity=50)])
    (_, h1), (_, h2) = e.patient(), e.patient()
    start = e.slots(h1, _day(2))[0]["start"]
    codes = [e.book(h1, start).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429
    assert e.book(h2, start).status_code == 200          # another account is not throttled


# --------------------------------------------------------------- cancel

def test_cancel_only_booker_and_only_future(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers)
    (u, h), (_, other) = e.patient(), e.patient()
    appt = e.book(h, e.slots(h, _day(2))[0]["start"]).json()

    assert test_client.post(f"/booking/appointments/{appt['id']}/cancel", headers=other).status_code == 404
    clinician = make_user(role="clinician", facility=e.facility)
    assert test_client.post(f"/booking/appointments/{appt['id']}/cancel",
                            headers=auth_headers(clinician)).status_code == 404

    r = test_client.post(f"/booking/appointments/{appt['id']}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert r.json()["booking_category"] == "general"
    assert test_client.post(f"/booking/appointments/{appt['id']}/cancel", headers=h).status_code == 409

    # an appointment already in the past
    past = models.Appointment(
        patient_id=u.pid, facility_name=e.facility, scheduled_at=datetime.now(timezone.utc) - timedelta(hours=2),
        status="scheduled", created_by=u.id, self_booked=True, booking_category="general")
    db_session.add(past)
    db_session.commit()
    assert test_client.post(f"/booking/appointments/{past.id}/cancel", headers=h).status_code == 409

    # a staff-published appointment is not an online booking, even for its own patient
    staff = models.Appointment(
        patient_id=u.pid, facility_name=e.facility, scheduled_at=datetime.now(timezone.utc) + timedelta(days=3),
        status="scheduled", created_by=u.id)
    db_session.add(staff)
    db_session.commit()
    assert test_client.post(f"/booking/appointments/{staff.id}/cancel", headers=h).status_code == 404

    assert test_client.post("/booking/appointments/does-not-exist/cancel", headers=h).status_code == 404


# ----------------------------------------------------------- admin side

def test_admin_get_lists_all_categories_with_defaults(test_client, make_user, auth_headers, db_session):
    f = _facility("Fresh")
    admin = make_user(role="admin", facility=f)
    r = test_client.get("/booking/admin/settings", headers=auth_headers(admin))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["facility_name"] == f and b["online_booking_enabled"] is False
    assert b["latitude"] is None and b["longitude"] is None
    assert [s["category"] for s in b["services"]] == [
        "general", "chronic", "vaccination", "maternal_child", "dental", "screening", "mental_health", "physio"]
    s = b["services"][0]
    assert s == {"category": "general", "label": "General consultation", "active": False, "slot_minutes": 30,
                 "capacity": 1, "advance_days": 14, "min_notice_minutes": 60, "hours": []}


def test_admin_put_round_trip(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers, lat=3.5, lng=101.5, services=[
        _svc("vaccination", [{"weekday": 1, "start": "14:00", "end": "17:00"},
                             {"weekday": 1, "start": "08:30", "end": "12:00"}],
             slot_minutes=15, capacity=5, advance_days=30, min_notice_minutes=0)])
    b = test_client.get("/booking/admin/settings", headers=e.admin_h).json()
    assert b["online_booking_enabled"] is True and (b["latitude"], b["longitude"]) == (3.5, 101.5)
    assert b["display_name"] == f"{e.facility} Clinic"
    v = [s for s in b["services"] if s["category"] == "vaccination"][0]
    assert v["active"] and (v["slot_minutes"], v["capacity"], v["advance_days"], v["min_notice_minutes"]) == (15, 5, 30, 0)
    assert v["hours"] == [{"weekday": 1, "start": "08:30", "end": "12:00"},
                          {"weekday": 1, "start": "14:00", "end": "17:00"}]
    assert [s for s in b["services"] if s["category"] == "general"][0]["active"] is False

    # replace: the previous timetable is gone, "24:00" is a valid end
    b["services"] = [_svc("general", [{"weekday": 0, "start": "22:00", "end": "24:00"}], slot_minutes=60)]
    r = test_client.put("/booking/admin/settings", headers=e.admin_h, json=b)
    assert r.status_code == 200, r.text
    again = r.json()
    assert [s for s in again["services"] if s["category"] == "vaccination"][0]["hours"] == []
    assert [s for s in again["services"] if s["category"] == "general"][0]["hours"] == [
        {"weekday": 0, "start": "22:00", "end": "24:00"}]
    assert db_session.query(models.BookingService).filter_by(facility_name=e.facility).count() == 1


def test_admin_put_validation(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers)
    before = test_client.get("/booking/admin/settings", headers=e.admin_h).json()

    def put(**over):
        body = {"online_booking_enabled": True, "latitude": 3.0, "longitude": 101.0, "services": [_svc()]}
        body.update(over)
        return test_client.put("/booking/admin/settings", headers=e.admin_h, json=body)

    def hours(*ranges, wd=0, **kw):
        return [_svc(hours=[{"weekday": wd, "start": a, "end": b} for a, b in ranges], **kw)]

    bad = {
        "overlap": put(services=hours(("09:00", "12:00"), ("11:30", "15:00"))),
        "identical": put(services=hours(("09:00", "12:00"), ("09:00", "12:00"))),
        "end == start": put(services=hours(("09:00", "09:00"))),
        "end < start": put(services=hours(("12:00", "09:00"))),
        "shorter than a slot": put(services=hours(("09:00", "09:20"))),
        "bad time": put(services=hours(("09:00", "25:00"))),
        "bad minute": put(services=hours(("09:60", "12:00"))),
        "bad weekday": put(services=hours(("09:00", "12:00"), wd=7)),
        "lat high": put(latitude=90.5),
        "lat low": put(latitude=-91),
        "lng high": put(longitude=180.1),
        "lng low": put(longitude=-181),
        "lat only": put(latitude=3.0, longitude=None),
        "unknown category": put(services=[_svc("cardiology")]),
        "duplicate category": put(services=[_svc("general"), _svc("general")]),
        "slot too small": put(services=[_svc(slot_minutes=4)]),
        "slot too big": put(services=[_svc(slot_minutes=241)]),
        "capacity 0": put(services=[_svc(capacity=0)]),
        "capacity 51": put(services=[_svc(capacity=51)]),
        "advance 0": put(services=[_svc(advance_days=0)]),
        "advance 91": put(services=[_svc(advance_days=91)]),
        "notice negative": put(services=[_svc(min_notice_minutes=-1)]),
        "notice too big": put(services=[_svc(min_notice_minutes=10081)]),
    }
    for name, r in bad.items():
        assert r.status_code == 422, (name, r.status_code, r.text)
    # touching ranges and the same range on different weekdays are fine
    assert put(services=hours(("09:00", "12:00"), ("12:00", "15:00"))).status_code == 200
    assert put(services=[_svc(hours=_week(("09:00", "12:00")))]).status_code == 200

    # none of the rejected bodies changed anything
    assert before["services"][0]["hours"] != []
    put(services=[_svc()])
    assert test_client.get("/booking/admin/settings", headers=e.admin_h).json()["services"] == before["services"]


def test_admin_cannot_touch_another_facility(test_client, make_user, auth_headers, db_session):
    a = _env(test_client, db_session, make_user, auth_headers, label="FacA")
    b = _env(test_client, db_session, make_user, auth_headers, label="FacB", services=[
        _svc("dental", _week(("10:00", "11:00")), capacity=3)])

    # admin A names facility B in the body and in extra fields: ignored, only A changes
    body = test_client.get("/booking/admin/settings", headers=a.admin_h).json()
    body["facility_name"] = b.facility
    body["online_booking_enabled"] = False
    body["services"] = [_svc("physio", capacity=9)]
    r = test_client.put("/booking/admin/settings", headers=a.admin_h, json=body)
    assert r.status_code == 200 and r.json()["facility_name"] == a.facility

    bset = test_client.get("/booking/admin/settings", headers=b.admin_h).json()
    assert bset["facility_name"] == b.facility and bset["online_booking_enabled"] is True
    dental = [s for s in bset["services"] if s["category"] == "dental"][0]
    assert dental["active"] and dental["capacity"] == 3
    assert [s for s in bset["services"] if s["category"] == "physio"][0]["active"] is False

    # staff of other roles and patients have no access
    _, ph = a.patient()
    assert test_client.get("/booking/admin/settings", headers=ph).status_code == 403
    assert test_client.put("/booking/admin/settings", headers=ph, json=body).status_code == 403
    clin = make_user(role="clinician", facility=a.facility)
    assert test_client.put("/booking/admin/settings", headers=auth_headers(clin), json=body).status_code == 403
    nofac = make_user(role="admin")
    assert test_client.get("/booking/admin/settings", headers=auth_headers(nofac)).status_code == 403
    assert test_client.get("/booking/admin/settings").status_code == 401


def test_admin_put_is_audit_logged(test_client, make_user, auth_headers, db_session):
    e = _env(test_client, db_session, make_user, auth_headers)
    row = (db_session.query(models.AuditLog)
           .filter(models.AuditLog.action == "update_booking_settings",
                   models.AuditLog.actor == e.admin.id).first())
    assert row is not None and row.actor_facility == e.facility
