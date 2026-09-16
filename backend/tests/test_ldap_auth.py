"""P1.10 — LDAP/AD auth provider.

Two layers:
  1. app/ldap_auth.py in isolation, against ldap3's MOCK_SYNC strategy (no
     real directory server -- see mock_ldap fixture below).
  2. End-to-end through POST /auth/login, via the shared test_client /
     db_session fixtures from conftest.py (P1.12 -- this file predates it
     and used to set up its own throwaway DB/TestClient; deduped 2026-09-16,
     see git history for the old self-contained version).
"""
import os
import logging

import pytest
from ldap3 import Connection, MOCK_SYNC, Server

from app import ldap_auth, models

os.environ.pop("LDAP_ENABLED", None)  # ensure a clean starting state regardless of the outer shell env


# --------------------------------------------------------------------------
# Mock directory fixture -- ldap3 MOCK_SYNC, no real LDAP/AD server.
# --------------------------------------------------------------------------
# ldap3's MOCK_SYNC in-memory DIT lives on each Connection's own
# `.strategy`, not shared automatically across separate Connection
# instances (authenticate_ldap makes two: the service bind and the user
# re-bind). So every mock Connection created below is re-seeded with the
# same fixed entries immediately after construction -- cheap, and gives
# both connections an identical view of the directory.
_DIRECTORY = {
    "cn=svc,dc=example,dc=com": {"userPassword": "svcpass"},
    "cn=alice,dc=example,dc=com": {
        "userPassword": "alicepass",
        "mail": "alice@example.com",
        # A realistic AD login attribute, deliberately a DIFFERENT string
        # from `mail` -- exercises the sAMAccountName-based filter tests
        # below (voltagent review C1 regression coverage).
        "sAMAccountName": "alice.example",
        "displayName": "Alice Example",
        "memberOf": [
            "cn=Clinicians,ou=groups,dc=example,dc=com",
            "cn=AllStaff,ou=groups,dc=example,dc=com",
        ],
    },
    "cn=bob,dc=example,dc=com": {
        "userPassword": "bobpass",
        "mail": "bob@example.com",
        "displayName": "Bob Example",
        "memberOf": ["cn=Unmapped,ou=groups,dc=example,dc=com"],
    },
    "cn=dup1,dc=example,dc=com": {"userPassword": "x", "mail": "dup@example.com"},
    "cn=dup2,dc=example,dc=com": {"userPassword": "x", "mail": "dup@example.com"},
}


def _seeded_mock_connection(server, user=None, password=None, **kwargs):
    conn = Connection(server, user=user, password=password, client_strategy=MOCK_SYNC)
    for dn, attrs in _DIRECTORY.items():
        conn.strategy.add_entry(dn, dict(attrs))
    return conn


@pytest.fixture
def mock_ldap(monkeypatch):
    """Patches app.ldap_auth's Server/Connection construction to hit the
    in-memory mock directory above instead of a real network LDAP server.
    Also sets the minimal LDAP_ENABLED + connection env vars a test needs;
    LDAP_ENABLED is popped again at fixture teardown so it never leaks into
    an unrelated test."""
    monkeypatch.setenv("LDAP_ENABLED", "true")
    monkeypatch.setenv("LDAP_SERVER_URI", "ldap://mock-server")
    monkeypatch.setenv("LDAP_BIND_DN", "cn=svc,dc=example,dc=com")
    monkeypatch.setenv("LDAP_BIND_PASSWORD", "svcpass")
    monkeypatch.setenv("LDAP_BASE_DN", "dc=example,dc=com")
    # This is a mock, in-process directory, not a real network channel --
    # there's no actual plaintext-on-the-wire risk to opt out of here.
    # Real TLS enforcement (_make_tls / the fail-closed check in
    # authenticate_ldap) is covered directly against LdapConfig, not via
    # this mock, which never sees the ldap3 Tls machinery at all.
    monkeypatch.setenv("LDAP_ALLOW_INSECURE_BIND", "true")
    monkeypatch.setattr(
        ldap_auth, "_make_server", lambda cfg: Server("mock-server", get_info=None)
    )
    monkeypatch.setattr(ldap_auth, "Connection", _seeded_mock_connection)
    yield


def _map_group(db_session, group_dn: str, role: str, facility: str | None = None, priority: int = 0):
    row = models.LdapRoleMapping(group_dn=group_dn, role=role, facility=facility, priority=priority)
    db_session.add(row)
    db_session.commit()
    return row


def _cleanup_ldap_rows(db_session):
    db_session.query(models.LdapRoleMapping).delete()
    db_session.query(models.User).filter(models.User.auth_source == "ldap").delete()
    db_session.commit()


@pytest.fixture(autouse=True)
def _isolate_ldap_state(db_session):
    """Every test starts and ends with a clean ldap_role_mappings table and
    no leftover ldap-sourced User rows, so tests can run in any order."""
    _cleanup_ldap_rows(db_session)
    yield
    _cleanup_ldap_rows(db_session)


# --------------------------------------------------------------------------
# 1. Unit tests -- app.ldap_auth.authenticate_ldap
# --------------------------------------------------------------------------
def test_empty_password_rejected_before_any_bind(mock_ldap, monkeypatch, caplog):
    calls = []
    real = ldap_auth.Connection
    monkeypatch.setattr(
        ldap_auth, "Connection",
        lambda *a, **kw: (calls.append(1), real(*a, **kw))[1],
    )
    with caplog.at_level(logging.WARNING):
        result = ldap_auth.authenticate_ldap("alice@example.com", "")
    assert result is None
    assert calls == []  # no Connection was ever constructed -- rejected pre-bind
    assert any("empty password" in r.message for r in caplog.records)


def test_successful_bind_search_rebind(mock_ldap):
    result = ldap_auth.authenticate_ldap("alice@example.com", "alicepass")
    assert result is not None
    assert result.dn == "cn=alice,dc=example,dc=com"
    assert result.email == "alice@example.com"
    assert result.full_name == "Alice Example"
    assert set(result.group_dns) == {
        "cn=Clinicians,ou=groups,dc=example,dc=com",
        "cn=AllStaff,ou=groups,dc=example,dc=com",
    }


def test_wrong_password_on_rebind_fails(mock_ldap, monkeypatch):
    # Search by mail (the default filter), but the account itself is
    # addressed by DN in this fixture's seed data -- use a filter that
    # matches on DN's cn instead, since the default (mail={username})
    # filter needs to find alice by her mail attribute.
    monkeypatch.setenv("LDAP_USER_SEARCH_FILTER", "(mail={username})")
    result = ldap_auth.authenticate_ldap("alice@example.com", "WRONG-PASSWORD")
    assert result is None


def test_zero_search_results(mock_ldap):
    result = ldap_auth.authenticate_ldap("nobody@example.com", "whatever")
    assert result is None


def test_multiple_search_results_denied(mock_ldap, caplog):
    with caplog.at_level(logging.WARNING):
        result = ldap_auth.authenticate_ldap("dup@example.com", "x")
    assert result is None
    assert any("directory matches" in r.message for r in caplog.records)


def test_filter_injection_is_escaped(mock_ldap, monkeypatch):
    """A classic LDAP filter-injection payload must be neutralised by
    escape_filter_chars before it's substituted into the search filter --
    assert the EXACT filter string ldap_auth builds and sends."""
    sent_filters = []
    orig_search = Connection.search

    def spy_search(self, search_base, search_filter, **kwargs):
        sent_filters.append(search_filter)
        return orig_search(self, search_base, search_filter, **kwargs)

    monkeypatch.setattr(Connection, "search", spy_search)

    payload = "*)(uid=*))(|(uid=*"
    result = ldap_auth.authenticate_ldap(payload, "whatever")
    assert result is None  # no such entry -- injection didn't broaden the match
    assert len(sent_filters) == 1
    # The raw payload's parens/asterisks must be backslash-escaped, not
    # passed through raw -- i.e. the filter is NOT "(mail=*)(uid=*))...)".
    assert sent_filters[0] == "(mail=\\2a\\29\\28uid=\\2a\\29\\29\\28|\\28uid=\\2a)"


def test_service_bind_failure_returns_none_no_exception(mock_ldap, monkeypatch):
    monkeypatch.setenv("LDAP_BIND_PASSWORD", "WRONG-SERVICE-PASSWORD")
    result = ldap_auth.authenticate_ldap("alice@example.com", "alicepass")
    assert result is None


# --------------------------------------------------------------------------
# 2. Unit tests -- resolve_role_for_groups
# --------------------------------------------------------------------------
def test_resolve_role_highest_priority_wins(db_session):
    _map_group(db_session, "cn=Clinicians,ou=groups,dc=example,dc=com", "clinician", priority=1)
    _map_group(db_session, "cn=AllStaff,ou=groups,dc=example,dc=com", "records_officer", priority=10)
    role, facility = ldap_auth.resolve_role_for_groups(
        db_session,
        ["cn=Clinicians,ou=groups,dc=example,dc=com", "cn=AllStaff,ou=groups,dc=example,dc=com"],
    )
    assert role == "records_officer"  # priority 10 beats priority 1
    assert facility is None


def test_resolve_role_no_match_returns_none(db_session):
    _map_group(db_session, "cn=Clinicians,ou=groups,dc=example,dc=com", "clinician")
    role, facility = ldap_auth.resolve_role_for_groups(db_session, ["cn=Unmapped,ou=groups,dc=example,dc=com"])
    assert role is None
    assert facility is None


def test_resolve_role_case_insensitive(db_session):
    _map_group(db_session, "CN=Clinicians,OU=groups,DC=example,DC=com", "clinician", facility="Branch Campus")
    role, facility = ldap_auth.resolve_role_for_groups(
        db_session, ["cn=clinicians,ou=groups,dc=example,dc=com"]
    )
    assert role == "clinician"
    assert facility == "Branch Campus"


# --------------------------------------------------------------------------
# 3. End-to-end through POST /auth/login
# --------------------------------------------------------------------------
def test_ldap_disabled_login_unaffected(db_session, test_client):
    """LDAP_ENABLED unset (the default) -- an identifier with no local
    account behaves exactly as before P1.10: generic 401, no directory
    contacted (no mock_ldap fixture applied here at all)."""
    assert os.environ.get("LDAP_ENABLED") is None
    resp = test_client.post("/auth/login", data={"username": "nobody@example.com", "password": "x"})
    assert resp.status_code == 401


def test_case_a_jit_provision_and_login(mock_ldap, db_session, test_client):
    _map_group(db_session, "cn=Clinicians,ou=groups,dc=example,dc=com", "clinician", facility="Branch Campus")

    assert db_session.query(models.User).filter(models.User.email == "alice@example.com").first() is None

    resp = test_client.post(
        "/auth/login", data={"username": "alice@example.com", "password": "alicepass"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["role"] == "clinician"
    assert body["user"]["facility"] == "Branch Campus"
    assert body["access_token"]

    db_session.expire_all()
    row = db_session.query(models.User).filter(models.User.email == "alice@example.com").first()
    assert row is not None
    assert row.auth_source == "ldap"
    assert row.ldap_dn == "cn=alice,dc=example,dc=com"
    # The placeholder hash must never validate a real-looking password --
    # this account can only ever authenticate via LDAP from here on.
    from app import auth as auth_module
    assert not auth_module.verify_password("alicepass", row.hashed_password)


def test_case_a_jit_denied_when_no_group_mapped(mock_ldap, db_session, test_client):
    """bob authenticates fine against the mock directory but his only
    group has no mapping -- login must be denied, and no User row created
    (no silent default role)."""
    resp = test_client.post("/auth/login", data={"username": "bob@example.com", "password": "bobpass"})
    assert resp.status_code == 401
    assert db_session.query(models.User).filter(models.User.email == "bob@example.com").first() is None


def test_case_b_existing_ldap_user_resync_on_group_change(mock_ldap, db_session, test_client):
    _map_group(db_session, "cn=Clinicians,ou=groups,dc=example,dc=com", "clinician")
    first = test_client.post("/auth/login", data={"username": "alice@example.com", "password": "alicepass"})
    assert first.status_code == 200
    assert first.json()["user"]["role"] == "clinician"

    # AD group membership changes: Clinicians mapping removed, AllStaff now
    # maps to records_officer. Next login must pick this up.
    db_session.query(models.LdapRoleMapping).delete()
    db_session.commit()
    _map_group(db_session, "cn=AllStaff,ou=groups,dc=example,dc=com", "records_officer")

    second = test_client.post("/auth/login", data={"username": "alice@example.com", "password": "alicepass"})
    assert second.status_code == 200
    assert second.json()["user"]["role"] == "records_officer"

    db_session.expire_all()
    users = db_session.query(models.User).filter(models.User.email == "alice@example.com").all()
    assert len(users) == 1  # re-synced the same row, not a duplicate


def test_case_b_failed_ldap_rebind_increments_lockout(mock_ldap, db_session, test_client):
    _map_group(db_session, "cn=Clinicians,ou=groups,dc=example,dc=com", "clinician")
    good = test_client.post("/auth/login", data={"username": "alice@example.com", "password": "alicepass"})
    assert good.status_code == 200

    for _ in range(5):
        bad = test_client.post("/auth/login", data={"username": "alice@example.com", "password": "WRONG"})
        assert bad.status_code == 401

    db_session.expire_all()
    row = db_session.query(models.User).filter(models.User.email == "alice@example.com").first()
    assert row.login_locked_until is not None

    # Locked out now even with the CORRECT password -- same per-account
    # lockout an LDAP-backed account is not exempt from.
    locked_attempt = test_client.post(
        "/auth/login", data={"username": "alice@example.com", "password": "alicepass"}
    )
    assert locked_attempt.status_code == 429


def test_case_c_local_account_unaffected_by_ldap_enabled(mock_ldap, db_session, test_client):
    """A pre-existing LOCAL account (auth_source default) must keep
    authenticating with its own local password even while LDAP_ENABLED is
    true -- LDAP is never consulted for it."""
    from app import auth as auth_module

    local_user = models.User(
        email="carol.local@example.com",
        hashed_password=auth_module.hash_password("carolpass"),
        full_name="Carol Local",
        role="clinician",
    )
    db_session.add(local_user)
    db_session.commit()

    resp = test_client.post(
        "/auth/login", data={"username": "carol.local@example.com", "password": "carolpass"}
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "carol.local@example.com"

    db_session.expire_all()
    row = db_session.query(models.User).filter_by(email="carol.local@example.com").first()
    assert row.auth_source == "local"  # untouched -- LDAP was never consulted for this account
    db_session.delete(row)
    db_session.commit()


def test_real_patient_nric_never_reaches_ldap(mock_ldap, db_session, monkeypatch, test_client):
    """A real Patient's NRIC -- even one with NO linked User account yet --
    must fall through to the generic 401 WITHOUT ever contacting the
    directory. This is the actual staff-only boundary (see
    _resolve_login_user's ldap_eligible docstring): once the identifier
    resolves to a genuine patient, it is never treated as an LDAP
    candidate, JIT-provision or otherwise."""
    patient = models.Patient(full_name="Dana Patient", date_of_birth="1990-01-01", national_id="990101-01-1234")
    db_session.add(patient)
    db_session.commit()
    # Deliberately no linked User row -- this patient has never had an
    # account issued. Even so, LDAP must not be consulted for their NRIC.

    called = []
    orig = ldap_auth.authenticate_ldap
    monkeypatch.setattr(ldap_auth, "authenticate_ldap", lambda *a, **kw: (called.append(1), orig(*a, **kw))[1])

    resp = test_client.post("/auth/login", data={"username": "990101-01-1234", "password": "whatever"})
    assert resp.status_code == 401
    assert called == []

    db_session.delete(db_session.query(models.Patient).filter_by(id=patient.id).first())
    db_session.commit()


def test_unmatched_garbage_identifier_may_reach_ldap_but_is_denied(mock_ldap, db_session, test_client):
    """An identifier that is neither a known email nor a real patient's NRIC
    (garbage / a typo) is LDAP-eligible -- the search simply comes back
    empty and the login is denied with the same generic 401. This is NOT a
    security-sensitive path (nothing about a real patient or account is
    exposed either way); it documents actual behavior rather than asserting
    a stronger guarantee this codebase's normalize_nric (format-agnostic by
    design) can't cheaply provide."""
    resp = test_client.post("/auth/login", data={"username": "990101-01-1234", "password": "whatever"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# 4. voltagent security review follow-ups (C1, L3, M4, and coverage gaps)
# --------------------------------------------------------------------------
def test_c1_regression_non_mail_filter_survives_second_login(mock_ldap, monkeypatch, db_session, test_client):
    """THE regression test for voltagent finding C1: under a realistic
    sAMAccountName-based search filter (where mail and the login string
    are DIFFERENT values), a second login for the same identity must find
    the row the first login created -- not crash trying to re-provision it,
    and not fail to re-search the directory. Before the ldap_username fix,
    this 500'd on the second attempt."""
    monkeypatch.setenv("LDAP_USER_SEARCH_FILTER", "(sAMAccountName={username})")
    _map_group(db_session, "cn=Clinicians,ou=groups,dc=example,dc=com", "clinician")

    first = test_client.post("/auth/login", data={"username": "alice.example", "password": "alicepass"})
    assert first.status_code == 200, first.text
    assert first.json()["user"]["email"] == "alice@example.com"

    db_session.expire_all()
    rows = db_session.query(models.User).filter(models.User.email == "alice@example.com").all()
    assert len(rows) == 1
    assert rows[0].ldap_username == "alice.example"

    second = test_client.post("/auth/login", data={"username": "alice.example", "password": "alicepass"})
    assert second.status_code == 200, second.text  # NOT a 500

    db_session.expire_all()
    rows_after = db_session.query(models.User).filter(models.User.email == "alice@example.com").all()
    assert len(rows_after) == 1  # still exactly one row -- no duplicate provisioning


def test_c1_regression_group_revocation_takes_effect_under_non_mail_filter(mock_ldap, monkeypatch, db_session, test_client):
    """Companion to the above: the "revoked AD group takes effect on next
    login" resync (Case B) must also work under a non-mail filter -- before
    the fix, Case B searched the directory BY user.email, which doesn't
    exist as a sAMAccountName and so could never find the entry again."""
    monkeypatch.setenv("LDAP_USER_SEARCH_FILTER", "(sAMAccountName={username})")
    _map_group(db_session, "cn=Clinicians,ou=groups,dc=example,dc=com", "clinician")

    first = test_client.post("/auth/login", data={"username": "alice.example", "password": "alicepass"})
    assert first.status_code == 200
    assert first.json()["user"]["role"] == "clinician"

    db_session.query(models.LdapRoleMapping).delete()
    db_session.commit()
    _map_group(db_session, "cn=AllStaff,ou=groups,dc=example,dc=com", "records_officer")

    second = test_client.post("/auth/login", data={"username": "alice.example", "password": "alicepass"})
    assert second.status_code == 200, second.text
    assert second.json()["user"]["role"] == "records_officer"


def test_wrong_placeholder_name_in_filter_denied_not_crashed(mock_ldap, monkeypatch, caplog):
    """A filter referencing an undefined format placeholder (a real typo,
    e.g. {user} instead of {username}) must be caught and denied, not raise
    a KeyError out of authenticate_ldap."""
    monkeypatch.setenv("LDAP_USER_SEARCH_FILTER", "(mail={user})")
    with caplog.at_level(logging.WARNING):
        result = ldap_auth.authenticate_ldap("alice@example.com", "alicepass")
    assert result is None
    assert any("malformed" in r.message for r in caplog.records)


def test_unbind_called_even_when_search_raises(mock_ldap, monkeypatch):
    """The finally: service_conn.unbind() cleanup must run even when the
    directory call raises mid-flow (a connection leak otherwise) -- not
    just on the expected-failure return paths every other test exercises."""
    from ldap3.core.exceptions import LDAPException

    unbind_calls = []
    orig_unbind = Connection.unbind

    def spy_unbind(self):
        unbind_calls.append(1)
        return orig_unbind(self)

    def raise_on_search(self, *a, **kw):
        raise LDAPException("simulated directory failure mid-search")

    monkeypatch.setattr(Connection, "unbind", spy_unbind)
    monkeypatch.setattr(Connection, "search", raise_on_search)

    result = ldap_auth.authenticate_ldap("alice@example.com", "alicepass")
    assert result is None
    assert len(unbind_calls) >= 1  # the service connection was unbound despite the exception


def test_jit_provision_race_falls_back_to_winner_row(mock_ldap, db_session):
    """voltagent finding M4: simulates two concurrent first-logins for the
    same new identity by pre-inserting, via a SEPARATE session, the row a
    'concurrent' request would have created -- the loser must return that
    existing row (and the login must still succeed), not crash with an
    unhandled IntegrityError."""
    from app import auth as auth_module
    from app.database import SessionLocal
    from app.routers import auth_router

    _map_group(db_session, "cn=Clinicians,ou=groups,dc=example,dc=com", "clinician")

    # A separate DB session simulates the "concurrent" winning request --
    # its insert+commit is fully independent of (and precedes) the one
    # _jit_provision_ldap_user is about to attempt on db_session below.
    other_session = SessionLocal()
    try:
        other_session.add(models.User(
            email="alice@example.com",
            hashed_password=auth_module.hash_password("irrelevant"),
            full_name="Alice Example",
            role="clinician",
            auth_source="ldap",
            ldap_dn="cn=alice,dc=example,dc=com",
            ldap_username="alice@example.com",
        ))
        other_session.commit()
    finally:
        other_session.close()

    result = auth_router._jit_provision_ldap_user(db_session, "alice@example.com", "alicepass")
    assert result is not None
    assert result.email == "alice@example.com"

    db_session.expire_all()
    rows = db_session.query(models.User).filter(models.User.email == "alice@example.com").all()
    assert len(rows) == 1  # no duplicate/orphaned row left behind
