"""Tests for MILESTONE 5A -- the Compare Packages engine
(compare_packages.py): comparison categories, unbookmarked-manual-
package page-sequence matching, protected differences, caching via
source hash, cancellation, and analysis-only (never modifies either
input).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.builders import make_pdf, make_pdf_with_pages, make_signed_pdf_variant

from lender_package_builder import compare_packages as cp
from lender_package_builder.cancellation import CancellationToken, ProcessingCancelled


# TEST 1 - identical single-file packages: everything is an Exact Match
def test_identical_packages_are_all_exact_matches(tmp_path):
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Page one text", "Page two text"])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", ["Page one text", "Page two text"])

    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])
    result = cp.compare_packages(old_side, new_side)

    assert result.old_page_count == 2
    assert result.new_page_count == 2
    assert all(f.category == cp.CATEGORY_EXACT_MATCH for f in result.findings)
    assert len(result.findings) == 2


# TEST 2 - a protected (meaningful) difference is never averaged away
# by many surrounding matching pages -- weakest-link, same as the main
# dedup engine.
def test_meaningful_difference_is_flagged_not_averaged_away(tmp_path):
    old_pages = [f"Shared boilerplate page {i}" for i in range(5)] + ["Loan amount: $100,000"]
    new_pages = [f"Shared boilerplate page {i}" for i in range(5)] + ["Loan amount: $200,000"]
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", old_pages)
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", new_pages)

    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])
    result = cp.compare_packages(old_side, new_side)

    diff_findings = [f for f in result.findings if f.category == cp.CATEGORY_MEANINGFUL_DIFFERENCE]
    assert len(diff_findings) == 1
    assert diff_findings[0].protected_differences
    assert diff_findings[0].review_recommended is True


# TEST 3 - a page moved to a different position is found and reported
# as "Moved or Reordered", not "Only in Old" + "Only in New".
def test_moved_page_is_detected_not_reported_as_missing_and_extra(tmp_path):
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Alpha page", "Bravo page", "Charlie page"])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", ["Charlie page", "Alpha page", "Bravo page"])

    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])
    result = cp.compare_packages(old_side, new_side)

    categories = {f.category for f in result.findings}
    assert cp.CATEGORY_ONLY_IN_OLD not in categories
    assert cp.CATEGORY_ONLY_IN_NEW not in categories
    assert cp.CATEGORY_POSSIBLE_MISSING not in categories
    moved = [f for f in result.findings if f.category == cp.CATEGORY_MOVED_OR_REORDERED]
    assert len(moved) >= 1


# TEST 4 - genuinely missing content is reported, but only after
# checking it isn't actually a cover/index/report page.
def test_possible_missing_document_reported_for_genuinely_absent_content(tmp_path):
    old_pdf = make_pdf_with_pages(
        tmp_path / "old.pdf",
        [
            "Shared page",
            "Unique borrower disclosure content that only appears in the old package and describes "
            "specific loan terms, conditions, and other substantive borrower-facing information.",
        ],
    )
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", ["Shared page"])

    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])
    result = cp.compare_packages(old_side, new_side)

    missing = [f for f in result.findings if f.category == cp.CATEGORY_POSSIBLE_MISSING]
    assert len(missing) == 1
    assert missing[0].review_recommended is True


# TEST 5 - a blank/cover/index page that's only on one side is
# classified as an extra page, not a missing/extra borrower document.
def test_extra_cover_page_not_classified_as_missing_document(tmp_path):
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Shared page"])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", ["Table of Contents", "Shared page"])

    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])
    result = cp.compare_packages(old_side, new_side)

    extra = [f for f in result.findings if f.category == cp.CATEGORY_EXTRA_PAGE]
    assert len(extra) == 1
    assert cp.CATEGORY_ONLY_IN_NEW not in {f.category for f in result.findings}


# TEST 6 - a genuinely blank page present only on one side is also an
# extra page, not a missing document.
def test_blank_page_only_on_one_side_is_extra_page_not_missing(tmp_path):
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Shared page", None])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", ["Shared page"])

    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])
    result = cp.compare_packages(old_side, new_side)

    extra = [f for f in result.findings if f.category == cp.CATEGORY_EXTRA_PAGE]
    assert len(extra) == 1


# TEST 7 - a duplicate page in Old that correctly has only one copy in
# New is "Likely Duplicate Removed", not "Possible Missing Document".
def test_duplicate_removed_correctly_not_reported_as_missing(tmp_path):
    disclosure_text = (
        "Disclosure text describing specific loan terms, conditions, and other substantive "
        "borrower-facing information that repeats identically on both copies."
    )
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", [disclosure_text, disclosure_text, "Other page"])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", [disclosure_text, "Other page"])

    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])
    result = cp.compare_packages(old_side, new_side)

    categories = [f.category for f in result.findings]
    assert cp.CATEGORY_LIKELY_DUPLICATE_REMOVED in categories
    assert cp.CATEGORY_POSSIBLE_MISSING not in categories


# TEST 8 - genuinely new-only content is reported as "Only in New".
def test_only_in_new_reported_for_genuinely_new_content(tmp_path):
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Shared page"])
    new_pdf = make_pdf_with_pages(
        tmp_path / "new.pdf",
        [
            "Shared page",
            "Brand new borrower disclosure content describing specific loan terms, conditions, and "
            "other substantive borrower-facing information not present anywhere in the old package.",
        ],
    )

    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])
    result = cp.compare_packages(old_side, new_side)

    only_new = [f for f in result.findings if f.category == cp.CATEGORY_ONLY_IN_NEW]
    assert len(only_new) == 1


# TEST 9 - multi-file inputs are sorted into natural numeric part order
# (Part 2 before Part 10), not lexical order.
def test_multi_file_inputs_sorted_naturally(tmp_path):
    make_pdf(tmp_path / "Package, Part 010.pdf", pages=1, text_prefix="Ten")
    make_pdf(tmp_path / "Package, Part 002.pdf", pages=1, text_prefix="Two")
    make_pdf(tmp_path / "Package, Part 001.pdf", pages=1, text_prefix="One")

    side = cp.load_package_side("Old", list(tmp_path.glob("*.pdf")))
    assert [f.name for f in side.files] == [
        "Package, Part 001.pdf",
        "Package, Part 002.pdf",
        "Package, Part 010.pdf",
    ]


# TEST 10 - source hash is stable for the same inputs and changes the
# instant either side's content changes -- the caching invalidation
# contract.
def test_source_hash_stable_and_invalidated_by_content_change(tmp_path):
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Page one"])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", ["Page one"])

    hash_1 = cp.compute_source_hash([old_pdf], [new_pdf])
    hash_2 = cp.compute_source_hash([old_pdf], [new_pdf])
    assert hash_1 == hash_2

    make_pdf_with_pages(new_pdf, ["Page one changed"])
    hash_3 = cp.compute_source_hash([old_pdf], [new_pdf])
    assert hash_3 != hash_1


# TEST 11 - cancellation is honored during comparison.
def test_comparison_honors_cancellation(tmp_path):
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", [f"Page {i}" for i in range(5)])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", [f"Page {i}" for i in range(5)])

    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])

    token = CancellationToken()
    token.request()
    with pytest.raises(ProcessingCancelled):
        cp.compare_packages(old_side, new_side, cancellation_token=token)


# TEST 12 - comparison never modifies either input package.
def test_comparison_never_modifies_inputs(tmp_path):
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Page one", "Page two"])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", ["Page one changed", "Page two"])
    old_bytes_before = old_pdf.read_bytes()
    new_bytes_before = new_pdf.read_bytes()

    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])
    cp.compare_packages(old_side, new_side)

    assert old_pdf.read_bytes() == old_bytes_before
    assert new_pdf.read_bytes() == new_bytes_before


# TEST 13 - wet-signed vs e-signed vs unsigned versions of the same
# document are flagged as a protected (signature-state) difference,
# not silently matched.
def test_different_signature_state_is_a_protected_difference(tmp_path):
    unsigned = make_signed_pdf_variant(tmp_path / "unsigned.pdf", "Jane Doe", common_pages=2, signature_kind="unsigned")
    e_signed = make_signed_pdf_variant(tmp_path / "e_signed.pdf", "Jane Doe", common_pages=2, signature_kind="e_signed")

    old_side = cp.load_package_side("Old", [unsigned])
    new_side = cp.load_package_side("New", [e_signed])
    result = cp.compare_packages(old_side, new_side)

    last_page_findings = [f for f in result.findings if f.old_overall_page == 2 or f.new_overall_page == 2]
    assert any(f.category == cp.CATEGORY_MEANINGFUL_DIFFERENCE for f in last_page_findings)


# TEST 15 - inspecting an app-generated output folder separates Final
# parts from Original Lender Package parts and ignores everything else
# (extracted key documents, reports).
def test_describe_folder_contents_separates_final_and_original(tmp_path):
    output_dir = tmp_path / "True, Michael, 6192278785"
    final_dir = output_dir / "Final"
    final_dir.mkdir(parents=True)
    (output_dir / "Reports").mkdir()

    make_pdf(final_dir / "True, Michael, Lender Package, Part 001.pdf", pages=1)
    make_pdf(final_dir / "True, Michael, Lender Package, Part 002.pdf", pages=1)
    make_pdf(final_dir / "True, Michael, Original Lender Package, Part 001.pdf", pages=1)
    make_pdf(final_dir / "True, Michael, Closing Disclosure, Unsigned, 6192278785.pdf", pages=1)
    (output_dir / "Reports" / "Processing_Report.txt").write_text("not a pdf folder scan target")

    contents = cp.describe_folder_contents(output_dir)

    assert [f.name for f in contents.final_files] == [
        "True, Michael, Lender Package, Part 001.pdf",
        "True, Michael, Lender Package, Part 002.pdf",
    ]
    assert [f.name for f in contents.original_files] == ["True, Michael, Original Lender Package, Part 001.pdf"]
    assert [f.name for f in contents.other_pdf_files] == [
        "True, Michael, Closing Disclosure, Unsigned, 6192278785.pdf"
    ]


# TEST 16 - a plain folder of PDFs (no Final/ subfolder) is scanned
# directly.
def test_describe_folder_contents_plain_folder(tmp_path):
    folder = tmp_path / "manual_package"
    folder.mkdir()
    make_pdf(folder / "doc_a.pdf", pages=1)
    make_pdf(folder / "doc_b.pdf", pages=1)

    contents = cp.describe_folder_contents(folder)
    assert contents.final_files == []
    assert contents.original_files == []
    assert {f.name for f in contents.other_pdf_files} == {"doc_a.pdf", "doc_b.pdf"}


# TEST 14 - report and manifest are written correctly and are
# human-/machine-readable.
def test_report_and_manifest_written(tmp_path):
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Page one"])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", ["Page one"])

    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])
    result = cp.compare_packages(old_side, new_side)

    report_path = tmp_path / "Package Comparison Report.txt"
    manifest_path = tmp_path / "Package Comparison Manifest.json"
    cp.write_comparison_report(result, report_path)
    cp.write_comparison_manifest(result, manifest_path)

    report_text = report_path.read_text()
    assert "PACKAGE COMPARISON REPORT" in report_text
    assert "CMP-0001" in report_text
    assert "analysis-only" in report_text

    import json

    manifest = json.loads(manifest_path.read_text())
    assert manifest["source_hash"] == result.source_hash
    assert len(manifest["findings"]) == len(result.findings)
