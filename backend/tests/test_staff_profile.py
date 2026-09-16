"""Bio / internal contact email / profile photo (self-service + admin +
public clinician-booking read). See routers/profile.py, routers/admin.py's
update_staff_profile/upload_staff_photo, routers/patients.py's
list_booking_options/get_clinician_photo.

Covers the three real judgment calls from that feature: (1) `contact_email`
never touches the login/auth `email` column, (2) admin edits are facility-
scoped (same non-leaking-404 as the rest of routers/admin.py), (3) a
clinician's photo is readable by a PATIENT (the public-booking case) but a
non-clinician's photo is not, through that same open endpoint.
"""
import base64
import io

from tests.conftest import _facility, _TEST_SIGNATURE_B64

_TEST_PHOTO_BYTES = base64.b64decode(_TEST_SIGNATURE_B64)  # any real small PNG works


def _upload_photo(test_client, headers, path="/me/photo"):
    return test_client.post(
        path,
        headers=headers,
        files={"file": ("photo.png", io.BytesIO(_TEST_PHOTO_BYTES), "image/png")},
    )


def test_self_profile_update_never_touches_login_email(test_client, make_user, auth_headers):
    user = make_user(role="clinician")
    headers = auth_headers(user)

    resp = test_client.put(
        "/me/profile",
        headers=headers,
        json={"bio": "10 years in cardiology.", "contact_email": "contact@example.com"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bio"] == "10 years in cardiology."
    assert body["contact_email"] == "contact@example.com"

    me = test_client.get("/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    me_body = me.json()
    assert me_body["bio"] == "10 years in cardiology."
    assert me_body["contact_email"] == "contact@example.com"
    # The real login/auth identity column is untouched.
    assert me_body["email"] == user.email


def test_self_photo_upload_get_delete(test_client, make_user, auth_headers):
    user = make_user(role="clinician")
    headers = auth_headers(user)

    assert test_client.get("/auth/me", headers=headers).json()["has_photo"] is False

    up = _upload_photo(test_client, headers)
    assert up.status_code == 200, up.text
    assert up.json()["has_photo"] is True
    assert test_client.get("/auth/me", headers=headers).json()["has_photo"] is True

    got = test_client.get("/me/photo", headers=headers)
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/jpeg"

    deleted = test_client.delete("/me/photo", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["has_photo"] is False
    assert test_client.get("/me/photo", headers=headers).status_code == 404


def test_admin_profile_edit_is_facility_scoped(test_client, make_user, auth_headers):
    facility_a = _facility("Admin Profile A")
    facility_b = _facility("Admin Profile B")
    admin_a = make_user(role="admin", facility=facility_a)
    clinician_a = make_user(role="clinician", facility=facility_a)
    clinician_b = make_user(role="clinician", facility=facility_b)
    admin_headers = auth_headers(admin_a)

    ok = test_client.patch(
        f"/admin/staff/{clinician_a.id}/profile",
        headers=admin_headers,
        json={"bio": "Admin-corrected bio.", "contact_email": None},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["bio"] == "Admin-corrected bio."

    photo = _upload_photo(test_client, admin_headers, path=f"/admin/staff/{clinician_a.id}/photo")
    assert photo.status_code == 200, photo.text
    assert photo.json()["has_photo"] is True

    # Same admin, a clinician at a DIFFERENT facility -- non-leaking 404,
    # same posture as assign_staff_section.
    cross = test_client.patch(
        f"/admin/staff/{clinician_b.id}/profile",
        headers=admin_headers,
        json={"bio": "should not land"},
    )
    assert cross.status_code == 404

    cross_photo = _upload_photo(test_client, admin_headers, path=f"/admin/staff/{clinician_b.id}/photo")
    assert cross_photo.status_code == 404


def test_clinician_photo_is_patient_readable_but_scoped_to_clinicians(
    test_client, make_user, auth_headers,
):
    facility = _facility("Booking Photo")
    clinician = make_user(role="clinician", facility=facility)
    receptionist = make_user(role="receptionist", facility=facility)
    patient_user = make_user(role="patient")

    clinician_headers = auth_headers(clinician)
    assert _upload_photo(test_client, clinician_headers).status_code == 200

    patient_headers = auth_headers(patient_user)

    # A patient CAN read a clinician's photo (the public-booking case).
    ok = test_client.get(f"/patients/clinicians/{clinician.id}/photo", headers=patient_headers)
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/jpeg"

    # The same open endpoint refuses a non-clinician staff id outright --
    # this path is scoped to role="clinician", not "any staff member".
    receptionist_headers = auth_headers(receptionist)
    assert _upload_photo(test_client, receptionist_headers).status_code == 200
    non_clinician = test_client.get(
        f"/patients/clinicians/{receptionist.id}/photo", headers=patient_headers
    )
    assert non_clinician.status_code == 404


def test_booking_options_exposes_bio_and_has_photo(test_client, make_user, auth_headers):
    facility = _facility("Booking Options Bio")
    clinician = make_user(role="clinician", facility=facility)
    clinician_headers = auth_headers(clinician)

    prof = test_client.put(
        "/me/profile", headers=clinician_headers, json={"bio": "Family medicine.", "contact_email": None},
    )
    assert prof.status_code == 200, prof.text
    assert _upload_photo(test_client, clinician_headers).status_code == 200

    patient_user = make_user(role="patient")
    patient_headers = auth_headers(patient_user)
    resp = test_client.get(
        "/patients/booking-options", headers=patient_headers, params={"facility_name": facility},
    )
    assert resp.status_code == 200, resp.text
    entries = {c["id"]: c for c in resp.json()["clinicians"]}
    assert entries[clinician.id]["bio"] == "Family medicine."
    assert entries[clinician.id]["has_photo"] is True
