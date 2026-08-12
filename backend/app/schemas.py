from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr


# ---------- Auth ----------
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str  # admin | clinician | records_officer | patient | emergency_responder
    facility: Optional[str] = None
    patient_id: Optional[str] = None


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    facility: Optional[str] = None
    patient_id: Optional[str] = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


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
