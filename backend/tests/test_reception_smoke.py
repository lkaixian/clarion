"""Post-split smoke coverage for the reception router.

`app/routers/reception.py` (one 1456-line APIRouter) was split into the
`app/routers/reception/` package (`checkin` / `queue` / `stations` / `rooms`
/ `admissions` sub-routers combined in `__init__.py`). The split was
verified body-identical, but the repo had NO test exercising any
`/reception/*` endpoint through HTTP -- so a broken mount / lost auth gate
would not have been caught by the suite. This closes that: one live request
per sub-router, checking the route is mounted (not 404) and still behind
`require_page_access("reception")` + its own `require_roles`.
"""

from app import models


def _patient(db_session, **kw):
    p = models.Patient(
        full_name=kw.pop("full_name", "Reception Smoke"),
        date_of_birth=kw.pop("date_of_birth", "1980-02-02"),
        **kw,
    )
    db_session.add(p)
    db_session.commit()
    db_session.refresh(p)
    return p


def test_reception_page_gate_blocks_pharmacist(test_client, make_user, auth_headers):
    """require_page_access("reception") (mounted on the parent router in
    main.py) must still cover every sub-router -- a pharmacist's default
    page set is ["pharmacy"]."""
    pharmacist = make_user(role="pharmacist", facility="Main Hospital")
    for method, path in [
        ("get", "/reception/queue"),
        ("get", "/reception/admissions"),
        ("get", "/reception/ward-map"),
        ("get", "/reception/station"),
        ("get", "/reception/my-room"),
    ]:
        resp = getattr(test_client, method)(path, headers=auth_headers(pharmacist))
        assert resp.status_code == 403, f"{path} -> {resp.status_code}"


def test_checkin_then_queue_board(test_client, db_session, make_user, auth_headers):
    """checkin.py + queue.py: a receptionist checks a walk-in in by
    patient_id and the ticket shows on the queue board."""
    receptionist = make_user(role="receptionist", facility="Smoke Clinic")
    patient = _patient(db_session)

    checkin = test_client.post(
        "/reception/checkin",
        headers=auth_headers(receptionist),
        json={"patient_id": patient.id},
    )
    assert checkin.status_code == 200, checkin.text
    queue_number = checkin.json()["ticket"]["queue_number"]

    board = test_client.get("/reception/queue", headers=auth_headers(receptionist))
    assert board.status_code == 200, board.text
    numbers = [t["queue_number"] for t in board.json()["tickets"]]
    assert queue_number in numbers


def test_admissions_create_and_list(test_client, db_session, make_user, auth_headers):
    """admissions.py: create an admission into a ward, then see it listed."""
    staff = make_user(role="records_officer", facility="Smoke Clinic")
    patient = _patient(db_session, full_name="Admit Smoke")
    ward = models.Ward(facility_name="Smoke Clinic", ward_name="Ward S", total_beds=4)
    db_session.add(ward)
    db_session.commit()
    db_session.refresh(ward)

    created = test_client.post(
        "/reception/admissions",
        headers=auth_headers(staff),
        json={"patient_id": patient.id, "ward_id": ward.id, "bed_number": 1},
    )
    assert created.status_code == 200, created.text

    listed = test_client.get("/reception/admissions", headers=auth_headers(staff))
    assert listed.status_code == 200
    assert any(a["patient_id"] == patient.id for a in listed.json())


def test_station_and_rooms_routes_mounted(test_client, make_user, auth_headers):
    """stations.py + rooms.py: routes resolve (not 404) and enforce their
    own role gate on top of the page gate."""
    receptionist = make_user(role="receptionist", facility="Smoke Clinic")

    station = test_client.get("/reception/station", headers=auth_headers(receptionist))
    assert station.status_code == 200, station.text  # no active station yet -> {"active": False}-ish

    # /rooms/release is CONSULT_ROOM_ROLES only (clinician/admin) -- a
    # receptionist passes the page gate but must be rejected here.
    release = test_client.post("/reception/rooms/release", headers=auth_headers(receptionist))
    assert release.status_code == 403

    rooms = test_client.get("/reception/rooms", headers=auth_headers(receptionist))
    assert rooms.status_code == 200


def test_queue_status_is_patient_reachable(test_client, db_session, make_user, auth_headers):
    """queue.py `/queue/status/{patient_id}` uses get_current_user (not the
    staff role gate) so a patient can poll their own wait -- confirm that
    path still resolves after the move."""
    patient_row = _patient(db_session, full_name="Poller Smoke")
    patient_user = make_user(role="patient", patient_id=patient_row.id)
    resp = test_client.get(
        f"/reception/queue/status/{patient_row.id}",
        headers=auth_headers(patient_user),
    )
    # 200 with a "nothing in queue" shape, never 404/403
    assert resp.status_code == 200, resp.text
