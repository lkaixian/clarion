"""Federation: reading another hospital's visits without a shared database.

Two audiences, deliberately on separate routes:

* STAFF (`/federation/patients/...`): a clinician at this hospital asks
  "where else has this patient been seen?" (pointers from central) and
  "show me that visit" (fetched from the origin and verified end to end).
  Same gate as the rest of patient data: `patients` page access and the
  patient must be present at this facility.
* PEERS (`/federation/visits/{ref}`): another hospital fetching one of OUR
  visits. Authenticated by an Ed25519 signature checked against the key
  central has registered for the caller -- no passwords, no shared secrets.

A fetched visit is returned for display; it is never written into this
hospital's own tables (foreign records stay read-only, by design).
"""
import re
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .. import auth, models, mpi_client
from ..audit import log_access
from ..clinical_access import _patient_present_at
from ..database import get_db
from ..rate_limit import limiter
from mpi import sigs

router = APIRouter(prefix="/federation", tags=["federation"])

# Process-local: with several gunicorn workers a replay inside the 120 s window
# can land on a worker that has not seen the original (audience binding limits
# what a captured signature is good for).
_replays = sigs.ReplayCache()


def _require_enabled() -> None:
    if not mpi_client.enabled():
        raise HTTPException(status_code=503, detail="Federation is not configured on this node")


def _staff_patient(db: Session, current_user: models.User, patient_id: str) -> models.Patient:
    patient = db.query(models.Patient).filter_by(id=patient_id).first()
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if not (current_user.facility and _patient_present_at(db, patient_id, current_user.facility)):
        raise HTTPException(status_code=403, detail="Patient is not present at your facility")
    if not patient.national_id:
        raise HTTPException(status_code=409, detail="Patient has no national ID to match on")
    return patient


# ---- staff side ------------------------------------------------------------

@router.get("/patients/{patient_id}/other-visits")
def other_visits(
    patient_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_page_access("patients")),
):
    _require_enabled()
    patient = _staff_patient(db, current_user, patient_id)
    try:
        pointers = mpi_client.lookup(patient.national_id)
    except mpi_client.MpiError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    own = mpi_client._cfg()["facility_id"]
    log_access(db, patient.id, current_user.id, current_user.role, "federation_lookup",
               detail=f"pointers={len(pointers)}", actor_facility=current_user.facility)
    return [p for p in pointers if p["facility_id"] != own]


@router.get("/patients/{patient_id}/visits/{facility_id}/{visit_ref}")
def fetch_other_visit(
    patient_id: str,
    facility_id: str,
    visit_ref: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_page_access("patients")),
):
    _require_enabled()
    patient = _staff_patient(db, current_user, patient_id)
    try:
        pointer = next(
            (p for p in mpi_client.lookup(patient.national_id)
             if p["facility_id"] == facility_id and p["visit_ref"] == visit_ref),
            None,
        )
        if pointer is None:
            raise HTTPException(status_code=404, detail="No such visit for this patient")
        document = mpi_client.fetch_visit(patient.national_id, pointer)
    except mpi_client.MpiError as exc:
        log_access(db, patient.id, current_user.id, current_user.role, "federation_fetch_failed",
                   detail=f"origin={facility_id} visit_ref={visit_ref} reason={exc}"[:500],
                   actor_facility=current_user.facility)
        raise HTTPException(status_code=502, detail=str(exc))
    log_access(db, patient.id, current_user.id, current_user.role, "federation_fetch",
               detail=f"origin={facility_id} visit_ref={visit_ref}", actor_facility=current_user.facility)
    return {"verified": True, "origin": facility_id, "document": document}


# ---- peer side -------------------------------------------------------------

_FACILITY_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{2,64}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


@router.get("/visits/{patient_key}/{visit_ref}")
@limiter.limit("60/minute")
def serve_visit_to_peer(
    request: Request,
    patient_key: str,
    visit_ref: str,
    db: Session = Depends(get_db),
    x_facility: str = Header(None),
    x_timestamp: str = Header(None),
    x_nonce: str = Header(None),
    x_signature: str = Header(None),
):
    """Serve one of OUR visits to a registered peer. Unknown/forged callers
    and unknown visits all look the same (401/404) to avoid an oracle."""
    _require_enabled()
    if not (x_facility and x_timestamp and x_nonce and x_signature):
        raise HTTPException(status_code=401, detail="Missing signature headers")
    try:
        ts = int(x_timestamp)
    except ValueError:
        raise HTTPException(status_code=401, detail="Bad timestamp")
    now = time.time()
    if not sigs.timestamp_fresh(ts, now):
        raise HTTPException(status_code=401, detail="Stale or future timestamp")
    if not _FACILITY_ID_RE.match(x_facility) or not _HEX64_RE.match(patient_key):
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        peer = mpi_client.facility_info(x_facility)
    except mpi_client.MpiError:
        raise HTTPException(status_code=401, detail="Invalid signature")
    # Audience = THIS hospital: a request signed for any other recipient (e.g.
    # captured by a hostile endpoint) is useless here.
    message = sigs.request_message(
        "GET", request.url.path, ts, x_nonce, mpi_client._cfg()["facility_id"], b"")
    if not sigs.verify(peer["public_key"], message, x_signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    if not _replays.first_time((x_facility, x_signature), now):
        raise HTTPException(status_code=401, detail="Replayed request")

    # Only SIGNED-OFF visits authored here, and only for the patient key the
    # caller names (so a bare visit_ref guess gets nothing).
    enc = (
        db.query(models.Encounter)
        .filter(models.Encounter.id == visit_ref,
                models.Encounter.facility_name == mpi_client.facility_name(),
                models.Encounter.signed_by.isnot(None))
        .first()
    )
    patient = db.query(models.Patient).filter_by(id=enc.patient_id).first() if enc else None
    if (enc is None or patient is None or not patient.national_id
            or mpi_client.patient_key(patient.national_id) != patient_key):
        raise HTTPException(status_code=404, detail="Not found")
    log_access(db, enc.patient_id, f"facility:{x_facility}", "federation_peer", "federation_visit_served",
               detail=f"visit_ref={visit_ref}")
    return mpi_client.visit_document(db, enc)
