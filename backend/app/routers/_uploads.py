"""Shared upload helpers (P1.6 hardening).

`enforce_upload_size` rejects an over-cap upload from its declared size
BEFORE the body is pulled into memory with `.read()`. Starlette's multipart
parser has already spooled the whole part (to a temp file past ~1 MB) by the
time an endpoint runs, and `UploadFile.size` is the true byte count at that
point, so this check is cheap and keeps a multi-GB body from being
`.read()`-ed into RAM just to 413 afterwards. Callers still keep their
post-read length check as defence in depth.
"""
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
