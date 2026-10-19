"""extract_nric_fields: LLM -> RapidOCR -> Tesseract ordering. The real engine is faked, so this
checks the wiring and parsing, not model accuracy (see the on-Pi check in docs/deployment.md)."""
import io

import pytest
from PIL import Image

from app.ai import nric_ocr


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 25), "white").save(buf, "PNG")
    return buf.getvalue()


def _box(x, y):  # one text box, top-left at (x, y)
    return [[x, y], [x + 50, y], [x + 50, y + 10], [x, y + 10]]


class _Engine:
    def __init__(self, lines):
        self.lines = lines

    def __call__(self, arr):
        return self.lines, None


def _setup(monkeypatch, engine, tess=None):
    monkeypatch.setattr(nric_ocr, "_extract_via_llm", lambda b, m: None)
    monkeypatch.setattr(nric_ocr, "_get_rapid_engine", lambda: engine)
    monkeypatch.setattr(nric_ocr, "_extract_via_tesseract", lambda b: tess or {
        "ic_number": None, "name": None, "method": "tesseract", "name_confidence": "low", "raw_text": ""})


def test_rapidocr_reads_ic_and_name_in_reading_order(monkeypatch):
    pytest.importorskip("numpy")  # in the Docker image via onnxruntime; not in the dev venv
    # Detections arrive out of order; they must be read top to bottom.
    lines = [
        [_box(10, 80), "040130-07-0493", 0.99],
        [_box(10, 20), "KAD PENGENALAN", 0.9],
        [_box(10, 120), "AHMAD BIN ABDULLAH", 0.97],
    ]
    _setup(monkeypatch, _Engine(lines))
    r = nric_ocr.extract_nric_fields(_png())
    assert r["method"] == "rapidocr"
    assert r["ic_number"] == "040130070493"
    assert r["name"] == "AHMAD BIN ABDULLAH"
    assert r["raw_text"].splitlines()[0] == "KAD PENGENALAN"


def test_falls_back_to_tesseract_when_rapidocr_finds_no_ic(monkeypatch):
    tess = {"ic_number": "900101011234", "name": "X", "method": "tesseract", "name_confidence": "low", "raw_text": ""}
    _setup(monkeypatch, _Engine([[_box(0, 0), "blurry", 0.3]]), tess)
    assert nric_ocr.extract_nric_fields(_png())["method"] == "tesseract"


def test_unavailable_rapidocr_uses_tesseract_and_never_raises(monkeypatch):
    _setup(monkeypatch, None)
    r = nric_ocr.extract_nric_fields(b"not an image")
    assert r["ic_number"] is None and r["method"] == "tesseract"


def test_engine_error_is_swallowed(monkeypatch):
    class Boom:
        def __call__(self, arr):
            raise RuntimeError("onnx exploded")
    _setup(monkeypatch, Boom())
    assert nric_ocr.extract_nric_fields(_png())["method"] == "tesseract"


def test_name_on_card_ignores_spaces_dropped_by_the_engine():
    text = "KADPENGENALANMALAYSIA\n040130-07-0493\nAHMADBINABDULLAH\nLELAKIWARGANEGARAISLAM"
    assert nric_ocr.name_on_card("Ahmad bin Abdullah", text)
    assert nric_ocr.name_on_card("AHMAD BIN ABDULLAH", "AHMAD BIN ABDULLAH\nJALAN 1")
    assert not nric_ocr.name_on_card("Siti Aminah Binti Yusof", text)
    assert not nric_ocr.name_on_card("Ahmad bin Abdullah", None)
    assert not nric_ocr.name_on_card("Al", text)  # too short to mean anything


def _patient(**kw):
    from types import SimpleNamespace
    base = dict(national_id="040130-07-0493", full_name="Ahmad bin Abdullah", date_of_birth="2004-01-30")
    return SimpleNamespace(**{**base, **kw})


def test_photo_verification_accepts_spaceless_name_but_still_needs_the_ic():
    from app.routers.self_registration import _evaluate_photo_verification as ev
    text = "KADPENGENALANMALAYSIA\n040130-07-0493\nAHMADBINABDULLAH\nLELAKIWARGANEGARAISLAM"
    front = {"ic_number": "040130070493", "name": "LELAKIWARGANEGARAISLAM", "raw_text": text}
    assert ev(front, {}, _patient())[0] is True
    # someone else's card: right layout, wrong IC and name
    other = {"ic_number": "900101011234", "name": "SITI", "raw_text": "SITIAMINAH\n900101-01-1234"}
    ok, msg, note = ev(other, {}, _patient())
    assert ok is False and note == "ic_number_mismatch"
    # right IC, name nowhere on the card
    nameless = {"ic_number": "040130070493", "name": "LELAKIISLAM", "raw_text": "040130-07-0493\nLELAKIISLAM"}
    ok, msg, note = ev(nameless, {}, _patient())
    assert ok is False and note == "name_mismatch"
