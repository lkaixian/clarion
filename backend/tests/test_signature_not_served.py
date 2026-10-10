"""A signature image is only ever served back to its owner (GET /me/signature).
Colleagues and record viewers must not be able to pull anyone else's PNG."""
from tests.conftest import _facility


def test_other_staff_signature_endpoints_are_gone(test_client, make_user, auth_headers):
    fac = _facility("SigFac")
    viewer = make_user("receptionist", facility=fac)
    doctor = make_user("clinician", facility=fac)
    h = auth_headers(viewer)
    assert test_client.get(f"/staff/{doctor.id}/signature", headers=h).status_code in (404, 405)
    assert test_client.get("/patients/x/annotations/y/signature", headers=h).status_code in (404, 405)
