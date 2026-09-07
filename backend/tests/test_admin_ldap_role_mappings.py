"""P1.10 admin.py /admin/ldap-role-mappings CRUD -- gap flagged by the
voltagent security review (the original P1.10 test suite had zero coverage
here). Uses the shared conftest.py fixtures (P1.12).

Covers:
  - plain RBAC (non-admin 403)
  - H3: `facility` must be omitted or equal to the acting admin's own
    facility -- an admin cannot plant a mapping that provisions/resyncs a
    user at a DIFFERENT facility
  - M1: "patient"/"emergency_responder" are not assignable roles here
  - M2: a duplicate group_dn (including a case-variant) is a clean 409, not
    an unhandled IntegrityError -> 500
  - basic CRUD round-trip (already smoke-tested manually during
    development; kept here as a real regression test)
"""
from app import models


def test_non_admin_forbidden(test_client, make_user, auth_headers):
    clinician = make_user(role="clinician", facility="Main Hospital")
    resp = test_client.get("/admin/ldap-role-mappings", headers=auth_headers(clinician))
    assert resp.status_code == 403


def test_create_and_list_round_trip(test_client, make_user, auth_headers, db_session):
    admin = make_user(role="admin", facility="Main Hospital")
    resp = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(admin),
        json={"group_dn": "cn=Clinicians,dc=example,dc=com", "role": "clinician", "priority": 5},
    )
    assert resp.status_code == 201, resp.text
    mapping_id = resp.json()["id"]

    listed = test_client.get("/admin/ldap-role-mappings", headers=auth_headers(admin))
    assert listed.status_code == 200
    assert any(row["id"] == mapping_id for row in listed.json())

    db_session.query(models.LdapRoleMapping).filter_by(id=mapping_id).delete()
    db_session.commit()


def test_facility_must_match_acting_admin_own_facility(test_client, make_user, auth_headers):
    """voltagent H3: an admin at Facility A cannot create a mapping whose
    facility is Facility B -- that would provision/resync a user at a
    hospital the acting admin has no authority over, the exact cross-tenant
    escalation the rest of admin.py is hardened against."""
    admin_a = make_user(role="admin", facility="Facility A")
    resp = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(admin_a),
        json={"group_dn": "cn=Escalate,dc=example,dc=com", "role": "admin", "facility": "Facility B"},
    )
    assert resp.status_code == 403


def test_facility_omitted_or_own_facility_is_allowed(test_client, make_user, auth_headers, db_session):
    admin_a = make_user(role="admin", facility="Facility A")

    no_facility = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(admin_a),
        json={"group_dn": "cn=NoFacility,dc=example,dc=com", "role": "clinician"},
    )
    assert no_facility.status_code == 201, no_facility.text

    own_facility = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(admin_a),
        json={"group_dn": "cn=OwnFacility,dc=example,dc=com", "role": "clinician", "facility": "Facility A"},
    )
    assert own_facility.status_code == 201, own_facility.text

    db_session.query(models.LdapRoleMapping).filter(
        models.LdapRoleMapping.group_dn.in_(["cn=NoFacility,dc=example,dc=com", "cn=OwnFacility,dc=example,dc=com"])
    ).delete(synchronize_session=False)
    db_session.commit()


def test_update_also_enforces_facility_restriction(test_client, make_user, auth_headers, db_session):
    admin_a = make_user(role="admin", facility="Facility A")
    row = models.LdapRoleMapping(group_dn="cn=Existing,dc=example,dc=com", role="clinician", facility="Facility A")
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)

    resp = test_client.put(
        f"/admin/ldap-role-mappings/{row.id}",
        headers=auth_headers(admin_a),
        json={"group_dn": "cn=Existing,dc=example,dc=com", "role": "clinician", "facility": "Facility B", "priority": 0},
    )
    assert resp.status_code == 403

    db_session.delete(db_session.query(models.LdapRoleMapping).filter_by(id=row.id).first())
    db_session.commit()


def test_patient_role_rejected(test_client, make_user, auth_headers):
    """voltagent M1: a directory group must never be mappable to
    role="patient" -- a JIT-provisioned "patient" User has no linked
    Patient row (patient_id stays None), violating this codebase's
    invariant that patients never authenticate via LDAP."""
    admin = make_user(role="admin", facility="Main Hospital")
    resp = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(admin),
        json={"group_dn": "cn=Patients,dc=example,dc=com", "role": "patient"},
    )
    assert resp.status_code == 422


def test_emergency_responder_role_rejected(test_client, make_user, auth_headers):
    admin = make_user(role="admin", facility="Main Hospital")
    resp = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(admin),
        json={"group_dn": "cn=Responders,dc=example,dc=com", "role": "emergency_responder"},
    )
    assert resp.status_code == 422


def test_admin_role_mapping_requires_a_platform_admin(test_client, make_user, auth_headers, db_session):
    """Code-review follow-up 2026-09-07: "admin" IS a legitimate
    LDAP-assignable role (an IT/Helpdesk AD group), but only a PLATFORM
    admin (no facility of their own) may create such a mapping -- a
    facility-scoped admin doing so would be a facility-admin ->
    platform-admin escalation path."""
    facility_admin = make_user(role="admin", facility="Main Hospital")
    denied = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(facility_admin),
        json={"group_dn": "cn=Helpdesk,dc=example,dc=com", "role": "admin"},
    )
    assert denied.status_code == 403

    platform_admin = make_user(role="admin", facility=None)
    allowed = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(platform_admin),
        json={"group_dn": "cn=Helpdesk,dc=example,dc=com", "role": "admin"},
    )
    assert allowed.status_code == 201, allowed.text
    db_session.query(models.LdapRoleMapping).filter_by(id=allowed.json()["id"]).delete()
    db_session.commit()


def test_duplicate_group_dn_is_clean_409_not_500(test_client, make_user, auth_headers, db_session):
    admin = make_user(role="admin", facility="Main Hospital")
    first = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(admin),
        json={"group_dn": "cn=Dup,dc=example,dc=com", "role": "clinician"},
    )
    assert first.status_code == 201

    dup = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(admin),
        json={"group_dn": "cn=Dup,dc=example,dc=com", "role": "receptionist"},
    )
    assert dup.status_code == 409

    # Case-variant duplicate (M2: the pre-check is case-insensitive too).
    dup_case = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(admin),
        json={"group_dn": "CN=DUP,DC=EXAMPLE,DC=COM", "role": "receptionist"},
    )
    assert dup_case.status_code == 409

    db_session.query(models.LdapRoleMapping).filter_by(id=first.json()["id"]).delete()
    db_session.commit()


def test_delete_round_trip(test_client, make_user, auth_headers, db_session):
    admin = make_user(role="admin", facility="Main Hospital")
    created = test_client.post(
        "/admin/ldap-role-mappings",
        headers=auth_headers(admin),
        json={"group_dn": "cn=ToDelete,dc=example,dc=com", "role": "pharmacist"},
    )
    assert created.status_code == 201
    mapping_id = created.json()["id"]

    deleted = test_client.delete(f"/admin/ldap-role-mappings/{mapping_id}", headers=auth_headers(admin))
    assert deleted.status_code == 200

    assert db_session.query(models.LdapRoleMapping).filter_by(id=mapping_id).first() is None
