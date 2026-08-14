from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, field_validator

# Minimum acceptable length for any newly-set password (staff-issued temp
# passwords are exempt -- they're generated server-side via
# auth.generate_temp_password(), which always produces 14 chars). Applied
# everywhere a human can choose/submit their own password: initial
# registration, the self-service email-OTP password reset, and
# authenticated change-password. Deliberately just a length floor, not a complexity
# policy (mandatory mixed-case/digits/symbols) -- this is a health-record
# demo app, not a bank, and complexity rules mostly just push people toward
# predictable substitutions without meaningfully raising entropy.
MIN_PASSWORD_LENGTH = 8


def _validate_password_length(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    return value


# ---------- Auth ----------
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str  # admin | clinician | records_officer | patient | emergency_responder
    facility: Optional[str] = None
    patient_id: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _password_min_length(cls, v: str) -> str:
        return _validate_password_length(v)


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    facility: Optional[str] = None
    patient_id: Optional[str] = None
    must_change_password: bool = False
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

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


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
    date_of_birth: str
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
    facility_name: Optional[str] = None
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
        if v < datetime.utcnow():
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
    # Computed (not a DB column) via appointments.compute_reminder_offsets --
    # see that function's docstring for why the exact reminder rule lives
    # only there. Populated explicitly by the router (not via from_attributes
    # ORM auto-read), since it isn't a plain attribute on models.Appointment.
    reminders: List[dict] = []

    class Config:
        from_attributes = True


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
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    created_at: datetime
    # Computed (not a DB column) -- deliberately re-derived on every read
    # rather than stored, so a change to reorder_threshold or
    # quantity_on_hand can never leave a stale is_low_stock flag behind.
    is_low_stock: bool = False

    class Config:
        from_attributes = True


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
    clocked_in: bool
    since: Optional[datetime] = None
    last_clock_out_at: Optional[datetime] = None


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

    @field_validator("valid_minutes")
    @classmethod
    def _check_valid_minutes(cls, v: int) -> int:
        if v <= 0 or v > NFC_VALID_MINUTES_MAX:
            raise ValueError(
                f"valid_minutes must be between 1 and {NFC_VALID_MINUTES_MAX} (2 years)."
            )
        return v


class NfcScanRequest(BaseModel):
    nfc_uid: str
    responder_name: Optional[str] = None
    responder_org: Optional[str] = None


# ---------- AI ----------
class SummaryRequest(BaseModel):
    patient_id: str
