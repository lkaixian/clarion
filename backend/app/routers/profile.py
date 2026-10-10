"""
Saved digital signature, stored on the staff member's own profile.

A clinician (or records_officer / admin) uploads a PNG of their signature
once; it is then reused to sign off a completed consultation
(routers/consultation.py) or a clinical-record annotation
(routers/patients.py). Both of those COPY this object to their own per-row
snapshot at signing time, so a later change/clear here never rewrites an
already-signed record.

Storage (P1.6): every blob goes through the ObjectStore (app/storage.py) —
the local filesystem for the demo, MinIO on-prem. Signatures live in the
`clarion-signatures` bucket:
  - the profile signature at key `users/{user_id}.png`,
  - the consultation snapshot at `encounters/{encounter_id}.png`,
  - the annotation snapshot at `annotations/{annotation_id}.png`.

Security, unchanged from the on-disk version:
  - the object key is ALWAYS built server-side from a row id, never from a
    client-supplied name,
  - the upload is validated by content-type AND extension AND magic bytes
    (all three must agree) and size-capped,
  - the download endpoints read the key from the DB column only and send
    `X-Content-Type-Options: nosniff`.

This router carries NO require_page_access gate (registered plainly in
main.py, same as staff.py) -- it's "for yourself" plus one facility-scoped
read of a colleague's signature for rendering "signed by Dr X" thumbnails.
"""
import base64
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session

from .. import models, auth, schemas
from ..database import get_db
from ..audit import log_access
from ..imaging import ImageProcessingError, normalise_image, sniff_image_mime
from ..storage import (
    BUCKET_SIGNATURES,
    BUCKET_STAFF_PHOTOS,
    ObjectMeta,
    ObjectNotFound,
    ObjectStoreError,
    apply_object_meta,
    get_object_store,
)
from ._uploads import enforce_upload_size

router = APIRouter(tags=["profile"])

SIGNATURE_MIME = "image/png"

# A signature is a small line drawing -- comfortably under half a megabyte.
MAX_SIGNATURE_BYTES = 500 * 1024

# The 8-byte PNG magic number -- the one thing a client can't spoof by
# renaming a file or setting a Content-Type header.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def signature_key_for_user(user_id: str) -> str:
    return f"users/{user_id}.png"


def _validate_png_bytes(raw: bytes) -> None:
    if not raw:
        raise HTTPException(status_code=422, detail="Empty file.")
    if len(raw) > MAX_SIGNATURE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Signature image too large — max {MAX_SIGNATURE_BYTES // 1024}KB.",
        )
    if not raw.startswith(_PNG_MAGIC):
        raise HTTPException(status_code=422, detail="Signature must be a PNG image.")


def _persist_signature_bytes(db: Session, user: models.User, raw: bytes) -> None:
    """Validate + store the signature at `clarion-signatures/users/{id}.png`
    (overwrite), record its object coordinates on the user row, commit.
    Shared by POST /me/signature and the `signature_b64`-on-first-use path in
    consultation / annotation sign-off."""
    _validate_png_bytes(raw)
    try:
        meta = get_object_store().put(
            BUCKET_SIGNATURES, signature_key_for_user(user.id), raw, mime=SIGNATURE_MIME
        )
    except (OSError, ObjectStoreError):
        raise HTTPException(status_code=500, detail="Could not store the signature. Try again.")
    apply_object_meta(user, meta, "signature")
    db.add(user)
    db.commit()
    db.refresh(user)


def save_signature_from_b64(db: Session, user: models.User, signature_b64: str) -> None:
    """Decode a base64 PNG and persist it as `user`'s saved signature.
    Raises 422 on bad base64. Used by the consultation / annotation sign-off
    endpoints when the caller passed `signature_b64` and has no saved
    signature yet. Tolerates a full `data:image/png;base64,...` data-URL as
    well as bare base64 -- a `<canvas>.toDataURL()` result is the former, so
    accepting both keeps every caller from having to remember to strip it."""
    payload = (signature_b64 or "").strip()
    if payload.startswith("data:"):
        payload = payload.split(",", 1)[-1]
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="signature_b64 is not valid base64.")
    _persist_signature_bytes(db, user, raw)


def copy_signature_snapshot(user: models.User, dest_key: str) -> "ObjectMeta | None":
    """Best-effort COPY of `user`'s current signature object to `dest_key`
    within the signatures bucket (a per-row snapshot). Returns the new
    :class:`ObjectMeta` on success, ``None`` if the source is missing. Never
    raises -- a signed record is still worth creating even if the snapshot
    copy fails."""
    src = user.signature_object_key
    if not src:
        return None
    store = get_object_store()
    try:
        data = store.get_checked(BUCKET_SIGNATURES, src, user.signature_sha256)
    except ObjectStoreError:
        return None
    try:
        return store.put(
            BUCKET_SIGNATURES, dest_key, data, mime=user.signature_mime or SIGNATURE_MIME
        )
    except (OSError, ObjectStoreError):
        return None


def _signature_response(
    key: "str | None", *, sha256: "str | None" = None, not_found_detail: str
) -> Response:
    """Fetch a signature PNG by key (integrity-checked against `sha256` when
    known) and return it with a nosniff header. 404 if the key is unset or
    the object is gone; 503 on a storage-backend error."""
    if not key:
        raise HTTPException(status_code=404, detail=not_found_detail)
    try:
        data = get_object_store().get_checked(BUCKET_SIGNATURES, key, sha256)
    except (ObjectNotFound, ValueError):
        raise HTTPException(status_code=404, detail=not_found_detail)
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="Signature storage is temporarily unavailable.")
    return Response(
        content=data,
        media_type="image/png",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.post("/me/signature")
def upload_my_signature(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Save (overwrite) the caller's own digital signature. PNG only,
    <= 500KB; content-type, filename extension and magic bytes must all
    agree."""
    enforce_upload_size(file, MAX_SIGNATURE_BYTES, "Signature image")
    raw = file.file.read()
    declared_type = (file.content_type or "").split(";")[0].strip().lower()
    ext = os.path.splitext(file.filename or "")[1].lower()
    if declared_type != "image/png" or ext != ".png":
        raise HTTPException(
            status_code=422,
            detail="Signature must be a PNG file (content-type and .png extension).",
        )
    _persist_signature_bytes(db, current_user, raw)

    log_access(
        db, None, current_user.id, current_user.role, "set_signature",
        actor_facility=current_user.facility,
    )
    return {"status": "ok", "has_signature": True}


@router.get("/me/signature")
def get_my_signature(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """The caller's own saved signature PNG. 404 if none. Key is read from
    the DB column only."""
    return _signature_response(
        current_user.signature_object_key,
        sha256=current_user.signature_sha256,
        not_found_detail="No signature saved.",
    )


@router.delete("/me/signature")
def delete_my_signature(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Clear the caller's saved signature. Best-effort delete of the object;
    already-signed records keep their own snapshot copy regardless."""
    key = current_user.signature_object_key
    apply_object_meta(current_user, None, "signature")
    db.add(current_user)
    db.commit()
    if key:
        try:
            get_object_store().delete(BUCKET_SIGNATURES, key)
        except OSError:
            pass

    log_access(
        db, None, current_user.id, current_user.role, "clear_signature",
        actor_facility=current_user.facility,
    )
    return {"status": "ok", "has_signature": False}


# ---------- Bio / contact email / profile photo ----------
# Same "for yourself" posture as the signature endpoints above, plus the
# matching admin-editing endpoints on routers/admin.py (PATCH
# /admin/staff/{id}/profile, POST /admin/staff/{id}/photo) for a facility's
# own roster. `bio` is PUBLIC (see routers/patients.py::list_booking_options
# + GET /patients/clinicians/{id}/photo); `contact_email` stays
# internal/staff-only, never surfaced there.

PHOTO_MIME = "image/jpeg"  # normalise_image always re-encodes to JPEG

# A profile photo is a single headshot, not a multi-page scan -- same
# ceiling as a medicine packaging photo (inventory.py::MAX_MEDICINE_IMAGE_BYTES).
MAX_PHOTO_BYTES = 2 * 1024 * 1024

# content-type -> allowed extension. Declared type, extension and sniffed
# magic bytes must all agree (same triple-check as the medicine-photo path
# in app/inventory.py) before the bytes are even handed to normalise_image.
_PHOTO_TYPES = {
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/webp": {".webp"},
    "image/heic": {".heic", ".heif"},  # iPhone default; always re-encoded to JPEG below
}
_PHOTO_SNIFF_OK = set(_PHOTO_TYPES)


def photo_key_for_user(user_id: str) -> str:
    return f"users/{user_id}.jpg"


def _persist_photo(db: Session, user: models.User, file: UploadFile) -> None:
    """Validate + normalise + persist an uploaded profile photo, best-effort
    replacing any existing one. Shared by POST /me/photo and POST
    /admin/staff/{id}/photo. Commits the row."""
    enforce_upload_size(file, MAX_PHOTO_BYTES, "Photo")
    raw = file.file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Empty file.")
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Photo too large — max {MAX_PHOTO_BYTES // (1024 * 1024)}MB",
        )

    declared_type = (file.content_type or "").split(";")[0].strip().lower()
    ext = os.path.splitext(file.filename or "")[1].lower()
    sniffed_type = sniff_image_mime(raw)
    allowed_exts = _PHOTO_TYPES.get(declared_type)
    if (
        allowed_exts is None
        or ext not in allowed_exts
        or sniffed_type not in _PHOTO_SNIFF_OK
        or sniffed_type != declared_type
    ):
        raise HTTPException(
            status_code=422,
            detail="Photo must be a PNG, JPEG, WebP or HEIC file (content-type, extension and contents must all agree).",
        )

    # Strips EXIF/GPS, auto-orients, caps the long edge, re-encodes as JPEG --
    # identical treatment to a medicine photo (P1.7). A profile photo is not
    # a legal record, so overwriting the stored bytes on replace is fine.
    try:
        processed = normalise_image(raw)
    except ImageProcessingError:
        raise HTTPException(status_code=422, detail="Could not process that image. Try a different file.")

    try:
        meta = get_object_store().put(
            BUCKET_STAFF_PHOTOS, photo_key_for_user(user.id), processed.data, mime=processed.mime
        )
    except (OSError, ValueError, ObjectStoreError):
        raise HTTPException(status_code=500, detail="Could not store the photo. Try again.")

    apply_object_meta(user, meta, "photo")
    db.add(user)
    db.commit()
    db.refresh(user)


def photo_response(key: Optional[str], *, sha256: Optional[str], not_found_detail: str) -> Response:
    """Fetch a staff/clinician photo by key (integrity-checked against
    `sha256`) and return it with a nosniff header. Public (no leading
    underscore) -- shared with routers/patients.py::get_clinician_photo,
    same reason save_signature_from_b64 is shared."""
    if not key:
        raise HTTPException(status_code=404, detail=not_found_detail)
    try:
        data = get_object_store().get_checked(BUCKET_STAFF_PHOTOS, key, sha256)
    except (ObjectNotFound, ValueError):
        raise HTTPException(status_code=404, detail=not_found_detail)
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="Photo storage is temporarily unavailable.")
    return Response(
        content=data,
        media_type=PHOTO_MIME,
        headers={"X-Content-Type-Options": "nosniff"},
    )


@router.put("/me/profile")
def update_my_profile(
    payload: schemas.MyProfileUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Set (full-replace) the caller's own bio + internal contact email.
    Never touches the login/auth email -- see schemas.MyProfileUpdate."""
    current_user.bio = payload.bio
    current_user.contact_email = payload.contact_email
    db.add(current_user)
    db.commit()

    log_access(
        db, None, current_user.id, current_user.role, "update_own_profile",
        actor_facility=current_user.facility,
    )
    return {"status": "ok", "bio": current_user.bio, "contact_email": current_user.contact_email}


@router.post("/me/photo")
def upload_my_photo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """Save (overwrite) the caller's own profile photo."""
    _persist_photo(db, current_user, file)

    log_access(
        db, None, current_user.id, current_user.role, "set_profile_photo",
        actor_facility=current_user.facility,
    )
    return {"status": "ok", "has_photo": True}


@router.get("/me/photo")
def get_my_photo(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    return photo_response(
        current_user.photo_object_key,
        sha256=current_user.photo_sha256,
        not_found_detail="No photo saved.",
    )


@router.delete("/me/photo")
def delete_my_photo(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    key = current_user.photo_object_key
    apply_object_meta(current_user, None, "photo")
    db.add(current_user)
    db.commit()
    if key:
        try:
            get_object_store().delete(BUCKET_STAFF_PHOTOS, key)
        except OSError:
            pass

    log_access(
        db, None, current_user.id, current_user.role, "clear_profile_photo",
        actor_facility=current_user.facility,
    )
    return {"status": "ok", "has_photo": False}


@router.get("/staff/{user_id}/photo")
def get_staff_photo(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    """A colleague's saved profile photo. Same facility-scoped, non-leaking-
    404 posture as the rest of this file. Patient-facing
    access to a CLINICIAN's photo (the public-booking use case) is a
    separate, deliberately-broader endpoint:
    GET /patients/clinicians/{id}/photo."""
    if current_user.role == "patient":
        raise HTTPException(status_code=403, detail="Not available for patient accounts.")

    target = db.query(models.User).filter(models.User.id == user_id).first()
    if (
        target is None
        or not current_user.facility
        or target.facility != current_user.facility
        or not target.photo_object_key
    ):
        raise HTTPException(status_code=404, detail="Photo not found.")

    return photo_response(
        target.photo_object_key,
        sha256=target.photo_sha256,
        not_found_detail="Photo not found.",
    )
