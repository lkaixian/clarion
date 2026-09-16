"""P1.7 — app/imaging.py: EXIF/metadata strip, orientation, resize, thumbnail,
and hardened decoding of attacker-supplied bytes. All fixtures built in memory.
"""
import io

import pytest
from PIL import Image
from reportlab.pdfgen import canvas

from app import imaging
from app.imaging import (
    ImageProcessingError,
    is_pdf,
    is_supported_image,
    make_thumbnail,
    normalise_image,
    render_pdf_first_page,
)


def _bytes(img: Image.Image, fmt="PNG", **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


def _decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


# --------------------------------------------------------------------------
# normalise_image — happy path
# --------------------------------------------------------------------------
def test_plain_jpeg_roundtrips_to_rgb_jpeg():
    src = _bytes(Image.new("RGB", (100, 100), (200, 50, 50)), "JPEG")
    out = normalise_image(src)
    assert out.mime == "image/jpeg"
    img = _decode(out.data)
    assert img.format == "JPEG"
    assert img.mode == "RGB"
    assert img.size == (100, 100)


def test_exif_orientation_is_applied_and_tag_removed():
    # 20x10 image, EXIF Orientation=6 (device rotated 90° CW -> viewer must
    # rotate 270° CW, i.e. the displayed image is 10x20).
    base = Image.new("RGB", (20, 10), (0, 128, 255))
    exif = Image.Exif()
    exif[0x0112] = 6
    src = _bytes(base, "JPEG", exif=exif)

    out = normalise_image(src)
    img = _decode(out.data)
    assert img.size == (10, 20)  # orientation baked in
    assert not dict(img.getexif())  # no EXIF on the output


def test_camera_metadata_and_icc_are_stripped():
    base = Image.new("RGB", (64, 64), (10, 20, 30))
    exif = Image.Exif()
    exif[0x010F] = "ACME Phone"          # Make
    exif[0x0110] = "Model X"             # Model
    exif[0x9286] = "at the pharmacy"     # UserComment — a privacy leak
    icc = b"\x00\x00\x02\x0cADBE" + b"\x00" * 100  # bogus but non-empty ICC blob
    src = _bytes(base, "JPEG", exif=exif, icc_profile=icc)
    # sanity: the source really does carry the metadata
    assert dict(Image.open(io.BytesIO(src)).getexif())
    assert "icc_profile" in Image.open(io.BytesIO(src)).info

    out = normalise_image(src)
    res = _decode(out.data)
    assert "exif" not in res.info
    assert "icc_profile" not in res.info
    assert "xmp" not in res.info
    assert not dict(res.getexif())  # every EXIF tag (incl. any GPS IFD) is gone


# --------------------------------------------------------------------------
# resize
# --------------------------------------------------------------------------
def test_downscales_long_edge_to_max():
    src = _bytes(Image.new("RGB", (4000, 3000), (1, 2, 3)), "JPEG")
    out = normalise_image(src, max_edge=2500)
    assert _decode(out.data).size == (2500, 1875)


def test_never_upscales():
    src = _bytes(Image.new("RGB", (100, 80), (1, 2, 3)), "JPEG")
    out = normalise_image(src, max_edge=2500)
    assert _decode(out.data).size == (100, 80)


# --------------------------------------------------------------------------
# mode handling
# --------------------------------------------------------------------------
def test_rgba_transparency_flattened_onto_white():
    im = Image.new("RGBA", (50, 50), (0, 0, 0, 0))  # fully transparent
    out = normalise_image(_bytes(im, "PNG"))
    res = _decode(out.data).convert("RGB")
    assert res.mode == "RGB"
    assert res.getpixel((25, 25)) == (255, 255, 255)


def test_palette_png_with_transparency():
    im = Image.new("P", (30, 30))
    im.info["transparency"] = 0
    out = normalise_image(_bytes(im, "PNG"))
    assert _decode(out.data).mode == "RGB"


def test_cmyk_jpeg():
    src = _bytes(Image.new("CMYK", (40, 40), (0, 0, 0, 0)), "JPEG")
    assert _decode(normalise_image(src).data).mode == "RGB"


def test_grayscale():
    src = _bytes(Image.new("L", (40, 40), 128), "PNG")
    assert _decode(normalise_image(src).data).mode == "RGB"


def test_animated_gif_keeps_first_frame_only():
    frames = [Image.new("RGB", (30, 30), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:])
    out = normalise_image(buf.getvalue())
    img = _decode(out.data)
    assert img.format == "JPEG"
    assert getattr(img, "n_frames", 1) == 1


# --------------------------------------------------------------------------
# make_thumbnail
# --------------------------------------------------------------------------
def test_thumbnail_fits_box_and_keeps_aspect():
    src = _bytes(Image.new("RGB", (1000, 500), (9, 9, 9)), "JPEG")
    out = make_thumbnail(src, size=300)
    img = _decode(out.data)
    assert img.format == "JPEG"
    assert img.size == (300, 150)


def test_thumbnail_never_upscales():
    src = _bytes(Image.new("RGB", (50, 50), (9, 9, 9)), "PNG")
    assert _decode(make_thumbnail(src, size=300).data).size == (50, 50)


# --------------------------------------------------------------------------
# hardening
# --------------------------------------------------------------------------
def test_decompression_bomb_rejected(monkeypatch):
    monkeypatch.setattr(imaging, "MAX_INPUT_PIXELS", 100)
    src = _bytes(Image.new("RGB", (200, 200), (0, 0, 0)), "PNG")
    with pytest.raises(ImageProcessingError):
        normalise_image(src)


@pytest.mark.parametrize(
    "blob",
    [b"not an image", b"%PDF-1.4\n%\xe2\xe3\xcf\xd3", b"<svg xmlns='...'></svg>", b"", b"\x00" * 32],
)
def test_non_image_bytes_rejected(blob):
    with pytest.raises(ImageProcessingError):
        normalise_image(blob)
    with pytest.raises(ImageProcessingError):
        make_thumbnail(blob)


@pytest.mark.parametrize("fmt", ["ICO", "TIFF"])
def test_format_outside_allowlist_rejected(fmt):
    # ICO and TIFF are formats Pillow CAN decode but we exclude from
    # Image.open(formats=...) -- the parser never runs on them.
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (1, 2, 3)).save(buf, format=fmt)
    with pytest.raises(ImageProcessingError):
        normalise_image(buf.getvalue())
    with pytest.raises(ImageProcessingError):
        make_thumbnail(buf.getvalue())


def test_truncated_jpeg_rejected_not_hung():
    full = _bytes(Image.new("RGB", (400, 400), (5, 5, 5)), "JPEG")
    truncated = full[:120]
    with pytest.raises(ImageProcessingError):
        normalise_image(truncated)


def test_is_supported_image():
    for fmt in ("PNG", "JPEG", "GIF", "BMP", "WEBP"):
        assert is_supported_image(_bytes(Image.new("RGB", (4, 4)), fmt)), fmt
    # TIFF is deliberately excluded now (CVE-prone parser)
    assert not is_supported_image(_bytes(Image.new("RGB", (8, 8)), "TIFF"))
    assert not is_supported_image(b"%PDF-1.4 ................")
    assert not is_supported_image(b"<svg></svg> ............")
    assert not is_supported_image(b"random bytes ...........")


def test_concurrency_gate_is_bounded():
    import app.imaging as m
    assert m._decode_gate._value <= m._CONCURRENCY  # semaphore, not unbounded


# --------------------------------------------------------------------------
# HEIC input (P1.7b) — an iPhone camera's default photo format
# --------------------------------------------------------------------------
def _heic_bytes(w=64, h=48, color=(10, 20, 200)) -> bytes:
    import pillow_heif
    buf = io.BytesIO()
    pillow_heif.from_pillow(Image.new("RGB", (w, h), color)).save(buf, quality=80)
    return buf.getvalue()


def test_heic_is_recognised_and_decodes():
    raw = _heic_bytes()
    assert is_supported_image(raw)
    out = normalise_image(raw)
    assert out.mime == "image/jpeg"  # every input normalises to JPEG, HEIC included
    img = _decode(out.data)
    assert img.format == "JPEG"
    assert img.size == (64, 48)


def test_heic_thumbnail():
    out = make_thumbnail(_heic_bytes(400, 300), size=100)
    img = _decode(out.data)
    assert max(img.size) <= 100


# --------------------------------------------------------------------------
# render_pdf_first_page (P1.7b)
# --------------------------------------------------------------------------
def _pdf_bytes(w=400, h=300) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setFillColorRGB(0.8, 0.2, 0.2)
    c.rect(0, 0, w, h, fill=1)
    c.showPage()
    c.save()
    return buf.getvalue()


def test_render_pdf_first_page_matches_aspect_and_caps_long_edge():
    out = render_pdf_first_page(_pdf_bytes(w=400, h=300), max_edge=200)
    assert out.mime == "image/jpeg"
    img = _decode(out.data)
    assert img.format == "JPEG"
    assert img.size == (200, 150)  # 4:3 aspect preserved, long edge == max_edge exactly


def test_render_pdf_first_page_only_uses_page_one():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(300, 300))
    c.setFillColorRGB(1, 0, 0)
    c.rect(0, 0, 300, 300, fill=1)
    c.showPage()
    c.setFillColorRGB(0, 0, 1)
    c.rect(0, 0, 300, 300, fill=1)
    c.showPage()
    c.save()

    img = _decode(render_pdf_first_page(buf.getvalue(), max_edge=50).data)
    assert img.getpixel((25, 25))[0] > img.getpixel((25, 25))[2]  # red page, not blue


@pytest.mark.parametrize("blob", [b"not a pdf at all", b"", b"%PDF-1.4 truncated garbage"])
def test_corrupt_pdf_rejected(blob):
    with pytest.raises(ImageProcessingError):
        render_pdf_first_page(blob)


def test_is_pdf():
    assert is_pdf(_pdf_bytes())
    assert not is_pdf(b"not a pdf")
    assert not is_pdf(_bytes(Image.new("RGB", (4, 4)), "PNG"))
