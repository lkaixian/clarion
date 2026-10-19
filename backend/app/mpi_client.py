"""Hospital-side client for the central MPI (see backend/mpi/main.py).

A hospital keeps its own records. After a consultation is signed off it
publishes ONE signed pointer {patient_key, visit_ref, visited_at,
content_hash} to central; later any hospital can ask central *where* a
patient's recent visits are, fetch the visit from its origin, and verify it
against the origin's signed content hash. Nothing clinical ever sits at
central, and central never learns an NRIC (the pepper behind `patient_key`
is held by hospitals only).

Disabled (every function a safe no-op) unless all four are set:
  MPI_BASE_URL                 central base URL (include any /mpi prefix)
  CLARION_FACILITY_ID          this hospital's id, as registered at central
  CLARION_FACILITY_PRIVATE_KEY base64 Ed25519 seed (32 bytes)
  CLARION_MPI_PEPPER           shared among hospitals only; NOT given to central
Optional: CLARION_FACILITY_NAME -- the `Encounter.facility_name` value this
hospital's records carry; only those encounters are served to peers
(default: the facility id).
"""
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import timezone
from typing import Optional

import httpx

from . import jobs, models
from .database import SessionLocal
from .nric import normalize_nric
from mpi import sigs

logger = logging.getLogger("clarion.mpi")

JOB_KIND = "mpi_publish_visit"
_KEY_CACHE_SECONDS = 300

# Tests swap this to return a Starlette TestClient bound to the MPI app.
_client_factory = lambda: httpx.Client(timeout=5.0)  # noqa: E731


class MpiError(Exception):
    """Central / peer unreachable or answered with something unusable."""


def _cfg() -> "Optional[dict]":
    cfg = {
        "base": (os.environ.get("MPI_BASE_URL") or "").rstrip("/"),
        "facility_id": os.environ.get("CLARION_FACILITY_ID") or "",
        "seed": os.environ.get("CLARION_FACILITY_PRIVATE_KEY") or "",
        "pepper": os.environ.get("CLARION_MPI_PEPPER") or "",
    }
    # Bump to rotate the pepper-derived patient keys (republish afterwards).
    return cfg if all(cfg.values()) else None


def enabled() -> bool:
    return _cfg() is not None


def facility_name() -> str:
    cfg = _cfg()
    return os.environ.get("CLARION_FACILITY_NAME") or (cfg["facility_id"] if cfg else "")


def patient_key(national_id: str) -> str:
    cfg = _cfg()
    if cfg is None:
        raise MpiError("MPI is not configured")
    return hmac.new(
        cfg["pepper"].encode(),
        f"mpi-patient-v{os.environ.get('CLARION_MPI_KEY_VERSION', '1')}|".encode()
        + normalize_nric(national_id).encode(),
        hashlib.sha256,
    ).hexdigest()


def _pins() -> dict:
    """Out-of-band peer pins: CLARION_PEER_KEYS = path to (or inline) JSON
    {"facility-id": {"public_key": "<b64>", "endpoint": "https://..."}}.
    When set it is AUTHORITATIVE: a peer not listed is refused and a listed
    one must match -- so a compromised central (or admin token) cannot swap
    a hospital's key or redirect fetches. Unset = trust central's registry."""
    raw = os.environ.get("CLARION_PEER_KEYS", "").strip()
    if not raw:
        return {}
    if not raw.startswith("{"):
        with open(raw, encoding="utf-8") as fh:
            raw = fh.read()
    return json.loads(raw)


def _https_ok(url: str) -> bool:
    return url.startswith("https://") or os.environ.get("MPI_ALLOW_HTTP") == "1"


def _call(method: str, rel_path: str, body: "Optional[dict]" = None) -> httpx.Response:
    cfg = _cfg()
    if cfg is None:
        raise MpiError("MPI is not configured")
    raw = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
    headers = sigs.sign_headers(cfg["facility_id"], cfg["seed"], method, rel_path, raw)
    if raw:
        headers["Content-Type"] = "application/json"
    try:
        with _client_factory() as client:
            return client.request(method, cfg["base"] + rel_path, content=raw, headers=headers)
    except httpx.HTTPError as exc:
        raise MpiError(f"central unreachable: {exc.__class__.__name__}") from exc


# ---- publish ---------------------------------------------------------------

def visit_document(db, encounter: models.Encounter) -> dict:
    """The canonical, patient-identifier-free content of one visit. The
    content hash is computed over exactly this."""
    note = db.query(models.ConsultationNote).filter_by(encounter_id=encounter.id).first()
    started = encounter.started_at
    if started is not None and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return {
        "visit_ref": encounter.id,
        "facility": encounter.facility_name,
        "encounter_type": encounter.encounter_type,
        "reason": encounter.reason,
        "department": encounter.department,
        "started_at": started.isoformat() if started else None,
        "notes": encounter.notes,
        "signed_by_name": encounter.signed_by_name,
        "signed_by_role": encounter.signed_by_role,
        "consultation": None if note is None else {
            "subjective": note.subjective, "objective": note.objective,
            "assessment": note.assessment, "plan": note.plan, "treatment_plan": note.treatment_plan,
        },
    }


def _publish_job(payload: dict) -> None:
    """Job handler. Raises on failure so the queue retries (3 attempts)."""
    cfg = _cfg()
    if cfg is None:
        return
    db = SessionLocal()
    try:
        enc = db.query(models.Encounter).filter_by(id=payload["encounter_id"]).first()
        patient = db.query(models.Patient).filter_by(id=enc.patient_id).first() if enc else None
        if enc is None or patient is None or not patient.national_id:
            return  # nothing to key a pointer on -- not an error, not retried
        if enc.facility_name != facility_name():
            return  # not authored here: peers could never fetch it from us
        from .routers.federation import _has_sharing_consent  # lazy: routers import this module
        if not _has_sharing_consent(db, patient.id):
            return  # no cross_facility_sharing consent: central learns nothing about this visit
        doc = visit_document(db, enc)
        pkey = patient_key(patient.national_id)
        chash = sigs.content_hash(doc)
        visited_at = doc["started_at"]
        if not visited_at:
            return
        message = sigs.pointer_message(pkey, cfg["facility_id"], enc.id, visited_at, chash)
        resp = _call("PUT", "/pointers", {
            "patient_key": pkey, "visit_ref": enc.id, "visited_at": visited_at,
            "content_hash": chash, "signature": sigs.sign(cfg["seed"], message),
        })
        if 400 <= resp.status_code < 500:
            # Permanent (bad signature, unknown facility, validation, clock
            # skew): retrying the identical request cannot succeed. Log loudly
            # and stop rather than burn the queue's retries.
            logger.error("MPI rejected visit %s with %s: %s", enc.id, resp.status_code, resp.text[:200])
            return
        if resp.status_code != 200:
            raise MpiError(f"central answered {resp.status_code}")  # transient -> queue retries
    finally:
        db.close()


jobs.register(JOB_KIND, _publish_job)

WITHDRAW_KIND = "mpi_withdraw_patient"


def _withdraw_job(payload: dict) -> None:
    """Retract this hospital's pointers for one patient at central."""
    if _cfg() is None:
        return
    from .routers.federation import _has_sharing_consent  # lazy: routers import this module
    db = SessionLocal()
    try:
        patient = db.query(models.Patient).filter_by(id=payload["patient_id"]).first()
        if patient is None or not patient.national_id:
            return
        if _has_sharing_consent(db, patient.id):
            return  # consent was granted again since this was queued: keep the pointers
        resp = _call("DELETE", f"/patients/{patient_key(patient.national_id)}")
        if 400 <= resp.status_code < 500 and resp.status_code not in (401, 408, 429):
            logger.error("MPI rejected withdrawal for patient %s with %s", patient.id, resp.status_code)
            return
        if resp.status_code != 200:
            raise MpiError(f"central answered {resp.status_code}")
    finally:
        db.close()


jobs.register(WITHDRAW_KIND, _withdraw_job)


def enqueue_withdraw(db, patient_id: str) -> None:
    """Consent withdrawn: take this hospital's pointers for the patient off central."""
    if not enabled():
        return
    try:
        jobs.enqueue(db, WITHDRAW_KIND, {"patient_id": patient_id})
    except Exception:  # noqa: BLE001
        logger.exception("could not enqueue MPI withdrawal for patient %s", patient_id)


def enqueue_backfill(db, patient_id: str) -> None:
    """Consent granted late: publish the (newest few) visits signed here before it was."""
    if not enabled():
        return
    recent = (
        db.query(models.Encounter.id)
        .filter(models.Encounter.patient_id == patient_id,
                models.Encounter.facility_name == facility_name(),
                models.Encounter.signed_by.isnot(None))
        .order_by(models.Encounter.started_at.desc()).limit(3).all()
    )
    for (encounter_id,) in recent:
        enqueue_publish(db, encounter_id)


def enqueue_publish(db, encounter_id: str) -> None:
    """Best-effort: a sign-off must never fail because central is down."""
    if not enabled():
        return
    try:
        jobs.enqueue(db, JOB_KIND, {"encounter_id": encounter_id})
    except Exception:  # noqa: BLE001
        logger.exception("could not enqueue MPI publish for encounter %s", encounter_id)


# ---- lookup / fetch --------------------------------------------------------

_key_cache: dict = {}


def facility_info(facility_id: str) -> dict:
    cached = _key_cache.get(facility_id)
    if cached and cached[0] > time.time():
        return cached[1]
    pins = _pins()
    if pins and facility_id not in pins:
        raise MpiError(f"facility {facility_id!r} is not in the pinned peer list")
    resp = _call("GET", f"/facilities/{facility_id}")
    if resp.status_code != 200:
        raise MpiError(f"unknown facility {facility_id!r}")
    try:
        info = resp.json()
    except ValueError as exc:
        raise MpiError("central returned an unreadable facility record") from exc
    pin = pins.get(facility_id)
    if pin:
        if pin.get("public_key") != info.get("public_key"):
            raise MpiError(f"central's key for {facility_id!r} does not match the pinned key")
        if pin.get("endpoint"):
            info["endpoint"] = pin["endpoint"]
    _key_cache[facility_id] = (time.time() + _KEY_CACHE_SECONDS, info)
    return info


def lookup(national_id: str) -> list:
    """Recent visit pointers for a patient, newest first (may include this
    hospital's own -- callers filter). Raises MpiError on any central fault."""
    resp = _call("GET", f"/patients/{patient_key(national_id)}")
    if resp.status_code != 200:
        raise MpiError(f"central answered {resp.status_code}")
    return resp.json()


def verify_pointer(pointer: dict, pkey: str) -> bool:
    """The pointer really was signed by the facility it names."""
    info = facility_info(pointer["facility_id"])
    message = sigs.pointer_message(
        pkey, pointer["facility_id"], pointer["visit_ref"], pointer["visited_at"], pointer["content_hash"])
    return sigs.verify(info["public_key"], message, pointer["signature"])


def fetch_visit(national_id: str, pointer: dict) -> dict:
    """Fetch a visit from its origin and verify it end to end: the pointer's
    signature (origin vouched), and the document's hash against it."""
    pkey = patient_key(national_id)
    if not verify_pointer(pointer, pkey):
        raise MpiError("pointer signature does not verify")
    cfg = _cfg()
    # Use the registry (or pinned) endpoint for the origin -- never trust the
    # endpoint string that arrived inside the pointer dict.
    info = facility_info(pointer["facility_id"])
    endpoint = info["endpoint"].rstrip("/")
    if not _https_ok(endpoint):
        raise MpiError("origin endpoint is not https")
    rel = f"/federation/visits/{pkey}/{pointer['visit_ref']}"
    headers = sigs.sign_headers(
        cfg["facility_id"], cfg["seed"], "GET", rel, audience=pointer["facility_id"])
    try:
        with _client_factory() as client:
            resp = client.get(endpoint + rel, headers=headers)
    except httpx.HTTPError as exc:
        raise MpiError(f"origin unreachable: {exc.__class__.__name__}") from exc
    if resp.status_code != 200:
        raise MpiError(f"origin answered {resp.status_code}")
    try:
        doc = resp.json()
        digest = sigs.content_hash(doc)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise MpiError("origin returned an unreadable record") from exc
    if digest != pointer["content_hash"]:
        raise MpiError("record does not match the signed content hash")
    if doc.get("visit_ref") != pointer["visit_ref"]:
        raise MpiError("record is not the visit the pointer names")
    return doc
