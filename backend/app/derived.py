"""P1.7 — derived image assets (thumbnails / previews).

A *derived* asset is a downscaled JPEG generated from an original blob for
cheap display. Derived assets:

  - live in the ``clarion-derived`` bucket,
  - are NEVER the source of truth — the originals in ``clarion-documents`` /
    ``clarion-medicine`` are,
  - are regenerated on demand when missing.

So ``clarion-derived`` can carry an aggressive lifecycle policy (180-day
expiry, excluded from backup — provisioned as a MinIO ILM rule, see
``docs/deployment.md``) without data loss: a request for an expired thumbnail
just rebuilds it from the original.

**Key scheme** (deterministic — no DB column needed):

    {variant}/{source_bucket}/{source_key}.{sha8}.jpg

The source object's sha256 (already persisted on the row as ``*_sha256``) is
folded in, so replacing the original at the *same* object key (a phone
re-upload of ``image.jpg``) produces a *new* derived key — the stale thumbnail
is never served, and it just expires under ILM. ``source_key`` is spliced in
verbatim; its ``/`` separators become real path segments, each already
validated when the original was stored and re-checked by
:func:`app.storage.validate_key` on every put/get.

A definitive negative result (source is neither a decodable raster image nor
a renderable PDF) is itself cached as a zero-byte marker so a loop on the
thumbnail endpoint can't force repeated full-original reads.
"""
import logging

from .imaging import (
    ImageProcessingError,
    is_pdf,
    is_supported_image,
    make_thumbnail,
    render_pdf_first_page,
)
from .storage import (
    BUCKET_DERIVED,
    ObjectNotFound,
    ObjectStoreError,
    get_object_store,
)

logger = logging.getLogger("clarion.derived")

# 300 = list/table thumbnails; 1400 = the "web preview" (P1.7b) -- big enough
# to actually read a document without pulling the full, possibly 15MB, original.
# Public (no underscore): routers validate a requested ?size against this
# directly rather than keeping their own copy, so the two can't drift --
# a size dropped here without a matching router update would otherwise
# surface as an unhandled 500 (_variant's ValueError, uncaught below) instead
# of a clean 422 (voltagent review, 2026-09-15).
ALLOWED_THUMBNAIL_SIZES = (300, 1400)
_NEG_MARKER = b""  # zero-byte sentinel for "no preview possible"


def _variant(size: int) -> str:
    if size not in ALLOWED_THUMBNAIL_SIZES:
        raise ValueError(f"unsupported thumbnail size {size}")
    return f"thumb{size}"


def _sha8(sha256: "str | None") -> str:
    return (sha256 or "nosha")[:12]


def derived_key(source_bucket: str, source_key: str, *, variant: str, sha256: "str | None") -> str:
    return f"{variant}/{source_bucket}/{source_key}.{_sha8(sha256)}.jpg"


def _neg_key(pos_key: str) -> str:
    return pos_key + ".none"


def get_or_make_thumbnail(
    source_bucket: str, source_key: str, *, size: int = 300, sha256: "str | None" = None
) -> "bytes | None":
    """Thumbnail JPEG bytes for ``source_bucket/source_key`` — served from
    ``clarion-derived`` on a hit, regenerated + cached there on a miss.
    Returns ``None`` if the source is missing or is not a decodable raster
    image (e.g. a PDF). Raises :class:`ObjectStoreError` if the object store
    itself is unavailable, so the caller can distinguish "no preview" (404)
    from "storage down" (503)."""
    store = get_object_store()
    variant = _variant(size)
    dkey = derived_key(source_bucket, source_key, variant=variant, sha256=sha256)
    nkey = _neg_key(dkey)

    try:
        return store.get(BUCKET_DERIVED, dkey)
    except ObjectNotFound:
        pass
    except ValueError:
        return None
    # ObjectStoreError propagates.

    try:
        if store.exists(BUCKET_DERIVED, nkey):
            return None
    except ObjectStoreError:
        pass  # fall through and try to build

    try:
        original = store.get_checked(source_bucket, source_key, sha256)
    except (ObjectNotFound, ValueError):
        return None
    # ObjectStoreError (incl. an integrity mismatch) propagates.

    if is_supported_image(original):
        try:
            thumb = make_thumbnail(original, size=size)
        except ImageProcessingError:
            _cache_negative(store, nkey)
            return None
    elif is_pdf(original):
        # P1.7b: a PDF gets a rendered-page-1 preview instead of "no preview".
        try:
            thumb = render_pdf_first_page(original, max_edge=size)
        except ImageProcessingError:
            _cache_negative(store, nkey)
            return None
    else:
        _cache_negative(store, nkey)
        return None

    try:
        store.put(BUCKET_DERIVED, dkey, thumb.data, mime=thumb.mime)
    except (OSError, ObjectStoreError, ValueError) as exc:
        logger.warning("could not cache thumbnail %s: %s", dkey, exc)
    return thumb.data


def _cache_negative(store, nkey: str) -> None:
    try:
        store.put(BUCKET_DERIVED, nkey, _NEG_MARKER, mime="application/octet-stream")
    except (OSError, ObjectStoreError, ValueError):
        pass


def prime_thumbnail(source_bucket: str, source_key: str, sha256: "str | None" = None) -> None:
    """Best-effort proactive generation at upload time. Never raises — an
    upload must not fail because a thumbnail couldn't be built."""
    try:
        get_or_make_thumbnail(source_bucket, source_key, sha256=sha256)
    except Exception as exc:  # noqa: BLE001 - deliberately swallow everything
        logger.info("prime_thumbnail(%s/%s) failed: %s", source_bucket, source_key, exc)
