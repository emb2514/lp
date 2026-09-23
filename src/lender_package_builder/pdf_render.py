"""Last-tier, most-expensive PDF page comparison: rasterizes specific
still-ambiguous pages to images and compares them perceptually.

This is the ONLY module in the engine that imports `pypdfium2`, and is
deliberately isolated and thin: `content_dedup.py`'s staged comparison
pipeline (SHA-256 -> structural bucketing -> normalized text/form/
annotation fingerprints -> page-level content fingerprints) only ever
calls into this module for the small number of page pairs that remain
genuinely ambiguous after every cheaper signal has been exhausted (e.g.
a scanned page with no reliable extractable text). Keeping it isolated
also makes it easy to verify in tests that it is genuinely invoked
rarely, by monkeypatching its public functions and counting calls.

Perceptual comparison reuses `pdf_content._dhash`/`hamming_distance`
(a plain Pillow-only difference-hash) rather than a separate algorithm,
so a rendered page and an embedded-image fingerprint are directly
comparable using the same distance function.
"""

from __future__ import annotations

import functools
import io
from pathlib import Path

import pypdfium2 as pdfium

from .pdf_content import hamming_distance, _dhash

# 64-bit dHash: a Hamming distance of 0 is identical, 64 is maximally
# different. This similarity threshold is a starting default for
# content_dedup.py's blended text+visual scoring, flagged for empirical
# tuning against real scanned lender documents.
_MAX_HAMMING_DISTANCE = 64

# GUI thumbnail cache: bounded (unlike the comparison dHash cache above,
# an actual PNG per entry costs real memory) but big enough to hold a
# full Compare Packages grid for a typical multi-hundred-page package
# without repeated re-rendering as the user scrolls back and forth.
_THUMBNAIL_CACHE_SIZE = 600


@functools.lru_cache(maxsize=512)
def _render_cached(pdf_path_str: str, page_index: int, dpi: int) -> int:
    scale = dpi / 72.0
    pdf = pdfium.PdfDocument(pdf_path_str)
    try:
        page = pdf[page_index]
        try:
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
        finally:
            page.close()
    finally:
        pdf.close()
    return _dhash(pil_image)


def render_page_to_hash(pdf_path: Path, page_index: int, dpi: int = 100) -> int:
    """Renders one page to an image and returns its perceptual hash.

    Cached per (path, page index, dpi) for the lifetime of the process --
    repeated pairwise comparisons touching the same page (e.g. one
    candidate compared against several containers during merged-document
    overlap analysis) never re-render it.
    """

    return _render_cached(str(pdf_path), page_index, dpi)


def compare_rendered_pages(hash_a: int, hash_b: int) -> float:
    """Normalized similarity in [0.0, 1.0] from two perceptual hashes;
    1.0 means identical, 0.0 means maximally different.
    """

    distance = hamming_distance(hash_a, hash_b)
    return 1.0 - (distance / _MAX_HAMMING_DISTANCE)


def clear_render_cache() -> None:
    """Test/diagnostic hook -- also useful between independent runs in
    the same long-lived process (e.g. the GUI) so cached bitmaps from a
    prior run's temporary workspace (since deleted) are never reused.
    """

    _render_cached.cache_clear()
    _render_thumbnail_cached.cache_clear()


@functools.lru_cache(maxsize=_THUMBNAIL_CACHE_SIZE)
def _render_thumbnail_cached(pdf_path_str: str, page_index: int, max_dimension_px: int) -> bytes:
    pdf = pdfium.PdfDocument(pdf_path_str)
    try:
        page = pdf[page_index]
        try:
            width_pt, height_pt = page.get_size()
            longest_side = max(width_pt, height_pt, 1.0)
            scale = max_dimension_px / longest_side
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
        finally:
            page.close()
    finally:
        pdf.close()

    buf = io.BytesIO()
    pil_image.save(buf, format="PNG")
    return buf.getvalue()


def render_page_thumbnail_png(pdf_path: Path, page_index: int, max_dimension_px: int = 160) -> bytes:
    """Renders one page to a small PNG-encoded thumbnail, for GUI
    display only -- this is a display concern, never used for
    comparison (see `render_page_to_hash` for that). Returns raw PNG
    bytes rather than a Qt type so this engine module never imports Qt;
    the GUI layer hands the bytes straight to `QPixmap.loadFromData`.

    Cached per (path, page index, size) for the process lifetime, same
    reasoning as `render_page_to_hash` -- a Compare Packages grid
    re-rendering or a page revisited while scrolling never re-decodes
    the source PDF.
    """

    return _render_thumbnail_cached(str(pdf_path), page_index, max_dimension_px)
