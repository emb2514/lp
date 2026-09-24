"""Tests for the fast embedded-image decode path in pdf_content.py.

REAL, MEASURED PERFORMANCE BUG: pypdf's public `page.images` API always
pays a full decode-then-RE-ENCODE-then-decode round trip internally
(confirmed directly via cProfile and by reading pypdf's own
`_xobj_to_image`: it builds the real decoded image, then unconditionally
re-encodes it to a standalone file format and re-opens THAT, purely so
`ImageFile.data` is guaranteed to be valid standalone image bytes) --
on a realistic 100-page scanned document this was ~48% of the ENTIRE
per-page fingerprinting cost, itself already the single slowest stage
in the whole pipeline on a real package.

`_try_fast_extract_embedded_images` decodes the two most common real-
world cases directly (DCTDecode/JPEG needs no re-encode at all; simple
8-bit DeviceGray/DeviceRGB FlateDecode is a straight `Image.frombytes`)
and returns None -- falling back to the slower, fully general
`page.images`-based path with NO loss of correctness -- for anything
else. These tests exist specifically to prove that promise: the fast
path produces IDENTICAL analysis results to the slow path wherever it
engages, and correctly declines (never guesses) everywhere it doesn't.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from fixtures.builders import make_scanned_like_pdf

from lender_package_builder import pdf_content


def _build_pdf_with_image(path: Path, pil_image: Image.Image, fmt: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    buf = io.BytesIO()
    pil_image.save(buf, format=fmt)
    buf.seek(0)
    c.drawImage(ImageReader(buf), 0, 0, width=LETTER[0], height=LETTER[1])
    c.showPage()
    c.save()
    return path


def _slow_path_signals(page) -> list[tuple]:
    """Directly replicates the slow, page.images-based path (bypassing
    the fast path's own short-circuit) so it can be compared against
    the fast path's output for the same page.
    """

    results = []
    for image_file in list(page.images):
        pil_image = image_file.image
        width, height = pil_image.size
        analysis_image = pdf_content._prepare_analysis_image(pil_image) if width > 1 and height > 1 else pil_image
        phash = pdf_content._dhash(analysis_image) if width > 1 and height > 1 else None
        avg_color = pdf_content._average_color(analysis_image) if width >= 1 and height >= 1 else None
        is_blank = (
            pdf_content._classify_image_blank(pil_image, precomputed_quick=analysis_image)
            if width > 1 and height > 1
            else False
        )
        results.append((phash, avg_color, is_blank, width, height))
    return results


def _fast_path_signals(fast_result) -> list[tuple]:
    return [(s.perceptual_hash, s.average_color, s.is_blank, s.width, s.height) for s in fast_result]


# ---------------------------------------------------------------------
# Fast path engages and matches the slow path exactly
# ---------------------------------------------------------------------


def test_fast_path_matches_slow_path_for_realistic_rgb_scans(tmp_path):
    path = make_scanned_like_pdf(tmp_path / "scanned.pdf", pages=8, image_seed=3)
    reader = PdfReader(str(path))
    for page in reader.pages:
        fast = pdf_content._try_fast_extract_embedded_images(page)
        assert fast is not None, "fast path should engage for a plain RGB Flate scan"
        assert _fast_path_signals(fast) == _slow_path_signals(page)


def test_fast_path_engages_and_matches_for_grayscale_image(tmp_path):
    gray_img = Image.new("L", (400, 500), color=128)
    for x in range(50, 300, 20):
        for y in range(50, 60):
            gray_img.putpixel((x, y), 30)
    path = _build_pdf_with_image(tmp_path / "gray.pdf", gray_img, "PNG")
    reader = PdfReader(str(path))
    page = reader.pages[0]

    fast = pdf_content._try_fast_extract_embedded_images(page)
    assert fast is not None
    assert _fast_path_signals(fast) == _slow_path_signals(page)


def test_fast_path_engages_and_matches_for_jpeg_sourced_image(tmp_path):
    rgb_img = Image.new("RGB", (400, 500), color=(200, 100, 50))
    path = _build_pdf_with_image(tmp_path / "jpeg.pdf", rgb_img, "JPEG")
    reader = PdfReader(str(path))
    page = reader.pages[0]

    fast = pdf_content._try_fast_extract_embedded_images(page)
    assert fast is not None
    # JPEG is lossy -- the fast path opens the exact same compressed
    # bytes pypdf would, so results must still match exactly (both
    # decode the identical JPEG stream, no independent re-compression).
    assert _fast_path_signals(fast) == _slow_path_signals(page)


def test_full_fingerprint_pipeline_uses_fast_path_and_produces_correct_results(tmp_path):
    # End-to-end: build_document_fingerprint (the real public entry
    # point every caller actually uses) still produces sane, non-blank
    # signals for real scanned content, going through the fast path.
    path = make_scanned_like_pdf(tmp_path / "scanned.pdf", pages=3, image_seed=9)
    fp = pdf_content.build_document_fingerprint("D1", path)
    assert len(fp.pages) == 3
    for page_fp in fp.pages:
        assert len(page_fp.images) == 1
        assert page_fp.images[0].is_blank is False
        assert page_fp.images[0].width == 850
        assert page_fp.images[0].height == 1100


# ---------------------------------------------------------------------
# Fast path correctly DECLINES (never guesses) -- these matter as much
# as the "it works" cases, since a wrong guess here would silently
# misinterpret real image content.
# ---------------------------------------------------------------------


def test_fast_path_declines_cmyk_image(tmp_path):
    cmyk_img = Image.new("CMYK", (200, 200), color=(10, 10, 10, 10))
    path = _build_pdf_with_image(tmp_path / "cmyk.pdf", cmyk_img, "TIFF")
    reader = PdfReader(str(path))
    page = reader.pages[0]
    assert pdf_content._try_fast_extract_embedded_images(page) is None
    # Still correctly handled via the slow-path fallback -- not lost.
    assert len(pdf_content._extract_embedded_images(page)) == 1


class _FakeXObject(dict):
    def __init__(self, *args, raw_data=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._raw_data = raw_data

    def get_data(self):
        if self._raw_data is not None:
            return self._raw_data
        return b"\x80" * (self["/Width"] * self["/Height"] * 3)

    def get_object(self):
        return self


def _fake_xobject(raw_data=None, **overrides):
    base = {
        "/Filter": "/FlateDecode",
        "/Width": 10,
        "/Height": 10,
        "/BitsPerComponent": 8,
        "/ColorSpace": "/DeviceRGB",
        "/SMask": None,
        "/Mask": None,
    }
    base.update(overrides)
    return _FakeXObject(base, raw_data=raw_data)


def test_fast_decode_declines_indexed_colorspace():
    x_obj = _fake_xobject()
    x_obj["/ColorSpace"] = ["/Indexed", "/DeviceRGB", 255, b"lookup-bytes"]
    assert pdf_content._fast_decode_image_xobject(x_obj) is None


def test_fast_decode_declines_non_8_bit_depth():
    x_obj = _fake_xobject(**{"/BitsPerComponent": 4})
    assert pdf_content._fast_decode_image_xobject(x_obj) is None


def test_fast_decode_declines_unrecognized_filter():
    x_obj = _fake_xobject(**{"/Filter": "/LZWDecode"})
    assert pdf_content._fast_decode_image_xobject(x_obj) is None


def test_fast_decode_declines_when_smask_present():
    x_obj = _fake_xobject()
    x_obj["/SMask"] = object()  # any non-None stand-in for a real soft mask
    assert pdf_content._fast_decode_image_xobject(x_obj) is None


def test_fast_decode_declines_when_mask_present():
    x_obj = _fake_xobject()
    x_obj["/Mask"] = object()
    assert pdf_content._fast_decode_image_xobject(x_obj) is None


def test_fast_decode_declines_unrecognized_colorspace():
    x_obj = _fake_xobject(**{"/ColorSpace": "/Separation"})
    assert pdf_content._fast_decode_image_xobject(x_obj) is None


def test_fast_decode_declines_byte_length_mismatch():
    # A raw stream whose length doesn't match width*height*colors --
    # never guess at how to interpret malformed/unexpected data.
    x_obj = _fake_xobject(raw_data=b"\x80" * 5)  # far too short for a 10x10 RGB image
    assert pdf_content._fast_decode_image_xobject(x_obj) is None
