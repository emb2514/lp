from __future__ import annotations

from fixtures.builders import make_pdf

from lender_package_builder.config import AppConfig


def _big_limit_config(page_limit: int = 200, size_limit_mb: float = 5000.0) -> AppConfig:
    cfg = AppConfig()
    cfg.page_limit = page_limit
    cfg.size_limit_mb = size_limit_mb
    return cfg


# TEST 7 - WHOLE-DOCUMENT PAGE SPLITTING
def test_page_splitting_never_splits_a_document(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "a_110pages.pdf", pages=110)
    make_pdf(folder / "b_91pages.pdf", pages=91)
    make_pdf(folder / "c_4pages.pdf", pages=4)

    run = run_build(folder, config=_big_limit_config(page_limit=200))

    assert len(run.og_parts) == 2
    part1, part2 = run.og_parts
    assert part1.page_count == 110
    assert len(part1.document_ids) == 1
    assert part2.page_count == 95
    assert len(part2.document_ids) == 2

    total_pages = sum(p.page_count for p in run.og_parts)
    assert total_pages == 205
    for part in run.og_parts:
        assert not part.is_oversized


# TEST 8 - SINGLE OVERSIZED DOCUMENT BY PAGE COUNT
def test_single_oversized_document_by_page_count(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "huge.pdf", pages=205)

    run = run_build(folder, config=_big_limit_config(page_limit=200))

    assert len(run.og_parts) == 1
    part = run.og_parts[0]
    assert part.page_count == 205
    assert len(part.document_ids) == 1
    assert part.is_oversized is True

    report = (run.output_path / "Reports" / "Processing_Report.txt").read_text()
    assert "OVERSIZED" in report


# TEST 9 - WHOLE-DOCUMENT MB SPLITTING
def test_mb_based_splitting_only_between_documents(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "a_doc.pdf", pages=3, text_prefix="Doc A section")
    make_pdf(folder / "b_doc.pdf", pages=3, text_prefix="Doc B section")
    make_pdf(folder / "c_doc.pdf", pages=3, text_prefix="Doc C section")

    sizes = [(folder / n).stat().st_size for n in ("a_doc.pdf", "b_doc.pdf", "c_doc.pdf")]
    avg = sum(sizes) / len(sizes)
    size_limit_mb = (avg * 2.3) / (1024 * 1024)

    run = run_build(folder, config=_big_limit_config(page_limit=10_000, size_limit_mb=size_limit_mb))

    assert len(run.og_parts) == 2
    assert len(run.og_parts[0].document_ids) == 2
    assert len(run.og_parts[1].document_ids) == 1
    assert sum(p.page_count for p in run.og_parts) == 9
    for part in run.og_parts:
        assert not part.is_oversized


# TEST 10 - SINGLE OVERSIZED DOCUMENT BY SIZE
def test_single_oversized_document_by_size(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "big.pdf", pages=5, text_prefix="Oversized by size")
    size = (folder / "big.pdf").stat().st_size

    size_limit_mb = (size * 0.5) / (1024 * 1024)  # smaller than the document itself

    run = run_build(folder, config=_big_limit_config(page_limit=10_000, size_limit_mb=size_limit_mb))

    assert len(run.og_parts) == 1
    part = run.og_parts[0]
    assert len(part.document_ids) == 1
    assert part.is_oversized is True

    report = (run.output_path / "Reports" / "Processing_Report.txt").read_text()
    assert "OVERSIZED" in report
