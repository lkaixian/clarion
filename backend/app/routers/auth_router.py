from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from .. import models, schemas, auth
from ..database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.UserOut)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = models.User(
        email=payload.email,
        hashed_password=auth.hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        facility=payload.facility,
        patient_id=payload.patient_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _resolve_login_user(db: Session, identifier: str) -> models.User | None:
    """Resolve the OAuth2 `username` field to a User, accepting either an
    email or a patient's NRIC (Patient.national_id). Tries email first
    (the common case), then falls back to an NRIC -> Patient -> User lookup.
    Returns None if neither resolves, so callers can fall through to the
    existing generic "incorrect credentials" response.
    """
    user = db.query(models.User).filter(models.User.email == identifier).first()
    if user:
        return user

    patient = db.query(models.Patient).filter(models.Patient.national_id == identifier).first()
    if patient:
        user = db.query(models.User).filter(models.User.patient_id == patient.id).first()
        if user:
            return user

    return None


@router.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = _resolve_login_user(db, form_data.username)
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email/NRIC or password")

    token = auth.create_access_token({"sub": user.id, "role": user.role})
    return schemas.Token(access_token=token, user=user)


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user
