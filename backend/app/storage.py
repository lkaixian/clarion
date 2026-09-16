"""
ObjectStore abstraction (P1.6) — CLARION on-prem object storage.

Every binary blob the app persists — clinical-document originals, staff
signatures and their per-record snapshots, medicine photos, transient
OCR/NRIC scratch images — goes through an ObjectStore rather than touching
the filesystem directly. Two implementations:

  - ``LocalObjectStore`` — a plain directory tree (``{root}/{bucket}/{key}``).
    The default; the SQLite demo needs nothing else. NO WORM, NO versioning —
    ``put`` overwrites and ``delete`` removes. Fine for the demo, not for a
    regulated deployment.
  - ``MinioObjectStore`` — an S3-API MinIO server (the on-prem target from
    ``healthcare/On-Prem Architecture.md``).

**Retention / WORM status (be precise for an assessor):** the tender's
"documents WORM 7 yr" requirement is met by **bucket policy provisioned at
deploy time**, not by this module. On the MinIO target, run
``backend/db/minio/provision.sh`` (or the ``mc`` commands in
``docs/deployment.md``) to create the ``clarion-documents`` /
``clarion-signatures`` / ``clarion-dicom`` / ``clarion-reports-archive``
buckets with **object-lock enabled + COMPLIANCE default retention +
versioning**. When a bucket is lock-enabled, ``MinioObjectStore.put`` then
also stamps a per-object COMPLIANCE retention date (best-effort). Until that
provisioning is done — and always on ``LocalObjectStore`` — blobs are
rewritable and deletable. ``docs/deployment.md`` tracks this as a hard
go-live gate.

Backend and connection are env-driven — see :func:`get_object_store`.
Callers use the module-level ``BUCKET_*`` constants, never raw strings, and
build keys with :func:`sanitize_filename` for any client-influenced segment.

Portability (the mandated CI4 port): the bucket layout and key scheme are
the contract. A PHP rewrite re-implements this file against the same MinIO
buckets and the same ``*_object_key`` column values — nothing else changes.
"""
from __future__ import annotations

import abc
import hashlib
import io
import logging
import os
import re
import uuid
from dataclasses import dataclass

logger = logging.getLogger("clarion.storage")
from pathlib import Path
from typing import Iterator, Optional

# --------------------------------------------------------------------------
# Buckets  (see healthcare/On-Prem Architecture.md "Object / image / DICOM")
# --------------------------------------------------------------------------
BUCKET_DOCUMENTS = "clarion-documents"          # clinical-document originals
BUCKET_SIGNATURES = "clarion-signatures"        # staff signatures + per-record snapshots
BUCKET_MEDICINE = "clarion-medicine"            # medicine photos
BUCKET_STAFF_PHOTOS = "clarion-staff-photos"    # staff profile photos
BUCKET_DERIVED = "clarion-derived"              # thumbnails / normalised images (P1.7) — no backup
BUCKET_SCRATCH = "clarion-scratch"              # OCR / NRIC photos — 7-day expiry
BUCKET_DICOM = "clarion-dicom"                  # PACS objects (P4.7)
BUCKET_REPORTS = "clarion-reports-archive"      # sealed report/audit exports

ALL_BUCKETS = (
    BUCKET_DOCUMENTS,
    BUCKET_SIGNATURES,
    BUCKET_MEDICINE,
    BUCKET_STAFF_PHOTOS,
    BUCKET_DERIVED,
    BUCKET_SCRATCH,
    BUCKET_DICOM,
    BUCKET_REPORTS,
)

# Buckets that a real deployment provisions with object-lock + COMPLIANCE
# retention + versioning (see the module docstring). On such a bucket
# MinioObjectStore.put stamps a per-object retention date; elsewhere this set
# just documents intent.
WORM_BUCKETS = frozenset({BUCKET_DOCUMENTS, BUCKET_SIGNATURES, BUCKET_DICOM, BUCKET_REPORTS})
WORM_RETENTION_YEARS = 7

# A key is "<segment>/<segment>/..." — forward slashes only, each segment a
# conservative filename. Anything a client can influence must be run through
# sanitize_filename() first; this is the last line of defence.
_MAX_KEY_LEN = 512
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ObjectStoreError(RuntimeError):
    """Base class for object-store failures."""


class ObjectNotFound(ObjectStoreError, KeyError):
    """Raised by ``get`` / ``open_stream`` when the key does not exist."""


class ObjectIntegrityError(ObjectStoreError):
    """Raised by :meth:`ObjectStore.get_checked` when the bytes served back do
    not match the sha256 recorded at write time."""


_NOT_FOUND_CODES = ("NoSuchKey", "NoSuchObject", "NoSuchBucket")


@dataclass(frozen=True)
class ObjectMeta:
    """What a caller records about a stored object.

    ``key`` + ``bucket`` locate it; ``sha256`` / ``size`` / ``mime`` are
    persisted next to the ``*_object_key`` column for integrity checks and
    to serve the right ``Content-Type`` without sniffing.
    """

    key: str
    bucket: str
    sha256: str
    size: int
    mime: str


def apply_object_meta(obj, meta: Optional[ObjectMeta], prefix: str) -> None:
    """Copy an :class:`ObjectMeta` onto an ORM row's
    ``{prefix}_object_key`` / ``{prefix}_sha256`` / ``{prefix}_bytes`` /
    ``{prefix}_mime`` columns (P1.6). ``meta=None`` clears all four."""
    setattr(obj, f"{prefix}_object_key", meta.key if meta else None)
    setattr(obj, f"{prefix}_sha256", meta.sha256 if meta else None)
    setattr(obj, f"{prefix}_bytes", meta.size if meta else None)
    setattr(obj, f"{prefix}_mime", meta.mime if meta else None)


def _check_bucket(bucket: str) -> None:
    if bucket not in ALL_BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}")


def validate_key(key: str) -> str:
    """Return ``key`` unchanged if it is a safe relative object key, else
    raise ``ValueError``. Rejects absolute paths, ``..`` / ``.`` segments,
    backslashes, NUL, empty segments, leading/trailing slashes and anything
    outside ``[A-Za-z0-9._-]`` per segment."""
    if not isinstance(key, str) or not key:
        raise ValueError("empty object key")
    if len(key) > _MAX_KEY_LEN:
        raise ValueError("object key too long")
    if "\\" in key or "\x00" in key:
        raise ValueError(f"illegal character in object key {key!r}")
    if key.startswith("/") or key.endswith("/"):
        raise ValueError(f"object key must not start or end with '/': {key!r}")
    segments = key.split("/")
    for seg in segments:
        if not _SEGMENT_RE.match(seg):
            raise ValueError(f"illegal object-key segment {seg!r} in {key!r}")
    return key


_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_filename(name: Optional[str], *, fallback: str = "file") -> str:
    """Collapse an arbitrary client-supplied filename to a single safe key
    segment: strip any directory part, replace runs of unsafe characters
    with ``_``, trim leading dots/dashes, cap length. Never returns ''."""
    base = os.path.basename((name or "").strip().replace("\\", "/").split("/")[-1])
    base = _UNSAFE_NAME_RE.sub("_", base).lstrip("._-")
    if len(base) > 200:
        root, ext = os.path.splitext(base)
        base = root[: 200 - len(ext)] + ext
    return base or fallback


class ObjectStore(abc.ABC):
    """Minimal S3-shaped interface the app depends on."""

    @abc.abstractmethod
    def put(self, bucket: str, key: str, data: bytes, *, mime: str) -> ObjectMeta:
        """Store ``data`` at ``bucket/key`` (overwriting any existing object)
        and return its :class:`ObjectMeta`."""

    @abc.abstractmethod
    def get(self, bucket: str, key: str) -> bytes:
        """Return the whole object. Raises :class:`ObjectNotFound`."""

    def get_checked(self, bucket: str, key: str, expected_sha256: Optional[str]) -> bytes:
        """:meth:`get` plus an integrity check against ``expected_sha256``
        (the value recorded on the row at write time). Raises
        :class:`ObjectIntegrityError` on a mismatch — use for the small blobs
        (signatures, medicine photos) where reading the whole object is cheap
        anyway. ``expected_sha256`` falsy ⇒ no check (legacy rows)."""
        data = self.get(bucket, key)
        if expected_sha256:
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected_sha256:
                logger.error(
                    "object integrity failure %s/%s: expected sha256 %s, got %s",
                    bucket, key, expected_sha256, actual,
                )
                raise ObjectIntegrityError(f"sha256 mismatch for {bucket}/{key}")
        return data

    @abc.abstractmethod
    def open_stream(self, bucket: str, key: str, chunk_size: int = 65536) -> Iterator[bytes]:
        """Yield the object in chunks. Raises :class:`ObjectNotFound`."""

    @abc.abstractmethod
    def exists(self, bucket: str, key: str) -> bool:
        ...

    @abc.abstractmethod
    def delete(self, bucket: str, key: str) -> None:
        """Remove the object. Idempotent — a missing key is not an error."""

    def presign_get(self, bucket: str, key: str, expires_seconds: int = 300) -> Optional[str]:
        """A time-limited GET URL, or ``None`` if the backend can't issue one
        (the local store can't). Clinical blobs are currently always served
        through an authenticated app endpoint, so this stays unused for now."""
        return None

    def set_retention(self, bucket: str, key: str, retain_until) -> None:
        """Apply an object-lock retain-until date (WORM). No-op where the
        backend has no object lock (the local store)."""
        return None


class _ClosingIterator:
    """A byte iterator that owns a resource and releases it on exhaustion,
    ``.close()``, or GC. Used for ``open_stream`` so a stream that is created
    but never consumed (e.g. an error between building it and returning the
    response) still frees its file handle / HTTP connection. Starlette's
    ``StreamingResponse`` calls ``.close()`` on the iterator it is given."""

    def __init__(self, chunks: Iterator[bytes], closer):
        self._chunks = chunks
        self._closer = closer
        self._closed = False

    def __iter__(self) -> "_ClosingIterator":
        return self

    def __next__(self) -> bytes:
        try:
            return next(self._chunks)
        except StopIteration:
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._closer()

    def __del__(self):
        self.close()


# --------------------------------------------------------------------------
# Local filesystem implementation
# --------------------------------------------------------------------------
class LocalObjectStore(ObjectStore):
    def __init__(self, root: os.PathLike | str):
        self.root = Path(root).resolve()

    def _bucket_dir(self, bucket: str) -> Path:
        _check_bucket(bucket)
        return self.root / bucket

    def _path(self, bucket: str, key: str) -> Path:
        validate_key(key)
        base = self._bucket_dir(bucket).resolve()
        resolved = (base / key).resolve()
        # Defence in depth: validate_key already forbids traversal, but confirm
        # the resolved path is still inside the bucket dir (symlinks, odd FS).
        if resolved != base and base not in resolved.parents:
            raise ValueError(f"resolved path escapes bucket: {key!r}")
        return resolved

    def put(self, bucket: str, key: str, data: bytes, *, mime: str) -> ObjectMeta:
        dest = self._path(bucket, key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.parent / f".{dest.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}"
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, dest)  # atomic within a filesystem
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
        return ObjectMeta(
            key=key,
            bucket=bucket,
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            mime=mime,
        )

    def get(self, bucket: str, key: str) -> bytes:
        try:
            return self._path(bucket, key).read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFound(f"{bucket}/{key}") from exc

    def open_stream(self, bucket: str, key: str, chunk_size: int = 65536) -> _ClosingIterator:
        path = self._path(bucket, key)
        try:
            fh = open(path, "rb")
        except FileNotFoundError as exc:
            raise ObjectNotFound(f"{bucket}/{key}") from exc

        def _chunks() -> Iterator[bytes]:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                yield chunk

        return _ClosingIterator(_chunks(), fh.close)

    def exists(self, bucket: str, key: str) -> bool:
        try:
            return self._path(bucket, key).is_file()
        except ValueError:
            return False

    def delete(self, bucket: str, key: str) -> None:
        try:
            self._path(bucket, key).unlink()
        except (FileNotFoundError, ValueError):
            pass


# --------------------------------------------------------------------------
# MinIO / S3 implementation
# --------------------------------------------------------------------------
class MinioObjectStore(ObjectStore):
    """Wraps a ``minio.Minio`` client. Import of :mod:`minio` is deferred to
    :func:`get_object_store` so the SQLite/local demo never needs the package
    at runtime even though it is in requirements.txt.

    Every ``minio.error.S3Error`` other than a not-found is re-raised as
    :class:`ObjectStoreError` so callers can catch one exception type across
    both backends (``OSError`` alone misses S3 failures)."""

    def __init__(self, client, *, ensure_buckets: bool = True):
        self._client = client
        # Which existing buckets have object-lock on — checked once so `put`
        # can decide whether to stamp per-object retention.
        self._lock_enabled: set[str] = set()
        if ensure_buckets:
            self._ensure_buckets()

    # -- bucket bootstrap -------------------------------------------------
    def _ensure_buckets(self) -> None:
        from minio.error import S3Error

        for bucket in ALL_BUCKETS:
            want_lock = bucket in WORM_BUCKETS
            if not self._client.bucket_exists(bucket):
                # object_lock can only be set at creation; a real deployment
                # provisions these out-of-band, this is a dev/demo fallback.
                self._client.make_bucket(bucket, object_lock=want_lock)
            try:
                self._client.set_bucket_versioning(bucket, _versioning_enabled())
            except S3Error:
                pass  # versioning unsupported / not permitted — non-fatal
            if want_lock and self._object_lock_on(bucket):
                self._lock_enabled.add(bucket)

    def _object_lock_on(self, bucket: str) -> bool:
        from minio.error import S3Error

        try:
            self._client.get_object_lock_config(bucket)
            return True
        except S3Error:
            return False

    # -- error wrapping -------------------------------------------------
    @staticmethod
    def _wrap(bucket: str, key: str, exc) -> "ObjectStoreError":
        code = getattr(exc, "code", "")
        if code in _NOT_FOUND_CODES:
            return ObjectNotFound(f"{bucket}/{key}")
        return ObjectStoreError(f"object store error on {bucket}/{key}: {code or exc}")

    # -- writes --------------------------------------------------------
    def put(self, bucket: str, key: str, data: bytes, *, mime: str) -> ObjectMeta:
        from minio.error import S3Error

        _check_bucket(bucket)
        validate_key(key)
        try:
            self._client.put_object(
                bucket, key, io.BytesIO(data), length=len(data),
                content_type=mime or "application/octet-stream",
            )
            if bucket in self._lock_enabled:
                self._stamp_retention(bucket, key)
        except S3Error as exc:
            raise self._wrap(bucket, key, exc) from exc
        return ObjectMeta(
            key=key, bucket=bucket,
            sha256=hashlib.sha256(data).hexdigest(), size=len(data), mime=mime,
        )

    def _stamp_retention(self, bucket: str, key: str) -> None:
        from datetime import datetime, timedelta, timezone
        from minio.commonconfig import COMPLIANCE
        from minio.error import S3Error
        from minio.retention import Retention

        until = datetime.now(timezone.utc) + timedelta(days=365 * WORM_RETENTION_YEARS)
        try:
            self._client.set_object_retention(bucket, key, Retention(COMPLIANCE, until))
        except S3Error:
            pass  # best-effort — the bucket default retention still applies

    def set_retention(self, bucket: str, key: str, retain_until) -> None:
        from minio.commonconfig import COMPLIANCE
        from minio.error import S3Error
        from minio.retention import Retention

        _check_bucket(bucket)
        validate_key(key)
        try:
            self._client.set_object_retention(bucket, key, Retention(COMPLIANCE, retain_until))
        except S3Error as exc:
            raise self._wrap(bucket, key, exc) from exc

    # -- reads --------------------------------------------------------
    def _get_response(self, bucket: str, key: str):
        from minio.error import S3Error

        _check_bucket(bucket)
        validate_key(key)
        try:
            return self._client.get_object(bucket, key)
        except S3Error as exc:
            raise self._wrap(bucket, key, exc) from exc

    def get(self, bucket: str, key: str) -> bytes:
        resp = self._get_response(bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def open_stream(self, bucket: str, key: str, chunk_size: int = 65536) -> _ClosingIterator:
        resp = self._get_response(bucket, key)

        def _close() -> None:
            resp.close()
            resp.release_conn()

        return _ClosingIterator(iter(resp.stream(chunk_size)), _close)

    def exists(self, bucket: str, key: str) -> bool:
        from minio.error import S3Error

        _check_bucket(bucket)
        try:
            validate_key(key)
        except ValueError:
            return False
        try:
            self._client.stat_object(bucket, key)
            return True
        except S3Error as exc:
            if getattr(exc, "code", "") in _NOT_FOUND_CODES:
                return False
            raise self._wrap(bucket, key, exc) from exc

    def delete(self, bucket: str, key: str) -> None:
        from minio.error import S3Error

        _check_bucket(bucket)
        try:
            validate_key(key)
        except ValueError:
            return
        try:
            self._client.remove_object(bucket, key)
        except S3Error as exc:
            if getattr(exc, "code", "") not in _NOT_FOUND_CODES:
                raise self._wrap(bucket, key, exc) from exc

    def presign_get(self, bucket: str, key: str, expires_seconds: int = 300) -> Optional[str]:
        from datetime import timedelta
        from minio.error import S3Error

        _check_bucket(bucket)
        validate_key(key)
        try:
            return self._client.presigned_get_object(
                bucket, key, expires=timedelta(seconds=expires_seconds)
            )
        except S3Error as exc:
            raise self._wrap(bucket, key, exc) from exc


def _versioning_enabled():
    from minio.versioningconfig import VersioningConfig, ENABLED

    return VersioningConfig(ENABLED)


# --------------------------------------------------------------------------
# Factory
# --------------------------------------------------------------------------
_DEFAULT_LOCAL_ROOT = Path(__file__).resolve().parent.parent / "object_store"

_store: Optional[ObjectStore] = None


def _truthy(value: Optional[str]) -> bool:
    return (value or "").strip().lower() not in ("", "0", "false", "no", "off")


def _build_object_store() -> ObjectStore:
    backend = (os.environ.get("CLARION_STORAGE_BACKEND") or "local").strip().lower()

    if backend in ("local", "filesystem", "fs"):
        root = os.environ.get("CLARION_STORAGE_ROOT") or str(_DEFAULT_LOCAL_ROOT)
        return LocalObjectStore(root)

    if backend in ("minio", "s3"):
        from minio import Minio

        try:
            endpoint = os.environ["MINIO_ENDPOINT"]
            access_key = os.environ["MINIO_ACCESS_KEY"]
            secret_key = os.environ["MINIO_SECRET_KEY"]
        except KeyError as exc:
            raise RuntimeError(
                f"CLARION_STORAGE_BACKEND={backend} requires {exc.args[0]} to be set"
            ) from exc
        secure = _truthy(os.environ.get("MINIO_SECURE", "1"))
        region = os.environ.get("MINIO_REGION") or None
        client = Minio(
            endpoint, access_key=access_key, secret_key=secret_key, secure=secure, region=region
        )
        return MinioObjectStore(client)

    raise RuntimeError(f"unknown CLARION_STORAGE_BACKEND={backend!r} (use 'local' or 'minio')")


def get_object_store() -> ObjectStore:
    """Process-wide singleton, built from the environment on first use."""
    global _store
    if _store is None:
        _store = _build_object_store()
    return _store


def set_object_store(store: Optional[ObjectStore]) -> None:
    """Swap the singleton (tests). Pass ``None`` to force a rebuild next call."""
    global _store
    _store = store
