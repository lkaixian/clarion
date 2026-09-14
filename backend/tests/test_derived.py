"""P1.7 — app/derived.py: on-demand thumbnail generation, sha-scoped caching,
negative caching, and the WORM guarantee, against a real LocalObjectStore."""
import hashlib
import io

import pytest
from PIL import Image
from reportlab.pdfgen import canvas

from app import derived, storage
from app.storage import BUCKET_DERIVED, BUCKET_DOCUMENTS, BUCKET_MEDICINE, LocalObjectStore


@pytest.fixture
def local_store(tmp_path):
    prev = storage._store
    storage.set_object_store(LocalObjectStore(tmp_path))
    try:
        yield storage.get_object_store()
    finally:
        storage.set_object_store(prev)


def _png(w=800, h=600, color=(10, 120, 200)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _pdf(w=400, h=300):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setFillColorRGB(0.8, 0.2, 0.2)
    c.rect(0, 0, w, h, fill=1)
    c.showPage()
    c.save()
    return buf.getvalue()


def _put(store, bucket, key, data):
    store.put(bucket, key, data, mime="image/png")
    return hashlib.sha256(data).hexdigest()


def test_thumbnail_generated_and_cached(local_store):
    sha = _put(local_store, BUCKET_MEDICINE, "item1_photo.jpg", _png())
    dkey = derived.derived_key(BUCKET_MEDICINE, "item1_photo.jpg", variant="thumb300", sha256=sha)
    assert not local_store.exists(BUCKET_DERIVED, dkey)

    thumb = derived.get_or_make_thumbnail(BUCKET_MEDICINE, "item1_photo.jpg", sha256=sha)
    assert thumb is not None
    img = Image.open(io.BytesIO(thumb))
    assert img.format == "JPEG" and max(img.size) <= 300
    assert local_store.exists(BUCKET_DERIVED, dkey)
    assert derived.get_or_make_thumbnail(BUCKET_MEDICINE, "item1_photo.jpg", sha256=sha) == thumb


def test_same_key_reupload_gets_a_fresh_thumbnail(local_store):
    """The arch-review bug: a phone re-uploads image.jpg -> same object key,
    different bytes -> the sha-scoped derived key changes, so the stale
    thumbnail is never served."""
    sha1 = _put(local_store, BUCKET_MEDICINE, "k.jpg", _png(color=(255, 0, 0)))
    t1 = derived.get_or_make_thumbnail(BUCKET_MEDICINE, "k.jpg", sha256=sha1)
    sha2 = _put(local_store, BUCKET_MEDICINE, "k.jpg", _png(color=(0, 0, 255)))  # overwrite
    assert sha2 != sha1
    t2 = derived.get_or_make_thumbnail(BUCKET_MEDICINE, "k.jpg", sha256=sha2)
    assert t2 != t1  # a genuinely new preview, not the cached red one


def test_thumbnail_regenerated_after_ilm_eviction(local_store):
    sha = _put(local_store, BUCKET_MEDICINE, "k.jpg", _png())
    first = derived.get_or_make_thumbnail(BUCKET_MEDICINE, "k.jpg", sha256=sha)
    dkey = derived.derived_key(BUCKET_MEDICINE, "k.jpg", variant="thumb300", sha256=sha)
    local_store.delete(BUCKET_DERIVED, dkey)  # simulate the 30-day ILM expiry
    assert derived.get_or_make_thumbnail(BUCKET_MEDICINE, "k.jpg", sha256=sha) == first


def test_missing_source_returns_none(local_store):
    assert derived.get_or_make_thumbnail(BUCKET_MEDICINE, "nope_x.jpg", sha256="deadbeef") is None


def test_non_image_source_negatively_cached(local_store):
    sha = _put(local_store, BUCKET_DOCUMENTS, "p1/d1_report.pdf", b"%PDF-1.4 not really a pdf")
    assert derived.get_or_make_thumbnail(BUCKET_DOCUMENTS, "p1/d1_report.pdf", sha256=sha) is None
    dkey = derived.derived_key(BUCKET_DOCUMENTS, "p1/d1_report.pdf", variant="thumb300", sha256=sha)
    assert local_store.exists(BUCKET_DERIVED, dkey + ".none")  # negative marker cached
    # a second call short-circuits on the marker (still None)
    assert derived.get_or_make_thumbnail(BUCKET_DOCUMENTS, "p1/d1_report.pdf", sha256=sha) is None


def test_multi_segment_source_key(local_store):
    sha = _put(local_store, BUCKET_DOCUMENTS, "pat-1/doc-2_scan.png", _png(400, 400))
    thumb = derived.get_or_make_thumbnail(BUCKET_DOCUMENTS, "pat-1/doc-2_scan.png", sha256=sha)
    assert thumb is not None
    dkey = derived.derived_key(BUCKET_DOCUMENTS, "pat-1/doc-2_scan.png", variant="thumb300", sha256=sha)
    assert local_store.exists(BUCKET_DERIVED, dkey)


def test_worm_guarantee_source_buckets_never_written(local_store, tmp_path):
    """P1.7 must only READ clarion-documents / clarion-medicine and WRITE
    clarion-derived — never touch an original."""
    sha = _put(local_store, BUCKET_DOCUMENTS, "p/d_x.png", _png())
    docs_before = set((tmp_path / BUCKET_DOCUMENTS).rglob("*"))
    med_before = set((tmp_path / BUCKET_MEDICINE).rglob("*")) if (tmp_path / BUCKET_MEDICINE).exists() else set()

    derived.get_or_make_thumbnail(BUCKET_DOCUMENTS, "p/d_x.png", sha256=sha)
    derived.prime_thumbnail(BUCKET_DOCUMENTS, "p/d_x.png", sha)

    assert set((tmp_path / BUCKET_DOCUMENTS).rglob("*")) == docs_before
    med_after = set((tmp_path / BUCKET_MEDICINE).rglob("*")) if (tmp_path / BUCKET_MEDICINE).exists() else set()
    assert med_after == med_before
    assert (tmp_path / BUCKET_DERIVED).exists()  # the only bucket written


def test_storage_error_propagates(local_store, monkeypatch):
    """A backend outage must raise (so the endpoint 503s), not return None (404)."""
    sha = _put(local_store, BUCKET_MEDICINE, "k.jpg", _png())

    def boom(*a, **k):
        raise storage.ObjectStoreError("backend down")

    monkeypatch.setattr(local_store, "get", boom)
    with pytest.raises(storage.ObjectStoreError):
        derived.get_or_make_thumbnail(BUCKET_MEDICINE, "k.jpg", sha256=sha)


def test_prime_thumbnail_never_raises(local_store):
    derived.prime_thumbnail(BUCKET_MEDICINE, "does_not_exist.jpg", "abc")


def test_unsupported_size_rejected(local_store):
    with pytest.raises(ValueError):
        derived.get_or_make_thumbnail(BUCKET_MEDICINE, "k.jpg", size=999, sha256="x")


def test_real_pdf_gets_a_rendered_preview(local_store):
    """P1.7b: a genuine PDF now gets page-1 rendered instead of a blanket
    negative cache, same self-healing/sha-scoping guarantees as a raster."""
    sha = _put(local_store, BUCKET_DOCUMENTS, "p1/report.pdf", _pdf())
    thumb = derived.get_or_make_thumbnail(BUCKET_DOCUMENTS, "p1/report.pdf", sha256=sha)
    assert thumb is not None
    img = Image.open(io.BytesIO(thumb))
    assert img.format == "JPEG" and max(img.size) <= 300
    dkey = derived.derived_key(BUCKET_DOCUMENTS, "p1/report.pdf", variant="thumb300", sha256=sha)
    assert local_store.exists(BUCKET_DERIVED, dkey)


def test_1400_preview_variant(local_store):
    sha = _put(local_store, BUCKET_DOCUMENTS, "p1/report.pdf", _pdf())
    preview = derived.get_or_make_thumbnail(BUCKET_DOCUMENTS, "p1/report.pdf", size=1400, sha256=sha)
    assert preview is not None
    assert max(Image.open(io.BytesIO(preview)).size) == 1400
