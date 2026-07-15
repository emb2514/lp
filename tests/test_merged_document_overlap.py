"""Tests for overlap_detection.py -- merged-document containment
detection. Builds real merged PDFs via make_merged_pdf/
make_merged_pdf_with_gap and drives content_dedup.py + overlap_detection.py
together, since overlap detection only ever runs over occurrences not
already resolved by the cheaper exact-hash/content-aware passes.
"""

from __future__ import annotations

from pathlib import Path

from fixtures import builders

from lender_package_builder import content_dedup, overlap_detection, pdf_content
from lender_package_builder.models import ProcessingStatus, SourceOccurrence


def _occ(doc_id: str, traversal_index: int, pdf_path: Path) -> SourceOccurrence:
    fp = pdf_content.build_document_fingerprint(doc_id, pdf_path)
    return SourceOccurrence(
        document_id=doc_id,
        traversal_index=traversal_index,
        original_filename=pdf_path.name,
        original_relative_path=pdf_path.name,
        original_extension=".pdf",
        original_size_bytes=pdf_path.stat().st_size,
        status=ProcessingStatus.CONVERTED,
        converted_pdf_path=pdf_path,
        converted_page_count=len(fp.pages),
    )


def _run(occurrences: list[SourceOccurrence]):
    fingerprints = content_dedup.build_fingerprints(occurrences)
    content_dedup.detect_content_duplicates(occurrences, fingerprints)
    findings = overlap_detection.detect_overlaps(occurrences, fingerprints)
    return findings


# TEST 1 - a large merged PDF plus all of its identical standalone
# components -> only one copy of each logical document version in Final
def test_merged_plus_identical_standalone_components(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "component_a.pdf", pages=2, text_prefix="Component A Content")
    b = builders.make_pdf(tmp_path / "component_b.pdf", pages=3, text_prefix="Component B Content")
    merged = builders.make_merged_pdf(tmp_path / "merged.pdf", [a, b])

    occ_a, occ_b, occ_merged = _occ("A", 1, a), _occ("B", 2, b), _occ("M", 3, merged)
    _run([occ_a, occ_b, occ_merged])

    assert occ_a.is_contained_in_merged_document is True
    assert occ_a.contained_in_document_id == "M"
    assert occ_b.is_contained_in_merged_document is True
    assert occ_b.contained_in_document_id == "M"
    # the merged PDF itself is NEVER excluded -- it holds all the content
    assert occ_merged.is_contained_in_merged_document is False


# TEST 2 - merged PDF contains an unsigned version, a separately supplied
# signed version exists -> both retained (unsigned stays inside the
# merged PDF untouched, signed standalone is never proven contained)
def test_merged_unsigned_plus_separate_signed_both_retained(tmp_path: Path):
    unsigned = builders.make_signed_pdf_variant(
        tmp_path / "unsigned_in_merge.pdf", "Jane Doe", common_pages=2, signature_kind="unsigned"
    )
    signed = builders.make_signed_pdf_variant(
        tmp_path / "signed_standalone.pdf", "Jane Doe", common_pages=2, signature_kind="e_signed"
    )
    filler = builders.make_pdf(tmp_path / "filler.pdf", pages=2, text_prefix="Unrelated filler")
    merged = builders.make_merged_pdf(tmp_path / "merged.pdf", [unsigned, filler])

    occ_signed, occ_merged = _occ("SIGNED", 1, signed), _occ("MERGED", 2, merged)
    _run([occ_signed, occ_merged])

    assert occ_signed.is_contained_in_merged_document is False
    assert occ_merged.is_contained_in_merged_document is False


# TEST 3 - merged PDF contains unique content not supplied separately ->
# that content remains in Final (the merged PDF is never discarded)
def test_merged_with_unique_content_retained(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "component_a.pdf", pages=2, text_prefix="Component A Content")
    unique = builders.make_pdf(tmp_path / "unique_only_in_merge.pdf", pages=2, text_prefix="Unique Content Never Supplied Separately")
    merged = builders.make_merged_pdf(tmp_path / "merged.pdf", [a, unique])

    occ_a, occ_merged = _occ("A", 1, a), _occ("MERGED", 2, merged)
    _run([occ_a, occ_merged])

    assert occ_a.is_contained_in_merged_document is True
    # merged PDF is never excluded regardless -- its unique content
    # (the "unique" component) has no separate standalone copy to
    # even compare against, so it simply stays in Final via the merged
    # PDF's own presence.
    assert occ_merged.is_contained_in_merged_document is False


# TEST 4 - partial overlap between a standalone document and a merged PDF
# -> no unsafe automatic removal
def test_partial_overlap_no_unsafe_removal(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "component_a.pdf", pages=2, text_prefix="Component A Content")
    b = builders.make_pdf(tmp_path / "component_b.pdf", pages=3, text_prefix="Component B Content")
    gap = builders.make_pdf(tmp_path / "gap.pdf", pages=1, text_prefix="Unrelated Gap Content")
    combined = builders.make_merged_pdf(tmp_path / "combined.pdf", [a, b])
    merged_with_gap = builders.make_merged_pdf_with_gap(tmp_path / "merged_gap.pdf", [a, b], [gap])

    occ_combined, occ_merged_gap = _occ("COMBINED", 1, combined), _occ("MERGEDGAP", 2, merged_with_gap)
    _run([occ_combined, occ_merged_gap])

    assert occ_combined.is_contained_in_merged_document is False
    assert occ_combined.needs_review is False or occ_combined.is_contained_in_merged_document is False


# TEST 5 - a document fully contained in one merged PDF is never
# "double counted" against a second, unrelated merged PDF. Each merged
# PDF has genuinely MORE content than the single component being tested
# for containment -- a merged PDF containing only exactly one component
# is indistinguishable from a plain duplicate of that component (and is
# correctly caught by content_dedup.py instead; see
# test_exact_duplicates_excluded_from_overlap_candidate_pool below for
# that boundary case), so it would not exercise containment logic at all.
def test_containment_is_per_container_not_chained(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "a.pdf", pages=2, text_prefix="Content A")
    b = builders.make_pdf(tmp_path / "b.pdf", pages=2, text_prefix="Content B")
    filler_1 = builders.make_pdf(tmp_path / "filler1.pdf", pages=2, text_prefix="Filler One")
    filler_2 = builders.make_pdf(tmp_path / "filler2.pdf", pages=2, text_prefix="Filler Two")
    merged_1 = builders.make_merged_pdf(tmp_path / "merged1.pdf", [a, filler_1])
    merged_2 = builders.make_merged_pdf(tmp_path / "merged2.pdf", [b, filler_2])

    occ_a = _occ("A", 1, a)
    occ_b = _occ("B", 2, b)
    occ_m1 = _occ("M1", 3, merged_1)
    occ_m2 = _occ("M2", 4, merged_2)
    _run([occ_a, occ_b, occ_m1, occ_m2])

    assert occ_a.is_contained_in_merged_document is True
    assert occ_a.contained_in_document_id == "M1"
    assert occ_b.is_contained_in_merged_document is True
    assert occ_b.contained_in_document_id == "M2"


# TEST 6 - documents already resolved by exact-hash dedup are excluded
# from the overlap candidate pool entirely (no redundant work, no
# conflicting decisions)
def test_exact_duplicates_excluded_from_overlap_candidate_pool(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "a.pdf", pages=2, text_prefix="Content A")
    a_dup = builders.make_pdf(tmp_path / "a_dup.pdf", pages=2, text_prefix="Content A")
    merged = builders.make_merged_pdf(tmp_path / "merged.pdf", [a])

    occ_a = _occ("A", 1, a)
    occ_a_dup = _occ("A_DUP", 2, a_dup)
    occ_a_dup.is_duplicate = True
    occ_a_dup.duplicate_of_document_id = "A"
    occ_merged = _occ("MERGED", 3, merged)

    fingerprints = content_dedup.build_fingerprints([occ_a, occ_a_dup, occ_merged])
    assert "A_DUP" not in fingerprints
    findings = overlap_detection.detect_overlaps([occ_a, occ_a_dup, occ_merged], fingerprints)
    assert all(f.standalone_document_id != "A_DUP" for f in findings)


# TEST 7 - a standalone document larger than any candidate container never crashes
def test_no_candidate_container_available(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "a.pdf", pages=5, text_prefix="Large standalone")
    b = builders.make_pdf(tmp_path / "b.pdf", pages=1, text_prefix="Small standalone")
    occ_a, occ_b = _occ("A", 1, a), _occ("B", 2, b)
    findings = _run([occ_a, occ_b])
    assert occ_a.is_contained_in_merged_document is False
    assert occ_b.is_contained_in_merged_document is False
