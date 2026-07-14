from __future__ import annotations

import time

from fixtures.builders import make_pdf

from lender_package_builder.config import AppConfig


def _big_max_config(max_pages_per_part: int = 750, max_size_mb_per_part: float = 5000.0) -> AppConfig:
    cfg = AppConfig()
    cfg.max_pages_per_part = max_pages_per_part
    cfg.max_size_mb_per_part = max_size_mb_per_part
    return cfg


def _all_document_ids(parts) -> list[str]:
    return [doc_id for part in parts for doc_id in part.document_ids]


# Maximum-constraint page splitting using the exact walkthrough from the
# revised spec: max=400 pages, documents of 125/98/162/41 pages.
# Required: Part 1 = first three documents (385 pages, below the 400
# maximum -- it is never padded to reach it). Part 2 = the fourth
# document alone (41 pages). Forbidden: taking 15 pages from document 4
# to pad Part 1 to exactly 400.
def test_page_maximum_is_a_ceiling_not_a_target(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "a_125pages.pdf", pages=125)
    make_pdf(folder / "b_98pages.pdf", pages=98)
    make_pdf(folder / "c_162pages.pdf", pages=162)
    make_pdf(folder / "d_41pages.pdf", pages=41)

    run = run_build(folder, config=_big_max_config(max_pages_per_part=400))

    assert len(run.og_parts) == 2
    part1, part2 = run.og_parts

    assert len(part1.document_ids) == 3
    assert part1.page_count == 385  # 125 + 98 + 162, well below the 400 maximum
    assert part1.page_count < 400  # never padded to reach the maximum

    assert len(part2.document_ids) == 1
    assert part2.page_count == 41

    total_pages = sum(p.page_count for p in run.og_parts)
    assert total_pages == 125 + 98 + 162 + 41
    for part in run.og_parts:
        assert not part.is_oversized
    assert "page_maximum" in part1.close_reasons
    assert "end_of_package" in part2.close_reasons


# A next document that would exceed the page maximum forces a new part,
# even though the current part is nowhere near the maximum in size.
def test_next_document_exceeding_page_maximum_starts_new_part(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "a_10pages.pdf", pages=10)
    make_pdf(folder / "b_95pages.pdf", pages=95)  # 10 + 95 = 105 > 100 maximum

    run = run_build(folder, config=_big_max_config(max_pages_per_part=100))

    assert len(run.og_parts) == 2
    assert run.og_parts[0].page_count == 10
    assert run.og_parts[1].page_count == 95
    assert "page_maximum" in run.og_parts[0].close_reasons


# A next document that would exceed the MB maximum forces a new part,
# confirmed with real files and a dynamically measured threshold.
def test_next_document_exceeding_size_maximum_starts_new_part(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "a_doc.pdf", pages=3, text_prefix="Doc A section")
    make_pdf(folder / "b_doc.pdf", pages=3, text_prefix="Doc B section")
    make_pdf(folder / "c_doc.pdf", pages=3, text_prefix="Doc C section")

    sizes = [(folder / n).stat().st_size for n in ("a_doc.pdf", "b_doc.pdf", "c_doc.pdf")]
    avg = sum(sizes) / len(sizes)
    max_size_mb = (avg * 2.3) / (1024 * 1024)

    run = run_build(folder, config=_big_max_config(max_pages_per_part=10_000, max_size_mb_per_part=max_size_mb))

    assert len(run.og_parts) == 2
    assert len(run.og_parts[0].document_ids) == 2
    assert len(run.og_parts[1].document_ids) == 1
    assert sum(p.page_count for p in run.og_parts) == 9
    for part in run.og_parts:
        assert not part.is_oversized
    assert "size_maximum" in run.og_parts[0].close_reasons


# Parts are expected to vary in size and finish naturally below the
# maximum when the package simply runs out of documents -- not every
# part closes because of a constraint.
def test_final_part_naturally_finishes_below_maximum_with_few_pages(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "a_300pages.pdf", pages=300)
    make_pdf(folder / "b_3pages.pdf", pages=3)  # tiny trailing document

    run = run_build(folder, config=_big_max_config(max_pages_per_part=750))

    assert len(run.og_parts) == 1  # both fit comfortably under 750
    part = run.og_parts[0]
    assert part.page_count == 303
    assert part.page_count < 750
    assert "end_of_package" in part.close_reasons


# TEST 8 - SINGLE OVERSIZED DOCUMENT BY PAGE COUNT
def test_single_oversized_document_by_page_count(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "huge.pdf", pages=205)

    run = run_build(folder, config=_big_max_config(max_pages_per_part=200))

    assert len(run.og_parts) == 1
    part = run.og_parts[0]
    assert part.page_count == 205
    assert len(part.document_ids) == 1
    assert part.is_oversized is True
    assert "oversized_document" in part.close_reasons

    report = (run.output_path / "Reports" / "Processing_Report.txt").read_text()
    assert "OVERSIZED" in report


# TEST 10 - SINGLE OVERSIZED DOCUMENT BY SIZE
def test_single_oversized_document_by_size(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "big.pdf", pages=5, text_prefix="Oversized by size")
    size = (folder / "big.pdf").stat().st_size

    max_size_mb = (size * 0.5) / (1024 * 1024)  # smaller than the document itself

    run = run_build(folder, config=_big_max_config(max_pages_per_part=10_000, max_size_mb_per_part=max_size_mb))

    assert len(run.og_parts) == 1
    part = run.og_parts[0]
    assert len(part.document_ids) == 1
    assert part.is_oversized is True

    report = (run.output_path / "Reports" / "Processing_Report.txt").read_text()
    assert "OVERSIZED" in report


# No document ever crosses an output-part boundary, across OG and Final.
def test_no_document_crosses_part_boundaries(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "a_125pages.pdf", pages=125)
    make_pdf(folder / "b_98pages.pdf", pages=98)
    make_pdf(folder / "c_162pages.pdf", pages=162)
    make_pdf(folder / "d_41pages.pdf", pages=41)

    run = run_build(folder, config=_big_max_config(max_pages_per_part=400))

    for parts in (run.og_parts, run.final_parts):
        seen: set[str] = set()
        for part in parts:
            for doc_id in part.document_ids:
                assert doc_id not in seen, f"{doc_id} appeared in more than one part"
                seen.add(doc_id)


# A package with no exact duplicates: OG and Final page/document counts
# must fully reconcile with the source documents, using non-200 limits.
def test_og_and_final_page_count_reconciliation(tmp_path, run_build):
    folder = tmp_path / "input"
    page_counts = [125, 98, 162, 41, 300, 12]
    for i, pages in enumerate(page_counts):
        make_pdf(folder / f"doc_{i}_{pages}pages.pdf", pages=pages)

    run = run_build(folder, config=_big_max_config(max_pages_per_part=333, max_size_mb_per_part=50))

    expected_total = sum(page_counts)
    assert sum(p.page_count for p in run.og_parts) == expected_total
    assert sum(p.page_count for p in run.final_parts) == expected_total  # no duplicates in this fixture
    assert sum(len(p.document_ids) for p in run.og_parts) == len(page_counts)
    assert sum(len(p.document_ids) for p in run.final_parts) == len(page_counts)

    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"


# The engine must handle a package totaling at least 3,000 pages across
# many separate source documents -- the total input page count must
# never be treated as an output-part limit; it just creates as many
# parts as necessary.
def test_large_package_totaling_at_least_3000_pages(tmp_path, run_build):
    folder = tmp_path / "input"
    # 40 documents x 80 pages = 3200 pages total, comfortably over 3,000,
    # spread across many separate source documents (not one giant file).
    doc_pages = 80
    doc_count = 40
    for i in range(doc_count):
        make_pdf(folder / f"doc_{i:03d}.pdf", pages=doc_pages, text_prefix=f"Document {i}")

    total_pages = doc_pages * doc_count
    assert total_pages >= 3000

    cfg = _big_max_config(max_pages_per_part=750, max_size_mb_per_part=100)
    start = time.perf_counter()
    run = run_build(folder, config=cfg)
    elapsed = time.perf_counter() - start

    assert sum(p.page_count for p in run.og_parts) == total_pages
    assert sum(p.page_count for p in run.final_parts) == total_pages
    assert sum(len(p.document_ids) for p in run.og_parts) == doc_count

    # The 750-page maximum must have produced multiple parts rather than
    # one giant part or one part per document.
    assert 1 < len(run.og_parts) < doc_count
    for part in run.og_parts:
        assert part.page_count <= 750 or part.is_oversized

    # No document was split: every part's actual page count equals the
    # sum of its documents' recorded page counts (also re-verified
    # independently by the integrity checks below).
    for part in run.og_parts:
        assert part.page_count % doc_pages == 0 or len(part.document_ids) == 1

    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"

    assert run.success is True
    assert elapsed < 120, f"3000+ page package took too long: {elapsed:.1f}s"
