"""Tests for version_classification.py -- Level 5, purely descriptive
document family clustering and version labeling. Never sets any
exclusion-relevant field; only document_family_id/version_classification.
"""

from __future__ import annotations

from pathlib import Path

from fixtures import builders

from lender_package_builder import content_dedup, overlap_detection, pdf_content, version_classification
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
    groups, _, _ = content_dedup.detect_content_duplicates(occurrences, fingerprints)
    findings = overlap_detection.detect_overlaps(occurrences, fingerprints)
    return version_classification.build_document_families(occurrences, fingerprints, groups, findings)


# TEST 1 - the task's own motivating example: unsigned + e-signed +
# wet-signed versions of the same document cluster into one family,
# each labeled correctly, and none are removed from Final
def test_borrower_authorization_family_example(tmp_path: Path):
    unsigned = builders.make_signed_pdf_variant(tmp_path / "u.pdf", "Jane Doe", common_pages=2, signature_kind="unsigned")
    e_signed = builders.make_signed_pdf_variant(tmp_path / "e.pdf", "Jane Doe", common_pages=2, signature_kind="e_signed")
    wet_signed = builders.make_signed_pdf_variant(tmp_path / "w.pdf", "Jane Doe", common_pages=2, signature_kind="wet_signed")
    unrelated = builders.make_pdf(tmp_path / "x.pdf", pages=2, text_prefix="Totally Different Document Content")

    occ_u, occ_e, occ_w, occ_x = (
        _occ("U", 1, unsigned),
        _occ("E", 2, e_signed),
        _occ("W", 3, wet_signed),
        _occ("X", 4, unrelated),
    )
    families = _run([occ_u, occ_e, occ_w, occ_x])

    assert len(families) == 1
    family = families[0]
    assert set(family.document_ids) == {"U", "E", "W"}
    assert family.versions["U"] == "unsigned"
    assert family.versions["E"] == "e_signed"
    assert family.versions["W"] == "wet_signed"
    assert occ_x.document_family_id is None

    # descriptive only -- nothing was removed from Final
    for occ in (occ_u, occ_e, occ_w):
        assert occ.is_content_duplicate is False
        assert occ.is_contained_in_merged_document is False


# TEST 2 - repeated copies of the same version within a family ARE
# still excluded by content_dedup, and version_classification does not
# undo that -- it only labels, never restores
def test_duplicate_within_family_still_excluded(tmp_path: Path):
    e1 = builders.make_signed_pdf_variant(tmp_path / "e1.pdf", "Jane Doe", common_pages=2, signature_kind="e_signed")
    e2 = builders.make_signed_pdf_variant(tmp_path / "e2_copy.pdf", "Jane Doe", common_pages=2, signature_kind="e_signed")
    unsigned = builders.make_signed_pdf_variant(tmp_path / "u.pdf", "Jane Doe", common_pages=2, signature_kind="unsigned")

    occ_e1, occ_e2, occ_u = _occ("E1", 1, e1), _occ("E2", 2, e2), _occ("U", 3, unsigned)
    families = _run([occ_e1, occ_e2, occ_u])

    assert sum(o.is_content_duplicate for o in (occ_e1, occ_e2)) == 1
    assert len(families) == 1
    assert set(families[0].document_ids) == {"E1", "E2", "U"}


# TEST 3 - a document with no signature/form/image apparatus and no
# family is classified original_digital
def test_isolated_plain_document_classified_original_digital(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "a.pdf", pages=1, text_prefix="A plain digital memo")
    occ_a = _occ("A", 1, a)
    fingerprints = content_dedup.build_fingerprints([occ_a])
    label = version_classification.classify_version(fingerprints["A"])
    assert label == "original_digital"


# TEST 4 - a document with a signed AcroForm signature field is e_signed
def test_signed_field_classified_e_signed(tmp_path: Path):
    p = builders.make_signed_pdf_variant(tmp_path / "e.pdf", "Jane Doe", common_pages=1, signature_kind="e_signed")
    occ_p = _occ("E", 1, p)
    fingerprints = content_dedup.build_fingerprints([occ_p])
    assert version_classification.classify_version(fingerprints["E"]) == "e_signed"


# TEST 5 - a scanned-image-only document is classified scanned
def test_scanned_like_document_classified_scanned(tmp_path: Path):
    p = builders.make_scanned_like_pdf(tmp_path / "scan.pdf", pages=2, image_seed=1)
    occ_p = _occ("S", 1, p)
    fingerprints = content_dedup.build_fingerprints([occ_p])
    assert version_classification.classify_version(fingerprints["S"]) == "scanned"


# TEST 6 - families of size 1 (no related documents found) are not reported
def test_no_family_for_unrelated_singleton(tmp_path: Path):
    a = builders.make_pdf(tmp_path / "a.pdf", pages=3, text_prefix="Unique standalone content")
    occ_a = _occ("A", 1, a)
    families = _run([occ_a])
    assert families == []
    assert occ_a.document_family_id is None
