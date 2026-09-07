"""P1.6 — ObjectStore abstraction. Covers LocalObjectStore end to end, the
key-validation / filename-sanitisation guards, and the env-driven factory.

MinioObjectStore is exercised against a fake client here (no server); a live
MinIO smoke test belongs in the integration gate, not the unit suite.
"""
import hashlib

import pytest

from app import storage
from app.storage import (
    ALL_BUCKETS,
    BUCKET_DOCUMENTS,
    BUCKET_SCRATCH,
    LocalObjectStore,
    ObjectNotFound,
    get_object_store,
    sanitize_filename,
    set_object_store,
    validate_key,
)


# --------------------------------------------------------------------------
# LocalObjectStore
# --------------------------------------------------------------------------
def test_local_put_get_roundtrip(tmp_path):
    store = LocalObjectStore(tmp_path)
    data = b"hello \x89PNG world" * 10
    meta = store.put(BUCKET_DOCUMENTS, "p1/doc_1_report.pdf", data, mime="application/pdf")

    assert meta.key == "p1/doc_1_report.pdf"
    assert meta.bucket == BUCKET_DOCUMENTS
    assert meta.size == len(data)
    assert meta.mime == "application/pdf"
    assert meta.sha256 == hashlib.sha256(data).hexdigest()

    assert store.exists(BUCKET_DOCUMENTS, "p1/doc_1_report.pdf")
    assert store.get(BUCKET_DOCUMENTS, "p1/doc_1_report.pdf") == data
    assert b"".join(store.open_stream(BUCKET_DOCUMENTS, "p1/doc_1_report.pdf", chunk_size=8)) == data


def test_local_put_overwrites(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put(BUCKET_SCRATCH, "a.bin", b"one", mime="application/octet-stream")
    store.put(BUCKET_SCRATCH, "a.bin", b"two", mime="application/octet-stream")
    assert store.get(BUCKET_SCRATCH, "a.bin") == b"two"


def test_local_delete_is_idempotent(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put(BUCKET_SCRATCH, "gone.bin", b"x", mime="application/octet-stream")
    store.delete(BUCKET_SCRATCH, "gone.bin")
    assert not store.exists(BUCKET_SCRATCH, "gone.bin")
    store.delete(BUCKET_SCRATCH, "gone.bin")  # no raise


def test_local_missing_get_raises_objectnotfound(tmp_path):
    store = LocalObjectStore(tmp_path)
    with pytest.raises(ObjectNotFound):
        store.get(BUCKET_DOCUMENTS, "nope/missing.pdf")
    with pytest.raises(ObjectNotFound):
        list(store.open_stream(BUCKET_DOCUMENTS, "nope/missing.pdf"))


def test_local_open_stream_closes_handle_even_if_never_iterated(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put(BUCKET_SCRATCH, "x.bin", b"data" * 100, mime="application/octet-stream")
    it = store.open_stream(BUCKET_SCRATCH, "x.bin")
    it.close()  # created but never iterated (e.g. an error before the response is built)
    it.close()  # idempotent
    # Windows would raise PermissionError here if the handle were still open
    store.put(BUCKET_SCRATCH, "x.bin", b"new", mime="application/octet-stream")
    (tmp_path / BUCKET_SCRATCH / "x.bin").unlink()


def test_local_no_tmp_file_left_behind(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put(BUCKET_SCRATCH, "x.bin", b"payload", mime="application/octet-stream")
    leftovers = [p.name for p in (tmp_path / BUCKET_SCRATCH).iterdir() if ".tmp-" in p.name]
    assert leftovers == []


@pytest.mark.parametrize(
    "bad_key",
    [
        "../escape.txt",
        "a/../../escape.txt",
        "/absolute.txt",
        "trailing/",
        "nested//empty.txt",
        "back\\slash.txt",
        "nul\x00.txt",
        "a/./b.txt",
        "",
        "x" * 600,
    ],
)
def test_local_rejects_bad_keys(tmp_path, bad_key):
    store = LocalObjectStore(tmp_path)
    with pytest.raises(ValueError):
        store.put(BUCKET_DOCUMENTS, bad_key, b"x", mime="text/plain")
    # read-side guards degrade to "not found" / False rather than raising ValueError
    assert store.exists(BUCKET_DOCUMENTS, bad_key) is False


def test_local_rejects_unknown_bucket(tmp_path):
    store = LocalObjectStore(tmp_path)
    with pytest.raises(ValueError):
        store.put("clarion-nope", "a.txt", b"x", mime="text/plain")


def test_local_bucket_isolation(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put(BUCKET_DOCUMENTS, "same.bin", b"docs", mime="application/octet-stream")
    store.put(BUCKET_SCRATCH, "same.bin", b"scratch", mime="application/octet-stream")
    assert store.get(BUCKET_DOCUMENTS, "same.bin") == b"docs"
    assert store.get(BUCKET_SCRATCH, "same.bin") == b"scratch"


def test_local_presign_and_retention_are_noops(tmp_path):
    store = LocalObjectStore(tmp_path)
    store.put(BUCKET_DOCUMENTS, "a.bin", b"x", mime="application/octet-stream")
    assert store.presign_get(BUCKET_DOCUMENTS, "a.bin") is None
    assert store.set_retention(BUCKET_DOCUMENTS, "a.bin", None) is None


# --------------------------------------------------------------------------
# key / filename helpers
# --------------------------------------------------------------------------
def test_validate_key_accepts_reasonable_keys():
    for good in ("a.png", "p1/doc.pdf", "users/abc-123.png", "a/b/c/d.bin"):
        assert validate_key(good) == good


@pytest.mark.parametrize(
    "raw,expected_ok",
    [
        ("../../etc/passwd", "passwd"),
        ("my report (1).pdf", "my_report_1_.pdf"),
        ("..hidden", "hidden"),
        ("C:\\Windows\\evil.exe", "evil.exe"),
        ("", "file"),
        (None, "file"),
    ],
)
def test_sanitize_filename(raw, expected_ok):
    out = sanitize_filename(raw)
    assert out == expected_ok
    # whatever comes out must survive as a single key segment
    validate_key(out)


def test_sanitize_filename_caps_length():
    out = sanitize_filename("a" * 500 + ".png")
    assert len(out) <= 200
    assert out.endswith(".png")


# --------------------------------------------------------------------------
# factory
# --------------------------------------------------------------------------
def test_factory_defaults_to_local(tmp_path, monkeypatch):
    monkeypatch.delenv("CLARION_STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("CLARION_STORAGE_ROOT", str(tmp_path))
    set_object_store(None)
    try:
        store = get_object_store()
        assert isinstance(store, LocalObjectStore)
        assert get_object_store() is store  # singleton
    finally:
        set_object_store(None)


def test_factory_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("CLARION_STORAGE_BACKEND", "ceph")
    set_object_store(None)
    try:
        with pytest.raises(RuntimeError):
            get_object_store()
    finally:
        set_object_store(None)


def test_factory_minio_requires_endpoint(monkeypatch):
    monkeypatch.setenv("CLARION_STORAGE_BACKEND", "minio")
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)
    set_object_store(None)
    try:
        with pytest.raises(RuntimeError):
            get_object_store()
    finally:
        set_object_store(None)


# --------------------------------------------------------------------------
# MinioObjectStore against a fake client
# --------------------------------------------------------------------------
class _FakeS3Error(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _FakeMinio:
    def __init__(self, *, lock=False):
        self._objs: dict[tuple[str, str], bytes] = {}
        self.buckets = set()
        self.locked = set()
        self.versioned = set()
        self.retention = {}
        self._lock_default = lock

    def bucket_exists(self, b):
        return b in self.buckets

    def make_bucket(self, b, object_lock=False):
        self.buckets.add(b)
        if object_lock or self._lock_default:
            self.locked.add(b)

    def set_bucket_versioning(self, b, cfg):
        self.versioned.add(b)

    def get_object_lock_config(self, b):
        if b not in self.locked:
            raise _FakeS3Error("ObjectLockConfigurationNotFoundError")
        return object()

    def set_object_retention(self, bucket, key, retention):
        self.retention[(bucket, key)] = retention

    def put_object(self, bucket, key, stream, length, content_type=None):
        self._objs[(bucket, key)] = stream.read()

    def get_object(self, bucket, key):
        if (bucket, key) not in self._objs:
            raise _FakeS3Error("NoSuchKey")
        return _FakeResponse(self._objs[(bucket, key)])

    def stat_object(self, bucket, key):
        if (bucket, key) not in self._objs:
            raise _FakeS3Error("NoSuchKey")
        return object()

    def remove_object(self, bucket, key):
        self._objs.pop((bucket, key), None)


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data

    def stream(self, n):
        yield self._data

    def close(self):
        pass

    def release_conn(self):
        pass


@pytest.fixture
def _patch_s3error(monkeypatch):
    fake_mod = type("m", (), {"S3Error": _FakeS3Error})
    monkeypatch.setitem(__import__("sys").modules, "minio.error", fake_mod)
    return fake_mod


def test_minio_store_roundtrip(_patch_s3error):
    client = _FakeMinio()
    store = storage.MinioObjectStore(client)
    assert client.buckets == set(ALL_BUCKETS)
    assert client.versioned == set(ALL_BUCKETS)
    # WORM buckets created with object lock; others not
    assert storage.WORM_BUCKETS <= client.locked
    assert BUCKET_SCRATCH not in client.locked

    data = b"blob-data"
    meta = store.put(BUCKET_DOCUMENTS, "p/doc.pdf", data, mime="application/pdf")
    assert meta.sha256 == hashlib.sha256(data).hexdigest()
    # documents is a WORM bucket + lock is on -> a per-object retention stamped
    assert ("clarion-documents", "p/doc.pdf") in client.retention
    assert store.exists(BUCKET_DOCUMENTS, "p/doc.pdf")
    assert store.get(BUCKET_DOCUMENTS, "p/doc.pdf") == data
    assert b"".join(store.open_stream(BUCKET_DOCUMENTS, "p/doc.pdf")) == data
    assert store.get_checked(BUCKET_DOCUMENTS, "p/doc.pdf", meta.sha256) == data
    with pytest.raises(storage.ObjectIntegrityError):
        store.get_checked(BUCKET_DOCUMENTS, "p/doc.pdf", "deadbeef" * 8)

    store.delete(BUCKET_DOCUMENTS, "p/doc.pdf")
    assert not store.exists(BUCKET_DOCUMENTS, "p/doc.pdf")
    with pytest.raises(ObjectNotFound):
        store.get(BUCKET_DOCUMENTS, "p/doc.pdf")
    store.delete(BUCKET_DOCUMENTS, "p/doc.pdf")  # idempotent


def test_minio_wraps_s3_errors(_patch_s3error):
    client = _FakeMinio()
    store = storage.MinioObjectStore(client)

    def boom(*a, **k):
        raise _FakeS3Error("InternalError")

    client.get_object = boom
    with pytest.raises(storage.ObjectStoreError) as ei:
        store.get(BUCKET_DOCUMENTS, "x/y.bin")
    assert not isinstance(ei.value, ObjectNotFound)


def test_local_get_checked(tmp_path):
    store = LocalObjectStore(tmp_path)
    meta = store.put(BUCKET_SCRATCH, "a.bin", b"payload", mime="application/octet-stream")
    assert store.get_checked(BUCKET_SCRATCH, "a.bin", meta.sha256) == b"payload"
    assert store.get_checked(BUCKET_SCRATCH, "a.bin", None) == b"payload"  # legacy row
    with pytest.raises(storage.ObjectIntegrityError):
        store.get_checked(BUCKET_SCRATCH, "a.bin", "0" * 64)
