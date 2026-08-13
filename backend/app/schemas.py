from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, field_validator

# Minimum acceptable length for any newly-set password (staff-issued temp
# passwords are exempt -- they're generated server-side via
# auth.generate_temp_password(), which always produces 14 chars). Applied
# everywhere a human can choose/submit their own password: initial
# registration, self-service forgot-password, and authenticated
# change-password. Deliberately just a length floor, not a complexity
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


class ForgotPasswordRequest(BaseModel):
    """Public, unauthenticated self-service reset. Identity is proven with
    NRIC + date of birth (both are on the physical IC / commonly known to
    family, so this is a low-but-nonzero bar — mitigated with attempt
    rate-limiting/lockout below, same as a bank's "forgot password" flow)."""

    national_id: str
    date_of_birth: str  # ISO date string, must match Patient.date_of_birth exactly
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

    class Config:
        from_attributes = True


# ---------- Clinical sub-resources ----------
class ConditionCreate(BaseModel):
    name: str
    status: str = "active"
    diagnosed_at: Optional[str] = None
    is_chronic: bool = False
    critical_for_emergency: bool = False


class MedicationCreate(BaseModel):
    drug_name: str
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    prescribed_by_facility: Optional[str] = None
    start_date: Optional[str] = None
    active: bool = True
    critical_for_emergency: bool = True


class AllergyCreate(BaseModel):
    substance: str
    reaction: Optional[str] = None
    severity: str = "unknown"
    critical_for_emergency: bool = True


class EncounterCreate(BaseModel):
    facility_name: str
    encounter_type: str
    reason: Optional[str] = None
    notes: Optional[str] = None


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
