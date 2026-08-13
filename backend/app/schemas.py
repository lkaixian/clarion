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


class PatientFullRecord(PatientOut):
    conditions: List[ConditionCreate] = []
    medications: List[MedicationCreate] = []
    allergies: List[AllergyCreate] = []


# ---------- Emergency ----------
class EmergencyProfileRequest(BaseModel):
    patient_id: str
    scope: List[str] = ["allergies", "medications", "conditions", "blood_type"]
    valid_minutes: int = 43200  # default 30 days validity for the QR "grant"; each *scan* still mints a short-lived token


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


class NfcScanRequest(BaseModel):
    nfc_uid: str
    responder_name: Optional[str] = None
    responder_org: Optional[str] = None


# ---------- AI ----------
class SummaryRequest(BaseModel):
    patient_id: str
