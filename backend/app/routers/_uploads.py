"""Shared upload helpers (P1.6 hardening).

`enforce_upload_size` rejects an over-cap upload from its declared size
BEFORE the body is pulled into memory with `.read()`. Starlette's multipart
parser has already spooled the whole part (to a temp file past ~1 MB) by the
time an endpoint runs, and `UploadFile.size` is the true byte count at that
point, so this check is cheap and keeps a multi-GB body from being
`.read()`-ed into RAM just to 413 afterwards. Callers still keep their
post-read length check as defence in depth.
"""
import io
import json
import os
import zipfile
from typing import Optional

from fastapi import HTTPException, UploadFile

from ..imaging import sniff_image_mime


def _fmt(max_bytes: int) -> str:
    if max_bytes >= 1024 * 1024:
        return f"{max_bytes // (1024 * 1024)}MB"
    return f"{max_bytes // 1024}KB"


def enforce_upload_size(file: UploadFile, max_bytes: int, what: str = "File") -> None:
    size: Optional[int] = getattr(file, "size", None)
    if size is not None and size > max_bytes:
        raise HTTPException(status_code=413, detail=f"{what} too large — max {_fmt(max_bytes)}.")


def sniff_document_mime(raw: bytes) -> str:
    """Derive the stored mime for an uploaded clinical document SERVER-SIDE,
    from the file's own magic bytes — never the client's Content-Type header.
    Raster images go through the single sniffer in :mod:`app.imaging`; PDF is
    the one non-image type this path also recognises. Anything else is stored
    (and later served) as ``application/octet-stream`` — download-only.

    Defence in depth only: the serve path re-guesses the type from the object
    key against a strict allowlist and never trusts this value for a header."""
    if raw.startswith(b"%PDF-"):
        return "application/pdf"
    return sniff_image_mime(raw) or "application/octet-stream"


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"}
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_MAX_DOCX_UNZIPPED = 50 * 1024 * 1024
RESULT_FILE_HELP = "PDF, image (PNG/JPEG/WebP/HEIC), TXT, JSON, DOCX, DICOM (.dcm) or HL7 (.hl7)"


def _clean_docx(raw: bytes) -> bool:
    """A real, macro-free .docx: a zip holding word/document.xml, no VBA
    project, no embedded OLE objects, and a sane DECLARED size. The declared
    size comes from the zip's own directory and a hostile file can understate
    it: the server never extracts, so this protects nothing server-side and is
    only a courtesy check for staff who later open the file in Word."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            names = z.namelist()
            if "word/document.xml" not in names or "[Content_Types].xml" not in names:
                return False
            if any(n.startswith(("word/vbaProject", "word/embeddings/")) for n in names):
                return False
            return sum(i.file_size for i in z.infolist()) <= _MAX_DOCX_UNZIPPED
    except zipfile.BadZipFile:
        return False


def sniff_result_file(raw: bytes, filename: Optional[str]) -> str:
    """Stored mime for a result attachment, decided SERVER-SIDE: the
    extension picks the expected type and the file's own bytes must agree.
    Legacy .doc / macro formats / executables are refused on purpose."""
    ext = os.path.splitext(filename or "")[1].lower()
    mime: Optional[str] = None
    if ext == ".pdf" and raw.startswith(b"%PDF-"):
        mime = "application/pdf"
    elif ext in _IMAGE_EXTS:
        mime = sniff_image_mime(raw)
    elif ext == ".txt" and b"\x00" not in raw:
        try:
            raw.decode("utf-8")
            mime = "text/plain"
        except UnicodeDecodeError:
            pass
    elif ext == ".json":
        try:
            json.loads(raw.decode("utf-8"))
            mime = "application/json"
        except ValueError:
            pass
    elif ext == ".docx" and _clean_docx(raw):
        mime = _DOCX_MIME
    elif ext == ".dcm" and raw[128:132] == b"DICM":
        mime = "application/dicom"
    elif ext == ".hl7" and raw.lstrip(b"\x0b").startswith(b"MSH|"):
        mime = "application/hl7-v2"
    if mime is None:
        hint = " Save older Word files as .docx or PDF." if ext in (".doc", ".docm", ".rtf") else ""
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported or invalid file. Allowed: {RESULT_FILE_HELP}.{hint}",
        )
    return mime
