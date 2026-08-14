import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Text, Boolean, JSON, Integer
)
from sqlalchemy.orm import relationship

from .database import Base


def gen_id():
    return str(uuid.uuid4())


# Patient-profile fields that are worth nudging a patient to fill in right
# after login if still blank (missing_profile_fields on schemas.UserOut).
# Deliberately a plain list, not hardcoded logic per-field, so a future
# column addition (e.g. a 5th contact field) only ever means appending here
# — see auth_router.py's use of this for the "informational, not a security
# gate" computation.
PATIENT_PROFILE_FIELDS_TO_PROMPT = [
    "email",
    "phone",
    "emergency_contact_name",
    "emergency_contact_phone",
]


class User(Base):
    """A hospital staff account, a patient account, or an emergency-responder
    account. `role` drives what a token can see (see auth.py / rbac.py)."""
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # admin | clinician | records_officer | patient | emergency_responder
    facility = Column(String, nullable=True)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=True, index=True)  # set if role == patient

    # True right after a staff-issued temp password or a self-service reset,
    # cleared once the user successfully calls /auth/change-password. Lets
    # clients force a "you must change your password" screen.
    must_change_password = Column(Boolean, nullable=False, default=False)

    # Vestigial: rate limiting for the old self-service NRIC+DOB
    # /auth/forgot-password flow, which has been REMOVED and replaced by
    # the email-OTP reset (otp_* columns below). Left in place (unused by
    # any endpoint now, just zeroed by _apply_new_password for hygiene)
    # rather than dropped, since this project's migrations are additive
    # only (see main.py's _migrate_lightweight) — a destructive column
    # drop isn't worth the risk against a live seeded DB.
    reset_attempt_count = Column(Integer, nullable=False, default=0)
    reset_locked_until = Column(DateTime, nullable=True)

    # POST /auth/login failed-attempt rate limiting/lockout. Deliberately
    # separate columns from reset_attempt_count/reset_locked_until above —
    # those were scoped to the now-removed NRIC+DOB self-service
    # forgot-password flow only; these track wrong-password attempts
    # against this account's actual login. Keeping them independent means
    # a user locked out of one
    # flow isn't automatically locked out of the other, and vice versa.
    # Persisted (not in-memory) so it survives process restarts and works
    # correctly if the backend ever runs multiple workers.
    login_failed_count = Column(Integer, nullable=False, default=0)
    login_locked_until = Column(DateTime, nullable=True)

    # Password-reset-via-email-OTP state (POST /auth/request-password-reset-otp
    # and POST /auth/reset-password-with-otp). Only ever the HASH of the
    # 6-digit code is stored, never the plaintext — mirrors hashed_password.
    # otp_attempt_count is the *verify* attempt counter (wrong codes against
    # a live OTP); it is distinct from otp_request_count/otp_request_window_start
    # below, which rate-limit how often a fresh OTP can be *requested* in the
    # first place (stops email-bombing a patient's inbox). Both persisted
    # (not in-memory) so they survive process restarts, same reasoning as
    # reset_attempt_count/login_failed_count above.
    otp_code_hash = Column(String, nullable=True)
    otp_expires_at = Column(DateTime, nullable=True)
    otp_attempt_count = Column(Integer, nullable=False, default=0)
    otp_request_count = Column(Integer, nullable=False, default=0)
    otp_request_window_start = Column(DateTime, nullable=True)

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
    password_changed_at = Column(DateTime, nullable=True)

    patient = relationship("Patient", back_populates="user_account", foreign_keys=[patient_id])


class Patient(Base):
    __tablename__ = "patients"

    id = Column(String, primary_key=True, default=gen_id)
    full_name = Column(String, nullable=False)
    date_of_birth = Column(String, nullable=False)  # ISO date
    gender = Column(String, nullable=True)
    national_id = Column(String, unique=True, nullable=True)
    blood_type = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    senior_citizen_mode = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Patient-owned contact/profile fields, editable via the self-service
    # PATCH /patients/{id}/profile endpoint. Deliberately separate from
    # User.email, which stays the internal login-identifier/synthetic-
    # placeholder field (e.g. "patient-<id>@medibridge.local") and is never
    # shown to or edited by the patient directly. `email` here is where the
    # password-reset OTP is actually sent.
    email = Column(String, nullable=True)
    emergency_contact_name = Column(String, nullable=True)
    emergency_contact_phone = Column(String, nullable=True)
    emergency_contact_relationship = Column(String, nullable=True)

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

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    facility_name = Column(String, nullable=False)
    encounter_type = Column(String, nullable=False)  # outpatient | inpatient | emergency | transfer
    reason = Column(Text, nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)

    patient = relationship("Patient", back_populates="encounters")


class Condition(Base):
    __tablename__ = "conditions"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    name = Column(String, nullable=False)
    status = Column(String, default="active")  # active | resolved
    diagnosed_at = Column(String, nullable=True)
    is_chronic = Column(Boolean, default=False)
    critical_for_emergency = Column(Boolean, default=False)

    patient = relationship("Patient", back_populates="conditions")


class MedicationStatement(Base):
    __tablename__ = "medication_statements"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    drug_name = Column(String, nullable=False)
    dosage = Column(String, nullable=True)
    frequency = Column(String, nullable=True)
    prescribed_by_facility = Column(String, nullable=True)
    start_date = Column(String, nullable=True)
    active = Column(Boolean, default=True)
    critical_for_emergency = Column(Boolean, default=True)

    patient = relationship("Patient", back_populates="medications")


class AllergyIntolerance(Base):
    __tablename__ = "allergy_intolerances"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    substance = Column(String, nullable=False)
    reaction = Column(String, nullable=True)
    severity = Column(String, default="unknown")  # mild | moderate | severe
    critical_for_emergency = Column(Boolean, default=True)

    patient = relationship("Patient", back_populates="allergies")


class ClinicalDocument(Base):
    """A raw or AI-digitised document (scanned prescription, discharge summary,
    X-ray report). `extracted_text` / `ai_summary` are filled by the AI layer."""
    __tablename__ = "clinical_documents"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    doc_type = Column(String, nullable=False)  # prescription | discharge_summary | lab_report | imaging
    original_filename = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)          # OCR output
    ai_summary = Column(Text, nullable=True)         # LLM/rule-based summary
    uploaded_by_facility = Column(String, nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    # Local-disk path to the original uploaded file (backend/uploads/{patient_id}/{id}_{filename}),
    # set by POST /ai/digitise/{patient_id} on a best-effort basis after OCR.
    # NULL for any document uploaded before this column existed, or if the
    # disk write failed at upload time -- always check for NULL/missing-file
    # before assuming GET .../documents/{id}/file will succeed.
    file_path = Column(String, nullable=True)

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

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    facility_name = Column(String, nullable=False)
    venue = Column(String, nullable=True)             # room/building detail beyond facility_name
    scheduled_at = Column(DateTime, nullable=False)
    reason = Column(String, nullable=True)             # e.g. "Follow-up: diabetes review"
    precaution_notes = Column(Text, nullable=True)      # free-text, e.g. "bring prior scan results"
    fasting_required = Column(Boolean, default=False)
    fasting_hours = Column(Integer, nullable=True)      # meaningful only if fasting_required
    extra_reminder_hours_before = Column(JSON, nullable=True)  # list[int], doctor-added reminder offsets beyond the computed defaults, e.g. [72] for a 3-day-before reminder
    status = Column(String, default="scheduled")         # scheduled | cancelled | completed
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="appointments")


class MedicineInventoryItem(Base):
    """Facility-scoped medicine stock row, managed by that facility's own
    `admin` user (see routers/admin.py for the "manager admin, not super
    admin" scoping this and Ward both exist to demonstrate -- every
    query/write here is filtered/forced to the acting admin's own
    `User.facility`). Deliberately has NO relationship to `Patient` --
    this is inventory bookkeeping for a hospital, not clinical history tied
    to any one patient, so it doesn't belong under a patient record at all."""
    __tablename__ = "medicine_inventory"

    id = Column(String, primary_key=True, default=gen_id)
    facility_name = Column(String, nullable=False, index=True)
    drug_name = Column(String, nullable=False)
    quantity_on_hand = Column(Integer, nullable=False, default=0)
    unit = Column(String, nullable=False, default="units")  # e.g. "tablets", "vials", "boxes"
    reorder_threshold = Column(Integer, nullable=True)  # null = no low-stock tracking for this item
    notes = Column(Text, nullable=True)
    last_restocked_at = Column(DateTime, nullable=True)
    updated_by = Column(String, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class Ward(Base):
    """Facility-scoped bed/ward capacity row -- same "manager admin" scoping
    as MedicineInventoryItem above, and likewise has no relationship to
    `Patient` (bed occupancy here is an aggregate count, not a per-patient
    bed assignment -- this app doesn't model that level of detail)."""
    __tablename__ = "wards"

    id = Column(String, primary_key=True, default=gen_id)
    facility_name = Column(String, nullable=False, index=True)
    ward_name = Column(String, nullable=False)
    ward_type = Column(String, nullable=True)  # general | icu | pediatric | maternity | emergency | other -- validated in schemas.py, not a free enum in the DB
    total_beds = Column(Integer, nullable=False)
    occupied_beds = Column(Integer, nullable=False, default=0)
    updated_by = Column(String, ForeignKey("users.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)


class StaffClockEvent(Base):
    """One clock-in/clock-out shift record for a staff member. `facility_name`
    is SNAPSHOTTED at clock-in time (not a live join to User.facility) --
    same reasoning as AuditLog.actor_facility: a staff transfer to a
    different hospital later shouldn't rewrite which facility a past shift
    was actually worked at."""
    __tablename__ = "staff_clock_events"
    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    facility_name = Column(String, nullable=False, index=True)
    clock_in_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    clock_out_at = Column(DateTime, nullable=True)  # null while the shift is still open


class EmergencyToken(Base):
    """A short-lived, single-scope token bound to a QR code / physical card
    reference. Never stores the actual medical data — just the grant.

    Two independent "keys" can point at the same grant:
      - `card_reference`: the pointer encoded in the QR code, issued by the
        patient from the app (see /emergency/issue). Meant to be reissued
        often; short-lived by default.
      - `nfc_uid`: the UID of a physical NFC card/tag, registered by staff
        via /emergency/nfc/register (e.g. for a senior citizen without a
        smartphone). Longer-lived by default, admin-managed, admin-revocable.
    A grant may have either, both, or (rarely) be created with just one.
    """
    __tablename__ = "emergency_tokens"

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=False)
    token = Column(String, unique=True, nullable=False)
    card_reference = Column(String, unique=True, nullable=True)  # printed on physical card / encoded in QR
    nfc_uid = Column(String, unique=True, nullable=True)  # UID of a registered physical NFC tag/card
    scope = Column(JSON, default=lambda: ["allergies", "medications", "conditions", "blood_type"])
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    registered_by = Column(String, nullable=True)  # staff user id, for nfc_uid registrations


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

    id = Column(String, primary_key=True, default=gen_id)
    patient_id = Column(String, ForeignKey("patients.id"), nullable=True)
    actor = Column(String, nullable=False)          # user id, "emergency_token:<id>", or "system"
    actor_role = Column(String, nullable=True)
    actor_facility = Column(String, nullable=True)  # snapshot at access time -- see class docstring
    action = Column(String, nullable=False)         # e.g. "view_record", "emergency_access", "upload_document"
    fields_accessed = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    detail = Column(Text, nullable=True)
