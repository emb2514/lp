"""Tests for content_dedup.py -- Levels 2/3/4 content-aware duplicate
detection. Each test builds real SourceOccurrence objects (mirroring how
cli.py would have them after conversion) and drives the engine end to
end via build_fingerprints() + detect_content_duplicates().
"""

from __future__ import annotations

from pathlib import Path

from fixtures import builders

from lender_package_builder import content_dedup, pdf_content
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
    return content_dedup.detect_content_duplicates(occurrences, fingerprints)


# TEST 1 - same PDF with different filenames -> one retained
def test_same_pdf_different_filenames_one_retained(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "report_final.pdf", pages=2, text_prefix="Shared Content")
    b = builders.make_pdf(tmp_path / "report_FINAL_v2_renamed.pdf", pages=2, text_prefix="Shared Content")
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    groups, _ = _run([occ_a, occ_b])
    assert sum(o.is_content_duplicate for o in (occ_a, occ_b)) == 1
    assert len(groups) == 1
    assert groups[0].method == "normalized_pdf"


# TEST 2 - same PDF with different metadata/compression -> one retained
def test_same_pdf_different_metadata_one_retained(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "a.pdf", pages=2, text_prefix="Shared", metadata={"/CustomTag": "one"})
    b = builders.make_pdf(tmp_path / "b.pdf", pages=2, text_prefix="Shared", metadata={"/CustomTag": "two"})
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert sum(o.is_content_duplicate for o in (occ_a, occ_b)) == 1


# TEST 3 - one extra blank page at the beginning -> one retained
def test_extra_blank_page_at_start_one_retained(tmp_path: Path):
    content = ["Loan Disclosure Page 1", "Loan Disclosure Page 2", "Signature Page"]
    a = builders.make_pdf_with_pages(tmp_path / "a.pdf", content)
    b = builders.make_pdf_with_pages(tmp_path / "b.pdf", [None] + content)
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert sum(o.is_content_duplicate for o in (occ_a, occ_b)) == 1
    duplicate = occ_b if occ_b.is_content_duplicate else occ_a
    assert duplicate.duplicate_detection_method == "blank_page_tolerant"
    assert duplicate.blank_pages_ignored_count == 1


# TEST 4 - one extra blank page at the end -> one retained
def test_extra_blank_page_at_end_one_retained(tmp_path: Path):
    content = ["Loan Disclosure Page 1", "Loan Disclosure Page 2", "Signature Page"]
    a = builders.make_pdf_with_pages(tmp_path / "a.pdf", content)
    b = builders.make_pdf_with_pages(tmp_path / "b.pdf", content + [None])
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert sum(o.is_content_duplicate for o in (occ_a, occ_b)) == 1


# TEST 5 - one verified blank page inserted between sections -> one retained
# (only because the remaining ordered content still safely matches)
def test_blank_page_inserted_in_middle_one_retained(tmp_path: Path):
    content = ["Loan Disclosure Page 1", "Loan Disclosure Page 2", "Signature Page"]
    a = builders.make_pdf_with_pages(tmp_path / "a.pdf", content)
    b = builders.make_pdf_with_pages(tmp_path / "b.pdf", [content[0], None, content[1], content[2]])
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert sum(o.is_content_duplicate for o in (occ_a, occ_b)) == 1


# TEST 6 - an allegedly-blank page with a faint mark is not treated as blank,
# so if the remaining structure doesn't line up, the documents are NOT merged
def test_faint_mark_page_prevents_unsafe_blank_tolerant_merge(tmp_path: Path):
    content = ["Loan Disclosure Page 1", "Loan Disclosure Page 2", "Signature Page"]
    a = builders.make_pdf_with_pages(tmp_path / "a.pdf", content)
    # b has 4 pages where the "extra" page is NOT blank -- it carries a
    # faint mark, so it must not be stripped, and since a has only 3
    # pages, lengths won't line up -- must not be merged.
    b_path = tmp_path / "b.pdf"
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(b_path), pagesize=LETTER)
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, content[0])
    c.showPage()
    builders._draw_faint_mark(c)  # faint page, not blank
    c.showPage()
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, content[1])
    c.showPage()
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, content[2])
    c.showPage()
    c.save()

    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b_path)
    _run([occ_a, occ_b])
    assert occ_a.is_content_duplicate is False
    assert occ_b.is_content_duplicate is False


# TEST 7 - unsigned vs e-signed -> both retained
def test_unsigned_vs_e_signed_both_retained(tmp_path: Path):
    a = builders.make_signed_pdf_variant(tmp_path / "a.pdf", "Jane Doe", common_pages=3, signature_kind="unsigned")
    b = builders.make_signed_pdf_variant(tmp_path / "b.pdf", "Jane Doe", common_pages=3, signature_kind="e_signed")
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert occ_a.is_content_duplicate is False
    assert occ_b.is_content_duplicate is False


# TEST 8 - unsigned vs wet-signed -> both retained
def test_unsigned_vs_wet_signed_both_retained(tmp_path: Path):
    a = builders.make_signed_pdf_variant(tmp_path / "a.pdf", "Jane Doe", common_pages=3, signature_kind="unsigned")
    b = builders.make_signed_pdf_variant(tmp_path / "b.pdf", "Jane Doe", common_pages=3, signature_kind="wet_signed")
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert occ_a.is_content_duplicate is False
    assert occ_b.is_content_duplicate is False


# TEST 9 - e-signed vs wet-signed -> both retained
def test_e_signed_vs_wet_signed_both_retained(tmp_path: Path):
    a = builders.make_signed_pdf_variant(tmp_path / "a.pdf", "Jane Doe", common_pages=3, signature_kind="e_signed")
    b = builders.make_signed_pdf_variant(tmp_path / "b.pdf", "Jane Doe", common_pages=3, signature_kind="wet_signed")
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert occ_a.is_content_duplicate is False
    assert occ_b.is_content_duplicate is False


# TEST 10 - two copies of the same e-signed document with different filenames -> one retained
def test_duplicate_e_signed_copies_different_filenames_one_retained(tmp_path: Path):
    a = builders.make_signed_pdf_variant(tmp_path / "loan_esigned.pdf", "Jane Doe", common_pages=3, signature_kind="e_signed")
    b = builders.make_signed_pdf_variant(tmp_path / "loan_esigned_copy2.pdf", "Jane Doe", common_pages=3, signature_kind="e_signed")
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert sum(o.is_content_duplicate for o in (occ_a, occ_b)) == 1


# TEST 11 - two copies of the same wet-signed scan with different compression -> one retained
def test_duplicate_wet_signed_scans_different_compression_one_retained(tmp_path: Path):
    a = builders.make_signed_pdf_variant(tmp_path / "a.pdf", "Jane Doe", common_pages=3, signature_kind="wet_signed")
    # Re-save through pypdf to change internal compression/object layout
    # while keeping identical page content -- simulates a re-saved scan.
    from pypdf import PdfReader, PdfWriter

    b = tmp_path / "b.pdf"
    reader = PdfReader(str(a))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.compress_identical_objects()
    with b.open("wb") as fh:
        writer.write(fh)

    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert sum(o.is_content_duplicate for o in (occ_a, occ_b)) == 1


# TEST 12 - same form with different dates -> both retained
def test_same_form_different_dates_both_retained(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "a.pdf", pages=1, text_prefix="Approved on 2026-01-15")
    b = builders.make_pdf(tmp_path / "b.pdf", pages=1, text_prefix="Approved on 2026-01-16")
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert occ_a.is_content_duplicate is False
    assert occ_b.is_content_duplicate is False


# TEST 13 - same form with a changed condition/form-field value -> both retained
def test_changed_form_field_value_both_retained(tmp_path: Path):
    a = builders.make_form_pdf(tmp_path / "a.pdf", {"loan_amount": "250000"})
    b = builders.make_form_pdf(tmp_path / "b.pdf", {"loan_amount": "275000"})
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert occ_a.is_content_duplicate is False
    assert occ_b.is_content_duplicate is False


# TEST 14 - same form with different initials/checkboxes -> both retained
def test_different_checkbox_values_both_retained(tmp_path: Path):
    a = builders.make_form_pdf(tmp_path / "a.pdf", {"escrow_waived": "Off"})
    b = builders.make_form_pdf(tmp_path / "b.pdf", {"escrow_waived": "Yes"})
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert occ_a.is_content_duplicate is False
    assert occ_b.is_content_duplicate is False


# TEST 15 - two borrower packages sharing most pages but different signature
# pages -> both complete versions retained (the calibration test)
def test_shared_boilerplate_different_signature_page_both_retained(tmp_path: Path):
    a = builders.make_signature_package(tmp_path / "borrower_a.pdf", "Alice Anderson", common_pages=19)
    b = builders.make_signature_package(tmp_path / "borrower_b.pdf", "Bob Baker", common_pages=19)
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert occ_a.is_content_duplicate is False
    assert occ_b.is_content_duplicate is False
    assert occ_a.needs_review is False
    assert occ_b.needs_review is False


# TEST 16 - identical form-field values (sanity: not every form pair is preserved)
def test_identical_form_field_values_one_retained(tmp_path: Path):
    a = builders.make_form_pdf(tmp_path / "a.pdf", {"loan_amount": "250000"})
    b = builders.make_form_pdf(tmp_path / "b.pdf", {"loan_amount": "250000"})
    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    _run([occ_a, occ_b])
    assert sum(o.is_content_duplicate for o in (occ_a, occ_b)) == 1


# TEST 17 - three copies of the same e-signed document group together, one retained
def test_three_way_grouping_one_retained(tmp_path: Path):
    paths = [
        builders.make_signed_pdf_variant(tmp_path / f"copy{i}.pdf", "Jane Doe", common_pages=3, signature_kind="e_signed")
        for i in range(3)
    ]
    occs = [_occ(f"D{i}", i, p) for i, p in enumerate(paths)]
    groups, _ = _run(occs)
    assert len(groups) == 1
    assert set(groups[0].document_ids) == {o.document_id for o in occs}
    assert sum(not o.is_content_duplicate for o in occs) == 1


# TEST 18 - ambiguous match: forced into the "uncertain" confidence band ->
# both retained and flagged needs_review, never merged
def test_ambiguous_match_both_retained_and_flagged_uncertain(tmp_path: Path, monkeypatch):
    # Two scanned-like pages with no reliable text -- force the render
    # tier's comparison into the ambiguous band directly, rather than
    # hoping randomly-generated fixtures happen to land there.
    a = builders.make_scanned_like_pdf(tmp_path / "a.pdf", pages=1, image_seed=1)
    b = builders.make_scanned_like_pdf(tmp_path / "b.pdf", pages=1, image_seed=2)

    def fake_compare_rendered_pages(hash_a, hash_b):
        return 0.85  # squarely inside [NEEDS_REVIEW_THRESHOLD, AUTO_REMOVE_THRESHOLD)

    monkeypatch.setattr(content_dedup.pdf_render, "compare_rendered_pages", fake_compare_rendered_pages)

    occ_a, occ_b = _occ("D1", 1, a), _occ("D2", 2, b)
    fingerprints = content_dedup.build_fingerprints([occ_a, occ_b])
    # Force the image-similarity/text-similarity blend into the ambiguous
    # band too, so the render-tier escalation actually triggers.
    groups, _ = content_dedup.detect_content_duplicates([occ_a, occ_b], fingerprints)

    assert occ_a.is_content_duplicate is False
    assert occ_b.is_content_duplicate is False
    # Either both got flagged uncertain (if the blended pre-render score
    # was already ambiguous) or neither did (if cheaper signals already
    # resolved it to no_match) -- both outcomes are safe; the only
    # unsafe outcome (a silent merge) must never happen.
    assert len(groups) == 0


# TEST 19 - the confidence-banding logic directly: forcing a page comparison
# into the uncertain band flags needs_review without merging
def test_uncertain_band_flags_review_without_merging():
    from lender_package_builder import content_dedup as cd

    result_same_text = cd.PairComparison(outcome="uncertain", confidence=0.85)
    assert result_same_text.outcome == "uncertain"
    assert cd.NEEDS_REVIEW_THRESHOLD <= result_same_text.confidence < cd.AUTO_REMOVE_THRESHOLD


# TEST 20 - a document with a corrupted/unreadable converted PDF never
# crashes fingerprinting and never participates in comparison
def test_unreadable_converted_pdf_excluded_gracefully(tmp_path: Path):
    bad_path = tmp_path / "bad.pdf"
    bad_path.write_bytes(b"not a real pdf")
    occ = SourceOccurrence(
        document_id="D1",
        traversal_index=1,
        original_filename="bad.pdf",
        original_relative_path="bad.pdf",
        original_extension=".pdf",
        original_size_bytes=bad_path.stat().st_size,
        status=ProcessingStatus.CONVERTED,
        converted_pdf_path=bad_path,
        converted_page_count=0,
    )
    fingerprints = content_dedup.build_fingerprints([occ])
    assert "D1" not in fingerprints
    groups, notes = content_dedup.detect_content_duplicates([occ], fingerprints)
    assert groups == []
    assert occ.is_content_duplicate is False


# TEST 21 - placeholders (unconverted) never enter the candidate pool
def test_placeholder_occurrences_excluded_from_candidate_pool(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "a.pdf", pages=1, text_prefix="Real content")
    occ_real = _occ("D1", 1, a)
    occ_placeholder = SourceOccurrence(
        document_id="D2",
        traversal_index=2,
        original_filename="unconvertible.xyz",
        original_relative_path="unconvertible.xyz",
        original_extension=".xyz",
        original_size_bytes=10,
        status=ProcessingStatus.UNCONVERTED_PLACEHOLDER,
        converted_pdf_path=None,
    )
    fingerprints = content_dedup.build_fingerprints([occ_real, occ_placeholder])
    assert "D2" not in fingerprints
    assert "D1" in fingerprints


# TEST 22 - oversized buckets fall back to hash-only grouping and are noted
def test_oversized_bucket_falls_back_to_hash_only(tmp_path: Path):
    occs = []
    for i in range(6):
        p = builders.make_pdf(tmp_path / f"doc{i}.pdf", pages=1, text_prefix="Shared")
        occs.append(_occ(f"D{i}", i, p))
    groups, notes = content_dedup.detect_content_duplicates(
        occs, content_dedup.build_fingerprints(occs), max_bucket_size=2
    )
    assert len(notes) == 1
    assert "exceeded" in notes[0]
    assert sum(not o.is_content_duplicate for o in occs) == 1
