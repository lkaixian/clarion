"""CLARION central MPI / record locator.

Holds NO clinical data and NO identities -- only:

* a registry of hospitals (id, name, Ed25519 public key, endpoint), and
* per patient the 3 most recent visit pointers, keyed by an opaque
  HMAC(pepper, NRIC) that only the hospitals can compute (the pepper never
  reaches this service), each pointer carrying the origin hospital's
  signature over (key, facility, visit_ref, visited_at, content_hash).

A hospital needing another hospital's record asks here *where* it is, then
fetches it from the origin directly and verifies it against the signed
content hash. Central cannot read or alter a record, and cannot forge a
pointer (it has no hospital private key).

Run:  uvicorn mpi.main:app --workers 1   (see the replay-cache note below)
Env:  MPI_DATABASE_URL (default sqlite:///./mpi.db), MPI_ADMIN_TOKEN (required
      for facility registration; unset = registration disabled).
"""
import hmac
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from . import sigs

logger = logging.getLogger("clarion.mpi.central")

POINTERS_PER_PATIENT = 3  # returned per lookup; also kept per (patient, facility)
MAX_FUTURE_SKEW = timedelta(minutes=5)
_ALLOW_HTTP = os.environ.get("MPI_ALLOW_HTTP") == "1"  # tests / lab only

_engine = create_engine(
    os.environ.get("MPI_DATABASE_URL", "sqlite:///./mpi.db"),
    connect_args={"check_same_thread": False} if os.environ.get("MPI_DATABASE_URL", "sqlite").startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
Base = declarative_base()

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Facility(Base):
    __tablename__ = "facilities"
    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    public_key = Column(String(64), nullable=False)  # base64 of 32 raw bytes
    endpoint = Column(String(255), nullable=False)   # that hospital's base URL
    active = Column(Boolean, nullable=False, default=True)


class Pointer(Base):
    __tablename__ = "pointers"
    __table_args__ = (UniqueConstraint("facility_id", "visit_ref", name="uq_pointer_facility_visit"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    patient_key = Column(String(64), nullable=False, index=True)
    facility_id = Column(String(64), nullable=False)
    visit_ref = Column(String(64), nullable=False)
    visited_at = Column(DateTime, nullable=False)  # naive UTC, for ordering only
    visited_at_raw = Column(String(40), nullable=False)  # the exact string that was signed
    content_hash = Column(String(64), nullable=False)
    signature = Column(String(128), nullable=False)
    created_at = Column(DateTime, nullable=False, default=_now)


class Lookup(Base):
    """Who asked about which key, and what they were told -- central's own
    audit trail (it cannot see what the pointers mean, only the traffic)."""
    __tablename__ = "lookups"
    id = Column(Integer, primary_key=True, autoincrement=True)
    at = Column(DateTime, nullable=False, default=_now)
    requester = Column(String(64), nullable=False)
    patient_key_prefix = Column(String(12), nullable=False)
    hits = Column(Integer, nullable=False)


Base.metadata.create_all(_engine)

app = FastAPI(title="CLARION MPI", docs_url=None, redoc_url=None, openapi_url=None)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---- request authentication -------------------------------------------------
# Replay cache: (facility, signature) -> expiry. Process-local, so run ONE
# worker (or move this to Redis) -- with several, a replay inside the 120 s
# window could land on a worker that hasn't seen the original.
_replays = sigs.ReplayCache()


async def authenticated_facility(
    request: Request,
    db: Session = Depends(get_db),
    x_facility: Optional[str] = Header(None),
    x_timestamp: Optional[str] = Header(None),
    x_nonce: Optional[str] = Header(None),
    x_signature: Optional[str] = Header(None),
) -> Facility:
    if not (x_facility and x_timestamp and x_nonce and x_signature):
        raise HTTPException(status_code=401, detail="Missing signature headers")
    try:
        ts = int(x_timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="Bad timestamp")
    now = time.time()
    if not sigs.timestamp_fresh(ts, now):
        raise HTTPException(status_code=401, detail="Stale or future timestamp")
    fac = db.query(Facility).filter_by(id=x_facility, active=True).first()
    body = await request.body()
    message = sigs.request_message(
        request.method, request.url.path, ts, x_nonce, sigs.CENTRAL_AUDIENCE, body)
    # One opaque failure for unknown facility / bad signature.
    if fac is None or not sigs.verify(fac.public_key, message, x_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    if not _replays.first_time((fac.id, x_signature), now):
        raise HTTPException(status_code=401, detail="Replayed request")
    return fac


# ---- schemas ---------------------------------------------------------------

class FacilityIn(BaseModel):
    facility_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{2,64}$")
    name: str = Field(min_length=1, max_length=255)
    public_key: str
    endpoint: str = Field(pattern=r"^https?://[^\s]{3,250}$")

    @field_validator("endpoint")
    @classmethod
    def _https(cls, v: str) -> str:
        if not _ALLOW_HTTP and not v.startswith("https://"):
            raise ValueError("endpoint must be https://")
        return v
    active: bool = True

    @field_validator("public_key")
    @classmethod
    def _key(cls, v: str) -> str:
        if len(sigs.unb64(v)) != 32:
            raise ValueError("public_key must be 32 raw bytes, base64")
        return v


class PointerIn(BaseModel):
    patient_key: str
    visit_ref: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    visited_at: str
    content_hash: str
    signature: str

    @field_validator("patient_key", "content_hash")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not _HEX64.match(v):
            raise ValueError("expected 64 lowercase hex chars")
        return v

    @field_validator("visited_at")
    @classmethod
    def _when(cls, v: str) -> str:
        parsed = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("visited_at must carry a UTC offset")
        if not 2000 <= parsed.year <= 2100:
            raise ValueError("visited_at out of range")
        if parsed.astimezone(timezone.utc) > datetime.now(timezone.utc) + MAX_FUTURE_SKEW:
            raise ValueError("visited_at is in the future")
        return v


class PointerOut(BaseModel):
    facility_id: str
    facility_name: str
    endpoint: str
    visit_ref: str
    visited_at: str
    content_hash: str
    signature: str


# ---- routes ----------------------------------------------------------------

@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok"}


@app.post("/admin/facilities")
def register_facility(
    payload: FacilityIn,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(None),
):
    """Admin-only (bearer MPI_ADMIN_TOKEN): add or update a hospital. Done
    out-of-band when a hospital is onboarded -- never self-service."""
    expected = os.environ.get("MPI_ADMIN_TOKEN", "")
    given = (authorization or "").removeprefix("Bearer ").strip()
    # A short token is treated as "registration disabled", not as a weak one.
    if len(expected) < 24 or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Forbidden")
    logger.warning("facility registry change: id=%s active=%s endpoint=%s",
                   payload.facility_id, payload.active, payload.endpoint)
    fac = db.query(Facility).filter_by(id=payload.facility_id).first() or Facility(id=payload.facility_id)
    fac.name, fac.public_key = payload.name, payload.public_key
    fac.endpoint, fac.active = payload.endpoint, payload.active
    db.add(fac)
    db.commit()
    return {"facility_id": fac.id, "active": fac.active}


@app.get("/facilities/{facility_id}")
def get_facility(facility_id: str, db: Session = Depends(get_db),
                 caller: Facility = Depends(authenticated_facility)):
    """Public key + endpoint of a peer, so a hospital can verify a request
    from another hospital without any out-of-band key exchange."""
    fac = db.query(Facility).filter_by(id=facility_id, active=True).first()
    if fac is None:
        raise HTTPException(status_code=404, detail="Unknown facility")
    return {"facility_id": fac.id, "name": fac.name, "public_key": fac.public_key, "endpoint": fac.endpoint}


@app.put("/pointers")
def publish_pointer(payload: PointerIn, db: Session = Depends(get_db),
                    caller: Facility = Depends(authenticated_facility)):
    """A hospital publishes (or re-publishes, e.g. after an amendment) one
    visit. Only the caller's own facility id can ever be written, and the
    pointer must carry the caller's signature -- so it stays verifiable
    after it is handed to a third hospital."""
    message = sigs.pointer_message(
        payload.patient_key, caller.id, payload.visit_ref, payload.visited_at, payload.content_hash)
    if not sigs.verify(caller.public_key, message, payload.signature):
        raise HTTPException(status_code=422, detail="Pointer signature does not verify")

    visited = datetime.fromisoformat(payload.visited_at.replace("Z", "+00:00"))
    if visited.tzinfo is not None:
        visited = visited.astimezone(timezone.utc).replace(tzinfo=None)

    row = db.query(Pointer).filter_by(facility_id=caller.id, visit_ref=payload.visit_ref).first()
    if row is None:
        row = Pointer(facility_id=caller.id, visit_ref=payload.visit_ref)
    elif row.patient_key != payload.patient_key:
        # A visit_ref belongs to one patient for life; re-pointing it would
        # let a compromised hospital move a record between patients.
        raise HTTPException(status_code=409, detail="visit_ref already bound to a different patient key")
    row.patient_key, row.visited_at = payload.patient_key, visited
    row.visited_at_raw = payload.visited_at
    row.content_hash, row.signature = payload.content_hash, payload.signature
    db.add(row)
    db.flush()

    # Prune per (patient, facility): one hospital -- however many pointers it
    # publishes -- can only ever evict its OWN older entries, never another
    # hospital's. Lookup then returns the newest 3 across all of them.
    rows = (
        db.query(Pointer).filter_by(patient_key=payload.patient_key, facility_id=caller.id)
        .order_by(Pointer.visited_at.desc(), Pointer.id.desc()).all()
    )
    for stale in rows[POINTERS_PER_PATIENT:]:
        db.delete(stale)
    db.commit()
    return {"kept": min(len(rows), POINTERS_PER_PATIENT)}


@app.get("/patients/{patient_key}", response_model=List[PointerOut])
def lookup_patient(patient_key: str, db: Session = Depends(get_db),
                   caller: Facility = Depends(authenticated_facility)):
    if not _HEX64.match(patient_key):
        raise HTTPException(status_code=422, detail="Bad patient key")
    rows = (
        db.query(Pointer, Facility)
        .join(Facility, Facility.id == Pointer.facility_id)
        .filter(Pointer.patient_key == patient_key, Facility.active.is_(True))
        .order_by(Pointer.visited_at.desc(), Pointer.id.desc())
        .limit(POINTERS_PER_PATIENT).all()
    )
    db.add(Lookup(requester=caller.id, patient_key_prefix=patient_key[:12], hits=len(rows)))
    db.commit()
    return [
        PointerOut(
            facility_id=f.id, facility_name=f.name, endpoint=f.endpoint, visit_ref=p.visit_ref,
            visited_at=p.visited_at_raw,
            content_hash=p.content_hash, signature=p.signature,
        )
        for p, f in rows
    ]
