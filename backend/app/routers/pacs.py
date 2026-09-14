"""
PACS / DICOM imaging (P4.7, the tender -- integrated PACS with
a secure zoom/measure viewer). Sits ON TOP of the existing X-ray ancillary
module (app/routers/ancillary.py): a DicomStudy is uploaded against an
already-placed `ServiceRequest(module="xray")`, so every scoping/RBAC rule
that module already enforces (facility ownership, cross-facility
continuity-of-care read, SIGNOFF_ROLES-only clinical access) is reused
directly rather than re-derived here -- see `ancillary._request_or_404`'s
own docstring for the subtle immutability semantics this reuse inherits for
free.

The actual DICOM storage/streaming lives in Orthanc (app/pacs.py's client);
this router is the auth boundary in front of it (see that module's
docstring for why Orthanc itself has no per-user auth in this deploy).

No real modality/Modality-Worklist hardware -- studies are uploaded by
staff as a single .dcm file or a .zip of one study's instances, gated to
the same SIGNOFF_ROLES as a result sign-off (a receptionist orders an
X-ray but is not a clinical reader, same line ancillary.py already draws).
"""
from __future__ import annotations

import io
import zipfile
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models, schemas, auth, pacs
from ..database import get_db
from ..audit import log_access
from ..clinical_access import _hidden_author_facilities
from ._uploads import enforce_upload_size
from .ancillary import SIGNOFF_ROLES, _request_or_404

router = APIRouter(prefix="/pacs", tags=["pacs"])

# A single chest CR/DX instance is a few MB uncompressed; a whole study
# (multiple views) comfortably fits under this. Generous on purpose -- a
# rejected upload here is a bigger clinical problem than a rejected PDF.
MAX_DICOM_UPLOAD_BYTES = 80 * 1024 * 1024
MAX_ZIP_MEMBERS = 200
_DICM_MAGIC = b"DICM"
_DICM_OFFSET = 128


def _looks_like_dicom(raw: bytes) -> bool:
    return len(raw) > _DICM_OFFSET + 4 and raw[_DICM_OFFSET:_DICM_OFFSET + 4] == _DICM_MAGIC


_ZIP_READ_CHUNK = 1024 * 1024  # 1MB


def _read_zip_member_bounded(zf: zipfile.ZipFile, info: zipfile.ZipInfo, remaining_budget: int) -> bytes:
    """Reads one member in bounded chunks, trusting only the bytes actually
    decompressed -- NEVER `ZipInfo.file_size`. That field comes straight
    from the archive's central directory, which a hand-crafted (not
    zipfile-written) zip fully controls; CPython's zipfile only cross-checks
    it against the real output size AFTER fully decompressing, so trusting
    it as a pre-check (the original version of this function did) lets a
    single member with a forged small `file_size` and a real multi-GB
    deflate stream sail past the size guard and exhaust memory. Aborts the
    moment `remaining_budget` (the whole archive's shared, running budget)
    would be exceeded, so total in-memory growth is capped regardless of
    what any header claims."""
    chunks = []
    read = 0
    with zf.open(info) as member:
        while True:
            chunk = member.read(_ZIP_READ_CHUNK)
            if not chunk:
                break
            read += len(chunk)
            if read > remaining_budget:
                raise HTTPException(
                    status_code=413,
                    detail=f"Archive too large uncompressed — max {MAX_DICOM_UPLOAD_BYTES // (1024 * 1024)}MB.",
                )
            chunks.append(chunk)
    return b"".join(chunks)


def _extract_dicom_members(raw: bytes) -> List[bytes]:
    """`raw` is either one DICOM Part10 file or a .zip of several. Returns
    the list of member byte-strings that actually look like DICOM (skips
    anything else in the zip -- a DICOMDIR index, a README -- rather than
    forwarding it to Orthanc, which would just reject it).

    CPU-bound (decompression) -- callers run this via run_in_threadpool,
    same as every blocking call in this router, so a slow/hostile archive
    can't stall the event loop for other requests."""
    if not raw.startswith(b"PK\x03\x04"):
        if not _looks_like_dicom(raw):
            raise HTTPException(status_code=422, detail="Not a valid DICOM file (or a .zip of one study).")
        return [raw]

    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            infos = [i for i in zf.infolist() if not i.is_dir()]
            if len(infos) > MAX_ZIP_MEMBERS:
                raise HTTPException(status_code=413, detail=f"Too many files in archive — max {MAX_ZIP_MEMBERS}.")
            members = []
            budget = MAX_DICOM_UPLOAD_BYTES
            for info in infos:
                data = _read_zip_member_bounded(zf, info, budget)
                budget -= len(data)
                members.append(data)
    except zipfile.BadZipFile:
        raise HTTPException(status_code=422, detail="Not a valid DICOM file or .zip archive.")

    dicom_members = [m for m in members if _looks_like_dicom(m)]
    if not dicom_members:
        raise HTTPException(status_code=422, detail="Archive contained no valid DICOM files.")
    return dicom_members


def _study_or_404(db: Session, request_id: str, current_user: models.User) -> tuple[models.ServiceRequest, models.DicomStudy]:
    """Same cross-facility continuity-of-care read as
    ancillary.py::get_result_document: own facility always visible; another
    facility's only if it hasn't opted out via records_shared_publicly."""
    req = _request_or_404(db, request_id, current_user, require_same_facility=False)
    if req.ordering_facility_name != current_user.facility:
        if req.ordering_facility_name in _hidden_author_facilities(db, current_user.facility):
            raise HTTPException(status_code=404, detail="No imaging study available")
    if req.dicom_study is None:
        raise HTTPException(status_code=404, detail="No imaging study available")
    return req, req.dicom_study


def _serialize_study(study: models.DicomStudy) -> schemas.DicomStudyOut:
    return schemas.DicomStudyOut(
        id=study.id, service_request_id=study.service_request_id, description=study.description,
        instances=study.orthanc_instance_ids or [], uploaded_by_name=study.uploaded_by_name,
        uploaded_at=study.uploaded_at,
    )


@router.post("/requests/{request_id}/study", response_model=schemas.DicomStudyOut, status_code=201)
async def upload_study(
    request_id: str,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.require_roles(*SIGNOFF_ROLES)),
):
    req = _request_or_404(db, request_id, current_user, require_same_facility=True)
    if req.module != "xray":
        raise HTTPException(status_code=400, detail="Imaging studies are only for X-ray requests.")
    if req.status == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot attach imaging to a cancelled request.")
    if req.dicom_study is not None:
        raise HTTPException(status_code=409, detail="An imaging study is already attached to this request.")

    enforce_upload_size(file, MAX_DICOM_UPLOAD_BYTES, "File")
    raw = await file.read()
    if len(raw) > MAX_DICOM_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large — max {MAX_DICOM_UPLOAD_BYTES // (1024 * 1024)}MB")

    members = await run_in_threadpool(_extract_dicom_members, raw)

    def _upload_all() -> tuple[List[str], str, str]:
        # Blocking network I/O (httpx, sync) -- run off the event loop, same
        # as every other Orthanc/object-store call in this codebase.
        instance_ids: List[str] = []
        orthanc_study_id = ""
        for member in members:
            result = pacs.upload_instance(member)
            instance_ids.append(result["ID"])
            orthanc_study_id = result.get("ParentStudy", orthanc_study_id)
        description = None
        if orthanc_study_id:
            try:
                info = pacs.get_study(orthanc_study_id)
                description = (info.get("MainDicomTags") or {}).get("StudyDescription")
            except pacs.PacsError:
                pass  # cosmetic only -- the study is already stored either way
        return instance_ids, orthanc_study_id, description

    try:
        instance_ids, orthanc_study_id, description = await run_in_threadpool(_upload_all)
    except pacs.PacsError:
        raise HTTPException(status_code=503, detail="Imaging storage is temporarily unavailable.")
    if not orthanc_study_id:
        raise HTTPException(status_code=502, detail="Imaging storage did not return a study reference.")

    study = models.DicomStudy(
        service_request_id=req.id, patient_id=req.patient_id, facility_name=req.ordering_facility_name,
        orthanc_study_id=orthanc_study_id, orthanc_instance_ids=instance_ids, description=description,
        uploaded_by=current_user.id, uploaded_by_name=current_user.full_name,
    )
    db.add(study)
    db.commit()
    db.refresh(study)

    log_access(
        db, req.patient_id, current_user.id, current_user.role, "dicom_study_uploaded",
        detail=f"request_id={req.id} instances={len(instance_ids)}", actor_facility=current_user.facility,
    )
    return _serialize_study(study)


@router.get("/requests/{request_id}/study", response_model=schemas.DicomStudyOut)
def get_study(
    request_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*SIGNOFF_ROLES)),
):
    req, study = _study_or_404(db, request_id, current_user)
    log_access(
        db, req.patient_id, current_user.id, current_user.role, "view_dicom_study",
        detail=f"request_id={req.id}", actor_facility=current_user.facility,
    )
    return _serialize_study(study)


@router.get("/requests/{request_id}/study/instances/{instance_id}/file")
def get_study_instance_file(
    request_id: str,
    instance_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_roles(*SIGNOFF_ROLES)),
):
    """Streams one raw DICOM Part10 file -- the viewer (web/src/components
    DicomViewer) fetches every instance of a study this way and hands each
    blob to dwv. `instance_id` is checked against the study's OWN stored
    instance-id list, never passed through to Orthanc unchecked -- see
    models.DicomStudy's docstring."""
    _req, study = _study_or_404(db, request_id, current_user)
    if instance_id not in (study.orthanc_instance_ids or []):
        raise HTTPException(status_code=404, detail="Instance not found in this study")

    try:
        raw = pacs.get_instance_file(instance_id)
    except pacs.PacsError:
        raise HTTPException(status_code=503, detail="Imaging storage is temporarily unavailable.")

    return Response(content=raw, media_type="application/dicom")
