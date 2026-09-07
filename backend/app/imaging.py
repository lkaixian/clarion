"""
Image normalisation (P1.7) — CLARION.

Pure functions, no network / DB: bytes in, bytes out. Two callers:

  - ``routers/admin.py`` (medicine photos) — the STORED image is replaced with
    the normalised one. A packaging photo is not a legal record, and a phone
    photo carries EXIF **GPS + device serials** that must not be retained
    (PDPA). Also the tender: "uploaded image files resized to a
    compatible format to reduce storage".
  - ``routers/ai_router.py`` / ``derived.py`` (clinical documents) — the
    original is a legal record and is **never** modified; only a derived
    preview thumbnail is generated with :func:`make_thumbnail`.

Every function that decodes attacker-supplied bytes raises
:class:`ImageProcessingError` (and nothing else) on bad input — a decompression
bomb, a truncated file, a non-image, an unsupported format. Pillow exceptions
never escape.

Hardening (voltagent review, 2026-08-30):
  - ``Image.open(..., formats=_OPEN_FORMATS)`` — the decoder allowlist is
    enforced at parse time, so e.g. the CVE-prone TIFF plugin never runs on
    attacker bytes.
  - ``MAX_INPUT_PIXELS`` (24 MP) is checked on the header dimensions *before*
    any full decode; ``Image.MAX_IMAGE_PIXELS`` is pinned to half that so
    Pillow's own bomb check (which only fires at 2x) lines up.
  - ``_CONCURRENCY`` bounds how many decodes run at once, so a burst of
    uploads / thumbnail misses can't exhaust RAM or the request threadpool.
"""
from __future__ import annotations

import io
import struct
import threading
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

# Decoder allowlist — passed to Image.open(formats=...) so nothing else is even
# parsed. Deliberately NO TIFF (Pillow's most CVE-prone decoder), NO svg, NO
# pdf. A phone MPO (multi-picture JPEG) still opens here via the JPEG plugin —
# its primary image is a valid JPEG.
_OPEN_FORMATS = ["JPEG", "PNG", "GIF", "WEBP", "BMP"]

SUPPORTED_INPUT_MIMES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}
)

DEFAULT_MAX_EDGE = 2500
DEFAULT_QUALITY = 82
DEFAULT_THUMB_SIZE = 300
DEFAULT_THUMB_QUALITY = 80

# Decompression-bomb ceiling. 2500^2 is 6.25 MP; an A3 scan at 300 dpi is ~17 MP,
# a generous phone photo ~24 MP. Anything past this is refused outright — a
# clinic app has no business decoding a 100 MP image, and the transient RGBA +
# resize working set is roughly 12 bytes/pixel.
MAX_INPUT_PIXELS = 24_000_000

# Pillow raises DecompressionBombError only above 2x MAX_IMAGE_PIXELS (below
# that it's a warning), so pin it to half our ceiling to line the two up. The
# explicit w*h check in _open is the real enforcement regardless.
Image.MAX_IMAGE_PIXELS = MAX_INPUT_PIXELS // 2

# Cap concurrent decodes so a burst can't OOM the box or starve the threadpool.
_CONCURRENCY = 4
_decode_gate = threading.Semaphore(_CONCURRENCY)

_ANIMATION_FRAME_LIMIT = 2000

# Everything Pillow can throw from a decode / transform / encode of hostile
# bytes. OSError covers truncation ("image file is truncated") and most plugin
# faults; the rest are TIFF/GIF tag-parser edge cases and struct unpacking.
_DECODE_ERRORS = (
    UnidentifiedImageError,
    Image.DecompressionBombError,
    OSError,
    ValueError,
    SyntaxError,
    EOFError,
    KeyError,
    TypeError,
    struct.error,
)


class ImageProcessingError(Exception):
    """The input bytes are not a decodable supported raster image (bad format,
    truncated, unsupported, or a decompression bomb)."""


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    mime: str  # always "image/jpeg" for now
    width: int
    height: int


# --------------------------------------------------------------------------
# magic-byte sniffing — the single source of truth (was duplicated 3x)
# --------------------------------------------------------------------------
def sniff_image_mime(raw: bytes) -> Optional[str]:
    """The image mime implied by ``raw``'s leading bytes, or ``None``. Cheap —
    does not parse the image. Only returns mimes in :data:`SUPPORTED_INPUT_MIMES`."""
    if len(raw) < 12:
        return None
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw.startswith(b"BM"):
        return "image/bmp"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def is_supported_image(raw: bytes) -> bool:
    """True if ``raw`` sniffs as a format :func:`normalise_image` /
    :func:`make_thumbnail` can decode."""
    return sniff_image_mime(raw) is not None


# --------------------------------------------------------------------------
def _open(raw: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(raw), formats=_OPEN_FORMATS)
        w, h = img.size  # reads the header; raises on a non-image
    except _DECODE_ERRORS as exc:
        raise ImageProcessingError(f"could not decode image: {exc}") from exc
    if w <= 0 or h <= 0 or w * h > MAX_INPUT_PIXELS:
        raise ImageProcessingError(f"image {w}x{h} exceeds the {MAX_INPUT_PIXELS}px limit")
    # Reject a wildly multi-frame animation (APNG / animated GIF/WEBP) before we
    # touch pixel data. We only ever keep frame 0, but even enumerating 100k
    # frames is a DoS. n_frames is not present on static images.
    try:
        if getattr(img, "n_frames", 1) > _ANIMATION_FRAME_LIMIT:
            raise ImageProcessingError("too many frames")
    except _DECODE_ERRORS as exc:
        raise ImageProcessingError(f"could not read frame count: {exc}") from exc
    return img


def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    """Return an RGB image — compositing any alpha onto white, converting any
    other mode. Required before a JPEG encode."""
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "PA", "RGBa", "La") or (
        img.mode == "P" and "transparency" in img.info
    ):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    # P (no transparency), L, 1, CMYK, and 16/32-bit modes (I/I;16/F — rare
    # here; clip to 8-bit, good enough for a preview) all go straight to RGB.
    return img.convert("RGB")


def _finalise(img: Image.Image, *, quality: int) -> ProcessedImage:
    # Nothing from img.info must reach the encoder (EXIF/GPS that exif_transpose
    # stashes back, ICC, XMP, IPTC, Adobe APP markers, ...). The JPEG encoder
    # only writes what we pass in save() kwargs, which is never metadata --
    # clearing info as well is total and not a hand-maintained pop-list.
    img.info.clear()
    try:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
    except _DECODE_ERRORS as exc:
        raise ImageProcessingError(f"could not encode image: {exc}") from exc
    return ProcessedImage(buf.getvalue(), "image/jpeg", img.width, img.height)


def validate_image_safe_to_decode(raw: bytes) -> None:
    """Security Audit M5: a hardened, READ-ONLY validation pass for a
    caller that needs to know "is this safe to hand to an image decoder
    at all" but doesn't want normalise_image's re-encoded-JPEG output --
    e.g. ai_router.digitise_document, which decodes via a SEPARATE
    OCR-specific path (PIL + pytesseract, app/ai/ocr.py) that has none of
    this module's format allowlist / pixel-bomb ceiling / animation-frame
    guard / concurrency gate on its own. Raises ImageProcessingError (never
    returns a value) on anything that fails those same checks
    normalise_image/make_thumbnail already enforce -- callers should treat
    that as "do not proceed to OCR/further processing", not attempt to
    recover the Image object from here (Pillow would just decode it again
    on the caller's own path; this function exists to gate that, not skip
    it)."""
    with _decode_gate:
        _open(raw)


def normalise_image(
    raw: bytes,
    *,
    max_edge: int = DEFAULT_MAX_EDGE,
    quality: int = DEFAULT_QUALITY,
) -> ProcessedImage:
    """Decode ``raw``, bake in EXIF orientation, **strip all metadata**
    (EXIF/GPS, ICC, XMP), downscale so the longer edge is ``<= max_edge``
    (never upscale), flatten transparency onto white, and re-encode as a
    progressive JPEG. Animated inputs keep frame 0 only. Raises
    :class:`ImageProcessingError` on undecodable input or a decompression bomb.
    """
    with _decode_gate:
        img = _open(raw)
        try:
            img = ImageOps.exif_transpose(img)  # applies orientation, drops the tag
            img = _flatten_to_rgb(img)
            w, h = img.size
            longest = max(w, h)
            if longest > max_edge:
                scale = max_edge / longest
                img = img.resize(
                    (max(1, round(w * scale)), max(1, round(h * scale))),
                    Image.Resampling.LANCZOS,
                )
        except _DECODE_ERRORS as exc:
            raise ImageProcessingError(f"could not process image: {exc}") from exc
        return _finalise(img, quality=quality)


def make_thumbnail(
    raw: bytes,
    *,
    size: int = DEFAULT_THUMB_SIZE,
    quality: int = DEFAULT_THUMB_QUALITY,
) -> ProcessedImage:
    """A small preview JPEG: same decode / EXIF / strip / flatten rules as
    :func:`normalise_image`, then fit inside a ``size x size`` box preserving
    aspect ratio (never upscaling). Raises :class:`ImageProcessingError` on bad
    input."""
    with _decode_gate:
        img = _open(raw)
        try:
            img = ImageOps.exif_transpose(img)
            img = _flatten_to_rgb(img)
            img.thumbnail((size, size), Image.Resampling.LANCZOS)  # in-place, never upscales
        except _DECODE_ERRORS as exc:
            raise ImageProcessingError(f"could not process image: {exc}") from exc
        return _finalise(img, quality=quality)
