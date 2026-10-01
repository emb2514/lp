"""Tests for cli._build_uncertain_matches -- specifically the
merged-containment case's page-range text and `container_match_page_index`,
added after a real user found the dialog impossible to reason about: two
bare filenames and a confidence score, no way to see which pages
actually matched. See gui/widgets/uncertain_review_dialog.py for the
dialog-side fix (thumbnails rendered AT this page index).
"""

from __future__ import annotations

from lender_package_builder.cli import _build_uncertain_matches
from lender_package_builder.models import OverlapFinding


def test_merged_containment_detail_includes_single_page_match():
    finding = OverlapFinding(
        standalone_document_id="D1", container_document_id="D2",
        classification="uncertain_overlap", contained_page_range=(4, 4), confidence=0.91,
    )

    matches = _build_uncertain_matches([], [finding])

    assert len(matches) == 1
    assert "page 5 of the merged package" in matches[0].detail
    assert matches[0].container_match_page_index == 4


def test_merged_containment_detail_includes_page_range():
    finding = OverlapFinding(
        standalone_document_id="D1", container_document_id="D2",
        classification="uncertain_overlap", contained_page_range=(1, 5), confidence=0.91,
    )

    matches = _build_uncertain_matches([], [finding])

    assert "pages 2-6 of the merged package" in matches[0].detail
    assert matches[0].container_match_page_index == 1


def test_merged_containment_without_a_page_range_omits_the_sentence():
    finding = OverlapFinding(
        standalone_document_id="D1", container_document_id="D2",
        classification="uncertain_overlap", contained_page_range=None, confidence=0.91,
    )

    matches = _build_uncertain_matches([], [finding])

    assert "The match was found at" not in matches[0].detail
    assert matches[0].container_match_page_index is None


def test_non_uncertain_findings_are_excluded():
    finding = OverlapFinding(
        standalone_document_id="D1", container_document_id="D2",
        classification="exact_contained", contained_page_range=(0, 1), confidence=1.0,
    )

    matches = _build_uncertain_matches([], [finding])

    assert matches == []


def test_content_duplicate_matches_never_set_container_match_page_index():
    matches = _build_uncertain_matches([("D1", "D2", 0.85)], [])

    assert len(matches) == 1
    assert matches[0].container_match_page_index is None
    assert matches[0].excludable_ids == ("D1", "D2")
