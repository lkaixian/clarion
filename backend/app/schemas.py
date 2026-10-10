import re
from datetime import datetime, date, time, timezone
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from . import permissions
from . import models as _models


def _aware_utc(dt: datetime) -> datetime:
    """Normalise to aware UTC for a same-scope comparison against
    datetime.now(timezone.utc) -- a client-submitted datetime (Pydantic
    preserves whatever offset the request sent, e.g. '+08:00') would
    otherwise raise "can't compare offset-naive and offset-aware datetimes"
    against this codebase's naive-UTC "now" convention whenever the client
    includes a timezone offset. Genuinely offset-bearing input is CONVERTED
    (not just re-labelled), a naive one is tagged UTC -- same convention as
    routers/appointments.py::_to_aware_utc."""
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

# Minimum acceptable length for any newly-set password (staff-issued temp
# passwords are exempt -- they're generated server-side via
# auth.generate_temp_password(), which always produces 14 chars). Applied
# everywhere a human can choose/submit their own password: initial
# registration, the self-service email-OTP password reset, and
# authenticated change-password. Deliberately just a length floor, not a
# complexity policy (mandatory mixed-case/digits/symbols) -- this follows
# NIST SP 800-63B's guidance, which explicitly recommends AGAINST forced
# composition rules (they mostly push people toward predictable
# substitutions like "P@ssw0rd1" without meaningfully raising entropy) and
# FOR a longer minimum length plus a check against known-weak/breached
# passwords instead. Security Audit finding H3 flagged this policy as "no
# complexity" against 8 chars; the fix here is the length bump below plus
# _WEAK_PASSWORD_DENYLIST, not composition rules -- a stronger, better-
# evidenced mechanism aimed at the same underlying concern (guessable
# passwords), not a literal complexity checkbox.
MIN_PASSWORD_LENGTH = 12

# A small, deliberately non-exhaustive denylist of passwords that are weak
# regardless of length/composition (top-of-list common passwords, and this
# app's OWN seeded demo credentials -- see seed.py -- so a real user can
# never coincidentally reuse "admin123" etc. as their actual password).
# This is NOT a substitute for a real breached-password API (e.g.
# Have I Been Pwned's k-anonymity range API) -- that would be a network
# call to a third party, which this codebase deliberately avoids
# everywhere (all AI inference is on-prem too, see app/ai/local_llm.py) --
# it's a cheap, offline floor that catches the most obviously bad choices.
_WEAK_PASSWORD_DENYLIST = frozenset({
    "password", "password1", "password123", "12345678", "123456789",
    "1234567890", "qwerty123", "qwertyuiop", "letmein123", "welcome123",
    "changeme123", "iloveyou1", "admin1234", "administrator",
    "trustno1", "monkey123", "sunshine1", "princess1", "football1",
    # This app's own seeded demo credentials (see seed.py) -- never valid
    # as a REAL user's chosen password, demo convenience or not.
    "admin123", "clinician123", "pharmacist123", "receptionist123", "patient123",
})


def _validate_password_length(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if value.lower() in _WEAK_PASSWORD_DENYLIST:
        raise ValueError("This password is too common/predictable. Choose a different one.")
    return value


# Every role string the app recognises. Enforced on UserCreate.role (staff
# account creation via POST /auth/register) -- previously `role` was a bare
# `str` with no validation at all, so a typo ("clinicain") or an unknown
# value would create an account that silently failed every require_roles
# check. "pharmacist" (Phase G) is scoped to medicine inventory + own
# clock-in/out only.
VALID_ROLES = {
    "admin",
    "clinician",
    "records_officer",
    # Front-desk / reception staff. By default (see app/permissions.py's
    # DEFAULT_ROLE_PAGES) this role can only reach the Reception page --
    # an admin can widen that per facility via PUT /admin/role-permissions.
    "receptionist",
    "patient",
    "emergency_responder",
    "pharmacist",
}


# ---------- Auth ----------
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str  # admin | clinician | records_officer | receptionist | patient | emergency_responder | pharmacist
    facility: Optional[str] = None
    patient_id: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _password_min_length(cls, v: str) -> str:
        return _validate_password_length(v)

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in VALID_ROLES:
            raise ValueError(
                f"role must be one of: {', '.join(sorted(VALID_ROLES))}"
            )
        return v


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    facility: Optional[str] = None
    patient_id: Optional[str] = None
    must_change_password: bool = False
    # True once TOTP MFA is confirmed (models.User.mfa_enabled property).
    mfa_enabled: bool = False
    # Per-counter reception scoping (models.User.section) -- the
    # FacilitySection name this receptionist/clinician is hard-pinned to, or
    # None if unscoped. Plain ORM column, so UserOut.from_attributes picks it
    # up automatically on both POST /auth/login and GET /auth/me. Lets the
    # web console label the reception board with the active section.
    section: Optional[str] = None
    # Data-completeness signal for patient-role users only (always [] for
    # staff/emergency-responder roles) -- which of
    # models.PATIENT_PROFILE_FIELDS_TO_PROMPT are still null/empty on the
    # linked Patient row. Purely informational: unlike must_change_password
    # this is NOT a security gate and never blocks/403s anything, just lets
    # a client show a soft "please fill in your contact details" prompt.
    # Populated by auth_router (not a plain ORM attribute), so it always
    # goes through UserOut's from_attributes path via an explicit
    # model_validate(..., ) call rather than FastAPI's implicit ORM read.
    missing_profile_fields: List[str] = []
    # True when this user has a saved digital signature
    # (models.User.signature_object_key is set). Computed (bool of the key
    # column), attached by auth_router alongside allowed_pages on
    # POST /auth/login and GET /auth/me -- lets a client show/hide the
    # "save your signature" nudge and know a consultation sign-off won't 409.
    has_signature: bool = False
    # Free-text professional bio + internal contact email (models.User.bio /
    # .contact_email) -- plain ORM columns, picked up automatically via
    # from_attributes, same as `section` above. `bio` is PUBLIC (patient
    # booking picker); `contact_email` is internal-only and is never the
    # login/auth email. Self- or admin-editable, see routers/profile.py /
    # routers/admin.py.
    bio: Optional[str] = None
    contact_email: Optional[str] = None
    # True when this user has a saved profile photo
    # (models.User.photo_object_key is set). Same computed-and-stashed
    # pattern as has_signature above.
    has_photo: bool = False
    # The console pages this user is allowed to reach -- drives the web
    # console's nav, routing, and post-login landing page. Computed (not a
    # DB column) and stashed as an unmapped attribute by auth_router
    # (_attach_allowed_pages) on both POST /auth/login and GET /auth/me,
    # same technique as missing_profile_fields above:
    #   - admin                         -> ["patients","reception","pharmacy","admin"]
    #   - clinician / records_officer /
    #     receptionist / pharmacist      -> that (facility, role)'s allowed_pages
    #                                       (see models.RolePagePermission /
    #                                        app/permissions.py; lazy default)
    #   - patient / emergency_responder -> []  (not page-gated)
    # Enforced server-side by auth.require_page_access (router-level in
    # main.py) -- this field is the client's copy of that same decision.
    allowed_pages: List[str] = []

    class Config:
        from_attributes = True


class MfaChallenge(BaseModel):
    """POST /auth/login when a second factor is still needed: NO access
    token yet. `mfa_enrol` = the account's role requires MFA but it has not
    been set up (the client shows the enrolment screen instead of a code box)."""
    mfa_required: bool = True
    mfa_enrol: bool = False
    mfa_token: str


class MfaCodeRequest(BaseModel):
    mfa_token: str
    code: str = Field(min_length=6, max_length=16)


class MfaTokenRequest(BaseModel):
    mfa_token: str


class MfaEnrolStartOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_png_base64: str


class PasswordOnly(BaseModel):
    password: str


class PasswordAndCode(BaseModel):
    password: str
    code: str = Field(min_length=6, max_length=16)


class SessionOut(BaseModel):
    id: str
    ip: Optional[str] = None
    user_agent: Optional[str] = None
    issued_at: Any = None
    current: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    # P2.5 (Security Audit M4): present ONLY for a native client (Flutter),
    # which has no browser cookie jar and stores this itself via secure
    # OS-keychain storage (see mobile_flutter's TokenStorage) -- the web
    # console gets the equivalent refresh token exclusively as an HttpOnly
    # cookie (never in this JSON body) and MUST NOT read or persist this
    # field even if it happens to be present. See
    # docs/deployment.md's "Session / refresh tokens" section.
    refresh_token: Optional[str] = None


class RefreshTokenRequest(BaseModel):
    """POST /auth/refresh's optional JSON body -- native-client path only.
    The web client relies entirely on the HttpOnly cookie instead and
    sends no body at all."""
    refresh_token: Optional[str] = None


# ---------- Patient account issuance / password reset ----------
class IssueAccountResponse(BaseModel):
    """Response for POST /auth/patients/{patient_id}/issue-account.
    `temporary_password` is shown exactly once — it is never stored or
    logged in plaintext anywhere after this response is sent."""

    temporary_password: str
    national_id: Optional[str] = None
    email: str
    must_change_password: bool = True


class PasswordResetOtpRequest(BaseModel):
    """Public, unauthenticated. Step 1 of the two-step email-OTP reset:
    identify the account by NRIC alone (dash-tolerant, see nric.py). No DOB
    or other guessable PII involved -- proof of identity comes from the
    OTP emailed to the patient's own registered address in step 2."""

    national_id: str


class PasswordResetWithOtpRequest(BaseModel):
    """Public, unauthenticated. Step 2 of the two-step email-OTP reset."""

    national_id: str
    otp_code: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password_min_length(cls, v: str) -> str:
        return _validate_password_length(v)


# ---------- Self-service patient registration (NRIC-OCR identity verification) ----------
# Alternative to staff-issued accounts (IssueAccountResponse above) -- see
# routers/self_registration.py's module docstring for the full multi-factor
# design (NRIC + DOB + name + emailed OTP + OCR-verified NRIC photos, all
# checked against an EXISTING Patient row; never creates a new Patient).
class SelfRegisterStartRequest(BaseModel):
    """Public, unauthenticated. Step 1 of self-service registration.
    No date_of_birth field here (deliberately removed, not deprecated-kept)
    -- a standard Malaysian NRIC's first 6 digits already encode the
    holder's birthdate, so the router derives the expected date_of_birth
    from national_id itself (see routers/self_registration.py::
    start_self_registration, via ai/nric_ocr.py::dob_from_ic_number) and
    checks it against Patient.date_of_birth as a self-consistency check,
    rather than asking the caller to separately supply it as an
    independently-known factor."""

    national_id: str
    full_name: str
    email: EmailStr


class SelfRegisterVerifyOtpRequest(BaseModel):
    """Public, unauthenticated. Step 2 of self-service registration."""

    national_id: str
    otp_code: str


class SelfRegisterCompleteRequest(BaseModel):
    """Public, unauthenticated. Final step of self-service registration --
    only reachable once the attempt's status is photo_verified (router
    enforces this). Same password-length floor as every other
    human-chosen-password endpoint in this API."""

    national_id: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password_min_length(cls, v: str) -> str:
        return _validate_password_length(v)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password_min_length(cls, v: str) -> str:
        return _validate_password_length(v)


# ---------- Patient ----------
class PatientCreate(BaseModel):
    full_name: str
    # Optional on the wire: when national_id is a standard, parseable
    # Malaysian NRIC, the router derives date_of_birth server-side from the
    # NRIC itself (see routers/patients.py::create_patient, which uses
    # ai/nric_ocr.py's dob_from_ic_number) and that derived value OVERRIDES
    # whatever's sent here -- staff should never have to (and can't
    # override, if the NRIC is standard) hand-type a DOB that the NRIC
    # already encodes. Only actually required, and only actually taken from
    # the client, when national_id is absent or doesn't resolve to a
    # plausible date (see create_patient for the exact fallback logic).
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    national_id: Optional[str] = None
    blood_type: Optional[str] = None
    phone: Optional[str] = None
    senior_citizen_mode: bool = False


class PatientOut(PatientCreate):
    id: str
    created_at: datetime
    email: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None

    class Config:
        from_attributes = True


# Fields a patient is allowed to self-edit via PATCH /patients/{id}/profile.
# full_name / date_of_birth / national_id are deliberately NOT here --
# they're immutable via self-service by design (identity fields), and the
# endpoint explicitly rejects any request body that tries to set them
# rather than silently ignoring them.
PATIENT_SELF_EDITABLE_FIELDS = {
    "email",
    "phone",
    "emergency_contact_name",
    "emergency_contact_phone",
    "emergency_contact_relationship",
}

PATIENT_IMMUTABLE_FIELDS = {"full_name", "date_of_birth", "national_id"}


class PatientProfileUpdate(BaseModel):
    """Partial self-service profile update. Every field optional; the
    router only touches fields actually present in the request body (see
    model_fields_set), so omitting a field leaves it unchanged rather than
    clearing it. `extra="forbid"` at the model level would reject unknown
    keys, but full_name/date_of_birth/national_id are *known* keys we want
    a clear, specific error for -- handled explicitly in the router instead
    so the error message names exactly which immutable field was sent."""

    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    emergency_contact_name: Optional[str] = None
    emergency_contact_phone: Optional[str] = None
    emergency_contact_relationship: Optional[str] = None

    class Config:
        extra = "allow"  # so the router can detect & reject full_name/date_of_birth/national_id explicitly


# ---------- Clinical sub-resources ----------
class ConditionCreate(BaseModel):
    name: str
    status: str = "active"
    diagnosed_at: Optional[str] = None
    is_chronic: bool = False
    critical_for_emergency: bool = False


class ConditionUpdate(BaseModel):
    """Partial update for PATCH /patients/{id}/conditions/{condition_id}.
    Every field optional; only fields actually present in the request body
    are applied (see model_fields_set / exclude_unset in the router)."""

    name: Optional[str] = None
    status: Optional[str] = None
    diagnosed_at: Optional[str] = None
    is_chronic: Optional[bool] = None
    critical_for_emergency: Optional[bool] = None

    class Config:
        extra = "forbid"


class MedicationCreate(BaseModel):
    drug_name: str
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    prescribed_by_facility: Optional[str] = None
    start_date: Optional[str] = None
    active: bool = True
    critical_for_emergency: bool = True


class MedicationUpdate(BaseModel):
    drug_name: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    # The prescriber (may be external) -- informational, editable. NOT the
    # immutability key; that's recorded_by_facility, which has no field here
    # (mirrors ConditionUpdate/AllergyUpdate never exposing authored_by_facility).
    prescribed_by_facility: Optional[str] = None
    start_date: Optional[str] = None
    active: Optional[bool] = None
    critical_for_emergency: Optional[bool] = None

    class Config:
        extra = "forbid"


class AllergyCreate(BaseModel):
    substance: str
    reaction: Optional[str] = None
    severity: str = "unknown"
    critical_for_emergency: bool = True


class AllergyUpdate(BaseModel):
    substance: Optional[str] = None
    reaction: Optional[str] = None
    severity: Optional[str] = None
    critical_for_emergency: Optional[bool] = None

    class Config:
        extra = "forbid"


# Enforced on both create and edit (POST /patients/{id}/encounters and
# PATCH /patients/{id}/encounters/{encounter_id}) -- the Encounter.encounter_type
# column comment has documented this enum since the column was added, but
# nothing actually validated it server-side until now, so arbitrary strings
# were silently accepted.
VALID_ENCOUNTER_TYPES = {"outpatient", "inpatient", "emergency", "transfer"}


def _validate_encounter_type(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in VALID_ENCOUNTER_TYPES:
        raise ValueError(
            f"encounter_type must be one of: {', '.join(sorted(VALID_ENCOUNTER_TYPES))}"
        )
    return v


# Enforced on POST /ai/digitise/{patient_id} -- mirrors VALID_ENCOUNTER_TYPES
# above. ClinicalDocument.doc_type's intended enum has been documented in a
# models.py comment since the column was added (see app/models.py), but
# nothing actually validated it server-side until now, so arbitrary strings
# were silently accepted.
VALID_DOC_TYPES = {"prescription", "discharge_summary", "lab_report", "imaging"}

# P3.5: the 3 STAFF-GENERATED document kinds (routers/patients.py
# ::generate_document / app/document_generation.py) -- a deliberately
# separate set from VALID_DOC_TYPES above rather than folding into it, since
# these are never uploaded and carry different required fields.
VALID_GENERATED_DOC_TYPES = {"medical_certificate", "referral_letter", "timeslip"}


class GenerateDocumentRequest(BaseModel):
    """Body for POST /patients/{patient_id}/documents/generate. One flat,
    all-Optional field set covering all 3 doc_types (same style as
    ConsultationCompleteRequest's SOAP fields) -- the model_validator below
    enforces which fields are actually required, keyed on doc_type, so the
    error names the missing field instead of a generic 422 shape mismatch.
    Free-text fields are capped short enough that the rendered PDF's fixed
    single page (app/document_generation.py) never needs to overflow."""

    doc_type: str
    # Medical certificate
    diagnosis: Optional[str] = Field(default=None, max_length=500)
    rest_from: Optional[date] = None
    rest_to: Optional[date] = None
    remarks: Optional[str] = Field(default=None, max_length=500)
    # Referral letter
    referred_to: Optional[str] = Field(default=None, max_length=255)
    reason_for_referral: Optional[str] = Field(default=None, max_length=500)
    clinical_summary: Optional[str] = Field(default=None, max_length=500)
    urgency: Optional[str] = None  # "routine" | "urgent", defaults to routine
    # Timeslip
    visit_date: Optional[date] = None
    time_in: Optional[time] = None
    time_out: Optional[time] = None
    purpose: Optional[str] = Field(default=None, max_length=255)
    # Save-on-the-spot signature, same convention as every other sign-off
    # endpoint (ConsultationCompleteRequest / RecordAnnotationCreate).
    signature_b64: Optional[str] = Field(default=None, max_length=1_400_000)

    class Config:
        extra = "forbid"
        # A whitespace-only "diagnosis"/"reason_for_referral"/etc. must not
        # sneak past the required-field check below as truthy -- strip
        # first, so "   " normalizes to "" and is correctly caught as missing.
        str_strip_whitespace = True

    @field_validator("doc_type")
    @classmethod
    def _check_doc_type(cls, v: str) -> str:
        if v not in VALID_GENERATED_DOC_TYPES:
            raise ValueError(
                f"doc_type must be one of: {', '.join(sorted(VALID_GENERATED_DOC_TYPES))}"
            )
        return v

    @field_validator("urgency")
    @classmethod
    def _check_urgency(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("routine", "urgent"):
            raise ValueError("urgency must be 'routine' or 'urgent'")
        return v

    @model_validator(mode="after")
    def _check_required_fields(self) -> "GenerateDocumentRequest":
        required_by_type = {
            "medical_certificate": ("diagnosis", "rest_from", "rest_to"),
            "referral_letter": ("referred_to", "reason_for_referral"),
            "timeslip": ("visit_date", "time_in", "time_out"),
        }
        missing = [f for f in required_by_type[self.doc_type] if not getattr(self, f)]
        if missing:
            raise ValueError(
                f"doc_type '{self.doc_type}' requires: {', '.join(missing)}"
            )
        if self.doc_type == "medical_certificate" and self.rest_to < self.rest_from:
            raise ValueError("rest_to must not be before rest_from")
        if self.doc_type == "timeslip" and self.time_out <= self.time_in:
            raise ValueError("time_out must be after time_in")
        return self


class EncounterCreate(BaseModel):
    facility_name: str
    encounter_type: str
    reason: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("encounter_type")
    @classmethod
    def _check_encounter_type(cls, v: str) -> str:
        return _validate_encounter_type(v)


class EncounterUpdate(BaseModel):
    # facility_name is deliberately NOT editable here -- an encounter always
    # happens AT one facility, and that facility is the authoring facility for
    # the cross-hospital immutability guard (clinical_access.py::_row_author_facility).
    # Letting an editor rewrite it would let them hand the row's edit rights to
    # another facility or hide it by pointing it at an opted-out one.
    encounter_type: Optional[str] = None
    reason: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("encounter_type")
    @classmethod
    def _check_encounter_type(cls, v: Optional[str]) -> Optional[str]:
        return _validate_encounter_type(v)

    class Config:
        extra = "forbid"


# ---------- Appointments ----------
# Enforced on PATCH /patients/{id}/appointments/{appointment_id} (staff-only
# status transition) -- mirrors VALID_ENCOUNTER_TYPES/VALID_DOC_TYPES above.
# Soft-cancel only: a "cancelled" appointment row is never deleted (matches
# EmergencyToken.revoked's pattern elsewhere in this codebase), so history/
# audit trail stays intact.
VALID_APPOINTMENT_STATUSES = {"scheduled", "cancelled", "completed"}


def _validate_fasting_relationship(fasting_required: Optional[bool], fasting_hours: Optional[int]) -> None:
    """Shared guard for AppointmentCreate and (post-merge, in the router)
    AppointmentUpdate: fasting_hours only makes sense paired with
    fasting_required=True. Raising here on create catches the raw-payload
    case; the router re-runs this same check against the MERGED row after
    applying a PATCH's exclude_unset fields, so a PATCH that sets
    fasting_hours alone (leaving a pre-existing fasting_required=False
    untouched) is still caught -- see AppointmentUpdate's docstring."""
    if fasting_hours is not None and not fasting_required:
        raise ValueError("fasting_hours can only be set when fasting_required is true.")


class AppointmentCreate(BaseModel):
    facility_name: str
    venue: Optional[str] = None
    scheduled_at: datetime
    reason: Optional[str] = None
    fasting_required: bool = False
    fasting_hours: Optional[int] = None
    precaution_notes: Optional[str] = None
    extra_reminder_hours_before: Optional[List[int]] = None

    @field_validator("scheduled_at")
    @classmethod
    def _check_not_past(cls, v: datetime) -> datetime:
        # Staff shouldn't be able to publish an appointment already in the
        # past -- almost certainly a typo (wrong date/year) rather than an
        # intentional backdated record; this app has no legitimate use case
        # for a "past" scheduled appointment (that's what encounters are for).
        if _aware_utc(v) < datetime.now(timezone.utc):
            raise ValueError("scheduled_at cannot be in the past.")
        return v

    @field_validator("fasting_hours")
    @classmethod
    def _check_fasting_relationship(cls, v: Optional[int], info) -> Optional[int]:
        _validate_fasting_relationship(info.data.get("fasting_required"), v)
        return v


class AppointmentUpdate(BaseModel):
    """Partial update for PATCH /patients/{id}/appointments/{appointment_id}.
    Every field optional; only fields actually present in the request body
    are applied (see model_fields_set / exclude_unset in the router),
    matching ConditionUpdate/MedicationUpdate/etc.'s exact pattern.

    Deliberately does NOT re-validate the fasting_hours/fasting_required
    relationship against just this payload (a PATCH containing only
    fasting_hours, with fasting_required already true on the existing row,
    is legitimate) -- the router re-checks the relationship against the
    MERGED row after applying these fields instead.
    """

    facility_name: Optional[str] = None
    venue: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    reason: Optional[str] = None
    fasting_required: Optional[bool] = None
    fasting_hours: Optional[int] = None
    precaution_notes: Optional[str] = None
    extra_reminder_hours_before: Optional[List[int]] = None
    status: Optional[str] = None  # staff-only transition, e.g. to "cancelled"

    @field_validator("status")
    @classmethod
    def _check_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_APPOINTMENT_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(sorted(VALID_APPOINTMENT_STATUSES))}"
            )
        return v

    class Config:
        extra = "forbid"


# P3.10: patient self-service booking. Deliberately a much
# narrower surface than AppointmentCreate -- no reason/precaution_notes/
# fasting fields (clinical judgment calls, staff-only; see
# _APPOINTMENT_STAFF_ROLES in routers/appointments.py) -- a patient only
# ever picks WHERE and WHEN.
class SelfBookAppointmentRequest(BaseModel):
    facility_name: str
    department: Optional[str] = None
    clinician_id: Optional[str] = None
    scheduled_at: datetime

    class Config:
        extra = "forbid"


class AppointmentSlotOut(BaseModel):
    """One bookable slot returned by GET /patients/appointment-slots."""
    scheduled_at: datetime
    clinician_id: Optional[str] = None
    clinician_name: Optional[str] = None


class BookingClinicianOut(BaseModel):
    id: str
    full_name: str
    department: Optional[str] = None  # the clinician's pinned User.section, if any
    # PUBLIC-facing (models.User.bio) -- unlike contact_email, this is meant
    # for a patient's self-booking clinician picker. has_photo drives
    # whether the client bothers calling GET /patients/clinicians/{id}/photo.
    bio: Optional[str] = None
    has_photo: bool = False


class BookingOptionsOut(BaseModel):
    """GET /patients/booking-options -- the pickers a self-booking flow
    needs for one facility."""
    departments: List[str] = []
    clinicians: List[BookingClinicianOut] = []


class AppointmentOut(BaseModel):
    id: str
    patient_id: str
    facility_name: str
    venue: Optional[str] = None
    scheduled_at: datetime
    reason: Optional[str] = None
    fasting_required: bool = False
    fasting_hours: Optional[int] = None
    precaution_notes: Optional[str] = None
    extra_reminder_hours_before: Optional[List[int]] = None
    status: str
    created_by: str
    created_at: datetime
    # P3.10 -- see models.Appointment's docstring.
    department: Optional[str] = None
    clinician_id: Optional[str] = None
    self_booked: bool = False
    # Reschedule tracking -- see models.Appointment's docstring. All null on
    # an appointment that's never been rescheduled.
    previous_scheduled_at: Optional[datetime] = None
    reschedule_reason_code: Optional[str] = None
    reschedule_reason_other: Optional[str] = None
    # Computed (not a DB column) via appointments.compute_reminder_offsets --
    # see that function's docstring for why the exact reminder rule lives
    # only there. Populated explicitly by the router (not via from_attributes
    # ORM auto-read), since it isn't a plain attribute on models.Appointment.
    reminders: List[dict] = []
    # The most recent AppointmentRescheduleRequest filed against this
    # appointment, regardless of outcome (pending/accepted/rejected) -- None
    # if the patient has never requested a reschedule. Deliberately not
    # narrowed to "only pending" so a patient/staff member can still see how
    # their last request was resolved (e.g. a rejection note), not just
    # whether one is currently open. Populated explicitly by the router
    # (same pattern as `reminders` above), since it's a live query, not a
    # plain attribute on models.Appointment.
    latest_reschedule_request: Optional["RescheduleRequestOut"] = None

    class Config:
        from_attributes = True


# ---------- Appointment rescheduling ----------
# Staff reschedule (clinician/admin/records_officer picks a new time
# unprompted, or after agreeing one with the patient by phone following an
# accepted reschedule request) vs. patient reschedule REQUEST (the patient
# only ever asks; staff must accept/reject it, and accepting does not by
# itself move the appointment -- see AppointmentRescheduleRequest's
# docstring in models.py for why). Two separate, deliberately non-overlapping
# reason vocabularies: a patient never sees "Doctor unavailable" as a reason
# for THEIR OWN request, and staff never see "Transport issue" as a reason
# they'd give for rescheduling someone.
STAFF_RESCHEDULE_REASON_CODES = {
    "doctor_unavailable",
    "facility_or_equipment_issue",
    "emergency_prioritization",
    "patient_requested",  # staff rescheduling because the patient asked (by phone, in person, or after accepting an in-app request)
    "other",
}

PATIENT_RESCHEDULE_REASON_CODES = {
    "schedule_conflict",
    "unwell_or_cannot_travel",
    "transport_issue",
    "other",
}


def _check_reason_other_required(reason_code: str, reason_other: Optional[str]) -> None:
    """Shared guard for both reschedule reason vocabularies: 'other' is only
    useful paired with actual free text -- an 'other' reason with nothing
    typed in gives staff/patient strictly less information than one of the
    named options would have."""
    if reason_code == "other" and not (reason_other and reason_other.strip()):
        raise ValueError("reason_other is required when reason_code is 'other'.")


class RescheduleAppointmentRequest(BaseModel):
    """Body for POST /patients/{id}/appointments/{id}/reschedule -- the
    staff-only action that actually moves scheduled_at. Reuses
    AppointmentCreate._check_not_past's exact reasoning: a reschedule to a
    time already in the past is almost certainly a typo, not intentional."""

    new_scheduled_at: datetime
    reason_code: str
    reason_other: Optional[str] = None

    @field_validator("new_scheduled_at")
    @classmethod
    def _check_not_past(cls, v: datetime) -> datetime:
        if _aware_utc(v) < datetime.now(timezone.utc):
            raise ValueError("new_scheduled_at cannot be in the past.")
        return v

    @field_validator("reason_code")
    @classmethod
    def _check_reason_code(cls, v: str) -> str:
        if v not in STAFF_RESCHEDULE_REASON_CODES:
            raise ValueError(f"reason_code must be one of: {', '.join(sorted(STAFF_RESCHEDULE_REASON_CODES))}")
        return v

    @model_validator(mode="after")
    def _check_other_text(self):
        _check_reason_other_required(self.reason_code, self.reason_other)
        return self


class RescheduleRequestCreate(BaseModel):
    """Body for POST /patients/{id}/appointments/{id}/reschedule-requests --
    the patient-only action that files a request for staff to review."""

    reason_code: str
    reason_other: Optional[str] = None

    @field_validator("reason_code")
    @classmethod
    def _check_reason_code(cls, v: str) -> str:
        if v not in PATIENT_RESCHEDULE_REASON_CODES:
            raise ValueError(f"reason_code must be one of: {', '.join(sorted(PATIENT_RESCHEDULE_REASON_CODES))}")
        return v

    @model_validator(mode="after")
    def _check_other_text(self):
        _check_reason_other_required(self.reason_code, self.reason_other)
        return self


class RescheduleRequestRejectBody(BaseModel):
    clinician_note: Optional[str] = None


class RescheduleRequestOut(BaseModel):
    id: str
    appointment_id: str
    patient_id: str
    requested_by: str
    reason_code: str
    reason_other: Optional[str] = None
    status: str  # pending | accepted | rejected
    clinician_note: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None

    class Config:
        from_attributes = True


AppointmentOut.model_rebuild()


class PatientFullRecord(PatientOut):
    conditions: List[ConditionCreate] = []
    medications: List[MedicationCreate] = []
    allergies: List[AllergyCreate] = []


# ---------- Admin (facility-scoped: manager admin, not super admin) ----------
# See routers/admin.py's module docstring for the scoping rule these schemas
# support: every admin endpoint is auto-scoped to current_user.facility,
# never client-supplied.
class AdminAppointmentOut(AppointmentOut):
    """GET /admin/appointments row shape -- AppointmentOut (patient_id is
    already on that base) plus patient_name and created_by_name, both
    resolved via a LIVE join at read time (same "resolve display names live,
    don't snapshot them" reasoning as patients.py::get_audit_log's
    actor_name -- a patient's name correction or a staff member's legal name
    change shouldn't leave old admin-dashboard rows showing a stale name)."""

    patient_name: str
    # None if the creating staff account has since been deleted -- mirrors
    # get_audit_log's actor_name null-safety for the exact same reason (the
    # row/appointment itself must still render even if its creator is gone).
    created_by_name: Optional[str] = None


class MedicineInventoryCreate(BaseModel):
    drug_name: str
    quantity_on_hand: int = 0
    unit: str = "units"
    reorder_threshold: Optional[int] = None
    notes: Optional[str] = None
    # Optional scanned/keyed barcode (see MedicineInventoryItem.barcode).
    # Admin-set at create time; searchable via GET .../inventory?q=.
    barcode: Optional[str] = None
    # Per single `unit` procurement cost (RM). Drives the budget /
    # procurement-spend rollup (see routers/admin.py::get_budget and the
    # pharmacy restock flow). Nullable = "cost not tracked yet" (treated as
    # 0 in the rollup).
    unit_cost: Optional[float] = None

    @field_validator("quantity_on_hand")
    @classmethod
    def _check_quantity_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("quantity_on_hand cannot be negative.")
        return v

    @field_validator("reorder_threshold")
    @classmethod
    def _check_threshold_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("reorder_threshold cannot be negative.")
        return v

    @field_validator("unit_cost")
    @classmethod
    def _check_unit_cost_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("unit_cost cannot be negative.")
        return v


class MedicineInventoryUpdate(BaseModel):
    """Partial update for PATCH /admin/inventory/{item_id}. Every field
    optional; only fields actually present in the request body are applied
    (see exclude_unset in the router), matching ConditionUpdate/
    MedicationUpdate/etc.'s exact pattern. Same non-negative validation as
    MedicineInventoryCreate, applied to whatever's actually set."""

    drug_name: Optional[str] = None
    quantity_on_hand: Optional[int] = None
    unit: Optional[str] = None
    reorder_threshold: Optional[int] = None
    notes: Optional[str] = None
    unit_cost: Optional[float] = None
    barcode: Optional[str] = None
    # Admin-only toggle for the purchase-approval workflow: when True a
    # pharmacist restock applies immediately, when False it files a
    # MedicinePurchaseProposal for admin review. Only reachable through the
    # admin router (PATCH /admin/inventory/{id}); the pharmacy router never
    # accepts this schema, so a pharmacist token cannot flip it.
    auto_approved: Optional[bool] = None

    @field_validator("quantity_on_hand")
    @classmethod
    def _check_quantity_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("quantity_on_hand cannot be negative.")
        return v

    @field_validator("reorder_threshold")
    @classmethod
    def _check_threshold_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("reorder_threshold cannot be negative.")
        return v

    @field_validator("unit_cost")
    @classmethod
    def _check_unit_cost_non_negative(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v < 0:
            raise ValueError("unit_cost cannot be negative.")
        return v

    class Config:
        extra = "forbid"


class MedicineInventoryOut(BaseModel):
    id: str
    facility_name: str
    drug_name: str
    quantity_on_hand: int
    unit: str
    reorder_threshold: Optional[int] = None
    notes: Optional[str] = None
    last_restocked_at: Optional[datetime] = None
    unit_cost: Optional[float] = None
    barcode: Optional[str] = None
    # True while an admin has opted this item into immediate pharmacist
    # restocks (see MedicineInventoryItem.auto_approved).
    auto_approved: bool = False
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    created_at: datetime
    # Computed (not a DB column) -- deliberately re-derived on every read
    # rather than stored, so a change to reorder_threshold or
    # quantity_on_hand can never leave a stale is_low_stock flag behind.
    is_low_stock: bool = False
    # Computed in the serializer -- True while an unresolved (pending)
    # InventoryDeleteRequest exists for this item, so the UI can show
    # "deletion requested" instead of offering the request button again.
    pending_delete_request: bool = False
    # Whether a medicine photo has been uploaded (image_object_key set on
    # the row). `image_url` is the authenticated GET endpoint the frontend
    # hits to render it -- null when has_image is False. Both computed in
    # the serializer; the raw object key is never exposed.
    has_image: bool = False
    image_url: Optional[str] = None
    # P1.7: authenticated GET endpoint for a 300px preview JPEG (regenerated
    # on demand from the original). Null when has_image is False.
    thumbnail_url: Optional[str] = None

    class Config:
        from_attributes = True


# ---------- Pharmacy: stock adjustments, budget, delete-approval ----------
class StockAdjustRequest(BaseModel):
    """Body for POST /pharmacy/inventory/{item_id}/adjust. `delta` > 0 is a
    restock (accrues procurement spend at `unit_cost` or the item's stored
    unit_cost); `delta` < 0 is a dispense/consume (no budget effect)."""

    delta: int
    unit_cost: Optional[float] = None

    @field_validator("delta")
    @classmethod
    def _check_delta(cls, v: int) -> int:
        # A single stock movement is bounded -- a real restock/dispense is
        # never millions of units, and an unbounded delta lets a pharmacist
        # (or a stolen pharmacist token) drive the medicine budget wildly
        # negative in one call. Anything larger is a data-entry error.
        if v == 0:
            raise ValueError("delta must be a non-zero integer.")
        if abs(v) > 1_000_000:
            raise ValueError("delta magnitude must be <= 1,000,000.")
        return v

    @field_validator("unit_cost")
    @classmethod
    def _check_unit_cost(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0 or v > 1_000_000):
            raise ValueError("unit_cost must be between 0 and 1,000,000.")
        return v


class InventoryDeleteRequestCreate(BaseModel):
    reason: Optional[str] = None


class InventoryDeleteRequestOut(BaseModel):
    id: str
    item_id: str
    item_name: str
    requested_by: str
    # Live join to users.full_name (None if that account is since gone) --
    # same convention as AdminAppointmentOut.created_by_name.
    requested_by_name: Optional[str] = None
    reason: Optional[str] = None
    status: str  # pending | approved | rejected
    created_at: datetime
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    admin_note: Optional[str] = None

    class Config:
        from_attributes = True


class DeleteRequestResolve(BaseModel):
    admin_note: Optional[str] = None


class BudgetOut(BaseModel):
    allocated_amount: float
    procurement_spend: float
    current_stock_value: float
    remaining: float
    # Number of this facility's inventory items currently at/below their
    # reorder_threshold -- surfaced here (not just on GET
    # /pharmacy/inventory/low-stock) so the pharmacy/admin budget console
    # can badge "N items low" without a second round-trip. Defaulted so the
    # PUT /admin/budget response (which doesn't recompute it) stays valid.
    low_stock_count: int = 0


class PharmacySummaryOut(BaseModel):
    """GET /pharmacy/summary -- the two counters the pharmacy console badges
    on load. `pending_proposal_count` is this facility's purchase proposals
    still awaiting admin review; `low_stock_count` matches BudgetOut's."""
    low_stock_count: int = 0
    pending_proposal_count: int = 0


class PurchaseProposalCreate(BaseModel):
    """Body for POST /pharmacy/purchase-proposals -- a pharmacist proposing a
    BRAND-NEW catalogue item (item_id is NULL on the resulting proposal).
    Restocking an EXISTING item does not use this schema: that goes through
    POST /pharmacy/inventory/{id}/adjust with delta > 0, which builds the
    proposal server-side from the item."""

    proposed_drug_name: str
    proposed_unit: str = "units"
    proposed_barcode: Optional[str] = None
    quantity: int
    unit_cost: Optional[float] = None
    reason: Optional[str] = None

    @field_validator("proposed_drug_name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("proposed_drug_name is required.")
        return v.strip()

    @field_validator("quantity")
    @classmethod
    def _check_quantity(cls, v: int) -> int:
        # Same bound/rationale as StockAdjustRequest.delta -- a real purchase
        # is never millions of units, and an unbounded quantity lets a
        # stolen token drive the budget wildly negative on approval.
        if v <= 0:
            raise ValueError("quantity must be a positive integer.")
        if v > 1_000_000:
            raise ValueError("quantity must be <= 1,000,000.")
        return v

    @field_validator("unit_cost")
    @classmethod
    def _check_unit_cost(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0 or v > 1_000_000):
            raise ValueError("unit_cost must be between 0 and 1,000,000.")
        return v

    class Config:
        extra = "forbid"


class PurchaseProposalReject(BaseModel):
    reason: Optional[str] = None


class PurchaseProposalOut(BaseModel):
    id: str
    facility_name: str
    # NULL => this proposal creates a brand-new catalogue item on approval;
    # is_new_item mirrors that as a convenience flag for the UI.
    item_id: Optional[str] = None
    is_new_item: bool = False
    proposed_drug_name: str
    proposed_unit: str
    proposed_barcode: Optional[str] = None
    quantity: int
    unit_cost: Optional[float] = None
    reason: Optional[str] = None
    requested_by: str
    # Live join to users.full_name (None if that account is since gone) --
    # same convention as InventoryDeleteRequestOut.requested_by_name.
    requested_by_name: Optional[str] = None
    status: str  # pending | approved | rejected
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    admin_note: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class BudgetUpdate(BaseModel):
    allocated_amount: float

    @field_validator("allocated_amount")
    @classmethod
    def _check_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("allocated_amount cannot be negative.")
        return v

    class Config:
        extra = "forbid"


# ---------- Hospital settings (per-facility admin config) ----------
class HospitalSettingOut(BaseModel):
    """The caller's own facility's HospitalSetting row (lazily created with
    defaults on first GET, same as MedicineBudget)."""
    facility_name: str
    display_name: Optional[str] = None
    address: Optional[str] = None
    contact_phone: Optional[str] = None
    timezone: str = "Asia/Kuala_Lumpur"
    # When False, this facility's authored clinical sub-records are hidden
    # from staff at OTHER facilities (read filter in
    # routers/patients.py::_serialize_patient). The emergency-token scan path
    # ALWAYS ignores this flag (life-safety override), and the patient's own
    # view is never filtered.
    records_shared_publicly: bool = True
    brand_primary_color: Optional[str] = None
    logo_data_url: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# P3.9: a small inline logo, not an ObjectStore upload -- see
# models.HospitalSetting's docstring for why. 200KB caps the base64 text
# (comfortably enough for a clinic-logo PNG/JPEG at TV-display size; this is
# a wordmark on a waiting-room screen, not a print-resolution asset).
MAX_LOGO_DATA_URL_LENGTH = 200_000
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class HospitalSettingUpdate(BaseModel):
    """PUT /admin/hospital-settings -- every field optional; only the fields
    actually present in the body are applied (exclude_unset in the router).
    facility_name is NOT editable here: it's the identity of the row and is
    always the acting admin's own facility."""
    display_name: Optional[str] = None
    address: Optional[str] = None
    contact_phone: Optional[str] = None
    timezone: Optional[str] = None
    records_shared_publicly: Optional[bool] = None
    brand_primary_color: Optional[str] = None
    logo_data_url: Optional[str] = Field(default=None, max_length=MAX_LOGO_DATA_URL_LENGTH)

    @field_validator("brand_primary_color")
    @classmethod
    def _check_color(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _HEX_COLOR_RE.match(v):
            raise ValueError("brand_primary_color must be a '#rrggbb' hex string")
        return v

    @field_validator("logo_data_url")
    @classmethod
    def _check_logo(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith("data:image/"):
            raise ValueError("logo_data_url must be a data:image/... URI")
        return v

    class Config:
        extra = "forbid"


# ---------- Role -> page access (per-facility, admin-configurable) ----------
# See app/permissions.py + models.RolePagePermission. GET /admin/role-permissions
# returns one row per configurable staff role (plus a read-only `admin`
# row so the UI can render it greyed); PUT accepts a single {role,
# allowed_pages} object OR a list of them (bulk matrix save).
class RolePagePermissionOut(BaseModel):
    role: str
    allowed_pages: List[str] = []
    # The fixed full column set the matrix UI should render
    # (["patients","reception","pharmacy"]) -- same on every row so the
    # console knows which checkboxes exist regardless of what's ticked.
    configurable_pages: List[str] = []
    # False for the `admin` row only (all pages, not editable) so the UI can
    # show it greyed; True for every real configurable staff role.
    editable: bool = True


class RolePagePermissionUpdate(BaseModel):
    role: str
    allowed_pages: List[str]

    class Config:
        extra = "forbid"


# ---------- LDAP/AD role mapping (P1.10) ----------
# Unlike most of app/routers/admin.py, this config is NOT facility-scoped --
# it governs which AD groups can authenticate as which CLARION role at all
# (a platform-level identity-provider setting), so every admin sees and
# edits the same global table. See app/ldap_auth.py, models.LdapRoleMapping.
#
# Deliberately NOT the general VALID_ROLES set (voltagent security review
# finding M1): "patient" must never be LDAP-assignable -- a directory
# account JIT-provisioned as role="patient" would have patient_id=None (no
# linked Patient row), violating this codebase's stated invariant that
# patients never authenticate via LDAP. "emergency_responder" is likewise
# excluded -- that's a purpose-issued credential, not a general staff
# directory identity. Admin IS included: an AD "IT/Helpdesk" group mapping
# to admin is a normal, intended use of this feature.
LDAP_ASSIGNABLE_ROLES = set(permissions.CONFIGURABLE_STAFF_ROLES) | {"admin"}


class LdapRoleMappingOut(BaseModel):
    id: str
    group_dn: str
    role: str
    facility: Optional[str] = None
    priority: int

    class Config:
        from_attributes = True


class LdapRoleMappingCreate(BaseModel):
    group_dn: str
    role: str
    facility: Optional[str] = None
    priority: int = 0

    class Config:
        extra = "forbid"

    @field_validator("group_dn")
    @classmethod
    def _group_dn_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("group_dn must not be blank")
        return v

    @field_validator("role")
    @classmethod
    def _check_role(cls, v: str) -> str:
        if v not in LDAP_ASSIGNABLE_ROLES:
            raise ValueError(f"role must be one of: {', '.join(sorted(LDAP_ASSIGNABLE_ROLES))}")
        return v


class LdapRoleMappingUpdate(LdapRoleMappingCreate):
    """Same validated shape as create -- PUT replaces every field."""


VALID_WARD_TYPES = {"general", "icu", "pediatric", "maternity", "emergency", "other"}


def _validate_ward_type(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in VALID_WARD_TYPES:
        raise ValueError(
            f"ward_type must be one of: {', '.join(sorted(VALID_WARD_TYPES))}"
        )
    return v


def _validate_bed_counts(total_beds: Optional[int], occupied_beds: Optional[int]) -> None:
    """Shared guard for WardCreate and (post-merge, in the router)
    WardUpdate -- mirrors _validate_fasting_relationship's exact split:
    raising here catches the raw-payload case on create; the router
    re-runs this same check against the MERGED row after applying a PATCH's
    exclude_unset fields, so a PATCH that only touches occupied_beds (against
    a row whose total_beds is untouched) is still validated against the real
    total. Rejects rather than clamps -- a clamp would silently hide a
    fat-fingered input instead of surfacing it as an error."""
    if total_beds is not None and total_beds <= 0:
        raise ValueError("total_beds must be greater than 0.")
    if occupied_beds is not None and total_beds is not None and not (0 <= occupied_beds <= total_beds):
        raise ValueError("occupied_beds must be between 0 and total_beds.")


class WardCreate(BaseModel):
    ward_name: str
    ward_type: Optional[str] = None
    total_beds: int
    occupied_beds: int = 0

    @field_validator("ward_type")
    @classmethod
    def _check_ward_type(cls, v: Optional[str]) -> Optional[str]:
        return _validate_ward_type(v)

    @field_validator("occupied_beds")
    @classmethod
    def _check_bed_counts(cls, v: int, info) -> int:
        _validate_bed_counts(info.data.get("total_beds"), v)
        return v


class WardUpdate(BaseModel):
    """Partial update for PATCH /admin/wards/{ward_id}. Every field
    optional; only fields actually present in the request body are applied
    (see exclude_unset in the router). Deliberately does NOT re-validate the
    total_beds/occupied_beds relationship against just this payload (a PATCH
    containing only occupied_beds, against a row whose existing total_beds
    already accommodates it, is legitimate) -- the router re-checks the
    relationship against the MERGED row after applying these fields instead,
    same technique as AppointmentUpdate's fasting_hours/fasting_required
    cross-field validation."""

    ward_name: Optional[str] = None
    ward_type: Optional[str] = None
    total_beds: Optional[int] = None
    occupied_beds: Optional[int] = None

    @field_validator("ward_type")
    @classmethod
    def _check_ward_type(cls, v: Optional[str]) -> Optional[str]:
        return _validate_ward_type(v)

    @field_validator("total_beds")
    @classmethod
    def _check_total_beds_positive(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("total_beds must be greater than 0.")
        return v

    class Config:
        extra = "forbid"


class WardOut(BaseModel):
    id: str
    facility_name: str
    ward_name: str
    ward_type: Optional[str] = None
    total_beds: int
    occupied_beds: int
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    created_at: datetime
    # Both computed (not DB columns) -- re-derived on every read for the
    # same "never let a stale derived value drift from its source columns"
    # reason as MedicineInventoryOut.is_low_stock above.
    available_beds: int = 0
    occupancy_pct: float = 0.0

    class Config:
        from_attributes = True


# ---------- Floors (auto-generated wards) + per-bed admissions ----------
VALID_GENDER_RESTRICTIONS = {"male", "female"}


def _validate_gender_restriction(v: Optional[str]) -> Optional[str]:
    if v is not None and v not in VALID_GENDER_RESTRICTIONS:
        raise ValueError('gender_restriction must be "male", "female", or null (mixed).')
    return v


class FloorCreate(BaseModel):
    """facility_name is FORCED server-side from the acting admin's own row --
    this schema has no such field, same forced-facility boundary as
    WardCreate (see routers/admin.py docstring). Creating a floor also
    creates `ward_count` child Ward rows in the same request."""

    floor_label: str
    gender_restriction: Optional[str] = None
    ward_count: int
    beds_per_ward: int

    @field_validator("gender_restriction")
    @classmethod
    def _check_gender(cls, v: Optional[str]) -> Optional[str]:
        return _validate_gender_restriction(v)

    @field_validator("ward_count")
    @classmethod
    def _check_ward_count(cls, v: int) -> int:
        if not (1 <= v <= 200):
            raise ValueError("ward_count must be between 1 and 200.")
        return v

    @field_validator("beds_per_ward")
    @classmethod
    def _check_beds_per_ward(cls, v: int) -> int:
        if not (1 <= v <= 500):
            raise ValueError("beds_per_ward must be between 1 and 500.")
        return v


class FloorUpdate(BaseModel):
    """Partial update for PATCH /admin/floors/{floor_id}. Every field
    optional; only fields present in the request body are applied (see
    exclude_unset in the router). Cross-field consequences (adding/removing
    child wards, resizing every child ward, refusing a shrink that would
    strand an admitted patient) are all handled in the router against the
    merged row -- same technique as WardUpdate."""

    floor_label: Optional[str] = None
    gender_restriction: Optional[str] = None
    ward_count: Optional[int] = None
    beds_per_ward: Optional[int] = None

    @field_validator("gender_restriction")
    @classmethod
    def _check_gender(cls, v: Optional[str]) -> Optional[str]:
        return _validate_gender_restriction(v)

    @field_validator("ward_count")
    @classmethod
    def _check_ward_count(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 200):
            raise ValueError("ward_count must be between 1 and 200.")
        return v

    @field_validator("beds_per_ward")
    @classmethod
    def _check_beds_per_ward(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (1 <= v <= 500):
            raise ValueError("beds_per_ward must be between 1 and 500.")
        return v

    class Config:
        extra = "forbid"


class FloorOut(BaseModel):
    id: str
    facility_name: str
    floor_label: str
    gender_restriction: Optional[str] = None
    ward_count: int
    beds_per_ward: int
    created_by: Optional[str] = None
    created_at: datetime
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    # All computed in routers/admin.py::_serialize_floor from the live child
    # Ward rows + active Admission rows -- never stored, so they can't drift.
    ward_ids: List[str] = []
    total_beds: int = 0
    occupied_beds: int = 0

    class Config:
        from_attributes = True


class AdmissionCreate(BaseModel):
    """Exactly one of patient_id / national_id must be given -- same
    "fail loud if a client bug sends two" idiom as ReceptionCheckinRequest.
    If ward_id + bed_number are both given the patient goes to that exact
    bed (validated free + gender-compatible); otherwise the backend
    auto-assigns (optionally restricted to `floor_id`)."""

    patient_id: Optional[str] = None
    national_id: Optional[str] = None
    floor_id: Optional[str] = None
    ward_id: Optional[str] = None
    bed_number: Optional[int] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _check_exactly_one_identifier(self):
        provided = [self.patient_id, self.national_id]
        if sum(1 for p in provided if p) != 1:
            raise ValueError("Provide exactly one of patient_id or national_id.")
        return self


class AdmissionUpdate(BaseModel):
    ward_id: Optional[str] = None
    bed_number: Optional[int] = None
    notes: Optional[str] = None

    class Config:
        extra = "forbid"


class AdmissionOut(BaseModel):
    id: str
    patient_id: str
    patient_name: str
    national_id: Optional[str] = None
    ward_id: str
    ward_name: str
    floor_id: Optional[str] = None
    floor_label: Optional[str] = None
    bed_number: int
    admitted_at: datetime
    admitted_by: Optional[str] = None
    discharged_at: Optional[datetime] = None
    notes: Optional[str] = None

    class Config:
        from_attributes = True


class WardMapBedAdmission(BaseModel):
    # `id` (the Admission id) is included beyond the approved plan's field
    # list so the Ward Map's per-bed Discharge / Move actions have something
    # to address without a second round-trip to GET /reception/admissions.
    id: str
    patient_id: str
    patient_name: str
    national_id: Optional[str] = None
    admitted_at: datetime
    notes: Optional[str] = None


class WardMapBed(BaseModel):
    bed_number: int
    occupied: bool
    admission: Optional[WardMapBedAdmission] = None


class WardMapWard(BaseModel):
    id: str
    ward_name: str
    beds: List[WardMapBed] = []


class WardMapFloor(BaseModel):
    id: str
    floor_label: str
    gender_restriction: Optional[str] = None
    wards: List[WardMapWard] = []


class WardMapOut(BaseModel):
    floors: List[WardMapFloor] = []


# ---------- Staff clock-in/out ----------
class ClockStatusOut(BaseModel):
    """Response for POST /staff/clock-in, POST /staff/clock-out, and
    GET /staff/clock-status -- always reflects the CURRENT state of the
    calling user's own clock, so a client can just re-render the same
    widget off any of the three responses."""

    clocked_in: bool
    since: Optional[datetime] = None  # the open event's clock_in_at, if clocked_in
    # Most recent CLOSED event's clock_out_at, if any -- lets a UI show
    # "last clocked out at 6:02pm" even while currently clocked out (and is
    # left populated, not cleared, once a new shift starts -- it's "the last
    # time you clocked out", not "are you currently clocked out").
    last_clock_out_at: Optional[datetime] = None


class ClockEventOut(BaseModel):
    id: str
    clock_in_at: datetime
    clock_out_at: Optional[datetime] = None
    # Computed (not a DB column) -- None while the shift is still open,
    # otherwise whole minutes between clock_in_at/clock_out_at. Re-derived on
    # every read for the same "never let a stale derived value drift from its
    # source columns" reason as MedicineInventoryOut.is_low_stock /
    # WardOut.available_beds above.
    duration_minutes: Optional[int] = None

    class Config:
        from_attributes = True


class StaffRosterEntryOut(BaseModel):
    """One row of GET /admin/staff -- a clinician/records_officer at the
    admin's own facility, plus their live clock status. Duplicates (rather
    than nests) the clocked_in/since/last_clock_out_at fields from
    ClockStatusOut -- keeps this a single flat shape for the roster table,
    with no client-side unwrapping of a nested object needed."""

    id: str
    full_name: str
    email: str
    role: str
    facility: Optional[str] = None
    must_change_password: bool = False
    # Per-counter reception scoping (models.User.section). None for staff
    # not pinned to a FacilitySection, and always None for records_officer
    # (only receptionist/clinician are ever assignable -- see routers/admin.py).
    section: Optional[str] = None
    clocked_in: bool
    since: Optional[datetime] = None
    last_clock_out_at: Optional[datetime] = None
    bio: Optional[str] = None
    contact_email: Optional[str] = None
    has_photo: bool = False


class MyProfileUpdate(BaseModel):
    """Body for PUT /me/profile -- self-service bio + internal contact email.
    Full-replace semantics like StaffSectionAssign: both fields are always
    written (send null to clear one), neither is a partial patch. Never
    touches the login/auth email."""

    bio: Optional[str] = None
    contact_email: Optional[EmailStr] = None

    class Config:
        extra = "forbid"


class StaffProfileUpdate(MyProfileUpdate):
    """Body for PATCH /admin/staff/{user_id}/profile -- identical shape to
    MyProfileUpdate, admin-editing a colleague's bio/contact_email instead of
    their own."""


# ---------- Emergency ----------
# Server-side ceilings for EmergencyProfileRequest.valid_minutes /
# NfcRegisterRequest.valid_minutes below. Before this, `valid_minutes` was
# accepted from the client with no upper bound at all -- a patient (or
# anyone with a valid session) could request a QR grant valid for years, or
# staff could fat-finger/abuse an NFC registration into an effectively
# permanent, unrevoked-by-expiry credential. Comfortably above each
# endpoint's own default (so legitimate long-lived use cases -- a
# patient wanting their QR to last most of a season, or a staff-issued
# physical card meant to outlive a QR reissue cycle -- still fit), but not
# unbounded.
#   - QR_VALID_MINUTES_MAX: 90 days (129600 min) -- ~3x the 43200 (30 day)
#     default. A patient-self-issued QR grant is the more exposed medium
#     (screenshot/photo-able, no physical possession requirement to use),
#     so its ceiling is deliberately much tighter than the staff-managed
#     NFC one below.
QR_VALID_MINUTES_MAX = 129600  # 90 days
#   - NFC_VALID_MINUTES_MAX: 2 years (1051200 min) -- 2x the 525600
#     (1 year) default. Staff-issued/admin-managed physical cards
#     legitimately need longer validity than a patient-self-issued QR
#     (they're not reissued on every login the way a QR conceptually is),
#     but still bounded rather than effectively-forever.
NFC_VALID_MINUTES_MAX = 1051200  # 2 years


class EmergencyProfileRequest(BaseModel):
    patient_id: str
    scope: List[str] = ["allergies", "medications", "conditions", "blood_type"]
    valid_minutes: int = 43200  # default 30 days validity for the QR "grant"; each *scan* still mints a short-lived token

    @field_validator("valid_minutes")
    @classmethod
    def _check_valid_minutes(cls, v: int) -> int:
        if v <= 0 or v > QR_VALID_MINUTES_MAX:
            raise ValueError(
                f"valid_minutes must be between 1 and {QR_VALID_MINUTES_MAX} (90 days)."
            )
        return v


class EmergencyScanRequest(BaseModel):
    card_reference: str
    responder_name: Optional[str] = None
    responder_org: Optional[str] = None


# ---------- Emergency: NFC physical cards ----------
def _validated_nfc_uid(v: str) -> str:
    """Security Audit M7: a NFC/MIFARE UID is a hex byte string. Reject a
    blank / separators-only / non-hex value at the schema boundary so it
    can't be registered as a catch-all grant once auth.canonical_nfc_uid
    collapses it. Accepts common reader/manual formats (04:A1:B2, 04-a1-b2,
    04 A1 B2, 04a1b2); the raw string is stored only as its HMAC."""
    canon = "".join(str(v).split()).replace(":", "").replace("-", "").upper()
    if len(canon) < 4 or len(canon) % 2 or any(c not in "0123456789ABCDEF" for c in canon):
        raise ValueError("nfc_uid must be a hex card UID of at least 2 bytes")
    return v


class NfcRegisterRequest(BaseModel):
    """Staff-only: register (or re-register / update) a physical NFC card
    against a patient — for senior citizens / anyone without a smartphone.
    Re-registering the same nfc_uid updates the existing grant's scope and
    expiry rather than creating a duplicate row."""

    patient_id: str
    nfc_uid: str
    scope: List[str] = ["allergies", "medications", "conditions", "blood_type"]
    # Physical cards are meant to last a long time (not reissued every
    # login like the QR flow) — default to ~1 year.
    valid_minutes: int = 525600
    # The physical tag's real NDEF capacity in bytes, if the registering
    # device already tapped it and knows (e.g. NdefAndroid.maxSize --
    # NTAG213=144B, NTAG215=504B, NTAG216=888B). Drives how much of the
    # compact on-tag `tag_text` response the backend fits before
    # truncating. None = a conservative default (see _TAG_TEXT_MAX_BYTES).
    tag_max_bytes: "int | None" = None
    # What the registering device saw: "ntag21x" (NTAG213/215/216 -- no
    # tamper-proof read counter), "ntag424" (NTAG 424 DNA -- has one), or
    # "unknown". Only drives the warning in the response; every type works.
    tag_type: Literal["ntag21x", "ntag424", "unknown"] = "unknown"

    @field_validator("valid_minutes")
    @classmethod
    def _check_valid_minutes(cls, v: int) -> int:
        if v <= 0 or v > NFC_VALID_MINUTES_MAX:
            raise ValueError(
                f"valid_minutes must be between 1 and {NFC_VALID_MINUTES_MAX} (2 years)."
            )
        return v

    @field_validator("tag_max_bytes")
    @classmethod
    def _check_tag_max_bytes(cls, v: "int | None") -> "int | None":
        # Real-world tag range is ~48B (tiny) to a few KB (rare); this is
        # sanity bounds on a client-supplied number, not a spec limit.
        if v is not None and not (16 <= v <= 8192):
            raise ValueError("tag_max_bytes must be between 16 and 8192.")
        return v

    _check_nfc_uid = field_validator("nfc_uid")(_validated_nfc_uid)


class NfcScanRequest(BaseModel):
    nfc_uid: str
    responder_name: Optional[str] = None
    responder_org: Optional[str] = None

    _check_nfc_uid = field_validator("nfc_uid")(_validated_nfc_uid)


class OfflineTagReadEntry(BaseModel):
    """One offline tag read from the device's hash-chained log. `entry_hash`
    must equal tag_crypto.read_entry_hash(...) over the other fields."""
    seq: int = Field(ge=0, le=10**9)
    read_at: str  # ISO-8601 exactly as hashed on the device
    nfc_uid: str
    key_id: int = Field(ge=0, le=10**6)
    outcome: Literal["decrypted", "failed"]
    prev_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    entry_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    _check_nfc_uid = field_validator("nfc_uid")(_validated_nfc_uid)

    @field_validator("read_at")
    @classmethod
    def _check_read_at(cls, v: str) -> str:
        from datetime import datetime as _dt
        parsed = _dt.fromisoformat(v.replace("Z", "+00:00"))  # raises -> 422
        if not 2000 <= parsed.year <= 2100:
            raise ValueError("read_at out of range")
        return v


class OfflineTagReadsUpload(BaseModel):
    device_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    entries: List[OfflineTagReadEntry] = Field(min_length=1, max_length=25)


# ---------- Reception desk check-in / queue ----------
VALID_QUEUE_TICKET_STATUSES = {"waiting", "called", "done", "cancelled"}


class ReceptionCheckinRequest(BaseModel):
    """Exactly one of national_id / patient_id / card_reference / nfc_uid must
    be given -- whichever identifier the receptionist actually has to hand.
    Validated explicitly (not "silently pick the first non-null one") so a
    client bug that accidentally sends two identifiers fails loudly instead
    of checking in the wrong patient.

    `national_id` is the patient's IC/NRIC (dash-tolerant, resolved against
    Patient.national_id -- see routers/reception.py::_resolve_patient); it's
    the default front-desk path now that `patient_id` (an opaque internal
    UUID) is only a fallback."""

    national_id: Optional[str] = None
    patient_id: Optional[str] = None
    card_reference: Optional[str] = None
    nfc_uid: Optional[str] = None
    reason: Optional[str] = None
    department: Optional[str] = None

    @field_validator("nfc_uid")
    @classmethod
    def _check_nfc_uid(cls, v):
        return _validated_nfc_uid(v) if v else v

    @model_validator(mode="after")
    def _check_exactly_one_identifier(self):
        # A model_validator (not a field_validator on one of the four
        # fields) is used deliberately: field_validators don't run against
        # an untouched default value in pydantic v2 unless validate_default
        # is set, so a request that omits ALL FOUR identifiers would
        # otherwise slip through with nothing to check against. This always
        # runs, regardless of which (if any) fields were actually supplied.
        provided = [self.national_id, self.patient_id, self.card_reference, self.nfc_uid]
        count = sum(1 for p in provided if p)
        if count != 1:
            raise ValueError(
                "Provide exactly one of national_id, patient_id, card_reference, or nfc_uid."
            )
        return self


class QueueTicketOut(BaseModel):
    id: str
    patient_id: str
    facility_name: str
    queue_number: int
    department: Optional[str] = None
    room_id: Optional[str] = None
    room_name: Optional[str] = None
    reason: Optional[str] = None
    source: str
    status: str
    checked_in_at: datetime
    called_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    checked_in_by: str

    class Config:
        from_attributes = True


class ReceptionCheckinResponse(BaseModel):
    """Response for POST /reception/checkin -- the ticket plus enough of the
    patient's identity for the receptionist to visually confirm they
    checked in the right person (this endpoint is often reached via a
    fumble-prone manual card_reference/nfc_uid entry, so a wrong-lookup
    should be obvious immediately, not discovered later)."""

    ticket: QueueTicketOut
    patient_full_name: str
    patient_date_of_birth: str


class QueueBoardOut(BaseModel):
    """Response for GET /reception/queue -- today's tickets for the calling
    staff member's own facility, plus two small computed conveniences so
    the queue-board UI doesn't have to re-derive them client-side."""

    tickets: List[QueueTicketOut]
    now_serving: Optional[int] = None  # queue_number of the one ticket currently status == "called", if any
    waiting_count: int = 0
    # Per-counter reception scoping: the FacilitySection name the calling
    # staff member is pinned to (models.User.section), or None if unscoped.
    # When set, `tickets`/`now_serving`/`waiting_count` above are already
    # filtered to just that section -- this field lets the board UI label
    # which counter it's showing.
    section: Optional[str] = None


class QueueStatusOut(BaseModel):
    """Response for GET /reception/queue/status/{patient_id}. Mirrors
    GET /emergency/current/{patient_id}'s `{"active": false}` convention
    exactly for "nothing to show" -- see routers/reception.py."""

    active: bool
    ticket: Optional[QueueTicketOut] = None
    now_serving: Optional[int] = None
    people_ahead: Optional[int] = None


# ---------- Reception station (self-check-in QR) ----------
class ReceptionStationCreate(BaseModel):
    department: Optional[str] = None


class ReceptionStationOut(BaseModel):
    """Response for GET/POST /reception/station. `qr_base64` is rendered
    fresh on every response (same "fully deterministic, never persisted"
    approach as emergency.py::_render_qr_base64) -- it's just a rendering of
    `token`, nothing else to cache."""

    id: str
    facility_name: str
    department: Optional[str] = None
    revoked: bool
    created_at: datetime
    # Exposed alongside qr_base64, same convention as
    # EmergencyCardOut.card_reference alongside its own QR image -- this
    # isn't a secret protected by obscurity, the JWT auth on this endpoint
    # is; surfacing it lets staff read it out / type it as a fallback if a
    # camera scan ever fails.
    token: str
    qr_base64: str

    class Config:
        from_attributes = True


class ReceptionStationStatusOut(BaseModel):
    """Response for GET /reception/station when a facility has no active
    station yet -- mirrors QueueStatusOut's `{"active": false}` convention."""

    active: bool
    station: Optional[ReceptionStationOut] = None


class SelfCheckinRequest(BaseModel):
    """Body for POST /reception/self-checkin -- the patient-authenticated
    counterpart to staff-run ReceptionCheckinRequest. No patient_id/
    card_reference/nfc_uid field: the patient is identified from their own
    JWT (current_user.patient_id), never from anything client-supplied."""

    station_token: str
    reason: Optional[str] = None


# ---------- Consultation rooms ("Bilik") + clinician room claims ----------
class ConsultationRoomCreate(BaseModel):
    """facility_name is FORCED server-side from the acting admin's own row --
    this schema has no such field, same forced-facility boundary as
    WardCreate / MedicineInventoryCreate (see routers/admin.py docstring)."""

    room_name: str
    department: Optional[str] = None
    active: bool = True


class ConsultationRoomUpdate(BaseModel):
    room_name: Optional[str] = None
    department: Optional[str] = None
    active: Optional[bool] = None

    class Config:
        extra = "forbid"


class ConsultationRoomOut(BaseModel):
    id: str
    facility_name: str
    room_name: str
    department: Optional[str] = None
    active: bool
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    created_at: datetime
    # Computed in routers/admin.py::_serialize_room -- today's (Malaysia-local
    # date) non-cancelled ticket count routed to this room, so the admin can
    # see load at a glance. Not a DB column.
    waiting_today: int = 0

    class Config:
        from_attributes = True


# ---------- Facility sections (per-counter reception scoping) ----------
class FacilitySectionCreate(BaseModel):
    """facility_name is FORCED server-side from the acting admin's own row --
    this schema has no such field, same forced-facility boundary as
    ConsultationRoomCreate / WardCreate (see routers/admin.py docstring)."""

    name: str


class FacilitySectionUpdate(BaseModel):
    name: Optional[str] = None
    active: Optional[bool] = None

    class Config:
        extra = "forbid"


class FacilitySectionOut(BaseModel):
    id: str
    facility_name: str
    name: str
    active: bool
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    created_at: datetime
    # Computed in routers/admin.py::_serialize_section -- how many
    # receptionist/clinician accounts at this facility are currently pinned
    # to this section (models.User.section == name). Not a DB column.
    assigned_staff_count: int = 0

    class Config:
        from_attributes = True


# ---------- Announcements (P3.10) ----------
class AnnouncementCreate(BaseModel):
    """facility_name is FORCED server-side to the acting admin's own
    facility -- same "manager admin, not super admin" boundary as
    FacilitySectionCreate (see routers/admin.py's module docstring); this
    schema has no such field. models.Announcement.facility_name can still
    be NULL (global) in principle, but nothing in this API can currently
    produce that -- there is no cross-facility "super admin" action here."""
    title: str = Field(max_length=255)
    body: str = Field(max_length=4000)
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    class Config:
        extra = "forbid"


class AnnouncementOut(BaseModel):
    id: str
    facility_name: Optional[str] = None
    title: str
    body: str
    starts_at: datetime
    expires_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class StaffSectionAssign(BaseModel):
    """Body for PATCH /admin/staff/{user_id}. `section` is required in the
    payload (send explicit null to un-assign) -- a section string must be
    the name of an ACTIVE FacilitySection at the admin's own facility, else
    400 (see routers/admin.py::assign_staff_section)."""

    section: Optional[str] = None

    class Config:
        extra = "forbid"


class RoomClaimOut(BaseModel):
    """One clinician's live claim on a room. `claimed_by_name` is a
    read-time join to users.full_name (nullable if the claiming account was
    since deleted) -- same live-name-resolution convention as AuditLog's
    actor name."""

    room_id: str
    room_name: str
    user_id: str
    claimed_by_name: Optional[str] = None
    claimed_at: datetime


class ReceptionRoomOut(ConsultationRoomOut):
    """A room as shown on the clinician's "claim a Bilik" list -- the room
    plus who (if anyone) currently holds it."""

    claim: Optional[RoomClaimOut] = None


class MyRoomOut(BaseModel):
    """Response for GET /reception/my-room. `room`/`tickets` are empty unless
    the caller is BOTH currently clocked in AND holds an active RoomClaim --
    the "withdrawn on clock-out" rule (see routers/staff.py::clock_out)."""

    clocked_in: bool
    room: Optional[ConsultationRoomOut] = None
    tickets: List[QueueTicketOut] = []


class AssignRoomRequest(BaseModel):
    room_id: str


# ---------- Clinician "Start session" (consultation router) ----------
class ConsultationRoomStateOut(ReceptionRoomOut):
    """A consultation room as shown on the clinician Consultation page --
    identical to ReceptionRoomOut (the room fields + who currently holds it),
    aliased so the consultation router has its own named response type."""


class ConsultationSessionStartRequest(BaseModel):
    room_id: str


class ConsultationCompleteRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=4000)
    subjective: Optional[str] = Field(default=None, max_length=8000)
    objective: Optional[str] = Field(default=None, max_length=8000)
    assessment: Optional[str] = Field(default=None, max_length=8000)
    plan: Optional[str] = Field(default=None, max_length=8000)
    treatment_plan: Optional[str] = Field(default=None, max_length=8000)
    follow_up_at: Optional[datetime] = None
    # Optional link to an already-created in-facility ancillary referral.
    referral_service_request_id: Optional[str] = None
    # Base64 PNG of a signature to save on the caller's profile first, for a
    # clinician who hasn't saved one yet (POST /me/signature is the other
    # way). Ignored if the caller already has a saved signature.
    signature_b64: Optional[str] = Field(default=None, max_length=1_400_000)  # ~1MB PNG as base64

    # P3.10: vitals taken at this visit -- see
    # models.ConsultationNote's docstring. Bounds are generous physiological
    # limits (catch a fat-fingered typo, not a medical judgment call).
    bp_systolic: Optional[int] = Field(default=None, ge=40, le=300)
    bp_diastolic: Optional[int] = Field(default=None, ge=20, le=200)
    temperature_c: Optional[float] = Field(default=None, ge=25.0, le=45.0)
    pulse_bpm: Optional[int] = Field(default=None, ge=20, le=300)

    class Config:
        extra = "forbid"


class ConsultationNoteOut(BaseModel):
    id: str
    encounter_id: str
    patient_id: str
    facility_name: str
    subjective: Optional[str] = None
    objective: Optional[str] = None
    assessment: Optional[str] = None
    plan: Optional[str] = None
    treatment_plan: Optional[str] = None
    follow_up_at: Optional[datetime] = None
    referral_service_request_id: Optional[str] = None
    signed_by: str
    signed_by_name: Optional[str] = None
    signed_at: datetime
    bp_systolic: Optional[int] = None
    bp_diastolic: Optional[int] = None
    temperature_c: Optional[float] = None
    pulse_bpm: Optional[int] = None

    class Config:
        from_attributes = True


class CdsHintRequest(BaseModel):
    """Whatever the clinician has typed into the SOAP note so far -- never
    persisted, this is advisory-only input for ai/cds_hint.py. Same field
    names/caps as ConsultationCompleteRequest for consistency, but every
    field is optional and unrelated to sign-off."""
    subjective: Optional[str] = Field(default=None, max_length=8000)
    objective: Optional[str] = Field(default=None, max_length=8000)
    assessment: Optional[str] = Field(default=None, max_length=8000)
    plan: Optional[str] = Field(default=None, max_length=8000)

    class Config:
        extra = "forbid"


class CdsHintOut(BaseModel):
    hint: Optional[str] = None
    allergy_conflicts: list[str] = []
    disclaimer: str


class VoiceToSoapOut(BaseModel):
    # None only when speech-to-text itself is unavailable/failed -- a
    # segmentation failure still returns the raw transcript in `soap.subjective`.
    transcript: Optional[str] = None
    # Always exactly the 4 SOAP keys (voice_soap.py's _EMPTY_SOAP) -- a
    # one-caller wrapper model would say the same thing in more lines.
    soap: dict[str, str]


class ConsultationTicketOut(QueueTicketOut):
    """A queued consultation ticket routed to the caller's claimed room, with
    the patient's name + DOB joined in so the worklist is readable without a
    second call (mirrors ReceptionCheckinResponse's identity-confirmation
    fields)."""

    patient_full_name: Optional[str] = None
    patient_date_of_birth: Optional[str] = None


class ConsultationMyRoomOut(BaseModel):
    """Response for GET /consultation/my-room, POST /consultation/session/start
    and POST /consultation/session/end. `room` / `tickets` are empty unless
    the caller is BOTH clocked in AND holds an active RoomClaim -- same
    "withdrawn on clock-out" rule as reception's MyRoomOut."""

    clocked_in: bool
    room: Optional[ConsultationRoomStateOut] = None
    tickets: List[ConsultationTicketOut] = []


# ---------- Waiting-room display (public, unauthenticated feed) ----------
class WaitingRoomDisplayCreate(BaseModel):
    """Body for POST /admin/waiting-room-displays. `section` (optional) pins
    the screen to one FacilitySection's queue; omitted / null = whole
    facility. `show_full_names` opts this one screen out of the default
    masked patient labels."""

    section: Optional[str] = None
    show_full_names: bool = False

    class Config:
        extra = "forbid"


class WaitingRoomDisplayOut(BaseModel):
    id: str
    facility_name: str
    section: Optional[str] = None
    show_full_names: bool
    revoked: bool
    created_at: datetime
    # The unguessable token that goes in the display URL (GET /display/{token}).
    # Not a secret protected by obscurity -- the feed it unlocks is
    # deliberately public/low-sensitivity (queue numbers + masked names) --
    # surfaced so an admin can copy the URL onto the screen device.
    token: str

    class Config:
        from_attributes = True


# ---------- Clinical-record annotations (append-only sign-off) ----------
# "service_result" (P3.1) lets a correction be appended to a signed ancillary
# result (routers/patients.py::_ANNOTATION_MODEL -> models.ServiceResult).
ANNOTATION_TARGET_TYPES = {"condition", "medication", "allergy", "encounter", "service_result", "dental_chart_entry", "consultation_note"}
ANNOTATION_KINDS = {"resolved", "discontinued", "correction", "note"}


class RecordAnnotationCreate(BaseModel):
    """Body for POST /patients/{patient_id}/annotations. `kind` cross-rules
    (`discontinued` only for a medication, `resolved` only for a condition)
    are enforced in the router, not here, so the error names the target
    type. `signature_b64` saves a signature on the caller's profile first if
    they have none yet."""

    target_type: str
    target_id: str
    kind: str
    note: Optional[str] = Field(default=None, max_length=4000)
    signature_b64: Optional[str] = Field(default=None, max_length=1_400_000)

    @field_validator("target_type")
    @classmethod
    def _check_target_type(cls, v: str) -> str:
        if v not in ANNOTATION_TARGET_TYPES:
            raise ValueError(
                f"target_type must be one of: {', '.join(sorted(ANNOTATION_TARGET_TYPES))}"
            )
        return v

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, v: str) -> str:
        if v not in ANNOTATION_KINDS:
            raise ValueError(f"kind must be one of: {', '.join(sorted(ANNOTATION_KINDS))}")
        return v


# ---------- Data quality (P2.12) ----------
class DataQualityAlertOut(BaseModel):
    id: str
    rule: str
    category: str
    severity: str
    entity_type: str
    entity_id: str
    patient_id: Optional[str] = None
    detail: str
    first_seen_at: datetime
    last_seen_at: datetime
    times_seen: int
    acknowledged: bool
    resolved: bool
    resolved_by: Optional[str] = None

    class Config:
        from_attributes = True


# ---------- Security alerts / access-anomaly detection (P4.5) ----------

class SecurityAlertOut(BaseModel):
    id: str
    rule: str
    category: str
    severity: str
    actor: str
    actor_role: Optional[str] = None
    actor_facility: Optional[str] = None
    window_start: datetime
    window_end: datetime
    detail: str
    first_seen_at: datetime
    last_seen_at: datetime
    times_seen: int
    acknowledged: bool
    resolved: bool
    resolved_by: Optional[str] = None
    ai_explanation: Optional[str] = None

    class Config:
        from_attributes = True


# ---------- PDPA (P2.10) ----------
class ConsentRecordIn(BaseModel):
    purpose: str
    granted: bool
    patient_id: Optional[str] = None   # staff only; a patient omits it
    note: Optional[str] = Field(default=None, max_length=2000)


class ConsentRecordOut(BaseModel):
    id: str
    patient_id: str
    purpose: str
    granted: bool
    source: str
    note: Optional[str] = None
    recorded_by_role: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DataSubjectRequestIn(BaseModel):
    kind: str
    detail: Optional[str] = Field(default=None, max_length=4000)
    patient_id: Optional[str] = None   # staff filing on behalf


class DataSubjectRequestOut(BaseModel):
    id: str
    patient_id: str
    kind: str
    status: str
    detail: Optional[str] = None
    facility_name: Optional[str] = None
    requested_at: datetime
    due_at: Optional[datetime] = None
    assigned_to: Optional[str] = None
    resolution_note: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DpoRegisterIn(BaseModel):
    dpo_name: Optional[str] = Field(default=None, max_length=255)
    dpo_email: Optional[str] = Field(default=None, max_length=255)
    dpo_phone: Optional[str] = Field(default=None, max_length=64)
    jpdp_registration_ref: Optional[str] = Field(default=None, max_length=128)


class DpoRegisterOut(DpoRegisterIn):
    facility_name: str
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RetentionPolicyIn(BaseModel):
    category: str
    retain_years: Optional[int] = Field(default=None, ge=1, le=200)   # None = keep indefinitely
    basis: Optional[str] = Field(default=None, max_length=2000)


class RetentionPolicyOut(RetentionPolicyIn):
    class Config:
        from_attributes = True


# ---------- Ancillary engine: Procedure / Laboratory / X-ray / Physiotherapy
# (P3.1, the tender) -- see models.py's "Ancillary engine" section
# comment for the shared order -> result -> sign-off -> document pipeline
# these four modules share. Single source of truth for these three sets is
# models.py (code-review follow-up 2026-09-12 -- they were briefly
# duplicated here as literal sets, drifting from SERVICE_REQUEST_STATUSES,
# which was already correctly defined only in models.py and referenced
# from ancillary.py as `models.SERVICE_REQUEST_STATUSES`).
ANCILLARY_MODULES = set(_models.ANCILLARY_MODULES)
SERVICE_REQUEST_SOURCES = set(_models.SERVICE_REQUEST_SOURCES)
SERVICE_REQUEST_PRIORITIES = set(_models.SERVICE_REQUEST_PRIORITIES)


class ServiceCatalogItemCreate(BaseModel):
    """Body for POST /ancillary/catalog. A non-admin's item is always scoped
    to their own facility regardless of what they send here -- only an admin
    may set `facility_name=None` to publish a shared/global item (the router
    enforces this, not this schema)."""

    module: str
    name: str = Field(min_length=1, max_length=255)
    code: Optional[str] = Field(default=None, max_length=64)
    unit_price_cents: int = Field(default=0, ge=0)
    facility_name: Optional[str] = None

    class Config:
        extra = "forbid"

    @field_validator("module")
    @classmethod
    def _check_module(cls, v: str) -> str:
        if v not in ANCILLARY_MODULES:
            raise ValueError(f"module must be one of: {', '.join(sorted(ANCILLARY_MODULES))}")
        return v


class ServiceCatalogItemUpdate(BaseModel):
    """Body for PATCH /ancillary/catalog/{id}. No `module`/`facility_name`
    change -- moving an item between modules or facilities is a new item, not
    an edit (same reasoning as everywhere else immutable-identity columns
    stay off the PATCH schema)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    code: Optional[str] = Field(default=None, max_length=64)
    unit_price_cents: Optional[int] = Field(default=None, ge=0)
    active: Optional[bool] = None

    class Config:
        extra = "forbid"


class ServiceCatalogItemOut(BaseModel):
    id: str
    module: str
    name: str
    code: Optional[str] = None
    unit_price_cents: int
    facility_name: Optional[str] = None
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ServiceRequestCreate(BaseModel):
    """Body for POST /ancillary/requests -- the 'order'. `source_encounter_id`
    is required when `source == 'physician_order'` (checked here so the 400
    fires before any DB work) and ignored otherwise."""

    patient_id: str
    module: str
    catalog_item_id: str
    source: str
    source_encounter_id: Optional[str] = None
    clinical_indication: Optional[str] = Field(default=None, max_length=4000)
    priority: str = "routine"

    class Config:
        extra = "forbid"

    @field_validator("module")
    @classmethod
    def _check_module(cls, v: str) -> str:
        if v not in ANCILLARY_MODULES:
            raise ValueError(f"module must be one of: {', '.join(sorted(ANCILLARY_MODULES))}")
        return v

    @field_validator("source")
    @classmethod
    def _check_source(cls, v: str) -> str:
        if v not in SERVICE_REQUEST_SOURCES:
            raise ValueError(f"source must be one of: {', '.join(sorted(SERVICE_REQUEST_SOURCES))}")
        return v

    @field_validator("priority")
    @classmethod
    def _check_priority(cls, v: str) -> str:
        if v not in SERVICE_REQUEST_PRIORITIES:
            raise ValueError(f"priority must be one of: {', '.join(sorted(SERVICE_REQUEST_PRIORITIES))}")
        return v

    @model_validator(mode="after")
    def _check_physician_order_needs_encounter(self):
        if self.source == "physician_order" and not self.source_encounter_id:
            raise ValueError("source_encounter_id is required when source='physician_order'")
        return self


class ServiceRequestCancel(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)


class ServiceResultCreate(BaseModel):
    """Body for POST /ancillary/requests/{id}/result -- performs AND signs
    off in one atomic action (same shape as
    routers/consultation.py::ConsultationCompleteRequest). REQUIRES the
    caller to already have a saved digital signature, or pass
    `signature_b64` to save one on the spot."""

    result_text: Optional[str] = Field(default=None, max_length=8000)
    flag_abnormal: bool = False
    flag_critical: bool = False
    signature_b64: Optional[str] = Field(default=None, max_length=1_400_000)  # ~1MB PNG as base64

    class Config:
        extra = "forbid"


class ServiceResultOut(BaseModel):
    id: str
    service_request_id: str
    patient_id: str
    result_text: Optional[str] = None
    flag_abnormal: bool
    flag_critical: bool
    performed_by_name: Optional[str] = None
    performed_by_role: Optional[str] = None
    performed_at: Optional[datetime] = None
    facility_name: Optional[str] = None
    signed_by_name: Optional[str] = None
    signed_by_role: Optional[str] = None
    # Whether a softcopy attachment exists -- never the raw object key (see
    # GET /ancillary/requests/{id}/result/document to fetch it).
    has_document: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class ServiceRequestOut(BaseModel):
    id: str
    patient_id: str
    patient_full_name: Optional[str] = None
    module: str
    catalog_item_id: str
    catalog_item_name: Optional[str] = None
    source: str
    source_encounter_id: Optional[str] = None
    clinical_indication: Optional[str] = None
    priority: str
    status: str
    unit_price_cents: int
    requested_by_name: Optional[str] = None
    requested_by_role: Optional[str] = None
    ordering_facility_name: Optional[str] = None
    created_at: datetime
    cancelled_at: Optional[datetime] = None
    cancelled_reason: Optional[str] = None
    result: Optional[ServiceResultOut] = None
    # P4.7: true when an xray request has a linked DicomStudy -- the
    # worklist UI uses this alone to decide whether to show "View imaging"
    # vs. an upload control, never fetching the (possibly large) instance
    # list just to know whether one exists.
    has_dicom_study: bool = False

    class Config:
        from_attributes = True


class AnalyserResultInboxOut(BaseModel):
    """P4.8. `result_text` is hl7v2.format_observations' plain-text
    rendering of the parsed OBX segments -- a pre-fill for a clinician's
    review, never itself the signed result (see models.AnalyserResultInbox's
    docstring for why this table has no write path into ServiceResult)."""
    id: str
    service_request_id: Optional[str] = None
    hl7_control_id: Optional[str] = None
    sending_facility: Optional[str] = None
    result_text: str
    flag_abnormal: bool
    received_at: datetime
    patient_name: Optional[str] = None  # set only when service_request_id resolved to a known patient
    module: Optional[str] = None

    class Config:
        from_attributes = True


class AnalyserInboxDiscardRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


class DicomStudyOut(BaseModel):
    """P4.7. `instances` is the list of opaque Orthanc instance ids the
    viewer fetches one at a time from
    GET /pacs/requests/{request_id}/study/instances/{instance_id}/file --
    safe to expose to an already-authorized viewer since that endpoint's own
    membership check (against this same list, server-side) is the real
    access boundary, not id secrecy."""
    id: str
    service_request_id: str
    description: Optional[str] = None
    instances: List[str]
    uploaded_by_name: Optional[str] = None
    uploaded_at: datetime

    class Config:
        from_attributes = True


class AncillaryStatsOut(BaseModel):
    """GET /ancillary/stats -- the minimal 'Reporting Management: data &
    statistics' surface each module clause asks for. Counts are scoped to
    the caller's own facility, current open orders + a rolling 30-day
    signed-off count, grouped by module."""

    facility_name: Optional[str] = None
    open_by_module: dict
    signed_off_last_30d_by_module: dict


# ---------- Dental (P3.2, the tender) ----------
DENTAL_TOOTH_CODES = set(_models.DENTAL_TOOTH_CODES)
DENTAL_FINDINGS = set(_models.DENTAL_FINDINGS)
DENTAL_TREATMENTS = set(_models.DENTAL_TREATMENTS)


class DentalChartEntryCreate(BaseModel):
    """Body for POST /dental/chart -- create-with-signature is the sign-off
same shape as ServiceResultCreate. REQUIRES a saved
    digital signature; pass `signature_b64` to save one on the spot."""

    patient_id: str
    encounter_id: Optional[str] = None
    tooth_code: str
    finding: str
    treatment: str = "none"
    notes: Optional[str] = None
    signature_b64: Optional[str] = None

    class Config:
        extra = "forbid"

    @field_validator("tooth_code")
    @classmethod
    def _check_tooth_code(cls, v: str) -> str:
        if v not in DENTAL_TOOTH_CODES:
            raise ValueError("tooth_code must be a valid FDI permanent-dentition code (11-18/21-28/31-38/41-48)")
        return v

    @field_validator("finding")
    @classmethod
    def _check_finding(cls, v: str) -> str:
        if v not in DENTAL_FINDINGS:
            raise ValueError(f"finding must be one of: {', '.join(sorted(DENTAL_FINDINGS))}")
        return v

    @field_validator("treatment")
    @classmethod
    def _check_treatment(cls, v: str) -> str:
        if v not in DENTAL_TREATMENTS:
            raise ValueError(f"treatment must be one of: {', '.join(sorted(DENTAL_TREATMENTS))}")
        return v


class DentalChartEntryOut(BaseModel):
    id: str
    patient_id: str
    encounter_id: Optional[str] = None
    tooth_code: str
    finding: str
    treatment: str
    notes: Optional[str] = None
    facility_name: Optional[str] = None
    recorded_by_name: Optional[str] = None
    recorded_by_role: Optional[str] = None
    signed_by_name: Optional[str] = None
    signed_by_role: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DentalChartOptionsOut(BaseModel):
    """GET /dental/chart-options -- the static FDI tooth codes + finding/
    treatment vocabularies, so the tooth-chart UI never hardcodes them."""

    tooth_codes: list
    findings: list
    treatments: list


# ---------- Billing (P3.3, the tender + per-module billing) --
# see models.py's "Billing engine" section comment. Single source of truth
# for these five sets is models.py, same discipline as the Ancillary block
# above (2026-09-12 code-review follow-up).
CHARGE_MASTER_CATEGORIES = set(_models.CHARGE_MASTER_CATEGORIES)
BILL_ITEM_SOURCE_TYPES = set(_models.BILL_ITEM_SOURCE_TYPES)
PAYMENT_METHODS = set(_models.PAYMENT_METHODS)
CLAIM_STATUSES = set(_models.CLAIM_STATUSES)


class ChargeMasterItemCreate(BaseModel):
    """Body for POST /billing/charge-master. A non-admin's item is always
    scoped to their own facility regardless of what they send here -- only
    an admin may set `facility_name=None` to publish a shared/global item
    (the router enforces this, same convention as
    ServiceCatalogItemCreate)."""

    category: str
    code: Optional[str] = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    # le= is defensive (overflow/fat-finger guard, quality-review finding),
    # same RM 1,000,000 ceiling as PaymentCreate/ClaimCreate -- this price
    # feeds `amount_cents = quantity * unit_price_cents` (billing.py), which
    # is otherwise the one money field this session's earlier bound pass missed.
    unit_price_cents: int = Field(default=0, ge=0, le=100_000_000)
    facility_name: Optional[str] = None

    class Config:
        extra = "forbid"

    @field_validator("category")
    @classmethod
    def _check_category(cls, v: str) -> str:
        if v not in CHARGE_MASTER_CATEGORIES:
            raise ValueError(f"category must be one of: {', '.join(sorted(CHARGE_MASTER_CATEGORIES))}")
        return v


class ChargeMasterItemUpdate(BaseModel):
    """Body for PATCH /billing/charge-master/{id}. No `category`/
    `facility_name` change -- same reasoning as ServiceCatalogItemUpdate."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    code: Optional[str] = Field(default=None, max_length=64)
    unit_price_cents: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    active: Optional[bool] = None

    class Config:
        extra = "forbid"


class ChargeMasterItemOut(BaseModel):
    id: str
    category: str
    code: Optional[str] = None
    name: str
    unit_price_cents: int
    facility_name: Optional[str] = None
    active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class BillCreate(BaseModel):
    patient_id: str
    encounter_id: Optional[str] = None

    class Config:
        extra = "forbid"


class BillItemCreate(BaseModel):
    """Body for POST /billing/bills/{id}/items. Exactly one of
    `charge_master_item_id` / `service_request_id` /
    `medicine_inventory_item_id` must be set, matching `source_type` --
    there is deliberately no client-supplied price field anywhere on this
    schema (Design decision 2: every BillItem price is server-derived from
    the referenced source, never trusted from the caller)."""

    source_type: str
    charge_master_item_id: Optional[str] = None
    service_request_id: Optional[str] = None
    medicine_inventory_item_id: Optional[str] = None
    # Upper bound is defensive, not a business rule -- security-review
    # finding: `amount_cents = quantity * unit_price_cents` (billing.py)
    # is stored into a plain Integer column, so an unbounded quantity from
    # a trusted-but-fat-fingerable BILLING_WRITE_ROLES caller could
    # overflow it on a 32-bit-int DB backend and 500 the write.
    quantity: int = Field(default=1, ge=1, le=100_000)

    class Config:
        extra = "forbid"

    @field_validator("source_type")
    @classmethod
    def _check_source_type(cls, v: str) -> str:
        if v not in BILL_ITEM_SOURCE_TYPES:
            raise ValueError(f"source_type must be one of: {', '.join(sorted(BILL_ITEM_SOURCE_TYPES))}")
        return v

    @model_validator(mode="after")
    def _check_exactly_one_source(self):
        by_type = {
            "charge_master": self.charge_master_item_id,
            "service_request": self.service_request_id,
            "pharmacy_item": self.medicine_inventory_item_id,
        }
        provided = [k for k, v in by_type.items() if v]
        if len(provided) != 1:
            raise ValueError(
                "exactly one of charge_master_item_id/service_request_id/"
                "medicine_inventory_item_id must be set"
            )
        if provided[0] != self.source_type:
            raise ValueError(f"source_type must be '{provided[0]}' to match the id field provided")
        return self


class BillItemVoid(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    class Config:
        extra = "forbid"


class BillItemOut(BaseModel):
    id: str
    bill_id: str
    source_type: str
    charge_master_item_id: Optional[str] = None
    service_request_id: Optional[str] = None
    medicine_inventory_item_id: Optional[str] = None
    description: str
    quantity: int
    unit_price_cents: int
    amount_cents: int
    created_by_name: Optional[str] = None
    created_by_role: Optional[str] = None
    created_at: datetime
    voided_at: Optional[datetime] = None
    voided_reason: Optional[str] = None

    class Config:
        from_attributes = True


class PaymentCreate(BaseModel):
    """Body for POST /billing/bills/{id}/payments. `claim_id`, when set,
    links this payment to the Claim it settles -- the router requires the
    claim belong to the same bill and `method` be 'insurance' or 'panel'
    in that case (Design decision 6)."""

    # Upper bound is defensive (overflow/fat-finger guard, security-review
    # finding), not a cap on legitimate overpayment/deposits -- deliberately
    # NOT compared against the bill's amount_due_cents in the router, since
    # a patient overpaying (rounding, advance deposit) is a real scenario.
    amount_cents: int = Field(ge=1, le=100_000_000)  # RM 1,000,000 ceiling
    method: str
    reference_no: Optional[str] = Field(default=None, max_length=128)
    claim_id: Optional[str] = None

    class Config:
        extra = "forbid"

    @field_validator("method")
    @classmethod
    def _check_method(cls, v: str) -> str:
        if v not in PAYMENT_METHODS:
            raise ValueError(f"method must be one of: {', '.join(sorted(PAYMENT_METHODS))}")
        return v

    @model_validator(mode="after")
    def _check_claim_payment_method(self):
        if self.claim_id and self.method not in ("insurance", "panel"):
            raise ValueError("method must be 'insurance' or 'panel' when claim_id is set")
        return self


class PaymentVoid(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    class Config:
        extra = "forbid"


class PaymentOut(BaseModel):
    id: str
    bill_id: str
    claim_id: Optional[str] = None
    amount_cents: int
    method: str
    reference_no: Optional[str] = None
    received_by_name: Optional[str] = None
    received_by_role: Optional[str] = None
    received_at: datetime
    voided_at: Optional[datetime] = None
    voided_reason: Optional[str] = None

    class Config:
        from_attributes = True


class ClaimCreate(BaseModel):
    """Body for POST /billing/bills/{id}/claims. `claim_amount_cents` may
    be less than the bill's total -- the copay/split case (Design decision
    6) -- the router 400s if it exceeds the bill's current unclaimed
    balance (`patient_due_cents`, NOT raw `amount_due_cents` -- a
    security-review fix: capping against `amount_due_cents` alone let two
    full-amount claims be created against the same bill, since only a
    Payment reduces that figure, not a claim)."""

    payer_name: str = Field(min_length=1, max_length=255)
    claim_amount_cents: int = Field(ge=1, le=100_000_000)  # RM 1,000,000 ceiling, same defensive bound as PaymentCreate
    notes: Optional[str] = Field(default=None, max_length=2000)

    class Config:
        extra = "forbid"


class ClaimUpdate(BaseModel):
    """Body for PATCH /billing/claims/{id} -- content fields, only
    accepted while the claim is still `draft` (Design decision 4)."""

    payer_name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    claim_amount_cents: Optional[int] = Field(default=None, ge=1, le=100_000_000)
    notes: Optional[str] = Field(default=None, max_length=2000)

    class Config:
        extra = "forbid"


class ClaimRejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=2000)

    class Config:
        extra = "forbid"


class ClaimVoidRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    class Config:
        extra = "forbid"


class ClaimOut(BaseModel):
    id: str
    bill_id: str
    payer_name: str
    claim_amount_cents: int
    status: str
    notes: Optional[str] = None
    submitted_at: Optional[datetime] = None
    facility_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BillVoidRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)

    class Config:
        extra = "forbid"


class BillOut(BaseModel):
    id: str
    patient_id: str
    patient_full_name: Optional[str] = None
    encounter_id: Optional[str] = None
    facility_name: str
    status: str
    created_by_name: Optional[str] = None
    created_by_role: Optional[str] = None
    created_at: datetime
    finalized_at: Optional[datetime] = None
    voided_at: Optional[datetime] = None
    voided_reason: Optional[str] = None
    items: List[BillItemOut] = []
    payments: List[PaymentOut] = []
    claims: List[ClaimOut] = []
    # Computed in routers/billing.py::_serialize_bill, never stored -- see
    # models.py's Bill docstring and Design decision 6 for the exact
    # arithmetic (patient_due_cents excludes claimed-but-not-yet-paid
    # amounts so front desk only collects the copay/remainder).
    total_cents: int = 0
    paid_cents: int = 0
    claimed_pending_cents: int = 0
    amount_due_cents: int = 0
    patient_due_cents: int = 0

    class Config:
        from_attributes = True


class BillingStatsOut(BaseModel):
    """GET /billing/stats -- a light facility-level summary, explicitly a
    stand-in: the full 'Financial performance reports' clause
    is P3.6's job."""

    facility_name: Optional[str] = None
    total_billed_cents: int
    total_collected_cents: int
    total_outstanding_cents: int
    bills_by_status: dict
    claims_by_status: dict


# ---------- P3.6 Reporting (canned reports + Custom Report Builder) ----------

class ReportRunRequest(BaseModel):
    """Body for POST /reports/run. `dataset` is a key from GET
    /reports/datasets; `fields`/`filters`/`group_by`/`sort` are all
    optional and validated against that dataset's own field registry by
    app/reporting_engine.py (never raw SQL -- see that module's docstring),
    so there is no enumerable set of valid field names to check here."""

    dataset: str
    fields: Optional[List[str]] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    group_by: Optional[List[str]] = None
    sort: Optional[Dict[str, str]] = None
    # "data anonymization": replace every field the dataset
    # marks `pii` (patient name/NRIC) with a stable pseudonym -- see
    # reporting_engine._pseudonym.
    anonymize: bool = False

    class Config:
        extra = "forbid"


class ReportExportRequest(ReportRunRequest):
    format: str  # "pdf" | "excel"

    @field_validator("format")
    @classmethod
    def _check_format(cls, v: str) -> str:
        if v not in ("pdf", "excel"):
            raise ValueError("format must be one of: pdf, excel")
        return v


class ReportNarrativeOut(BaseModel):
    """P4.3c NL report narrative -- see ai/report_narrative.py. None only
    when the local LLM is unavailable/disabled or the report had no rows."""
    narrative: Optional[str] = None
    disclaimer: str


class ReportTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    dataset: str
    fields: List[str] = Field(min_length=1)
    filters: Dict[str, Any] = Field(default_factory=dict)
    group_by: Optional[List[str]] = None
    sort: Optional[Dict[str, str]] = None
    is_shared: bool = False

    class Config:
        extra = "forbid"
        str_strip_whitespace = True


class ReportTemplateOut(BaseModel):
    id: str
    facility_name: str
    name: str
    dataset: str
    fields: List[str]
    filters: Dict[str, Any]
    group_by: Optional[List[str]] = None
    sort: Optional[Dict[str, str]] = None
    is_shared: bool
    created_by: str
    created_by_name: Optional[str] = None
    created_at: datetime
    editable: bool  # true if the CALLER (not necessarily the creator) may edit/delete this row

    class Config:
        from_attributes = True


# ---------- P3.7 Notifiable disease reporting ----------

class NotifiableDiseaseReportCreate(BaseModel):
    patient_id: str
    disease_name: str = Field(min_length=1, max_length=255)
    condition_id: Optional[str] = None
    onset_date: Optional[str] = Field(default=None, max_length=64)
    notes: Optional[str] = Field(default=None, max_length=2000)

    class Config:
        extra = "forbid"
        str_strip_whitespace = True


class NotifiableDiseaseReportOut(BaseModel):
    id: str
    facility_name: str
    patient_id: str
    patient_name: Optional[str] = None
    condition_id: Optional[str] = None
    disease_name: str
    onset_date: Optional[str] = None
    notes: Optional[str] = None
    status: str
    reported_by: str
    reported_by_name: Optional[str] = None
    reported_at: datetime
    submitted_by: Optional[str] = None
    submitted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- P3.8 Management Dashboard ----------

class DashboardSummaryOut(BaseModel):
    facility_name: Optional[str] = None
    date: str  # Malaysia-local ISO calendar date this snapshot is for
    patients_in_queue: int
    patients_attended_today: int
    physicians_on_duty: int
    physicians_total: int
    avg_wait_minutes: Optional[float] = None
    unresolved_referrals: int
    health_score: float
    health_score_breakdown: Dict[str, float]


class DashboardFlowForecastOut(BaseModel):
    today_so_far: int
    today_forecast_total: float
    today_forecast_remaining: float
    today_scheduled_appointments: int
    tomorrow_forecast_total: float
    tomorrow_scheduled_appointments: int
    weeks_of_history_used: int


# ---------- AI ----------
class SummaryRequest(BaseModel):
    patient_id: str


class MfaTokenWithRecovery(Token):
    """Returned once when MFA enrolment is confirmed: the session AND the
    recovery codes (shown a single time, never retrievable again)."""
    recovery_codes: List[str]
