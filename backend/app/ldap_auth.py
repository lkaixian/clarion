"""
LDAP / Active Directory authentication provider (P1.10, tender clause
).

A SECOND auth provider next to the existing local-password accounts in
app/auth.py + app/routers/auth_router.py -- never a replacement. Local
accounts keep working unconditionally (break-glass admin, service
integrations, patient logins per healthcare/Integration Engine and LDAP.md).
Disabled by default: every function here is a no-op unless LDAP_ENABLED is
explicitly set, same opt-in-by-default-off discipline as
app/ai/_cloud_guard.py's CLARION_ALLOW_CLOUD_AI.

Flow (see auth_router.login for where this is wired in):
  1. service bind (LDAP_BIND_DN / LDAP_BIND_PASSWORD)
  2. search LDAP_BASE_DN with an escaped, templated filter
  3. re-bind AS THE FOUND USER with the password the caller supplied --
     this is the actual authentication step; the service bind never
     validates anyone's own password
  4. on success, read back email/full_name/memberOf and resolve a role
     from LdapRoleMapping (admin-editable, app/routers/admin.py)

Every ldap3 exception is caught here and turned into a plain `None` return --
callers must never see a raw ldap3 exception, both so a directory outage
degrades to "LDAP unavailable" (indistinguishable from "wrong password" to
the client -- same account-enumeration-safety discipline as the rest of
auth_router.py) and so no stack trace containing directory details reaches
a log line a lower-privileged process might read.
"""
from __future__ import annotations

import logging
import os
import ssl
import threading
from dataclasses import dataclass, field

from ldap3 import Connection, Server, Tls
from ldap3.utils.conv import escape_filter_chars
from sqlalchemy.orm import Session

from . import models

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


@dataclass(frozen=True)
class LdapConfig:
    enabled: bool
    server_uri: str
    use_ssl: bool
    start_tls: bool
    bind_dn: str
    bind_password: str
    base_dn: str
    user_search_filter: str
    attr_email: str
    attr_full_name: str
    attr_memberof: str
    connect_timeout_seconds: float
    # P1.10 voltagent security review, H4/M3: ldap3's default Tls() has
    # validate=ssl.CERT_NONE -- LDAP_USE_SSL/LDAP_START_TLS alone do NOT
    # get certificate-chain validation "for free". ca_cert_file (optional --
    # None uses the OS default trust store via ssl.create_default_context)
    # and allow_insecure (an explicit, loud opt-out, same pattern as
    # CLARION_ALLOW_CLOUD_AI) close that gap -- see _make_tls and the
    # plaintext-refusal check in authenticate_ldap below.
    ca_cert_file: str | None
    allow_insecure: bool

    @classmethod
    def from_env(cls) -> "LdapConfig":
        return cls(
            enabled=_bool_env("LDAP_ENABLED", False),
            server_uri=os.environ.get("LDAP_SERVER_URI", ""),
            use_ssl=_bool_env("LDAP_USE_SSL", False),
            start_tls=_bool_env("LDAP_START_TLS", False),
            bind_dn=os.environ.get("LDAP_BIND_DN", ""),
            bind_password=os.environ.get("LDAP_BIND_PASSWORD", ""),
            base_dn=os.environ.get("LDAP_BASE_DN", ""),
            user_search_filter=os.environ.get("LDAP_USER_SEARCH_FILTER", "(mail={username})"),
            attr_email=os.environ.get("LDAP_ATTR_EMAIL", "mail"),
            attr_full_name=os.environ.get("LDAP_ATTR_FULL_NAME", "displayName"),
            attr_memberof=os.environ.get("LDAP_ATTR_MEMBEROF", "memberOf"),
            connect_timeout_seconds=float(os.environ.get("LDAP_CONNECT_TIMEOUT_SECONDS", "5")),
            ca_cert_file=os.environ.get("LDAP_CA_CERT_FILE") or None,
            allow_insecure=_bool_env("LDAP_ALLOW_INSECURE_BIND", False),
        )


def ldap_enabled() -> bool:
    """True only when a deployer has deliberately opted in. Checked fresh
    from the environment each call (cheap; not on any hot path) rather than
    cached at import time, so tests can flip LDAP_ENABLED without a process
    restart -- same reasoning as cloud_ai_enabled()."""
    return _bool_env("LDAP_ENABLED", False)


@dataclass
class LdapAuthResult:
    dn: str
    email: str | None
    full_name: str | None
    group_dns: list[str] = field(default_factory=list)


def _make_tls(config: LdapConfig) -> Tls | None:
    """None when neither LDAP_USE_SSL nor LDAP_START_TLS is set (plaintext
    -- ldap3 ignores `tls=` entirely in that case). Otherwise an explicit
    `Tls(validate=ssl.CERT_REQUIRED, ...)` -- ldap3's own default Tls()
    (what you get by NOT passing `tls=` to Server(), i.e. what this code
    did before this fix) is `validate=ssl.CERT_NONE`: it happily completes
    a TLS handshake with ANY certificate, self-signed or not, matching
    hostname or not. That silently defeats the confidentiality
    LDAP_USE_SSL/LDAP_START_TLS are meant to provide -- a network attacker
    positioned between CLARION and the directory could MITM the service
    bind and, more importantly, every user's real password on the re-bind
    step. `ca_cert_file` unset uses the OS default trust store (via
    `ssl.create_default_context` inside ldap3, triggered by leaving
    `version` unset here); set `LDAP_CA_CERT_FILE` to pin a private/AD-CS
    CA in production. NOTE: ldap3 does not verify the certificate's
    hostname/SAN even with validate=CERT_REQUIRED (it explicitly sets
    `check_hostname = False` internally) -- chain-of-trust validation is
    real and meaningful, but pin a dedicated CA (not a public one) rather
    than relying on hostname matching to prevent a same-CA-issued rogue cert
    from a different host being accepted."""
    if not (config.use_ssl or config.start_tls):
        return None
    kwargs = {"validate": ssl.CERT_REQUIRED}
    if config.ca_cert_file:
        kwargs["ca_certs_file"] = config.ca_cert_file
    return Tls(**kwargs)


def _make_server(config: LdapConfig) -> Server:
    return Server(
        config.server_uri,
        use_ssl=config.use_ssl,
        tls=_make_tls(config),
        connect_timeout=config.connect_timeout_seconds,
        get_info=None,  # don't probe schema -- one less round trip, nothing here needs it
    )


def _first_attr(entry, name: str) -> str | None:
    """ldap3 entry attribute access normalised to a single str-or-None --
    an attribute can come back as a list, a single value, or absent
    depending on the directory and the ldap3 entry mode."""
    if name not in entry.entry_attributes:
        return None
    value = entry[name].value
    if isinstance(value, list):
        return str(value[0]) if value else None
    if value is None:
        return None
    return str(value)


def _all_attr(entry, name: str) -> list[str]:
    if name not in entry.entry_attributes:
        return []
    value = entry[name].value
    if isinstance(value, list):
        return [str(v) for v in value]
    if value is None:
        return []
    return [str(value)]


# voltagent review H1: /auth/login is exempt from the global per-IP rate
# limit on the grounds that it has its own stricter, persisted-in-DB,
# per-ACCOUNT lockout (see auth_router.login's docstring) -- but that
# lockout only ever applies to an identifier that already resolves to a
# real User row. Any OTHER identifier, when LDAP_ENABLED, now triggers a
# real, unauthenticated, slow (up to LDAP_CONNECT_TIMEOUT_SECONDS) network
# round trip with zero throttling -- an easy way to exhaust the backend's
# worker/thread pool by flooding non-existent usernames, and to hammer the
# organisation's real directory infrastructure. This semaphore bounds how
# many such binds can be in flight at once, process-wide; a caller that
# can't acquire one within the connect timeout is rejected immediately
# rather than queueing (queueing would just move the exhaustion here).
_MAX_CONCURRENT_LDAP_BINDS = int(os.environ.get("LDAP_MAX_CONCURRENT_BINDS", "8"))
_ldap_bind_gate = threading.Semaphore(_MAX_CONCURRENT_LDAP_BINDS)


def authenticate_ldap(username: str, password: str) -> LdapAuthResult | None:
    """Public entry point -- acquires the concurrency gate, then delegates
    to _authenticate_ldap_locked for the actual bind/search/rebind work."""
    if not password:
        # Checked here too (cheap, no gate/config needed) so an empty
        # password never even counts against the concurrency gate.
        logger.warning("ldap_auth: rejected empty password for %r before any bind attempt", username)
        return None

    config = LdapConfig.from_env()
    if not config.enabled:
        return None

    acquired = _ldap_bind_gate.acquire(timeout=config.connect_timeout_seconds)
    if not acquired:
        logger.warning(
            "ldap_auth: %d concurrent LDAP binds already in flight -- rejecting "
            "%r to avoid thread-pool exhaustion (LDAP_MAX_CONCURRENT_BINDS=%d)",
            _MAX_CONCURRENT_LDAP_BINDS, username, _MAX_CONCURRENT_LDAP_BINDS,
        )
        return None
    try:
        return _authenticate_ldap_locked(username, password, config)
    finally:
        _ldap_bind_gate.release()


def _authenticate_ldap_locked(username: str, password: str, config: LdapConfig) -> LdapAuthResult | None:
    """The actual bind/search/rebind flow, called only while the caller
    holds _ldap_bind_gate. `password` truthiness and `config.enabled` are
    already checked by the public authenticate_ldap wrapper above. Never
    raises -- every ldap3/network failure is caught and logged."""
    if not config.server_uri or not config.base_dn or not config.bind_dn:
        # voltagent review L2: fail loud and specific here rather than
        # letting an incomplete config surface only as a generic per-request
        # LDAPException/None further down (e.g. Server("") or an empty
        # search_base) -- a deployer who sets LDAP_ENABLED=true but forgets
        # the rest should see exactly what's missing in the log, at the
        # first real login attempt rather than a confusing opaque failure.
        logger.critical(
            "ldap_auth: LDAP_ENABLED is set but LDAP_SERVER_URI/LDAP_BASE_DN/"
            "LDAP_BIND_DN are not all configured -- refusing to bind. "
            "See backend/.env.example."
        )
        return None

    if not (config.use_ssl or config.start_tls) and not config.allow_insecure:
        # Fail closed on plaintext by default (voltagent review M3): a
        # deployer who follows only the minimal documented steps (server
        # URI, bind DN/password, base DN, filter) and leaves both TLS flags
        # unset would otherwise get a fully working feature that sends the
        # service account's password, and every real user's password on
        # every login, over an unencrypted connection. Same
        # opt-in-to-danger pattern as CLARION_ALLOW_CLOUD_AI.
        logger.critical(
            "ldap_auth: LDAP_ENABLED is set but LDAP_USE_SSL/LDAP_START_TLS are "
            "both unset -- refusing to bind over plaintext LDAP. Passwords "
            "would be sent in cleartext. Set one of those two, or "
            "LDAP_ALLOW_INSECURE_BIND=true to explicitly accept the risk "
            "(never in a campus/production deployment)."
        )
        return None

    escaped_username = escape_filter_chars(username)
    try:
        search_filter = config.user_search_filter.format(username=escaped_username)
    except (KeyError, IndexError):
        logger.error("ldap_auth: LDAP_USER_SEARCH_FILTER is malformed (must contain {username})")
        return None

    service_conn: Connection | None = None
    try:
        server = _make_server(config)
        service_conn = Connection(
            server,
            user=config.bind_dn,
            password=config.bind_password,
            auto_bind=False,
            receive_timeout=config.connect_timeout_seconds,
        )
        if config.start_tls:
            if not service_conn.open() or not service_conn.start_tls():
                logger.warning("ldap_auth: STARTTLS failed against %s", config.server_uri)
                return None
        if not service_conn.bind():
            logger.warning(
                "ldap_auth: service bind failed (result=%s) -- check LDAP_BIND_DN/LDAP_BIND_PASSWORD",
                service_conn.result,
            )
            return None

        service_conn.search(
            search_base=config.base_dn,
            search_filter=search_filter,
            attributes=[config.attr_email, config.attr_full_name, config.attr_memberof],
            # size_limit (voltagent review L1): the >1-match branch below
            # already denies on ambiguity, so nothing is lost by also
            # asking the SERVER to cap results -- defense-in-depth against
            # a misconfigured base_dn/filter matching a huge number of
            # entries and pulling them all into memory before that check runs.
            size_limit=5,
        )
        entries = service_conn.entries
        if len(entries) == 0:
            logger.info("ldap_auth: no directory match for filter %s", search_filter)
            return None
        if len(entries) > 1:
            logger.warning(
                "ldap_auth: %d directory matches for filter %s -- refusing to guess, denying login",
                len(entries), search_filter,
            )
            return None

        entry = entries[0]
        user_dn = entry.entry_dn
        email = _first_attr(entry, config.attr_email)
        full_name = _first_attr(entry, config.attr_full_name)
        group_dns = _all_attr(entry, config.attr_memberof)
    except Exception:  # noqa: BLE001 -- voltagent review L3: _make_server(config) (Server()
        # construction) now runs inside this block too, and its failure modes for a
        # malformed LDAP_SERVER_URI aren't guaranteed to all be LDAPException
        # subclasses. This function's contract is "never raise, always
        # degrade to None" -- narrowing this back to LDAPException would
        # reopen exactly the gap this broadening closes.
        logger.exception("ldap_auth: directory error during service bind/search")
        return None
    finally:
        if service_conn is not None:
            try:
                service_conn.unbind()
            except Exception:  # noqa: BLE001 -- cleanup must never raise, whatever ldap3 throws
                pass

    # Step 2: the actual authentication -- re-bind AS THE USER, on a fresh
    # connection, with the password the caller supplied. The service bind
    # above only ever proves the SERVICE account's credential; it says
    # nothing about this user's password.
    user_conn: Connection | None = None
    try:
        user_conn = Connection(
            server,
            user=user_dn,
            password=password,
            auto_bind=False,
            receive_timeout=config.connect_timeout_seconds,
        )
        if config.start_tls:
            if not user_conn.open() or not user_conn.start_tls():
                logger.warning("ldap_auth: STARTTLS failed on user re-bind for %s", user_dn)
                return None
        if not user_conn.bind():
            logger.info("ldap_auth: user re-bind failed for %s -- wrong password", user_dn)
            return None
    except Exception:  # noqa: BLE001 -- see the matching comment on the service-bind block above
        logger.exception("ldap_auth: directory error during user re-bind")
        return None
    finally:
        if user_conn is not None:
            try:
                user_conn.unbind()
            except Exception:  # noqa: BLE001 -- cleanup must never raise, whatever ldap3 throws
                pass

    return LdapAuthResult(dn=user_dn, email=email, full_name=full_name, group_dns=group_dns)


def resolve_role_for_groups(db: Session, group_dns: list[str]) -> tuple[str | None, str | None]:
    """Returns (role, facility) for the HIGHEST-priority LdapRoleMapping row
    whose group_dn matches (case-insensitively) one of group_dns. Returns
    (None, None) if nothing matches -- callers MUST treat that as "deny
    login", never invent a default role. `facility` is that mapping row's
    facility column (may be None even when role resolves)."""
    if not group_dns:
        return None, None
    lowered = {g.lower() for g in group_dns}
    rows = (
        db.query(models.LdapRoleMapping)
        .order_by(models.LdapRoleMapping.priority.desc())
        .all()
    )
    for row in rows:
        if row.group_dn.lower() in lowered:
            return row.role, row.facility
    return None, None
