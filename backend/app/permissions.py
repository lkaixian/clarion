"""Role -> page-access control (per facility).

This is the single source of truth for the "which console pages can this
staff role reach" feature:

  - the canonical page catalogue + which pages are admin-configurable,
  - which staff roles are governed by a RolePagePermission row,
  - the documented per-role defaults for a facility that has never opened
    the permissions matrix (lazy create-on-read, same pattern as
    routers/admin.py::_get_or_create_hospital_setting),
  - the resolver used by BOTH the server-side enforcement
    (auth.require_page_access, wired at router level in main.py) and the
    UserOut.allowed_pages payload the web console drives its nav / routing /
    post-login landing page off.

`admin` is deliberately NOT modelled as a stored row: an admin implicitly
holds every page and is never a configurable checkbox. `patient` /
`emergency_responder` are not page-gated at all -- their access is governed
only by each endpoint's own require_roles(...) gate.
"""
from typing import List

from sqlalchemy.orm import Session

from . import models

# ---------- Canonical page catalogue ----------
PAGE_PATIENTS = "patients"
PAGE_RECEPTION = "reception"
PAGE_PHARMACY = "pharmacy"
# P3.1: the shared Procedure/Laboratory/X-ray/Physiotherapy worklist -- one
# page, module-tabbed, backed by app/routers/ancillary.py.
PAGE_ANCILLARY = "ancillary"
# P3.2: the dental tooth-chart page, backed by app/routers/dental.py.
PAGE_DENTAL = "dental"
# P3.3: the billing page (charge master / bills / payments / claims),
# backed by app/routers/billing.py. Every CONFIGURABLE_STAFF_ROLE gets it
# by default -- unlike ancillary/dental it touches all four (frontdesk
# billing, consultation fees, pharmacy billing
#) -- the real write/read split is enforced by BILLING_WRITE_
# ROLES/BILLING_READ_ROLES in routers/billing.py, this page flag is only
# the coarse first gate (same two-layer pattern ancillary/dental use).
PAGE_BILLING = "billing"
# P3.6: the Reporting page (canned reports + Custom Report
# Builder), backed by app/routers/reporting.py. Management-
# facing, not a frontdesk task -- unlike billing it does NOT go to
# receptionist/pharmacist by default (see DEFAULT_ROLE_PAGES below).
PAGE_REPORTING = "reporting"
PAGE_ADMIN = "admin"

# Every page key the app knows about. `admin` last -- it's always admin-only.
ALL_PAGES: List[str] = [
    PAGE_PATIENTS, PAGE_RECEPTION, PAGE_PHARMACY, PAGE_ANCILLARY, PAGE_DENTAL, PAGE_BILLING, PAGE_REPORTING, PAGE_ADMIN,
]

# The pages an admin may assign to a non-admin staff role -- the columns of
# the permissions matrix in the web console. `admin` is intentionally
# excluded: it is ALWAYS admin-only and NEVER a configurable checkbox.
CONFIGURABLE_PAGES: List[str] = [
    PAGE_PATIENTS, PAGE_RECEPTION, PAGE_PHARMACY, PAGE_ANCILLARY, PAGE_DENTAL, PAGE_BILLING, PAGE_REPORTING,
]

# The staff roles whose page access is governed by a RolePagePermission row
# (the rows of the permissions matrix). Deliberately excludes:
#   - admin               (implicitly every page, not configurable)
#   - patient             (not page-gated -- self-service routes only)
#   - emergency_responder (not page-gated -- unauthenticated scan flow)
CONFIGURABLE_STAFF_ROLES = ("clinician", "records_officer", "receptionist", "pharmacist")

# Default allowed_pages for a facility that has no RolePagePermission row for
# a given role yet -- see models.RolePagePermission's docstring. Lazily
# written to a real row on first read (get_or_create_role_permission).
DEFAULT_ROLE_PAGES = {
    # A clinician now works out of the dedicated Consultation page (its
    # "Start session" = clock-in + claim-a-room in one step), which lives on
    # the `patients` router-gate -- they no longer need the front-desk
    # Reception page at all. admin / records_officer still get `reception`
    # (they cover the desk). See rewrite_legacy_clinician_pages below for the
    # one-time migration of already-stored rows that hold the OLD default.
    # P3.1: clinicians perform/sign results and can also place a
    # physician-order request; records_officer and receptionist can both
    # register a patient into a module directly from Frontdesk (every
    # ancillary clause explicitly allows this) but
    # only clinician/records_officer may sign a result off
    # (routers/ancillary.py::sign_off_service_request role gate) --
    # receptionist's page access only lets them place/cancel orders.
    # P3.2: dental chart entries are a clinical write/read, same
    # clinician/records_officer-only split as ancillary sign-off -- a
    # receptionist places/cancels ancillary orders but has no dental-chart
    # role at all (the dental clause's "Patient Management" piece is queue/
    # appointments, already covered by reception + PAGE_RECEPTION).
    # P3.3: billing touches every configurable staff role at least for
    # reading (clinician "views... fees", pharmacist "pharmacy
    # billing") -- routers/billing.py's BILLING_WRITE_ROLES/
    # BILLING_READ_ROLES do the real per-endpoint split.
    # P3.6: reporting is a clinician/records_officer tool (disease-specific
    # views, TAT, admission summaries) -- deliberately NOT given to
    # receptionist/pharmacist by default, same "not every role gets every
    # page" split as ancillary/dental (an admin can still grant it).
    "clinician": [PAGE_PATIENTS, PAGE_ANCILLARY, PAGE_DENTAL, PAGE_BILLING, PAGE_REPORTING],
    "records_officer": [PAGE_PATIENTS, PAGE_RECEPTION, PAGE_ANCILLARY, PAGE_DENTAL, PAGE_BILLING, PAGE_REPORTING],
    "receptionist": [PAGE_RECEPTION, PAGE_ANCILLARY, PAGE_BILLING],
    "pharmacist": [PAGE_PHARMACY, PAGE_BILLING],
}

# The exact OLD stored default for a clinician row, before the Consultation
# page landed -- see rewrite_legacy_clinician_pages.
_LEGACY_CLINICIAN_PAGES = [PAGE_PATIENTS, PAGE_RECEPTION]

# The exact OLD stored defaults (per role), before PAGE_ANCILLARY (P3.1)
# existed -- see add_ancillary_to_legacy_role_pages. Deliberately the
# pre-ancillary values of DEFAULT_ROLE_PAGES above, not derived from it, so
# this stays correct even if DEFAULT_ROLE_PAGES changes again later.
_PRE_ANCILLARY_ROLE_PAGES = {
    "clinician": [PAGE_PATIENTS],
    "records_officer": [PAGE_PATIENTS, PAGE_RECEPTION],
    "receptionist": [PAGE_RECEPTION],
}

# The exact OLD stored defaults (per role), before PAGE_DENTAL (P3.2)
# existed -- see add_dental_to_legacy_role_pages. Deliberately the
# pre-dental (but post-ancillary) values of DEFAULT_ROLE_PAGES above, not
# derived from it, for the same reason _PRE_ANCILLARY_ROLE_PAGES isn't.
# receptionist isn't listed: PAGE_DENTAL was never added to its default, so
# there's nothing to backfill there.
_PRE_DENTAL_ROLE_PAGES = {
    "clinician": [PAGE_PATIENTS, PAGE_ANCILLARY],
    "records_officer": [PAGE_PATIENTS, PAGE_RECEPTION, PAGE_ANCILLARY],
}

# The exact OLD stored defaults (per role), before PAGE_BILLING (P3.3)
# existed -- see add_billing_to_legacy_role_pages. Deliberately the
# pre-billing (but post-dental) values of DEFAULT_ROLE_PAGES above, not
# derived from it, for the same reason _PRE_ANCILLARY_ROLE_PAGES/
# _PRE_DENTAL_ROLE_PAGES aren't. Unlike those two, ALL FOUR configurable
# staff roles get PAGE_BILLING added, so all four are listed here.
_PRE_BILLING_ROLE_PAGES = {
    "clinician": [PAGE_PATIENTS, PAGE_ANCILLARY, PAGE_DENTAL],
    "records_officer": [PAGE_PATIENTS, PAGE_RECEPTION, PAGE_ANCILLARY, PAGE_DENTAL],
    "receptionist": [PAGE_RECEPTION, PAGE_ANCILLARY],
    "pharmacist": [PAGE_PHARMACY],
}

# The exact OLD stored defaults (per role), before PAGE_REPORTING (P3.6)
# existed -- see add_reporting_to_legacy_role_pages. Deliberately the
# pre-reporting (but post-billing) values of DEFAULT_ROLE_PAGES above, same
# reasoning as every _PRE_* table before it. receptionist/pharmacist aren't
# listed: PAGE_REPORTING was never added to their default, nothing to
# backfill there.
_PRE_REPORTING_ROLE_PAGES = {
    "clinician": [PAGE_PATIENTS, PAGE_ANCILLARY, PAGE_DENTAL, PAGE_BILLING],
    "records_officer": [PAGE_PATIENTS, PAGE_RECEPTION, PAGE_ANCILLARY, PAGE_DENTAL, PAGE_BILLING],
}

# What an admin token resolves to -- every page, including `admin` itself.
ADMIN_PAGES: List[str] = list(ALL_PAGES)


def default_pages_for(role: str) -> List[str]:
    """The documented default page list for a configurable staff role
    (empty for anything else). Always a fresh list -- callers mutate/store
    it."""
    return list(DEFAULT_ROLE_PAGES.get(role, []))


def _canonical_order(pages) -> List[str]:
    """De-dupe + force canonical page order, dropping anything not in
    CONFIGURABLE_PAGES -- so a stored allowed_pages list is always clean
    regardless of what order/duplicates a client sent."""
    wanted = set(pages or [])
    return [p for p in CONFIGURABLE_PAGES if p in wanted]


def get_or_create_role_permission(db: Session, facility: str, role: str) -> "models.RolePagePermission":
    """Lazily create-on-read a RolePagePermission row for (facility, role)
    with the documented defaults -- exact same pattern as
    routers/admin.py::_get_or_create_hospital_setting."""
    row = (
        db.query(models.RolePagePermission)
        .filter(
            models.RolePagePermission.facility_name == facility,
            models.RolePagePermission.role == role,
        )
        .first()
    )
    if row is None:
        row = models.RolePagePermission(
            facility_name=facility,
            role=role,
            allowed_pages=default_pages_for(role),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def rewrite_legacy_clinician_pages(db: Session) -> int:
    """One-time, best-effort migration: every stored RolePagePermission row
    for role=='clinician' whose allowed_pages is EXACTLY the old default
    ["patients","reception"] is rewritten to the new default ["patients"].

    Deliberately only touches rows that still hold the exact legacy default
    -- a facility that customised its clinician row (added pharmacy, removed
    patients, whatever) is left completely alone. Idempotent: a second run
    finds nothing left to change. Called from seed.py's idempotent block;
    safe to call anytime.
    """
    changed = 0
    rows = (
        db.query(models.RolePagePermission)
        .filter(models.RolePagePermission.role == "clinician")
        .all()
    )
    for row in rows:
        if list(row.allowed_pages or []) == _LEGACY_CLINICIAN_PAGES:
            row.allowed_pages = [PAGE_PATIENTS]
            changed += 1
    if changed:
        db.commit()
    return changed


def add_ancillary_to_legacy_role_pages(db: Session) -> int:
    """One-time, best-effort migration companion to
    rewrite_legacy_clinician_pages: every stored RolePagePermission row for a
    role in _PRE_ANCILLARY_ROLE_PAGES whose allowed_pages is EXACTLY that
    role's pre-P3.1 default gets PAGE_ANCILLARY appended.

    Deliberately only touches rows that still hold the exact legacy default
    -- a facility that customised its row (added/removed a page) is left
    completely alone, same discipline as rewrite_legacy_clinician_pages.
    Idempotent: a second run finds nothing left to change. Called from
    seed.py's idempotent block; safe to call anytime.
    """
    changed = 0
    rows = (
        db.query(models.RolePagePermission)
        .filter(models.RolePagePermission.role.in_(list(_PRE_ANCILLARY_ROLE_PAGES)))
        .all()
    )
    for row in rows:
        legacy = _PRE_ANCILLARY_ROLE_PAGES.get(row.role)
        if legacy is not None and list(row.allowed_pages or []) == legacy:
            row.allowed_pages = _canonical_order(legacy + [PAGE_ANCILLARY])
            changed += 1
    if changed:
        db.commit()
    return changed


def add_dental_to_legacy_role_pages(db: Session) -> int:
    """One-time, best-effort migration companion to
    add_ancillary_to_legacy_role_pages: every stored RolePagePermission row
    for a role in _PRE_DENTAL_ROLE_PAGES whose allowed_pages is EXACTLY that
    role's pre-P3.2 default gets PAGE_DENTAL appended. Same
    only-touch-still-default discipline; idempotent; called from seed.py's
    idempotent block. See docs/deployment.md's "Role permissions on
    upgrade" note -- this call is NOT wired into the automatic upgrade
    path, only seed.py's first-run path, same as add_ancillary_to_legacy_role_pages.
    """
    changed = 0
    rows = (
        db.query(models.RolePagePermission)
        .filter(models.RolePagePermission.role.in_(list(_PRE_DENTAL_ROLE_PAGES)))
        .all()
    )
    for row in rows:
        legacy = _PRE_DENTAL_ROLE_PAGES.get(row.role)
        if legacy is not None and list(row.allowed_pages or []) == legacy:
            row.allowed_pages = _canonical_order(legacy + [PAGE_DENTAL])
            changed += 1
    if changed:
        db.commit()
    return changed


def add_billing_to_legacy_role_pages(db: Session) -> int:
    """One-time, best-effort migration companion to
    add_dental_to_legacy_role_pages: every stored RolePagePermission row
    for a role in _PRE_BILLING_ROLE_PAGES whose allowed_pages is EXACTLY
    that role's pre-P3.3 default gets PAGE_BILLING appended. Same
    only-touch-still-default discipline; idempotent; called from seed.py's
    idempotent block, not the automatic upgrade path (see docs/
    deployment.md's "Role permissions on upgrade" note).
    """
    changed = 0
    rows = (
        db.query(models.RolePagePermission)
        .filter(models.RolePagePermission.role.in_(list(_PRE_BILLING_ROLE_PAGES)))
        .all()
    )
    for row in rows:
        legacy = _PRE_BILLING_ROLE_PAGES.get(row.role)
        if legacy is not None and list(row.allowed_pages or []) == legacy:
            row.allowed_pages = _canonical_order(legacy + [PAGE_BILLING])
            changed += 1
    if changed:
        db.commit()
    return changed


def add_reporting_to_legacy_role_pages(db: Session) -> int:
    """One-time, best-effort migration companion to
    add_billing_to_legacy_role_pages: every stored RolePagePermission row
    for a role in _PRE_REPORTING_ROLE_PAGES whose allowed_pages is EXACTLY
    that role's pre-P3.6 default gets PAGE_REPORTING appended. Same
    only-touch-still-default discipline; idempotent; called from seed.py's
    idempotent block, not the automatic upgrade path.
    """
    changed = 0
    rows = (
        db.query(models.RolePagePermission)
        .filter(models.RolePagePermission.role.in_(list(_PRE_REPORTING_ROLE_PAGES)))
        .all()
    )
    for row in rows:
        legacy = _PRE_REPORTING_ROLE_PAGES.get(row.role)
        if legacy is not None and list(row.allowed_pages or []) == legacy:
            row.allowed_pages = _canonical_order(legacy + [PAGE_REPORTING])
            changed += 1
    if changed:
        db.commit()
    return changed


def allowed_pages_for(db: Session, facility, role: str) -> List[str]:
    """Resolved allowed-page list for a (facility, role):
      - admin                         -> every page (ALL_PAGES, incl. "admin")
      - a CONFIGURABLE_STAFF_ROLE     -> its stored row (lazy default if none)
      - patient / emergency_responder -> [] (not page-gated)
    A configurable staff role with no facility assigned falls back to the
    documented default without writing a row (there's no facility to key
    one on)."""
    if role == "admin":
        return list(ADMIN_PAGES)
    if role not in CONFIGURABLE_STAFF_ROLES:
        return []
    if not facility:
        return default_pages_for(role)
    row = get_or_create_role_permission(db, facility, role)
    return list(row.allowed_pages or [])
