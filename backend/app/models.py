import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Text, Boolean, JSON, Integer, Index,
    UniqueConstraint, Float, Computed, BigInteger
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import relationship, validates

from .database import Base
from .nric import normalize_nric


def gen_id():
    return str(uuid.uuid4())


# P1.2b: a DateTime that keeps microsecond precision on MySQL/MariaDB. The
# plain SQLAlchemy DateTime renders there as bare `DATETIME` -- zero fractional
# seconds, and `timezone=True` is silently ignored -- so MariaDB *rounds* a
# sub-second value on write (can push `password_changed_at` past a JWT issued
# in the same second) and `ORDER BY` on any timestamp column becomes unstable.
# On SQLite this renders identically to `DateTime(timezone=True)`, so the
# Alembic baseline generated on SQLite is unaffected. Use this everywhere a
# timestamp column is declared.
TZDateTime = DateTime(timezone=True).with_variant(mysql.DATETIME(fsp=6), "mysql")


# Patient-profile fields that are worth nudging a patient to fill in right
# after login if still blank (missing_profile_fields on schemas.UserOut).
# Deliberately a plain list, not hardcoded logic per-field, so a future
# column addition (e.g. a 5th contact field) only ever means appending here
# â€” see auth_router.py's use of this for the "informational, not a security
# gate" computation.
PATIENT_PROFILE_FIELDS_TO_PROMPT = [
    "email",
    "phone",
    "emergency_contact_name",
    "emergency_contact_phone",
]


class User(Base):
    """A hospital staff account, a patient account, or an emergency-responder
    account. `role` drives what a token can see (see auth.py / permissions.py)."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=gen_id)
    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(64), nullable=False)  # admin | clinician | records_officer | receptionist | patient | emergency_responder | pharmacist
    facility = Column(String(255), nullable=True)
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=True, index=True)  # set if role == patient

    # Per-counter reception scoping (Malaysian government hospitals split
    # front-desk registration into specialty counters -- ICU, O&G, ortho,
    # general registration, emergency). When set to a FacilitySection.name at
    # this user's own facility, this receptionist/clinician's reception
    # console is HARD-SCOPED to that section: they only see / can act on
    # QueueTickets whose `department` matches, check-ins they run are forced
    # to that department regardless of what the client sends, and the room
    # board hides other sections' tagged rooms. NULL = not scoped (unchanged
    # behaviour -- sees the whole facility's queue). Only `receptionist` and
    # `clinician` accounts are ever assignable (admin.py enforces). It's a
    # plain denormalised string, not an FK: historical QueueTicket.department
    # values are point-in-time and a section rename fixes up assigned users
    # explicitly (see routers/admin.py's PATCH /admin/sections). Additive
    section = Column(String(64), nullable=True)

    # True right after a staff-issued temp password or a self-service reset,
    # cleared once the user successfully calls /auth/change-password. Lets
    # clients force a "you must change your password" screen.
    must_change_password = Column(Boolean, nullable=False, default=False)

    # Vestigial: rate limiting for the old self-service NRIC+DOB
    # /auth/forgot-password flow, which has been REMOVED and replaced by
    # the email-OTP reset (otp_* columns below). Left in place (unused by
    # any endpoint now, just zeroed by _apply_new_password for hygiene)
    # rather than dropped, since this project's migrations are additive
    # drop isn't worth the risk against a live seeded DB.
    reset_attempt_count = Column(Integer, nullable=False, default=0)
    reset_locked_until = Column(TZDateTime, nullable=True)

    # POST /auth/login failed-attempt rate limiting/lockout. Deliberately
    # separate columns from reset_attempt_count/reset_locked_until above â€”
    # those were scoped to the now-removed NRIC+DOB self-service
    # forgot-password flow only; these track wrong-password attempts
    # against this account's actual login. Keeping them independent means
    # a user locked out of one
    # flow isn't automatically locked out of the other, and vice versa.
    # Persisted (not in-memory) so it survives process restarts and works
    # correctly if the backend ever runs multiple workers.
    login_failed_count = Column(Integer, nullable=False, default=0)
    login_locked_until = Column(TZDateTime, nullable=True)

    # Password-reset-via-email-OTP state (POST /auth/request-password-reset-otp
    # and POST /auth/reset-password-with-otp). Only ever the HASH of the
    # 6-digit code is stored, never the plaintext â€” mirrors hashed_password.
    # otp_attempt_count is the *verify* attempt counter (wrong codes against
    # a live OTP); it is distinct from otp_request_count/otp_request_window_start
    # below, which rate-limit how often a fresh OTP can be *requested* in the
    # first place (stops email-bombing a patient's inbox). Both persisted
    # (not in-memory) so they survive process restarts, same reasoning as
    # reset_attempt_count/login_failed_count above.
    otp_code_hash = Column(String(255), nullable=True)
    otp_expires_at = Column(TZDateTime, nullable=True)
    otp_attempt_count = Column(Integer, nullable=False, default=0)
    otp_request_count = Column(Integer, nullable=False, default=0)
    otp_request_window_start = Column(TZDateTime, nullable=True)

    # JWT revocation-on-password-change watermark. Set by
    # auth_router._apply_new_password every time a password is actually
    # changed (staff-issued temp password, self-service OTP reset, or a
    # voluntary authenticated change). Nullable/defaulted to None so
    # existing rows from before this column existed have no watermark --
    # auth._resolve_current_user treats None as "nothing to compare
    # against, don't reject" rather than retroactively invalidating every
    # already-issued token the moment this migration lands. A token's
    # embedded `pwd_changed_at` claim (see auth.create_access_token) is
    # only ever rejected once an ACTUAL subsequent password change sets
    # this to a newer timestamp than what the token was issued with.
    password_changed_at = Column(TZDateTime, nullable=True)

    # Object key of this staff member's saved digital signature PNG in the
    # `clarion-signatures` bucket (see app/storage.py), key
    # `users/{user_id}.png`, set by POST /me/signature, cleared by
    # DELETE /me/signature. Consultation / annotation sign-off COPY this
    # object to their own per-row snapshot at signing time. sha256/bytes/mime
    # are captured on write so the file is served + integrity-checked without
    # touching the blob. All nullable/additive (P1.6).
    signature_object_key = Column(String(512), nullable=True)
    signature_sha256 = Column(String(64), nullable=True)
    signature_bytes = Column(Integer, nullable=True)
    signature_mime = Column(String(128), nullable=True)

    # P1.10: which auth provider owns this account's credential. "local"
    # (default) means hashed_password (above) is the real, user-chosen
    # credential and the normal POST /auth/login password check applies.
    # "ldap" means this row was JIT-provisioned from (or has since been
    # matched to) a directory account -- hashed_password is a random,
    # never-issued placeholder (see app/ldap_auth.py), and auth_router.login
    # skips the local password check entirely in favour of an LDAP bind. A
    # server_default keeps this NOT NULL migration additive against
    # existing rows (all backfill to "local", their real/only behaviour).
    # See app/ldap_auth.py and healthcare/Integration Engine and LDAP.md.
    auth_source = Column(String(32), nullable=False, server_default="local")
    # Cached directory DN for audit/debugging only -- never used to bypass
    # the search-then-bind flow on a subsequent login (ldap_auth always
    # re-searches by the configured filter, so a renamed/moved directory
    # entry is picked up rather than silently trusted from a stale cache).
    ldap_dn = Column(String(512), nullable=True)
    # THE stable identity key for an auth_source="ldap" row: the EXACT raw
    # string the person types as their login username, captured once at
    # JIT-provision time. Deliberately NOT `email` -- `email` is populated
    # from the directory's `mail` attribute (informational/display only),
    # which is only guaranteed to equal the login string under the default
    # `LDAP_USER_SEARCH_FILTER=(mail={username})`. A realistic AD deployment
    # (the actual tender target) logs staff in by `sAMAccountName`/`uid`,
    # which is a DIFFERENT string from their `mail` attribute -- keying
    # lookups on `email` there breaks re-login (a second attempt can't find
    # the row it created on first login, tries to JIT-provision again, and
    # collides on the `email` unique constraint) and breaks the "revoked AD
    # group takes effect on next login" resync entirely (searching the
    # directory BY `user.email` finds nothing under a non-mail filter).
    # `ldap_auth.authenticate_ldap` is always called with THIS value (never
    # `user.email`) once a row exists, so the search is exactly what
    # resolved the account in the first place. Unique (nullable-safe on
    # both SQLite/MariaDB, same technique as RoomClaim's generated-column
    # uniqueness) so a race between two concurrent first-logins for the
    # same new identity fails the SECOND insert with IntegrityError instead
    # of silently provisioning two rows for one person.
    ldap_username = Column(String(255), unique=True, nullable=True)

    patient = relationship("Patient", back_populates="user_account", foreign_keys=[patient_id])


class LdapRoleMapping(Base):
    """Admin-editable AD-group -> CLARION-role mapping (P1.10, tender clause
). Read by app.ldap_auth.resolve_role_for_groups against a
    logging-in user's `memberOf` list. `group_dn` is matched
    case-insensitively in code (LDAP DNs are case-insensitive per RFC 4514,
    but this column stores the literal directory casing for admin
    readability). `priority` breaks ties when a user is in multiple mapped
    groups -- highest wins, so e.g. an "AD-Admins" group can be given a
    higher priority than "AD-Clinicians" for a user in both. `facility` is
    optional: when set, it's applied to a user JIT-provisioned (or
    re-synced) from this group, letting one AD group pin its members to a
    specific campus/hospital; NULL leaves facility unset/unchanged."""
    __tablename__ = "ldap_role_mappings"

    id = Column(String(36), primary_key=True, default=gen_id)
    group_dn = Column(String(512), unique=True, nullable=False)
    role = Column(String(64), nullable=False)  # validated against schemas.VALID_ROLES at the API layer
    facility = Column(String(255), nullable=True)
    priority = Column(Integer, nullable=False, default=0)
    created_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        TZDateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class RefreshToken(Base):
    """P2.5 (Security Audit M4): a long-lived (REFRESH_TOKEN_EXPIRE_DAYS)
    credential that lets a client mint a fresh short-lived access JWT
    (ACCESS_TOKEN_EXPIRE_MINUTES, down from 8h to 15min) without a full
    re-login -- see app/auth.py's issue/rotate/revoke_refresh_token
    functions, the only code that ever touches this table.

    Only ever the HMAC-SHA256 hash of the token is stored (`token_hash`,
    same discipline as User.otp_code_hash) -- the plaintext exists only
    transiently: returned once in the login/refresh response body (native
    clients) and set once as an HttpOnly cookie (web), never persisted
    server-side and never logged.

    Rotation, not reuse: every successful POST /auth/refresh revokes THIS
    row (`revoked_at`) and issues a brand new one (`replaced_by_id` points
    at it, forensic-only -- nothing reads that column at auth time). A
    caller that presents an ALREADY-revoked token is proof of either a
    replay of an old request or a stolen/duplicated token still in use
    after the legitimate client rotated past it -- app.auth.rotate_refresh_token
    treats that as a compromise signal and revokes EVERY refresh token for
    the user, forcing a fresh login on every device.

    A password change (auth_router._apply_new_password) also revokes every
    live row for that user -- "change your password" now really does mean
    "log out everywhere", closing the other half of what Security Audit M4
    named (the JWT-only revocation watermark did this for the 8h access
    token; this does it for a session's ability to keep refreshing)."""
    __tablename__ = "refresh_tokens"

    id = Column(String(36), primary_key=True, default=gen_id)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    issued_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(TZDateTime, nullable=False, index=True)
    revoked_at = Column(TZDateTime, nullable=True)
    # Rotation chain pointer -- "what did this token get rotated into".
    # Primarily a forensic/audit trail, but auth.rotate_refresh_token DOES
    # read it at auth time (code-review follow-up 2026-09-07): its presence
    # distinguishes a rotated token from a logged-out / bulk-revoked one, and
    # _is_concurrent_refresh_race follows it one hop to check the chain head.
    # Nullable self-FK; no ondelete action needed since a row is never
    # hard-deleted.
    replaced_by_id = Column(String(36), ForeignKey("refresh_tokens.id"), nullable=True)
    # Coarse device fingerprint (sha256 of the User-Agent) captured when this
    # token was issued. Used ONLY to tighten the concurrent-refresh-race
    # grace (auth._is_concurrent_refresh_race): a reuse whose request comes
    # from a different fingerprint than the token was issued to is NOT
    # graced. NULL for a native client with no UA, or a pre-migration token
    # -- the check is skipped in that case, never fails closed on it.
    client_fingerprint = Column(String(64), nullable=True)

    user = relationship("User")


class Patient(Base):
    __tablename__ = "patients"

    id = Column(String(36), primary_key=True, default=gen_id)
    full_name = Column(String(255), nullable=False)
    date_of_birth = Column(String(64), nullable=False)  # ISO date
    gender = Column(String(64), nullable=True)
    national_id = Column(String(64), unique=True, nullable=True)
    # Security Audit M2: dash/case-normalized mirror of national_id (see
    # nric.normalize_nric), indexed + unique, so every NRIC lookup
    # (auth_router._resolve_patient_by_nric, used by login, both OTP
    # endpoints, and reused by patients.py/reception.py) is an indexed
    # query instead of a fetch-every-patient-and-compare-in-Python loop --
    # that loop ran on every unauthenticated login/OTP-reset attempt
    # regardless of a per-IP limit, so its cost scaled with total patient
    # count. Kept in sync automatically by the @validates hook below
    # (fires on ANY assignment to national_id -- ORM construction, a
    # later `.national_id = x`, a test fixture -- not just the one real
    # write path today) rather than requiring every call site to remember
    # to set it by hand; existing rows backfilled by Alembic
    # `649f25aeb36f`. NULL when national_id is NULL/blank (normalize_nric
    # of an empty string is "", stored as None here, never as "", so
    # multiple NULL-NRIC patients don't collide on the unique constraint).
    normalized_national_id = Column(String(64), unique=True, nullable=True, index=True)
    blood_type = Column(String(64), nullable=True)
    phone = Column(String(64), nullable=True)
    senior_citizen_mode = Column(Boolean, default=False)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))

    # Patient-owned contact/profile fields, editable via the self-service
    # PATCH /patients/{id}/profile endpoint. Deliberately separate from
    # User.email, which stays the internal login-identifier/synthetic-
    # placeholder field (e.g. "patient-<id>@clarion.local") and is never
    # shown to or edited by the patient directly. `email` here is where the
    # password-reset OTP is actually sent.
    email = Column(String(255), nullable=True)
    emergency_contact_name = Column(String(255), nullable=True)
    emergency_contact_phone = Column(String(64), nullable=True)
    emergency_contact_relationship = Column(String(64), nullable=True)

    @validates("national_id")
    def _sync_normalized_national_id(self, key, value):
        """Keeps normalized_national_id in lockstep with every assignment
        to national_id -- see that column's docstring above. Returns
        `value` unchanged (a SQLAlchemy @validates hook's return value is
        what actually gets stored in the validated column)."""
        self.normalized_national_id = normalize_nric(value) if value else None
        return value

    user_account = relationship("User", back_populates="patient", uselist=False, foreign_keys=[User.patient_id])
    conditions = relationship("Condition", back_populates="patient", cascade="all, delete-orphan")
    medications = relationship("MedicationStatement", back_populates="patient", cascade="all, delete-orphan")
    allergies = relationship("AllergyIntolerance", back_populates="patient", cascade="all, delete-orphan")
    encounters = relationship("Encounter", back_populates="patient", cascade="all, delete-orphan")
    documents = relationship("ClinicalDocument", back_populates="patient", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="patient", cascade="all, delete-orphan")


class Encounter(Base):
    """FHIR Encounter-lite: one visit / transfer event at a facility."""
    __tablename__ = "encounters"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    # Also the AUTHORING facility for cross-facility PATCH immutability (see
    # Condition.authored_by_facility) -- add_encounter forces it from
    # current_user.facility on create. NULL legacy rows are PATCH-immutable
    # to everyone by design. Indexed: it's one of the
    # _FACILITY_RELATIONSHIP_SOURCES scanned by list_patients' facility scope.
    facility_name = Column(String(255), nullable=False, index=True)
    encounter_type = Column(String(64), nullable=False)  # outpatient | inpatient | emergency | transfer
    reason = Column(Text, nullable=True)
    started_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
    notes = Column(Text, nullable=True)

    # --- Consultation sign-off (routers/consultation.py::complete_ticket) ---
    signed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    signed_by_name = Column(String(255), nullable=True)
    signed_by_role = Column(String(64), nullable=True)
    
    # A COPY of the signer's profile signature PNG taken at sign-off time,
    # `clarion-signatures` bucket, key `encounters/{id}.png` (see
    # app/storage.py), so it stays fixed even if the clinician later
    # changes/clears their profile signature. (P1.6)
    signature_object_key = Column(String(512), nullable=True)
    signature_sha256 = Column(String(64), nullable=True)
    signature_bytes = Column(Integer, nullable=True)
    signature_mime = Column(String(128), nullable=True)

    patient = relationship("Patient", back_populates="encounters")


class Condition(Base):
    __tablename__ = "conditions"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    status = Column(String(64), default="active")  # active | resolved
    diagnosed_at = Column(String(64), nullable=True)
    is_chronic = Column(Boolean, default=False)
    critical_for_emergency = Column(Boolean, default=False)
    # The facility whose staff AUTHORED this row (snapshot of
    # current_user.facility at create time -- see routers/patients.py
    # ::add_condition). Drives cross-facility PATCH immutability: a clinical
    # sub-record may only be amended in place by its authoring facility while
    # the patient is currently present there; everyone else must append a new
    # entry instead. Nullable/additive: legacy rows created before this
    # column existed have NULL here and are therefore immutable to EVERYONE
    # via PATCH (rule #1 -- "your facility == the author facility" -- can
    # never be satisfied against NULL), which is the intended safe default.
    authored_by_facility = Column(String(255), nullable=True, index=True)

    patient = relationship("Patient", back_populates="conditions")


class MedicationStatement(Base):
    __tablename__ = "medication_statements"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    drug_name = Column(String(255), nullable=False)
    dosage = Column(String(64), nullable=True)
    frequency = Column(String(64), nullable=True)
    # The facility that PRESCRIBED this drug -- frequently an EXTERNAL one
    # (a clinic the patient also attends), which is the whole point of the
    # cross-facility duplicate-prescription check. Client-supplied on create,
    # editable on PATCH. Deliberately NOT the immutability key (that would
    # forbid recording an external prescriber and hand edit rights to a
    # facility that never touched this record) -- see recorded_by_facility.
    prescribed_by_facility = Column(String(255), nullable=True)
    # The facility whose staff ACTUALLY ENTERED this row (snapshot of
    # current_user.facility at create time). This is the authoring facility
    # for cross-facility PATCH immutability -- same semantics as
    # Condition.authored_by_facility. Nullable/additive: NULL legacy rows are
    # PATCH-immutable to everyone by design.
    recorded_by_facility = Column(String(255), nullable=True, index=True)
    start_date = Column(String(64), nullable=True)
    active = Column(Boolean, default=True)
    critical_for_emergency = Column(Boolean, default=True)

    patient = relationship("Patient", back_populates="medications")


class AllergyIntolerance(Base):
    __tablename__ = "allergy_intolerances"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    substance = Column(String(255), nullable=False)
    reaction = Column(String(255), nullable=True)
    severity = Column(String(64), default="unknown")  # mild | moderate | severe
    critical_for_emergency = Column(Boolean, default=True)
    # Authoring facility -- same semantics as Condition.authored_by_facility
    # above (cross-facility PATCH immutability; NULL legacy rows are
    # PATCH-immutable to everyone by design).
    authored_by_facility = Column(String(255), nullable=True, index=True)

    patient = relationship("Patient", back_populates="allergies")


class ClinicalDocument(Base):
    """A raw or AI-digitised document (scanned prescription, discharge summary,
    X-ray report). `extracted_text` / `ai_summary` are filled by the AI layer."""
    __tablename__ = "clinical_documents"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_type = Column(String(64), nullable=False)  # prescription | discharge_summary | lab_report | imaging
    original_filename = Column(String(255), nullable=True)
    raw_text = Column(Text, nullable=True)          # OCR output
    ai_summary = Column(Text, nullable=True)         # LLM/rule-based summary
    uploaded_by_facility = Column(String(255), nullable=True)
    uploaded_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))

    # Object key of the original uploaded file in the `clarion-documents`
    # bucket (see app/storage.py), key
    # `{patient_id}/{id}_{sanitized_basename}`, set by
    # POST /ai/digitise/{patient_id} best-effort after OCR. NULL if never
    # persisted -- always check for NULL before serving. Key is built
    # server-side from the row id + a sanitized basename; never client input.
    # (P1.6)
    file_object_key = Column(String(512), nullable=True)
    file_sha256 = Column(String(64), nullable=True)
    file_bytes = Column(Integer, nullable=True)
    file_mime = Column(String(128), nullable=True)

    patient = relationship("Patient", back_populates="documents")


class Appointment(Base):
    """A doctor-published appointment (follow-up, procedure, etc.) for a
    patient. Reminder timing is deliberately NOT stored here as concrete
    scheduled rows -- it's computed on read from this row's own fields
    (scheduled_at, fasting_required/fasting_hours, extra_reminder_hours_before)
    via appointments.compute_reminder_offsets, so there's a single source of
    truth for "when do reminders fire" that can't drift out of sync with an
    edited appointment (e.g. a PATCH that reschedules scheduled_at
    automatically shifts every computed reminder with it -- no separate rows
    to reconcile)."""
    __tablename__ = "appointments"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    facility_name = Column(String(255), nullable=False, index=True)
    venue = Column(String(255), nullable=True)             # room/building detail beyond facility_name
    scheduled_at = Column(TZDateTime, nullable=False)
    reason = Column(String(255), nullable=True)             # e.g. "Follow-up: diabetes review"
    precaution_notes = Column(Text, nullable=True)      # free-text, e.g. "bring prior scan results"
    fasting_required = Column(Boolean, default=False)
    fasting_hours = Column(Integer, nullable=True)      # meaningful only if fasting_required
    extra_reminder_hours_before = Column(JSON, nullable=True)  # list[int], doctor-added reminder offsets beyond the computed defaults, e.g. [72] for a 3-day-before reminder
    status = Column(String(64), default="scheduled")         # scheduled | cancelled | completed
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))

    # Reschedule tracking -- set together, only by
    # routers/appointments.py::reschedule_appointment (staff-only). Only the
    # single MOST RECENT reschedule is snapshotted (previous_scheduled_at is
    # overwritten on a second reschedule, not appended to a history list) --
    # this app has no "appointment history" screen for anything else either,
    # so a full audit trail beyond "what was it before the latest change"
    # would be scope with no current consumer. AuditLog already captures
    # every reschedule event permanently if a real history is ever needed.
    previous_scheduled_at = Column(TZDateTime, nullable=True)
    reschedule_reason_code = Column(String(64), nullable=True)  # see schemas.STAFF_RESCHEDULE_REASON_CODES
    reschedule_reason_other = Column(Text, nullable=True)  # only meaningful when reschedule_reason_code == "other"

    patient = relationship("Patient", back_populates="appointments")


class AppointmentRescheduleRequest(Base):
    """A patient's request to reschedule one of their own doctor-published
    Appointments (see routers/appointments.py). Deliberately does NOT let
    the patient propose, or the system apply, a new time directly --
    accepting a request only records "staff will call the patient to agree
    a new time"; the appointment's actual scheduled_at only ever moves
    through the same staff-only reschedule action a clinician uses when
    rescheduling unprompted (see Appointment.previous_scheduled_at above),
    once a new time has been agreed by phone. This mirrors how the reason
    this feature exists at all: the app is not meant to let a reschedule
    happen without the clinic actually speaking to the patient first.

    At most one PENDING request per appointment is enforced at the router
    level (not a DB constraint, same style as ReceptionStation's
    "one active per facility" rule) -- a patient must wait for staff to
    accept/reject the existing one before filing another."""

    __tablename__ = "appointment_reschedule_requests"

    id = Column(String(36), primary_key=True, default=gen_id)
    appointment_id = Column(String(36), ForeignKey("appointments.id"), nullable=False, index=True)
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False)
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    reason_code = Column(String(64), nullable=False)  # see schemas.PATIENT_RESCHEDULE_REASON_CODES
    reason_other = Column(Text, nullable=True)  # only meaningful when reason_code == "other"
    status = Column(String(64), nullable=False, default="pending")  # pending | accepted | rejected
    clinician_note = Column(Text, nullable=True)  # optional, set on reject (or accept) to explain the decision
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(TZDateTime, nullable=True)
    resolved_by = Column(String(36), ForeignKey("users.id"), nullable=True)


class MedicineInventoryItem(Base):
    """Facility-scoped medicine stock row, managed by that facility's own
    `admin` user (see routers/admin.py for the "manager admin, not super
    admin" scoping this and Ward both exist to demonstrate -- every
    query/write here is filtered/forced to the acting admin's own
    `User.facility`). Deliberately has NO relationship to `Patient` --
    this is inventory bookkeeping for a hospital, not clinical history tied
    to any one patient, so it doesn't belong under a patient record at all."""
    __tablename__ = "medicine_inventory"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    drug_name = Column(String(255), nullable=False)
    quantity_on_hand = Column(Integer, nullable=False, default=0)
    unit = Column(String(64), nullable=False, default="units")  # e.g. "tablets", "vials", "boxes"
    reorder_threshold = Column(Integer, nullable=True)  # null = no low-stock tracking for this item
    notes = Column(Text, nullable=True)
    last_restocked_at = Column(TZDateTime, nullable=True)
    # Optional scanned/keyed barcode (EAN/UPC/etc.). Nullable = "no barcode
    # recorded". Indexed because the pharmacy/admin inventory search
    # (?q=) does an exact/prefix match against it -- a scanner hands the
    # console a full code and expects an instant single-row hit. NOT unique:
    # this app doesn't police barcode collisions (a repackaged generic can
    # legitimately share one), and a UNIQUE here would turn a data-entry
    # typo into a hard 500 on save. Migration for already-seeded DBs is in
    barcode = Column(String(64), nullable=True, index=True)
    # Object key of an uploaded photo of the medicine/packaging in the
    # `clarion-medicine` bucket (see app/storage.py), key
    # `{item_id}_{sanitized_basename}`, best-effort by
    # POST /pharmacy|admin/inventory/{item_id}/image. NULL = no photo.
    # Key is built server-side from the row id + a sanitized basename. (P1.6)
    image_object_key = Column(String(512), nullable=True)
    image_sha256 = Column(String(64), nullable=True)
    image_bytes = Column(Integer, nullable=True)
    image_mime = Column(String(128), nullable=True)
    # When True, a pharmacist restock (POST .../inventory/{id}/adjust with
    # delta > 0) applies immediately (stock + budget move on the spot).
    # When False (the default), that same restock instead files a
    # MedicinePurchaseProposal for an admin to approve first -- see
    # routers/pharmacy.py::adjust_stock and routers/admin.py's
    # purchase-proposals section. Admin-only to toggle (PATCH
    # /admin/inventory/{id}); deliberately NOT settable via the pharmacy
    # router. NOT NULL DEFAULT 0 so every existing row is "needs approval"
    # until an admin explicitly opts an item into auto-approval.
    auto_approved = Column(Boolean, nullable=False, default=False)
    # Procurement cost per single `unit` (RM). Nullable = "cost unknown"
    # (counted as 0 in the budget rollup). Migration for already-seeded DBs
    unit_cost = Column(Float, nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))


class MedicineBudget(Base):
    """One row per facility -- the pharmacy procurement budget. `allocated_amount`
    is set by that facility's admin (PUT /admin/budget); `procurement_spend`
    accrues automatically on every restock (delta > 0) through
    routers/pharmacy.py::adjust_stock, so "remaining" = allocated - spend can
    be shown without re-summing the stock-event log every read. `current_stock_value`
    (Î£ unit_cost x quantity_on_hand) is computed live in the serializer, not
    stored here."""
    __tablename__ = "medicine_budgets"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, unique=True, index=True)
    allocated_amount = Column(Float, nullable=False, default=0)
    procurement_spend = Column(Float, nullable=False, default=0)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class MedicineStockEvent(Base):
    """Append-only audit trail of every stock movement made through the
    pharmacy router (restock or consume). Lets the budget number be
    reconstructed/verified and gives a per-item movement history. `cost` is
    delta x unit_cost_at_time for a restock, 0 for a consume."""
    __tablename__ = "medicine_stock_events"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    item_id = Column(String(36), ForeignKey("medicine_inventory.id"), nullable=False, index=True)
    delta = Column(Integer, nullable=False)
    unit_cost_at_time = Column(Float, nullable=True)
    cost = Column(Float, nullable=False, default=0)
    kind = Column(String(64), nullable=False)  # "restock" | "consume"
    by = Column(String(36), ForeignKey("users.id"), nullable=True)
    at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class InventoryDeleteRequest(Base):
    """A pharmacist's request for an inventory item to be removed from the
    catalogue -- pharmacists can adjust stock volume but catalogue delete is
    an admin-approved action (see the approved plan's "request -> approve"
    decision). At most one `pending` request per item (router-enforced).
    Approval performs the hard delete; `item_name` is snapshotted so the
    request still renders meaningfully after the item is gone."""
    __tablename__ = "inventory_delete_requests"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    item_id = Column(String(36), ForeignKey("medicine_inventory.id"), nullable=False, index=True)
    item_name = Column(String(255), nullable=False)
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    reason = Column(Text, nullable=True)
    status = Column(String(64), nullable=False, default="pending")  # pending | approved | rejected
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
    resolved_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    resolved_at = Column(TZDateTime, nullable=True)
    admin_note = Column(Text, nullable=True)


class MedicinePurchaseProposal(Base):
    """A pharmacist's request to BUY stock -- the procurement counterpart to
    InventoryDeleteRequest (modelled on it deliberately: same
    request -> admin-approve -> apply shape, same facility-scoping, same
    router-level "one identical pending per requester" 409 rule).

    Two shapes, distinguished by `item_id`:
      - item_id SET: "restock this existing catalogue item by `quantity`".
        Created automatically when a pharmacist calls
        POST /pharmacy/inventory/{id}/adjust with delta > 0 on an item whose
        `auto_approved` is False. `proposed_*` fields snapshot the item's
        name/unit/barcode at request time so the queue row still renders if
        the item is later renamed.
      - item_id NULL: "add this brand-new medicine to the catalogue AND
        stock it with `quantity`". Created by POST /pharmacy/purchase-proposals.
        Approval creates the MedicineInventoryItem (quantity_on_hand=0,
        unit_cost=proposal.unit_cost) then runs the restock for `quantity`.

    Approval (POST /admin/purchase-proposals/{id}/approve) runs the EXACT
    same restock primitive (routers/admin.py::_apply_restock) the immediate
    auto-approved path uses -- stock += quantity, stamp last_restocked_at,
    write a `restock` MedicineStockEvent, accrue MedicineBudget.procurement_spend
    -- so the two paths can never drift. `unit_cost` here is the price the
    pharmacist expects to pay on THIS purchase (payload value, or the item's
    stored unit_cost at request time); like the adjust endpoint it does NOT
    overwrite the catalogue item.unit_cost on an existing item."""
    __tablename__ = "medicine_purchase_proposals"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    # NULL => "new catalogue item request" (see class docstring). FK is
    # intentionally nullable; no cascade -- if the target item is hard-deleted
    # while a proposal is pending, approval detects the dangling ref and 409s
    # rather than crashing (mirrors approve_inventory_delete_request's
    # "item may already be gone" tolerance, inverted).
    item_id = Column(String(36), ForeignKey("medicine_inventory.id"), nullable=True, index=True)
    proposed_drug_name = Column(String(255), nullable=False)  # new-item name, or a snapshot of the existing item's name
    proposed_unit = Column(String(64), nullable=False, default="units")
    proposed_barcode = Column(String(64), nullable=True)
    quantity = Column(Integer, nullable=False)  # units to add on approval (always > 0)
    unit_cost = Column(Float, nullable=True)  # expected price per unit for THIS purchase; nullable = "unknown" (0 in the budget rollup)
    reason = Column(Text, nullable=True)
    requested_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    status = Column(String(64), nullable=False, default="pending")  # pending | approved | rejected
    reviewed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(TZDateTime, nullable=True)
    admin_note = Column(Text, nullable=True)  # optional free-text set on reject
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))


class Ward(Base):
    """Facility-scoped bed/ward capacity row -- same "manager admin" scoping
    as MedicineInventoryItem above, and likewise has no relationship to
    `Patient` (bed occupancy here is an aggregate count, not a per-patient
    bed assignment -- this app doesn't model that level of detail)."""
    __tablename__ = "wards"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    ward_name = Column(String(255), nullable=False)
    ward_type = Column(String(64), nullable=True)  # general | icu | pediatric | maternity | emergency | other -- validated in schemas.py, not a free enum in the DB
    total_beds = Column(Integer, nullable=False)
    occupied_beds = Column(Integer, nullable=False, default=0)
    # Set when this ward was auto-generated by a Floor (see models.Floor and
    # routers/admin.py's floors section). NULL for legacy/hand-created wards
    # (ICU, etc.). The migration for this column on already-seeded DBs is
    floor_id = Column(String(36), ForeignKey("floors.id"), nullable=True, index=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))


class Floor(Base):
    """A hospital floor/level that AUTO-GENERATES a uniform block of wards.

    An admin sets `ward_count` + `beds_per_ward` as plain numbers and the
    backend creates/adjusts exactly that many identical `Ward` rows
    (`ward_type="general"`, `total_beds=beds_per_ward`) pointing back here
    via `Ward.floor_id` -- see routers/admin.py's floors section.

    `gender_restriction` (nullable: "male" | "female"; NULL = mixed) is a
    SOFT routing rule applied only at admission time
    (routers/reception.py::create_admission): changing it later never moves
    a patient already in a bed. Same "manager admin, not super admin"
    facility scoping as Ward / MedicineInventoryItem."""
    __tablename__ = "floors"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    floor_label = Column(String(255), nullable=False)
    gender_restriction = Column(String(64), nullable=True)  # "male" | "female" | None (mixed)
    ward_count = Column(Integer, nullable=False)
    beds_per_ward = Column(Integer, nullable=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class Admission(Base):
    """A lightweight per-patient bed assignment -- the source of truth for
    the Ward Map bed grid (routers/reception.py::get_ward_map). Active =
    `discharged_at IS NULL`; at most one active admission per patient
    (router-enforced, 409 otherwise).

    Deliberately coexists with the legacy aggregate `Ward.occupied_beds`
    counter and its Admin "Ward Capacity" tab stepper -- those are left
    untouched for backward-compat (see the approved plan's assumptions).

    `gender_at_admission` snapshots the patient's gender at admit time (the
    floor's gender rule is only checked then, not re-enforced later)."""
    __tablename__ = "admissions"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    ward_id = Column(String(36), ForeignKey("wards.id"), nullable=False, index=True)
    bed_number = Column(Integer, nullable=False)
    admitted_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
    admitted_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    discharged_at = Column(TZDateTime, nullable=True)
    discharged_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    gender_at_admission = Column(String(64), nullable=True)
    notes = Column(Text, nullable=True)


class ConsultationRoom(Base):
    """A facility-scoped physical consultation room ("Bilik A".."Bilik E"),
    managed by that facility's own `admin` user -- same "manager admin, not
    super admin" scoping as MedicineInventoryItem / Ward (every query/write
    forced to the acting admin's own `User.facility`).

    Distinct from `QueueTicket.department` (the clinical category -- General
    / Pharmacy / Lab / Emergency): a room is a physical space a clinician
    sits in, a department is what kind of care is given. `department` here is
    an optional tag so round-robin can keep e.g. Pharmacy check-ins flowing
    to Pharmacy rooms -- see routers/reception.py::_assign_room.

    `active=False` is a soft retire (same soft-invalidate pattern as
    EmergencyToken.revoked / ReceptionStation.revoked) -- an inactive room
    keeps its history on old QueueTickets but is skipped by round-robin and
    can't be newly claimed."""
    __tablename__ = "consultation_rooms"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    room_name = Column(String(255), nullable=False)
    department = Column(String(64), nullable=True)  # optional clinical-category tag
    active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class FacilitySection(Base):
    """A facility-scoped front-desk registration counter ("General
    Registration", "Emergency", "O&G", "Orthopaedics", "ICU"), managed by
    that facility's own `admin` user -- exact same "manager admin, not super
    admin" scoping as ConsultationRoom / Ward (every query/write forced to
    the acting admin's own `User.facility`).

    A section is an ADMINISTRATIVE grouping of the front desk, distinct from
    ConsultationRoom (a physical space) and from QueueTicket.department (the
    free-text clinical category). An admin defines the sections for their
    hospital and pins each receptionist/clinician to one via
    `User.section` -- that person's reception console is then hard-scoped to
    tickets whose `department` equals this section's `name` (see
    routers/reception.py). The section name IS the join key to
    QueueTicket.department, so the two vocabularies are deliberately shared.

    `active=False` is a soft retire (same soft-invalidate pattern as
    ConsultationRoom.active): an inactive section can't be newly assigned to
    staff, but users already pinned to it keep their assignment until an
    admin moves or unassigns them.

    BRAND-NEW table -- `create_all` picks it up on both a fresh and an
    RolePagePermission / QueueTicket / HospitalSetting)."""
    __tablename__ = "facility_sections"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("facility_name", "name", name="uq_facility_section_facility_name"),
    )


class RoomClaim(Base):
    """A clinician's live "I am sitting in this Bilik right now" claim,
    self-selected at (or after) clock-in and auto-released on clock-out (see
    routers/staff.py::clock_out). Active = `released_at IS NULL`.

    At most one active claim per room, and at most one active claim per
    user -- enforced at the router level (claiming a second room releases
    the first; see routers/reception.py::claim_room and
    routers/staff.py::clock_out). A SQLite-only partial unique index used to
    backstop this against a concurrent-claim race; it was removed for
    MariaDB portability (P1.2) and is scheduled to return as a MariaDB
    still creates the old partial index on the existing SQLite demo DB, so

    This is what powers the additive "My Room" worklist
    (GET /reception/my-room): today's QueueTickets whose room_id matches the
    caller's active claim, shown ONLY while the caller is also clocked in.
    It deliberately does NOT restrict the clinician's existing full
    patient-record access -- it's an extra worklist, not a permission gate."""
    __tablename__ = "room_claims"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    room_id = Column(String(36), ForeignKey("consultation_rooms.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    claimed_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    released_at = Column(TZDateTime, nullable=True)

    active_room_key = Column(
        String(36),
        Computed("CASE WHEN released_at IS NULL THEN room_id END", persisted=False),
        nullable=True,
    )
    active_user_key = Column(
        String(36),
        Computed("CASE WHEN released_at IS NULL THEN user_id END", persisted=False),
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("active_room_key", name="uq_room_claims_active_room_key"),
        UniqueConstraint("active_user_key", name="uq_room_claims_active_user_key"),
    )

    # P1.3: Restored active-claim exclusivity using virtual generated columns and a plain UniqueConstraint.
    # Supported on SQLite 3.31+ and MariaDB 10.5+ (NULL is non-colliding in UNIQUE).


class StaffClockEvent(Base):
    """One clock-in/clock-out shift record for a staff member. `facility_name`
    is SNAPSHOTTED at clock-in time (not a live join to User.facility) --
    same reasoning as AuditLog.actor_facility: a staff transfer to a
    different hospital later shouldn't rewrite which facility a past shift
    was actually worked at."""
    __tablename__ = "staff_clock_events"
    id = Column(String(36), primary_key=True, default=gen_id)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    facility_name = Column(String(255), nullable=False, index=True)
    clock_in_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    clock_out_at = Column(TZDateTime, nullable=True)  # null while the shift is still open


class EmergencyToken(Base):
    """A short-lived, single-scope token bound to a QR code / physical card
    reference. Never stores the actual medical data â€” just the grant.

    Two independent "keys" can point at the same grant:
      - `card_reference`: the pointer encoded in the QR code, issued by the
        patient from the app (see /emergency/issue). Meant to be reissued
        often; short-lived by default.
      - `nfc_uid`: a physical NFC card/tag, registered by staff via
        /emergency/nfc/register (e.g. for a senior citizen without a
        smartphone). Longer-lived by default, admin-managed, admin-revocable.
        Security Audit M7: the column stores `auth.hash_nfc_uid(raw)` (keyed
        HMAC-SHA256 hex), NOT the raw MIFARE UID -- every lookup hashes the
        presented UID first. `nfc_uid_last4` keeps a 4-char tail of the raw
        UID in the clear so staff can still tell two registered cards apart
        in the console (the grant `id` is the handle for revoke, not the UID).
    A grant may have either, both, or (rarely) be created with just one.
    """
    __tablename__ = "emergency_tokens"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False)
    token = Column(String(64), unique=True, nullable=False)
    card_reference = Column(String(64), unique=True, nullable=True)  # printed on physical card / encoded in QR
    nfc_uid = Column(String(64), unique=True, nullable=True)  # M7: HMAC of the UID, never the raw UID
    nfc_uid_last4 = Column(String(8), nullable=True)  # cleartext tail of the raw UID, display only
    scope = Column(JSON, default=lambda: ["allergies", "medications", "conditions", "blood_type"])
    expires_at = Column(TZDateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
    registered_by = Column(String(36), nullable=True)  # staff user id, for nfc_uid registrations


class SelfRegistrationAttempt(Base):
    """One row per NRIC's in-progress self-service registration (see
    routers/self_registration.py) -- the self-service ALTERNATIVE to
    staff-issued accounts (POST /auth/patients/{id}/issue-account),
    replacing "verify in person" with NRIC + DOB + name + an emailed OTP +
    OCR-verified photos of the physical NRIC, all checked against an
    EXISTING Patient row a hospital already created. This table never
    creates a Patient -- only ever links to one that already exists.

    Unique index on patient_id -- exactly one in-flight attempt per
    patient. A fresh POST /auth/self-register/start for a patient with an
    existing non-"completed" row resets/reuses that same row in place
    rather than creating a duplicate (same "re-registering updates in
    place" pattern as EmergencyToken / NfcRegisterRequest elsewhere in this
    codebase) -- see self_registration.py's `_get_or_reserve_attempt` for
    the one deliberate exception (a flagged_manual_review row is NOT reset
    by /start, so the self-service path stays a genuine dead end once flagged).

    otp_code_hash / otp_expires_at / otp_attempt_count / otp_request_count /
    otp_request_window_start mirror User's equivalent OTP columns/semantics
    EXACTLY (see models.User's own OTP column comments above) -- only ever
    the HASH of the OTP is stored here too, never the plaintext.
    """
    __tablename__ = "self_registration_attempts"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False, unique=True, index=True)
    # The address provided at /start -- becomes Patient.email on successful
    # /complete IF Patient.email is still null (never clobbers an existing
    # value). This is where the OTP below is actually emailed.
    email = Column(String(255), nullable=False)

    otp_code_hash = Column(String(255), nullable=True)
    otp_expires_at = Column(TZDateTime, nullable=True)
    otp_verified = Column(Boolean, nullable=False, default=False)
    otp_attempt_count = Column(Integer, nullable=False, default=0)
    otp_request_count = Column(Integer, nullable=False, default=0)
    otp_request_window_start = Column(TZDateTime, nullable=True)

    photo_verify_attempt_count = Column(Integer, nullable=False, default=0)
    # pending_otp -> pending_photo -> photo_verified -> completed, with a
    # possible pending_photo -> flagged_manual_review branch at 5 failed
    # photo-verification attempts (see verify_self_registration_photos).
    status = Column(String(64), nullable=False, default="pending_otp")
    # Set once the OTP is verified (status -> pending_photo); a photo
    # verification attempt after this deadline must restart from /start.
    photo_verification_deadline = Column(TZDateTime, nullable=True)
    # Short, internal-debugging-only note about the most recent OCR/match
    # failure (e.g. "ic_number_mismatch", "back_ic_mismatch") -- NEVER
    # shown verbatim to the client; see verify-photos' actionable-but-
    # non-leaking client-facing error messages instead.
    last_ocr_failure_reason = Column(Text, nullable=True)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    patient = relationship("Patient")


class QueueTicket(Base):
    """A single reception-desk check-in / queue ticket. Scoped per-facility
    and reset daily: `queue_number` only ever counts a given facility_name's
    tickets for the same `queue_date`, so numbering restarts at 1 every day
    without needing a separate "reset" job or a stored sequence row.

    `queue_date` is the Malaysia-local (Asia/Kuala_Lumpur, UTC+8, no DST)
    CALENDAR DATE the patient checked in on, stored as an ISO date string
    (e.g. "2026-08-19") -- deliberately NOT the UTC date. This project's
    target market is Malaysia; resetting the queue at UTC midnight would
    silently reset it at 8am local time, mid-morning, while patients are
    still waiting. See routers/reception.py's `_malaysia_today()` for where
    this is computed -- hardcoded to a single timezone rather than made
    per-facility-configurable, which is the right hackathon-scope call for
    now but would need revisiting for a real multi-region deployment.

    `UniqueConstraint(facility_name, queue_date, queue_number)`: this is
    the actual concurrency-safety mechanism, not just a data-integrity nicety.
    FastAPI runs sync `def` routes (all of this router's routes are `def`,
    not `async def`) in a threadpool even under a single `uvicorn` process,
    and database.py's SQLite engine sets `check_same_thread: False` -- so
    two concurrent POST /reception/checkin calls for the same facility on
    different threads really can both read the same COUNT(*) before either
    commits. Without a DB-level constraint, that would silently hand out a
    duplicate queue_number with no error anywhere. With it,
    routers/reception.py::_next_queue_number's bounded retry loop turns
    that race into either a correctly-serialized outcome or, in the
    pathological worst case, a clean retry -- never a silent collision.

    `facility_name` is SNAPSHOTTED from the checking-in staff member's
    `current_user.facility` at check-in time (not a live join) -- same
    reasoning as StaffClockEvent.facility_name / MedicineInventoryItem /
    Ward elsewhere in this file: a receptionist's account being reassigned
    to a different hospital later shouldn't rewrite which facility a past
    ticket was actually issued at, and a queue is inherently a
    point-in-time, at-this-desk concept anyway.

    Deliberately reuses the existing card_reference/nfc_uid identifier
    space from EmergencyToken to *identify* a walk-in patient (source
    records which one was used, if either) rather than minting a new
    identifier scheme -- but check-in is a READ-ONLY lookup against that
    grant; see routers/reception.py::checkin for why this must never
    revoke/consume/mutate the underlying EmergencyToken row."""

    __tablename__ = "queue_tickets"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    facility_name = Column(String(255), nullable=False)
    queue_date = Column(String(64), nullable=False)  # Malaysia-local ISO date, e.g. "2026-08-19" -- see class docstring
    queue_number = Column(Integer, nullable=False)
    department = Column(String(64), nullable=True)  # free text, e.g. "General" | "Pharmacy" | "Lab" | "Emergency"
    # Physical consultation room this ticket was round-robined to at check-in
    # (see routers/reception.py::_assign_room). room_name is SNAPSHOTTED
    # alongside room_id -- same reasoning as facility_name above: a room
    # being renamed/retired later shouldn't rewrite which room a past ticket
    # was sent to. Both nullable: a facility with no ConsultationRoom rows
    # configured yet still checks patients in fine, just without a room.
    room_id = Column(String(36), ForeignKey("consultation_rooms.id"), nullable=True, index=True)
    room_name = Column(String(255), nullable=True)
    reason = Column(Text, nullable=True)  # patient's stated reason for the visit
    source = Column(String(64), nullable=False)  # "ic" | "qr" | "nfc" | "manual" | "self_qr" -- how the patient was identified
    status = Column(String(64), nullable=False, default="waiting")  # waiting | called | done | cancelled
    checked_in_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    called_at = Column(TZDateTime, nullable=True)
    completed_at = Column(TZDateTime, nullable=True)
    checked_in_by = Column(String(36), ForeignKey("users.id"), nullable=False)  # the receptionist

    patient = relationship("Patient")

    __table_args__ = (
        Index("ix_queue_tickets_facility_checked_in", "facility_name", "checked_in_at"),
        # The hot path: display.py's public board and reception's queue views
        # all filter facility_name + queue_date (+ status). Polled up to
        # 120x/min per screen -- ix_..._checked_in doesn't cover queue_date.
        Index("ix_queue_tickets_facility_date", "facility_name", "queue_date"),
        UniqueConstraint("facility_name", "queue_date", "queue_number", name="uq_queue_ticket_facility_date_number"),
    )


class ReceptionStation(Base):
    """A facility's self-check-in QR target. A staff member (front desk)
    generates one from the web Reception console; a patient then scans it
    from the mobile app, while logged in, to check themselves into that
    facility's queue without a receptionist keying anything in -- see
    routers/reception.py::self_checkin. The QR itself just encodes `token`
    (as `CLARION-STATION:{token}`, mirroring EmergencyToken/`emergency.py`'s
    `CLARION-EMERGENCY:{card_reference}` payload convention); the app looks
    up which facility/department that resolves to server-side, never trusts
    a client-supplied facility name.

    Deliberately modeled as long-lived and admin-revocable, like
    EmergencyToken.nfc_uid, rather than short-lived/reissued like
    EmergencyToken.card_reference: this QR is meant to be printed and taped
    up at a physical front desk, so it needs to stay valid indefinitely
    until staff explicitly retire it (`revoked`, never deleted -- same
    soft-invalidate pattern as EmergencyToken.revoked / Appointment's
    "cancelled" status elsewhere in this file).

    At most one non-revoked row per facility_name is the intended usage,
    enforced at the router level, not a DB constraint: regenerating a
    facility's QR revokes the previous one first (see
    routers/reception.py::create_or_replace_station) rather than allowing
    active duplicates to pile up."""

    __tablename__ = "reception_stations"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False)
    department = Column(String(64), nullable=True)  # optional -- pins self-checkins from this station to one department
    revoked = Column(Boolean, default=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=False)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))


class AuditLog(Base):
    """Append-only-in-spirit log of every access to patient data.

    Deliberate design split on "who" vs "where" for a staff actor:
      - `actor` stores the stable `User.id` (never a display name), and the
        actor's human-readable name is resolved via a LIVE join to
        `users.full_name` at read time (see patients.py::get_audit_log) --
        a later name correction (typo fix, legal name change) should not
        stay frozen/wrong in years-old history.
      - `actor_facility`, by contrast, IS snapshotted onto the row at
        write time (not live-joined), because `User.facility` can change
        later (a transfer, multi-site staff) and the entire point of an
        audit log is "who accessed this, from where, at that moment" -- a
        live join here would silently rewrite history every time a staff
        member's facility changes, which defeats the purpose.
    Nullable because: (a) rows written before this column existed have no
    value for it, and (b) `actor` isn't always a staff `User` row at all --
    it's sometimes "system", or "emergency_responder:<name>" for the two
    unauthenticated emergency-scan endpoints, which have no `User`/facility
    to snapshot in the first place (those already fold org into `detail`).
    """
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=True, index=True)
    actor = Column(String(255), nullable=False)          # user id, "emergency_token:<id>", or "system"
    actor_role = Column(String(64), nullable=True)
    actor_facility = Column(String(255), nullable=True)  # snapshot at access time -- see class docstring
    action = Column(String(64), nullable=False)         # e.g. "view_record", "emergency_access", "upload_document"
    fields_accessed = Column(JSON, nullable=True)
    # Indexed: the M7c NFC-scan anomaly check and the patient audit-log read
    # both window on recent rows (WHERE timestamp >= now() - interval).
    timestamp = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), index=True)
    detail = Column(Text, nullable=True)

    # --- P2.9: tamper-evident hash chain ---------------------------------
    # Every row is cryptographically linked to its predecessor, so any
    # after-the-fact edit, delete, or insert-in-the-middle of audit_logs
    # breaks the chain and is caught by db/verify_audit_chain.py and
    # GET /admin/audit/chain-status. Enforced from two directions:
    #   - DB-level BEFORE UPDATE / BEFORE DELETE triggers (same migration)
    #     block edits + row deletes for the DML-scoped runtime account, which
    #     has no DROP/ALTER/TRIGGER rights and so also cannot TRUNCATE or
    #     drop the triggers. A DDL-capable account (deploy-time migrate, or
    #     root) can still bypass -- that residual is covered by the next line;
    #   - the hash chain + the off-box daily WORM seal make an out-of-band
    #     tamper (a DDL-capable wipe, raw datadir access, a restore from a
    #     doctored backup) detectable via verify_chain(check_worm=True).
    # `seq` is the gap-free 1-based chain position -- NOT `timestamp`, which
    # can tie at the same microsecond or step backwards on an NTP correction.
    # `row_hash` = HMAC-SHA256(SECRET_KEY, "audit-chain-v1:" || seq || "\n"
    # || prev_hash || "\n" || canonical_json(row)); see app/audit.py.
    # Written only by audit.log_access() -- the single audit-write chokepoint
    # -- which serialises the read-tip -> compute -> append critical section
    # (SELECT ... FOR UPDATE on AuditChainState for MariaDB; a process lock
    # for SQLite, which already serialises writers).
    seq = Column(BigInteger, nullable=False, unique=True)
    prev_hash = Column(String(64), nullable=False)
    row_hash = Column(String(64), nullable=False)


class AuditChainState(Base):
    """Singleton (``id = 1``) holding the current tip of the audit_logs hash
    chain: the last sequence number issued and its row_hash.

    audit.log_access() reads this row (``SELECT ... FOR UPDATE`` on MariaDB,
    under a process lock on SQLite), computes the next row from it, inserts
    the audit row, and advances this row -- all in one transaction. Keeping
    the tip here rather than recomputing ``MAX(audit_logs.seq)`` on every
    write keeps the hot path to one PK read + one PK update and gives the
    FOR UPDATE something stable to serialise on.
    """
    __tablename__ = "audit_chain_state"

    id = Column(Integer, primary_key=True, default=1)
    last_seq = Column(BigInteger, nullable=False, default=0)
    last_hash = Column(String(64), nullable=False)
    updated_at = Column(
        TZDateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AuditSeal(Base):
    """One row per sealed UTC day -- the daily WORM anchor for the audit
    hash chain (roadmap P2.9, the tender).

    ``db/seal_audit_day.py`` (a cron job) calls audit.seal_day() once the
    day is over: it records that day's ``[from_seq, to_seq]`` range, the row
    count, and ``to_seq``'s row_hash -- a short digest that pins the entire
    day's audit history. That digest can be published / shipped off-box /
    mirrored to the object-store WORM bucket (``object_key``), so a later
    wholesale replacement of audit_logs (e.g. restore from a doctored
    backup) is caught even if the attacker also rewrote the in-DB chain.
    Idempotent per ``seal_date``; re-sealing a day whose digest has changed
    raises -- that is the tamper signal.
    """
    __tablename__ = "audit_seals"

    id = Column(String(36), primary_key=True, default=gen_id)
    seal_date = Column(String(10), nullable=False, unique=True)  # 'YYYY-MM-DD' (UTC)
    from_seq = Column(BigInteger, nullable=False)
    to_seq = Column(BigInteger, nullable=False)
    row_count = Column(BigInteger, nullable=False)
    chain_hash = Column(String(64), nullable=False)  # row_hash of the row at seq = to_seq
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
    object_key = Column(String(512), nullable=True)  # object-store key if the seal was mirrored to WORM storage


class DataQualityAlert(Base):
    """One row per (rule, entity) that a batch data-quality scan has flagged
    -- roadmap P2.12, the tender ("automated data-quality monitoring in
    the DB layer -- missing values, duplicate patients, inconsistent coding,
    anomalous entries; configurable admin alerts").

    ``app/data_quality.py::run_scan`` (invoked by ``db/data_quality_scan.py``
    on a cron, or ad hoc by an admin) UPSERTs on ``(rule, entity_type,
    entity_id)``: a repeat sighting just bumps ``last_seen_at`` / ``times_seen``;
    a finding that stops firing is auto-resolved (``resolved_by='system'``).
    An admin can ``acknowledge`` a known/accepted issue (stays listed, drops
    out of the "open" count) or ``resolve`` it by hand.

    ``detail`` is a short human summary -- it names the field and the bad
    value's *shape* (e.g. "blood_type='O positiv' not a recognised ABO/Rh
    group"), never a diagnosis / drug / allergen string, keeping the same
    "no clinical values in a second store" discipline as audit_logs (M8).
    """
    __tablename__ = "data_quality_alerts"

    id = Column(String(36), primary_key=True, default=gen_id)
    rule = Column(String(64), nullable=False, index=True)
    category = Column(String(32), nullable=False)   # missing | duplicate | coding | anomaly
    severity = Column(String(16), nullable=False)   # info | warning | error
    entity_type = Column(String(32), nullable=False)  # patient | condition | medication | allergy | encounter
    entity_id = Column(String(36), nullable=False)
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=True, index=True)
    detail = Column(Text, nullable=False)

    first_seen_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_seen_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    times_seen = Column(Integer, nullable=False, default=1)

    acknowledged = Column(Boolean, nullable=False, default=False)
    acknowledged_by = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = Column(TZDateTime, nullable=True)

    resolved = Column(Boolean, nullable=False, default=False, index=True)
    # A users.id, or the literal 'system' for an auto-resolve -- deliberately a
    # plain string, not an FK, so the sentinel is legal and a deleted admin's
    # id stays as a historical record of who resolved it.
    resolved_by = Column(String(36), nullable=True)
    resolved_at = Column(TZDateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("rule", "entity_type", "entity_id", name="uq_data_quality_alerts_rule_entity"),
    )


class HospitalSetting(Base):
    """One row per facility (`facility_name` unique) holding that hospital's
    own admin-editable configuration. Lazily created on first read of
    GET /admin/hospital-settings (same create-on-read pattern as
    routers/admin.py::get_budget / MedicineBudget), so a facility that has
    never opened the settings screen still behaves as if it holds the
    documented defaults.

    `records_shared_publicly` (default True) is the cross-hospital record
    sharing switch: when a facility sets it False, that facility's authored
    clinical sub-records (Condition / MedicationStatement / AllergyIntolerance
    / Encounter) are omitted from routers/patients.py::_serialize_patient
    responses served to staff at OTHER facilities. It is deliberately a READ
    filter only -- it never blocks a write, never hides data from the
    patient's own view, and is ALWAYS ignored by the unauthenticated
    emergency-token scan path (routers/emergency.py), which is a
    life-safety override that must never be gated on an inter-hospital
    data-sharing preference.

    This is a BRAND-NEW table -- `create_all` picks it up on both a fresh
    """
    __tablename__ = "hospital_settings"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, unique=True, index=True)
    display_name = Column(String(255), nullable=True)
    address = Column(String(255), nullable=True)
    contact_phone = Column(String(64), nullable=True)
    timezone = Column(String(64), nullable=False, default="Asia/Kuala_Lumpur")
    records_shared_publicly = Column(Boolean, nullable=False, default=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class RolePagePermission(Base):
    """One row per `(facility_name, role)` -- which "pages" of the web
    console that staff role is allowed to reach at that facility. Powers
    both the server-side enforcement (auth.require_page_access, wired at
    router level in main.py) and the web console's nav / routing / post-
    login landing page (UserOut.allowed_pages).

    `allowed_pages` is a JSON list of page keys drawn from
    permissions.CONFIGURABLE_PAGES == ["patients", "reception", "pharmacy"].
    The `admin` page is ALWAYS admin-only and is never a stored/configurable
    value here.

    Lazily created with documented per-role defaults on first read (see
    permissions.get_or_create_role_permission and routers/admin.py's
    role-permissions endpoints) -- the exact same create-on-read pattern as
    HospitalSetting / MedicineBudget above, so a facility that has never
    opened the permissions matrix still behaves as if it holds the
    documented defaults:
        clinician        -> ["patients", "reception"]
        records_officer  -> ["patients", "reception"]
        receptionist     -> ["reception"]
        pharmacist       -> ["pharmacy"]
    `admin` is NEVER stored -- an admin implicitly holds every page.
    Only permissions.CONFIGURABLE_STAFF_ROLES ever get a row here;
    patient / emergency_responder are not page-gated at all.

    BRAND-NEW table -- `create_all` picks it up on both a fresh and an
    HospitalSetting / QueueTicket / SelfRegistrationAttempt).
    """
    __tablename__ = "role_page_permissions"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    role = Column(String(64), nullable=False)
    allowed_pages = Column(JSON, nullable=False, default=list)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("facility_name", "role", name="uq_role_page_permission_facility_role"),
    )


class WaitingRoomDisplay(Base):
    """A public, unauthenticated waiting-room TV/monitor feed for a facility,
    optionally scoped to one FacilitySection. Mirrors ReceptionStation's
    long-lived, admin-managed, soft-revocable token model: `token` is an
    unguessable secrets.token_urlsafe(16) the display device puts in the URL
    (GET /display/{token}, no auth, NOT under require_page_access), looked up
    server-side to resolve which facility/section to show -- a client never
    supplies a facility name.

    Unlike ReceptionStation, MULTIPLE non-revoked rows per facility are
    allowed on purpose (a hospital may run one screen per waiting area, each
    scoped to a different section). `show_full_names` opts a given screen
    into showing patients' full names instead of the default masked label
    ("Ahmad bin Ismail" -> "Ahmad I.") -- a per-screen privacy choice the
    admin makes when they know that screen faces staff-only space.

    BRAND-NEW table -- `create_all` picks it up on both a fresh and an
    RolePagePermission / HospitalSetting / FacilitySection).
    """
    __tablename__ = "waiting_room_displays"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False)
    section = Column(String(64), nullable=True)
    show_full_names = Column(Boolean, nullable=False, default=False)
    revoked = Column(Boolean, nullable=False, default=False)
    created_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))


class ClinicalRecordAnnotation(Base):
    """Append-only clinical-record sign-off / correction note. NEVER updated
    or deleted -- no endpoint exposes either operation; a change of mind is
    recorded as another annotation. Snapshots the signer's name / role /
    facility and a COPY of their digital signature PNG
    (clarion-signatures bucket, key annotations/{id}.png) at signing time, so
    the annotation stays verifiable even if the signer's account or profile signature
    changes later -- same snapshot-not-live-join reasoning as
    Encounter.signed_by_name and AuditLog.actor_facility.

    `target_type` / `target_id` point at a Condition / MedicationStatement /
    AllergyIntolerance / Encounter row. The read path
    (routers/patients.py::_serialize_patient) groups these by target_id and
    folds kind=='resolved' / kind=='discontinued' into a COMPUTED
    effective_status / effective_active on the serialized record WITHOUT ever
    mutating the underlying row -- the immutability-safe way to mark a
    cross-facility record resolved/discontinued (the row's own author facility
    still owns the actual column via PATCH).

    BRAND-NEW table -- `create_all` picks it up on both a fresh and an
    """
    __tablename__ = "clinical_record_annotations"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    target_type = Column(String(64), nullable=False)  # condition | medication | allergy | encounter
    target_id = Column(String(36), nullable=False, index=True)
    kind = Column(String(64), nullable=False)  # resolved | discontinued | correction | note
    note = Column(Text, nullable=True)
    signed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    signed_by_name = Column(String(255), nullable=True)
    signed_by_role = Column(String(64), nullable=True)
    facility_name = Column(String(255), nullable=True)
    # A COPY of the signer's profile signature PNG taken at signing time,
    # `clarion-signatures` bucket, key `annotations/{id}.png` (see
    # app/storage.py), so the annotation stays verifiable even if the signer
    # later changes/clears their profile signature. (P1.6)
    signature_object_key = Column(String(512), nullable=True)
    signature_sha256 = Column(String(64), nullable=True)
    signature_bytes = Column(Integer, nullable=True)
    signature_mime = Column(String(128), nullable=True)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))


# ==========================================================================
# Ancillary engine (roadmap P3.1, the tender). One shared
# order -> result -> sign-off -> document pipeline behind the near-identical
# Procedure / Laboratory / X-ray / Physiotherapy module text -- each module
# is just a `module` value plus its own ServiceCatalogItem rows, not a
# separate schema. Reporting/AI enrichment (intelligent
# result interpretation, longitudinal trends) is P4.5/P4.6, layered on top
# of `flag_abnormal`/`flag_critical` later without a schema change.
# ==========================================================================

ANCILLARY_MODULES = ("procedure", "laboratory", "xray", "physiotherapy")
SERVICE_REQUEST_SOURCES = ("frontdesk", "physician_order")
SERVICE_REQUEST_PRIORITIES = ("routine", "urgent", "stat")
# Deliberately just 3 states, not the fuller ordered/in_progress/resulted/
# signed_off/cancelled state machine a bigger build might want: this demo's
# "perform + sign off" is one atomic action (see routers/ancillary.py
# ::sign_off_service_request, same shape as consultation.py::complete_ticket),
# so there's no separately-observable "in progress" or "resulted-but-unsigned"
# state to persist yet.
SERVICE_REQUEST_STATUSES = ("ordered", "signed_off", "cancelled")


class ServiceCatalogItem(Base):
    """One orderable/billable ancillary test, procedure or treatment
    definition -- the shared 'Parameter Management' surface behind
    Procedure/Laboratory/X-ray/Physiotherapy's near-identical clause text
`facility_name` NULL = a shared/global item
    every facility can order (demo-seeded); set = one facility's own
    addition, invisible to other facilities. No delete endpoint -- toggle
    `active` off instead, same reasoning as MedicineInventoryItem/
    InventoryDeleteRequest (an existing ServiceRequest FKs to this row and
    must never be orphaned)."""
    __tablename__ = "service_catalog_items"

    id = Column(String(36), primary_key=True, default=gen_id)
    module = Column(String(32), nullable=False, index=True)  # one of ANCILLARY_MODULES
    name = Column(String(255), nullable=False)
    code = Column(String(64), nullable=True)  # local code, free text (no LOINC/CPT mapping yet)
    unit_price_cents = Column(Integer, nullable=False, default=0)
    facility_name = Column(String(255), nullable=True, index=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))

    requests = relationship("ServiceRequest", back_populates="catalog_item")


class ServiceRequest(Base):
    """The 'order': a registered patient routed into one ancillary module,
    either straight from Frontdesk or off a physician's order raised during
    a consultation (-- every module explicitly
    accepts both paths). One request carries at most one ServiceResult; a
    repeat test is a NEW request, never an edit to an old one -- the same
    append-only discipline as Condition/Encounter."""
    __tablename__ = "service_requests"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    module = Column(String(32), nullable=False, index=True)
    catalog_item_id = Column(String(36), ForeignKey("service_catalog_items.id"), nullable=False)
    source = Column(String(32), nullable=False)  # frontdesk | physician_order
    # Set when source == physician_order -- the consultation Encounter this
    # order was raised from. Not a facility-scoping signal by itself; see
    # ordering_facility_name below for that.
    source_encounter_id = Column(String(36), ForeignKey("encounters.id"), nullable=True)
    clinical_indication = Column(Text, nullable=True)
    priority = Column(String(16), nullable=False, default="routine")
    status = Column(String(32), nullable=False, default="ordered", index=True)
    # Snapshot of the catalog item's price at order time (P3.3 billing will
    # read this rather than the live catalog row, so a later price change
    # never reprices an already-placed order).
    unit_price_cents = Column(Integer, nullable=False, default=0)

    requested_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    requested_by_name = Column(String(255), nullable=True)
    requested_by_role = Column(String(64), nullable=True)
    # The AUTHORING facility -- same cross-facility PATCH-immutability
    # semantics as Condition.authored_by_facility (see routers/patients.py
    # ::_FACILITY_RELATIONSHIP_SOURCES / _patient_present_at): only this
    # facility may cancel the request or perform/sign its result while it's
    # still open. NULL legacy rows (pre-this-column) are immutable to
    # everyone by design -- same safe default as the rest of the clinical
    # tables. Indexed: it's one of the _FACILITY_RELATIONSHIP_SOURCES scanned
    # by list_patients' facility scope.
    ordering_facility_name = Column(String(255), nullable=True, index=True)

    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))
    cancelled_at = Column(TZDateTime, nullable=True)
    cancelled_reason = Column(Text, nullable=True)

    patient = relationship("Patient")
    catalog_item = relationship("ServiceCatalogItem", back_populates="requests")
    result = relationship("ServiceResult", back_populates="request", uselist=False)


class ServiceResult(Base):
    """The signed result for one ServiceRequest -- same snapshot-signature,
    immutable-once-signed discipline as Encounter
    (routers/consultation.py::complete_ticket) and ClinicalRecordAnnotation.
    No PATCH endpoint exists once `signed_by` is set; a correction is a NEW
    ClinicalRecordAnnotation with target_type='service_result' (registered in
    routers/patients.py::_ANNOTATION_MODEL), never an edit to this row."""
    __tablename__ = "service_results"

    id = Column(String(36), primary_key=True, default=gen_id)
    service_request_id = Column(
        String(36), ForeignKey("service_requests.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    result_text = Column(Text, nullable=True)
    # Manually set by the signing clinician for now (no AI yet) -- the column
    # exists so P4.5's AI audit-trail / P4.6 predictive layer, and P4.4's
    # medication/lab-safety rule engine, have somewhere to write a computed
    # flag later without a schema change.
    flag_abnormal = Column(Boolean, default=False, nullable=False)
    flag_critical = Column(Boolean, default=False, nullable=False)

    performed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    performed_by_name = Column(String(255), nullable=True)
    performed_by_role = Column(String(64), nullable=True)
    performed_at = Column(TZDateTime, nullable=True)
    # Authoring facility, same semantics as ServiceRequest.ordering_facility_name.
    facility_name = Column(String(255), nullable=True, index=True)

    # Softcopy attachment (scanned lab/X-ray report, etc.) -- same 4-column
    # object-store pattern as ClinicalDocument (P1.6): `clarion-documents`
    # bucket, key `service-results/{id}_{sanitized_basename}`. NULL if none
    # was uploaded.
    file_object_key = Column(String(512), nullable=True)
    file_sha256 = Column(String(64), nullable=True)
    file_bytes = Column(Integer, nullable=True)
    file_mime = Column(String(128), nullable=True)

    signed_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    signed_by_name = Column(String(255), nullable=True)
    signed_by_role = Column(String(64), nullable=True)
    # A COPY of the signer's profile signature PNG taken at sign-off time,
    # `clarion-signatures` bucket, key `service-results/{id}.png` (see
    # app/storage.py), so it stays fixed even if the clinician later
    # changes/clears their profile signature. (P1.6 pattern)
    signature_object_key = Column(String(512), nullable=True)
    signature_sha256 = Column(String(64), nullable=True)
    signature_bytes = Column(Integer, nullable=True)
    signature_mime = Column(String(128), nullable=True)

    created_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc))

    request = relationship("ServiceRequest", back_populates="result")


# ==========================================================================
# PDPA (roadmap P2.10, the tender). Research: Malaysia's PDPA has NO
# right to erasure -- clinical records run on the s.40 "medical purposes"
# basis and are kept per Act 586 / MMC retention rules. So this is
# consent-for-OPTIONAL-purposes + a data-subject-request workflow (access /
# correction / portability / withdraw-consent -- never delete) + a DPO
# register + a retention-schedule config. See healthcare/Malaysia Health
# Regulation.md.
# ==========================================================================

# Optional processing purposes a patient can consent to / withdraw. Clinical
# treatment is NOT here -- it needs no consent (s.40).
CONSENT_PURPOSES = ("pdpa_notice", "research", "marketing", "sms_reminders", "cross_facility_sharing")
DSR_KINDS = ("access", "correction", "portability", "withdraw_consent", "objection")
DSR_STATUSES = ("open", "in_progress", "completed", "rejected")


class ConsentRecord(Base):
    """Append-only consent ledger. A grant and a later withdrawal are two
    rows; the *effective* consent for a (patient, purpose) is the newest row
    (see routers/pdpa.py::_effective_consent). Never updated or deleted --
    same discipline as ClinicalRecordAnnotation. `pdpa_notice` records that
    the patient was shown the PDPA privacy notice (transparency, not a
    processing gate).
    """
    __tablename__ = "consent_records"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose = Column(String(64), nullable=False, index=True)
    granted = Column(Boolean, nullable=False)          # True = grant, False = withdrawal
    source = Column(String(32), nullable=False)        # registration | portal | staff
    note = Column(Text, nullable=True)
    recorded_by = Column(String(36), nullable=True)    # users.id -- the patient's own id, or the staff who recorded it
    recorded_by_role = Column(String(64), nullable=True)
    created_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)


class DataSubjectRequest(Base):
    """A PDPA data-subject request and its handling workflow (tender
). `kind` is one of DSR_KINDS -- crucially NOT "erasure"
    (Malaysian PDPA has no such right; a withdraw_consent request toggles the
    consent ledger, it does not delete records). `due_at` = requested_at + 21
    days (the PDPA data-access-request statutory period, +14 extendable).
    An `access` / `portability` request's generated export lands in the
    object store (`export_object_key`, `clarion-reports-archive` bucket).
    """
    __tablename__ = "data_subject_requests"

    id = Column(String(36), primary_key=True, default=gen_id)
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default="open", index=True)
    detail = Column(Text, nullable=True)              # the patient's own description of the ask
    facility_name = Column(String(255), nullable=True, index=True)  # where it was filed
    requested_by = Column(String(36), nullable=True)  # users.id (patient's own, or staff on behalf)
    requested_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    due_at = Column(TZDateTime, nullable=True)

    assigned_to = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution_note = Column(Text, nullable=True)
    resolved_by = Column(String(36), nullable=True)
    resolved_at = Column(TZDateTime, nullable=True)
    export_object_key = Column(String(512), nullable=True)


class DpoRegister(Base):
    """One row per facility -- the Data Protection Officer contact registered
    with the Commissioner (JPDP). PDPA 2024 makes a DPO mandatory once a
    controller processes >=20,000 subjects (or >=10,000 sensitive-data
    subjects) -- University PKU is well over both. Lazily created on first read of
    GET /admin/dpo-register (same create-on-read pattern as HospitalSetting).
    """
    __tablename__ = "dpo_register"

    id = Column(String(36), primary_key=True, default=gen_id)
    facility_name = Column(String(255), nullable=False, unique=True, index=True)
    dpo_name = Column(String(255), nullable=True)
    dpo_email = Column(String(255), nullable=True)
    dpo_phone = Column(String(64), nullable=True)
    jpdp_registration_ref = Column(String(128), nullable=True)
    updated_by = Column(String(36), ForeignKey("users.id"), nullable=True)
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class RetentionPolicy(Base):
    """The retention schedule, one row per record category. `retain_years` is
    counted from the record's last-activity date; NULL = keep indefinitely
    (medico-legal). The retention scan (db/retention_scan.py) FLAGS rows past
    their window into `RetentionReviewItem` for an admin to review -- it
    never deletes (the audit chain is append-only and disposal is a DBA
    partition-drop job anyway). Seeded from the Malaysian defaults
    (healthcare/Malaysia Health Regulation.md); admin-editable.
    """
    __tablename__ = "retention_policies"

    id = Column(String(36), primary_key=True, default=gen_id)
    category = Column(String(48), nullable=False, unique=True)   # patient | encounter | condition | medication | allergy | document | audit | obstetric | paediatric | medicolegal
    retain_years = Column(Integer, nullable=True)                # NULL = indefinite
    basis = Column(Text, nullable=True)                          # the legal reference
    updated_by = Column(String(36), nullable=True)
    updated_at = Column(TZDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class RetentionReviewItem(Base):
    """One row per record flagged by the retention scan as past its window.
    FLAG ONLY -- an admin dispositions it (`disposed`) after the actual
    partition-drop / archival; the scan re-flags anything still present and
    not yet dispositioned. Keyed on (entity_type, entity_id) for the UPSERT.
    """
    __tablename__ = "retention_review_items"

    id = Column(String(36), primary_key=True, default=gen_id)
    entity_type = Column(String(32), nullable=False)
    entity_id = Column(String(36), nullable=False)
    patient_id = Column(String(36), ForeignKey("patients.id", ondelete="CASCADE"), nullable=True, index=True)
    category = Column(String(48), nullable=False)
    last_activity_at = Column(TZDateTime, nullable=True)
    retain_until = Column(TZDateTime, nullable=True)
    first_flagged_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    last_flagged_at = Column(TZDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    disposed = Column(Boolean, nullable=False, default=False, index=True)
    disposed_by = Column(String(36), nullable=True)
    disposed_at = Column(TZDateTime, nullable=True)
    disposition_note = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", name="uq_retention_review_items_entity"),
    )

