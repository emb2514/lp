"""Tests for pdf_render.py -- the isolated, last-tier page-rasterization
comparison module. Deliberately kept small: this module should be
invoked rarely by content_dedup.py (only for genuinely ambiguous
candidates), so the important properties to test are correctness of the
comparison itself and that it's easy to observe/mock call counts from
higher-level tests.
"""

from __future__ import annotations

from pathlib import Path

from fixtures import builders

from lender_package_builder import pdf_render


# TEST 1 - identical rendered pages have similarity 1.0
def test_identical_pages_have_similarity_one(tmp_path: Path):
    a = builders.make_scanned_like_pdf(tmp_path / "a.pdf", pages=1, image_seed=1)
    b = builders.make_scanned_like_pdf(tmp_path / "b.pdf", pages=1, image_seed=1)
    h_a = pdf_render.render_page_to_hash(a, 0)
    h_b = pdf_render.render_page_to_hash(b, 0)
    assert pdf_render.compare_rendered_pages(h_a, h_b) == 1.0


# TEST 2 - visually different pages have lower similarity
def test_different_pages_have_lower_similarity(tmp_path: Path):
    a = builders.make_scanned_like_pdf(tmp_path / "a.pdf", pages=1, image_seed=1)
    c = builders.make_scanned_like_pdf(tmp_path / "c.pdf", pages=1, image_seed=999)
    h_a = pdf_render.render_page_to_hash(a, 0)
    h_c = pdf_render.render_page_to_hash(c, 0)
    assert pdf_render.compare_rendered_pages(h_a, h_c) < 1.0


# TEST 3 - repeated calls for the same page are cached (same hash, no crash on reuse)
def test_render_page_to_hash_is_cached(tmp_path: Path):
    a = builders.make_scanned_like_pdf(tmp_path / "a.pdf", pages=1, image_seed=1)
    h1 = pdf_render.render_page_to_hash(a, 0)
    h2 = pdf_render.render_page_to_hash(a, 0)
    assert h1 == h2
    info = pdf_render._render_cached.cache_info()
    assert info.hits >= 1


# TEST 4 - multi-page documents render each page independently
def test_multipage_document_renders_each_page(tmp_path: Path):
    a = builders.make_scanned_like_pdf(tmp_path / "a.pdf", pages=3, image_seed=5)
    hashes = [pdf_render.render_page_to_hash(a, i) for i in range(3)]
    assert len(hashes) == 3


# TEST 5 - the render tier is mockable for higher-level "invoked rarely" assertions
def test_render_functions_are_mockable(tmp_path: Path, monkeypatch):
    calls = []

    def fake_render(pdf_path, page_index, dpi=100):
        calls.append((pdf_path, page_index))
        return 0

    monkeypatch.setattr(pdf_render, "render_page_to_hash", fake_render)
    pdf_render.render_page_to_hash(tmp_path / "whatever.pdf", 0)
    assert calls == [(tmp_path / "whatever.pdf", 0)]
