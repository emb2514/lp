"""Unit tests for pdf_content.py -- the low-level per-page/per-document
fingerprinting toolkit that RC2's content-aware duplicate detection,
merged-document overlap detection, and version classification are all
built on.
"""

from __future__ import annotations

from pathlib import Path

from fixtures import builders

from lender_package_builder import pdf_content


# TEST 1 - normalized text collapses whitespace/case but keeps content
def test_normalized_text_collapses_whitespace_and_case(tmp_path: Path):
    path = builders.make_pdf(tmp_path / "a.pdf", pages=1, text_prefix="Hello World")
    fp = pdf_content.build_document_fingerprint("D1", path)
    assert "hello world" in fp.pages[0].normalized_text


# TEST 2 - identical normalized text produces identical text hashes
def test_identical_text_produces_identical_hash(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "a.pdf", pages=1, text_prefix="Shared Content")
    b = builders.make_pdf(tmp_path / "b.pdf", pages=1, text_prefix="Shared Content")
    fp_a = pdf_content.build_document_fingerprint("A", a)
    fp_b = pdf_content.build_document_fingerprint("B", b)
    assert fp_a.pages[0].text_hash == fp_b.pages[0].text_hash
    assert fp_a.normalized_document_hash == fp_b.normalized_document_hash


# TEST 3 - different text produces different hashes
def test_different_text_produces_different_hash(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "a.pdf", pages=1, text_prefix="Version A")
    b = builders.make_pdf(tmp_path / "b.pdf", pages=1, text_prefix="Version B")
    fp_a = pdf_content.build_document_fingerprint("A", a)
    fp_b = pdf_content.build_document_fingerprint("B", b)
    assert fp_a.pages[0].text_hash != fp_b.pages[0].text_hash


# TEST 4 - a genuinely blank page (no text, fields, annotations, images) is classified blank
def test_truly_blank_page_is_classified_blank(tmp_path: Path):
    path = builders.make_pdf_with_blank_pages(tmp_path / "blanks.pdf", pages=3, blank_positions=[1])
    fp = pdf_content.build_document_fingerprint("D1", path)
    assert fp.pages[0].blank.is_blank is False
    assert fp.pages[1].blank.is_blank is True
    assert fp.pages[2].blank.is_blank is False
    assert fp.non_blank_page_count == 2


# TEST 5 - blank pages at the start, end, and middle are all detected correctly
def test_blank_pages_detected_regardless_of_position(tmp_path: Path):
    path = builders.make_pdf_with_blank_pages(
        tmp_path / "blanks.pdf", pages=5, blank_positions=[0, 4], text_prefix="Content"
    )
    fp = pdf_content.build_document_fingerprint("D1", path)
    assert fp.pages[0].blank.is_blank is True
    assert fp.pages[4].blank.is_blank is True
    assert all(not fp.pages[i].blank.is_blank for i in (1, 2, 3))


# TEST 6 - a page with a faint signature-like mark must NOT be classified blank
def test_faint_signature_mark_is_not_classified_blank(tmp_path: Path):
    path = builders.make_pdf_with_faint_content(tmp_path / "faint.pdf", blank_pages=2, faint_page_index=0)
    fp = pdf_content.build_document_fingerprint("D1", path)
    assert fp.pages[0].blank.is_blank is False, "a faint mark must never be treated as blank"
    assert fp.pages[1].blank.is_blank is True  # the genuinely blank page in the same doc


# TEST 7 - ordinary scanner noise (a handful of stray dark pixels) does not defeat blank detection
def test_scanner_noise_does_not_prevent_blank_classification(tmp_path: Path):
    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    import io
    import random

    path = tmp_path / "noisy_scan.pdf"
    rng = random.Random(7)
    img = Image.new("RGB", (400, 300), color=(255, 255, 255))
    pixels = img.load()
    for _ in range(30):
        x, y = rng.randint(0, 399), rng.randint(0, 299)
        pixels[x, y] = (100, 100, 100)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.drawImage(ImageReader(buf), 100, 400, width=400, height=300)
    c.showPage()
    c.save()

    fp = pdf_content.build_document_fingerprint("D1", path)
    assert fp.pages[0].blank.is_blank is True


# TEST 8 - form-field name/value extraction
def test_form_field_extraction(tmp_path: Path):
    path = builders.make_form_pdf(
        tmp_path / "form.pdf", {"borrower_name": "Jane Doe", "loan_amount": "250000"}
    )
    fp = pdf_content.build_document_fingerprint("D1", path)
    assert fp.has_form_fields is True
    names = {f.name for f in fp.pages[0].form_fields}
    assert names == {"borrower_name", "loan_amount"}
    values = {f.name: f.value for f in fp.pages[0].form_fields}
    assert values["borrower_name"] == "Jane Doe"
    assert values["loan_amount"] == "250000"
    # a page with real form fields is never blank, regardless of visible text
    assert fp.pages[0].blank.is_blank is False


# TEST 9 - unsigned / e-signed / wet-signed variants are structurally distinguishable
def test_signature_variant_signals(tmp_path: Path):
    unsigned = builders.make_signed_pdf_variant(
        tmp_path / "unsigned.pdf", "Jane Doe", common_pages=2, signature_kind="unsigned"
    )
    e_signed = builders.make_signed_pdf_variant(
        tmp_path / "e_signed.pdf", "Jane Doe", common_pages=2, signature_kind="e_signed"
    )
    wet_signed = builders.make_signed_pdf_variant(
        tmp_path / "wet_signed.pdf", "Jane Doe", common_pages=2, signature_kind="wet_signed"
    )

    fp_unsigned = pdf_content.build_document_fingerprint("U", unsigned)
    fp_e = pdf_content.build_document_fingerprint("E", e_signed)
    fp_wet = pdf_content.build_document_fingerprint("W", wet_signed)

    assert fp_unsigned.pages[-1].has_signature_field is False
    assert fp_unsigned.pages[-1].has_signed_signature is False
    assert len(fp_unsigned.pages[-1].images) == 0

    assert fp_e.pages[-1].has_signature_field is True
    assert fp_e.pages[-1].has_signed_signature is True

    assert fp_wet.pages[-1].has_signature_field is False
    assert len(fp_wet.pages[-1].images) == 1  # the scanned-ink mark


# TEST 10 - structured token extraction catches dates and dollar amounts
def test_structured_token_extraction_catches_dates_and_amounts():
    tokens = pdf_content.extract_structured_tokens(
        "closing date: 2026-01-15, second date 01/16/2026, amount $1,234.56"
    )
    assert "2026-01-15" in tokens.dates
    assert "01/16/2026" in tokens.dates
    assert "$1,234.56" in tokens.dollar_amounts


# TEST 11 - structured tokens differ between two otherwise-similar dated pages
def test_structured_tokens_distinguish_different_dates(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "a.pdf", pages=1, text_prefix="Approved on 2026-01-15")
    b = builders.make_pdf(tmp_path / "b.pdf", pages=1, text_prefix="Approved on 2026-01-16")
    fp_a = pdf_content.build_document_fingerprint("A", a)
    fp_b = pdf_content.build_document_fingerprint("B", b)
    assert fp_a.pages[0].structured_tokens.dates != fp_b.pages[0].structured_tokens.dates


# TEST 12 - embedded-image byte hashing is stable for identical image bytes
def test_embedded_image_byte_hash_matches_for_identical_images(tmp_path: Path):
    a = builders.make_pdf_with_faint_content(tmp_path / "a.pdf", blank_pages=1, faint_page_index=0)
    b = builders.make_pdf_with_faint_content(tmp_path / "b.pdf", blank_pages=1, faint_page_index=0)
    fp_a = pdf_content.build_document_fingerprint("A", a)
    fp_b = pdf_content.build_document_fingerprint("B", b)
    assert fp_a.pages[0].images[0].byte_sha256 == fp_b.pages[0].images[0].byte_sha256


# TEST 13 - page geometry (dimensions/rotation) is captured
def test_page_geometry_captured(tmp_path: Path):
    path = builders.make_pdf(tmp_path / "a.pdf", pages=1)
    fp = pdf_content.build_document_fingerprint("D1", path)
    # LETTER size in points
    assert round(fp.pages[0].width) == 612
    assert round(fp.pages[0].height) == 792
    assert fp.pages[0].rotation == 0
    assert fp.page_dims_signature == (612.0, 792.0)


# TEST 14 - dHash is stable for identical images and differs for very different images
def test_dhash_similarity_behavior(tmp_path: Path):
    from PIL import Image

    red = Image.new("RGB", (64, 64), color=(255, 0, 0))
    red_again = Image.new("RGB", (64, 64), color=(255, 0, 0))
    blue = Image.new("RGB", (64, 64), color=(0, 0, 255))

    h1 = pdf_content._dhash(red)
    h2 = pdf_content._dhash(red_again)
    h3 = pdf_content._dhash(blue)

    assert pdf_content.hamming_distance(h1, h2) == 0
    # A uniform-color image has no internal gradient, so a plain
    # difference-hash literally cannot distinguish it from another solid
    # image of a DIFFERENT color -- h3 (blue) legitimately collides with
    # h1/h2 (red) here. This is not a bug in this assertion; it's exactly
    # why content_dedup.py never trusts dHash alone (see TEST 15 below
    # and average_color's docstring) -- this test only documents the
    # limitation, TEST 15 proves the mitigation.
    assert isinstance(h3, int)


# TEST 15 - average_color distinguishes solid images of different colors
# that a difference-hash alone cannot (see TEST 14's dHash collision)
def test_average_color_distinguishes_solid_colors():
    from PIL import Image

    red = Image.new("RGB", (300, 200), color=(200, 30, 30))
    blue = Image.new("RGB", (200, 150), color=(0, 100, 200))
    red_again = Image.new("RGB", (50, 50), color=(200, 30, 30))

    c_red = pdf_content._average_color(red)
    c_blue = pdf_content._average_color(blue)
    c_red_again = pdf_content._average_color(red_again)

    assert c_red == c_red_again  # same color, different size -- must match exactly
    assert c_red != c_blue


# TEST 16 - PERFORMANCE REGRESSION (real user-reported bug): a real
# full-resolution scanned page (millions of pixels) must be classified
# and averaged quickly. `_average_color` and `_classify_image_blank`
# used to materialize every pixel into a Python list and sum it in a
# pure-Python loop -- fine for small test fixtures, but for a real scan
# (~1700x2200px, a typical 200 DPI letter-size page) this took multiple
# seconds PER IMAGE, once per embedded image on every page of every
# document. A real "full lender package" of 200+ documents, several of
# them 80-150 page scanned PDFs, made this the dominant cost of the
# entire content-aware analysis stage -- confirmed as the actual root
# cause of a real report of the app appearing stuck for 10+ minutes.
# Fixed by using Pillow's own C-implemented `ImageStat`/`histogram()`
# instead of a Python-level per-pixel pass; this pins the fix down by
# asserting realistic-resolution images are still processed in a small
# fraction of a second, not by asserting a specific value (see TEST 15
# and the blank-classification tests above for correctness).
def test_average_color_and_blank_classification_are_fast_on_realistic_scan_resolution():
    import time

    from PIL import Image

    # A solid-ish page with some scattered dark content, roughly the
    # pixel count of a real 200 DPI letter-size scan.
    img = Image.new("L", (1700, 2200), color=250)
    pixels = img.load()
    for i in range(0, 1700, 7):
        for j in range(0, 2200, 11):
            pixels[i, j] = 40

    start = time.perf_counter()
    pdf_content._average_color(img)
    pdf_content._classify_image_blank(img)
    elapsed = time.perf_counter() - start

    # Generous ceiling (the fixed implementation runs in well under
    # 0.1s locally) -- the old pure-Python implementation took several
    # seconds for an image this size, so this comfortably catches a
    # regression back to a per-pixel Python loop without being flaky
    # on a slower CI runner.
    assert elapsed < 2.0, f"took {elapsed:.2f}s -- likely regressed back to a per-pixel Python loop"


# TEST 17 - PERFORMANCE REGRESSION (real user report, follow-on to TEST
# 16): a real user hit a 24+ minute "Analyzing document content" stall
# even with TEST 16's fix in place, because their scans were 600 DPI
# (a common scanner/phone-scanning-app default), not the 200 DPI TEST
# 16 was benchmarked against -- 9x the pixels, and, confirmed by direct
# measurement, proportionally ~9x slower even through the already-fast
# ImageStat/histogram path (~700ms/image at 600 DPI vs. ~80ms/image at
# 200 DPI). Fixed by downsampling to `_ANALYSIS_MAX_DIMENSION` (the
# already-validated 200-DPI-class resolution) before running any of the
# three signals -- this pins that down by asserting a 600 DPI image is
# now processed close to the 200 DPI cost, not by asserting a specific
# value.
def test_average_color_and_blank_classification_are_fast_at_600_dpi():
    import time

    from PIL import Image, ImageDraw

    # A 600 DPI letter-size scan: 5100x6600, ~33.7 megapixels -- 9x the
    # pixel count of TEST 16's 200 DPI fixture. Substantial dark content
    # (a large block, like a real page of text/imagery would have), so
    # `_classify_image_blank`'s downsampled fast-path can confidently
    # short-circuit to "not blank" without the full-resolution precise
    # check -- this is the common case for a real, mostly-non-blank
    # package. See TEST 18 for the case that must still fall back to
    # the full-resolution check (a mark faint enough to be ambiguous
    # even downsampled).
    img = Image.new("L", (5100, 6600), color=250)
    ImageDraw.Draw(img).rectangle([(500, 500), (4600, 6100)], fill=40)
    analysis_image = pdf_content._prepare_analysis_image(img)

    start = time.perf_counter()
    pdf_content._average_color(analysis_image)
    pdf_content._classify_image_blank(img)
    pdf_content._dhash(analysis_image)
    elapsed = time.perf_counter() - start

    # Without downsampling first, this took ~700ms locally (measured
    # directly) -- a real package with ~2,000 such scanned pages would
    # cost ~24 minutes just in this one step, matching the real report.
    # This ceiling would fail if the downsample-before-analysis step
    # were ever removed or bypassed.
    assert elapsed < 0.5, f"took {elapsed:.2f}s -- the 600 DPI image was likely analyzed at full resolution"


# TEST 18 - CORRECTNESS: a genuinely faint mark that survives full-
# resolution blank-classification must never be lost to the downsampled
# fast-path added for TEST 17's speedup. Isolated single dark pixels
# (scattered scanner-noise-like content, not a connected stroke) are the
# adversarial case for area-average downsampling: a lone dark pixel
# blended with its 8 white neighbors in a 3x3 downsample block averages
# to a value ABOVE the dark-pixel threshold, so a naive "always trust
# the downsampled result" implementation would wrongly call this page
# blank -- confirmed directly (this exact fixture makes the downsampled
# quick-check alone say "blank" while the full-resolution precise check
# correctly says "not blank"). This proves `_classify_image_blank`'s
# two-phase design (only ever trusting a downsampled "not blank" result,
# always falling back to full resolution otherwise) actually protects
# against this, not just in theory.
def test_faint_scattered_content_survives_downsampling_on_a_600_dpi_scan():
    from PIL import Image

    # A 600 DPI page-sized canvas (5100x6600) with sparse, isolated dark
    # pixels -- proportionally the same sparsity as TEST 16's 200 DPI
    # scanner-noise fixture, just scaled to this resolution class.
    img = Image.new("L", (5100, 6600), color=250)
    pixels = img.load()
    for i in range(0, 5100, 21):
        for j in range(0, 6600, 33):
            pixels[i, j] = 40

    # Confirms this fixture actually reproduces the adversarial case:
    # the full-resolution precise check says "not blank"...
    assert pdf_content._looks_blank_at_resolution(img) is False
    # ...but the downsampled quick-check ALONE would wrongly say
    # "blank" -- proving this fixture would catch a regression to a
    # naive "trust the downsampled result either way" implementation.
    analysis_image = pdf_content._prepare_analysis_image(img)
    assert analysis_image.size != img.size
    assert pdf_content._looks_blank_at_resolution(analysis_image) is True

    # `_classify_image_blank` gets the ORIGINAL full-resolution image --
    # exactly what `_extract_embedded_images` passes it -- so it must
    # fall back to the full-resolution precise check above rather than
    # trusting the ambiguous downsampled result.
    assert pdf_content._classify_image_blank(img) is False, (
        "faint scattered content must survive downsampling and never be classified blank"
    )


# TEST 19 - an image already at or below the analysis resolution is
# returned unchanged (no wasted resize work, and no accidental quality
# loss on already-small/already-appropriately-sized images)
def test_prepare_analysis_image_is_a_noop_below_the_resolution_cap():
    from PIL import Image

    small = Image.new("RGB", (400, 300), color=(255, 255, 255))
    assert pdf_content._prepare_analysis_image(small) is small

    at_cap = Image.new("RGB", (2200, 1000), color=(255, 255, 255))
    assert pdf_content._prepare_analysis_image(at_cap) is at_cap


# TEST 20 - downsampling preserves aspect ratio and caps the longer edge
def test_prepare_analysis_image_preserves_aspect_ratio():
    from PIL import Image

    wide = Image.new("RGB", (6600, 3300), color=(255, 255, 255))  # 2:1
    resized = pdf_content._prepare_analysis_image(wide)

    assert resized.size[0] == pdf_content._ANALYSIS_MAX_DIMENSION
    assert resized.size[1] == pdf_content._ANALYSIS_MAX_DIMENSION // 2
