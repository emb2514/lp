"""Tests for reporting.py's RC2 expansion: the per-method sections added
to Duplicate_Removal_Log.txt, the two new report files
(Document_Version_Report.txt, Merged_Document_Overlap_Report.txt), and
the new RC2 fields added to Processing_Manifest.json. Exercises the
real pipeline end-to-end via run_build rather than hand-built RunResult
objects, so these tests fail if the wiring between content_dedup.py /
overlap_detection.py / pdf_portfolio.py / version_classification.py and
reporting.py ever drifts.
"""

from __future__ import annotations

import dataclasses
import json

from fixtures.builders import make_merged_pdf, make_pdf, make_pdf_portfolio, make_signed_pdf_variant, make_txt


# TEST 1 - Duplicate_Removal_Log.txt has all four method sections, and
# the normalized_pdf section carries full per-item detail.
def test_duplicate_removal_log_has_all_method_sections(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "version_x.pdf", pages=2, text_prefix="Shared Text",
              metadata={"/CustomTag": "version-x-only"})
    make_pdf(folder / "version_y.pdf", pages=2, text_prefix="Shared Text",
              metadata={"/CustomTag": "version-y-only"})

    run = run_build(folder)
    dup_log = (run.output_path / "Reports" / "Duplicate_Removal_Log.txt").read_text()

    for header in (
        "EXACT BYTE DUPLICATES",
        "NORMALIZED PDF DUPLICATES",
        "CONTENT-EQUIVALENT DUPLICATES",
        "BLANK-PAGE-TOLERANT DUPLICATES",
    ):
        assert header in dup_log

    # The normalized_pdf section actually found and explained the pair.
    section_start = dup_log.index("NORMALIZED PDF DUPLICATES")
    section_end = dup_log.index("CONTENT-EQUIVALENT DUPLICATES")
    normalized_section = dup_log[section_start:section_end]
    assert "Count: 1" in normalized_section
    assert "version_x.pdf" in normalized_section or "version_y.pdf" in normalized_section
    assert "Detection method:  normalized_pdf" in normalized_section
    assert "Confidence:" in normalized_section

    # The other two content-aware sections found nothing in this run.
    content_equiv_start = dup_log.index("CONTENT-EQUIVALENT DUPLICATES")
    blank_tolerant_start = dup_log.index("BLANK-PAGE-TOLERANT DUPLICATES")
    content_equiv_section = dup_log[content_equiv_start:blank_tolerant_start]
    assert "Count: 0" in content_equiv_section
    assert "None found." in content_equiv_section


# TEST 2 - Document_Version_Report.txt groups related occurrences into a
# family and shows each member's version classification and retention
# status. An unsigned and an e-signed copy of the same underlying
# document differ meaningfully (signature state) so BOTH are retained --
# never silently merged.
def test_document_version_report_lists_family_and_versions(tmp_path, run_build):
    folder = tmp_path / "input"
    make_signed_pdf_variant(folder / "auth_unsigned.pdf", "Alice Anderson", common_pages=5, signature_kind="unsigned")
    make_signed_pdf_variant(folder / "auth_signed.pdf", "Alice Anderson", common_pages=5, signature_kind="e_signed")

    run = run_build(folder)
    version_report = (run.output_path / "Reports" / "Document_Version_Report.txt").read_text()

    assert "DOCUMENT VERSION REPORT" in version_report
    assert "Document families identified: 1" in version_report
    assert "auth_unsigned.pdf" in version_report
    assert "auth_signed.pdf" in version_report
    assert "Version: e_signed" in version_report
    assert "Version: unsigned" in version_report
    assert "RETAINED in Final" in version_report
    assert "EXCLUDED from Final" not in version_report

    final_ids = {doc_id for part in run.final_parts for doc_id in part.document_ids}
    unsigned = next(o for o in run.occurrences if o.original_filename == "auth_unsigned.pdf")
    signed = next(o for o in run.occurrences if o.original_filename == "auth_signed.pdf")
    assert unsigned.document_id in final_ids
    assert signed.document_id in final_ids
    assert unsigned.document_family_id == signed.document_family_id
    assert {unsigned.version_classification, signed.version_classification} == {"unsigned", "e_signed"}


# TEST 3 - Document_Version_Report.txt reports "no families" cleanly
# when nothing in the run is related.
def test_document_version_report_empty_when_no_families(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "solo.pdf", pages=1, text_prefix="Only Document")

    run = run_build(folder)
    version_report = (run.output_path / "Reports" / "Document_Version_Report.txt").read_text()
    assert "No related document families were identified in this run." in version_report


# TEST 4 - Merged_Document_Overlap_Report.txt lists a detected PDF
# Portfolio and its extracted attachments.
def test_merged_overlap_report_lists_portfolio_and_attachments(tmp_path, run_build):
    folder = tmp_path / "input"
    attachment_path = tmp_path / "_attachment_source.pdf"
    make_pdf(attachment_path, pages=1, text_prefix="Disclosure Attachment")
    attachment_bytes = attachment_path.read_bytes()

    make_pdf_portfolio(folder / "binder.pdf", [("disclosure.pdf", attachment_bytes)])

    run = run_build(folder)
    overlap_report = (run.output_path / "Reports" / "Merged_Document_Overlap_Report.txt").read_text()

    assert "PDF PORTFOLIOS DETECTED" in overlap_report
    assert "binder.pdf" in overlap_report
    assert "Embedded attachments extracted: 1" in overlap_report
    assert "disclosure.pdf" in overlap_report

    binder = next(o for o in run.occurrences if o.original_filename == "binder.pdf")
    assert binder.is_portfolio_container is True
    final_ids = {doc_id for part in run.final_parts for doc_id in part.document_ids}
    assert binder.document_id not in final_ids  # its own cover page is excluded from Final
    og_ids = {doc_id for part in run.og_parts for doc_id in part.document_ids}
    assert binder.document_id in og_ids  # but still present in OG, untouched


# TEST 5 - Merged_Document_Overlap_Report.txt lists containment findings
# for standalone components safely proven fully contained inside a
# merged package, with the structural-safety-rule explanation, and the
# merged package itself is never excluded.
def test_merged_overlap_report_lists_containment_findings(tmp_path, run_build):
    folder = tmp_path / "input"
    a = make_pdf(folder / "component_a.pdf", pages=2, text_prefix="Component A Content")
    b = make_pdf(folder / "component_b.pdf", pages=3, text_prefix="Component B Content")
    make_merged_pdf(folder / "merged_package.pdf", [a, b])

    run = run_build(folder)
    overlap_report = (run.output_path / "Reports" / "Merged_Document_Overlap_Report.txt").read_text()

    assert "MERGED-PACKAGE CONTAINMENT FINDINGS" in overlap_report
    assert "EXACT_CONTAINED" in overlap_report
    assert "component_a.pdf" in overlap_report
    assert "component_b.pdf" in overlap_report
    assert "merged_package.pdf" in overlap_report
    assert "structural safety rule, not a quality judgment" in overlap_report

    final_ids = {doc_id for part in run.final_parts for doc_id in part.document_ids}
    comp_a = next(o for o in run.occurrences if o.original_filename == "component_a.pdf")
    comp_b = next(o for o in run.occurrences if o.original_filename == "component_b.pdf")
    merged = next(o for o in run.occurrences if o.original_filename == "merged_package.pdf")
    assert comp_a.document_id not in final_ids
    assert comp_b.document_id not in final_ids
    assert merged.document_id in final_ids
    assert comp_a.is_contained_in_merged_document is True
    assert comp_a.contained_in_document_id == merged.document_id


# TEST 6 - Processing_Manifest.json carries all four new RC2 fields,
# valid JSON, populated for a run that exercises content-aware
# duplicate detection.
def test_manifest_includes_rc2_fields(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "version_x.pdf", pages=2, text_prefix="Shared Text",
              metadata={"/CustomTag": "version-x-only"})
    make_pdf(folder / "version_y.pdf", pages=2, text_prefix="Shared Text",
              metadata={"/CustomTag": "version-y-only"})

    run = run_build(folder)
    manifest = json.loads((run.output_path / "Reports" / "Processing_Manifest.json").read_text())

    for key in ("content_duplicate_groups", "document_families", "overlap_findings", "content_dedup_notes"):
        assert key in manifest

    assert len(manifest["content_duplicate_groups"]) == len(run.content_duplicate_groups) == 1
    group = manifest["content_duplicate_groups"][0]
    assert group["method"] == "normalized_pdf"
    assert len(group["document_ids"]) == 2


# TEST 7 - all five reports are still generated, without crashing, when
# content-aware dedup is disabled -- the new report files simply show
# empty results rather than being omitted.
def test_reports_generated_cleanly_with_content_aware_dedup_disabled(tmp_path, run_build, config):
    folder = tmp_path / "input"
    make_txt(folder / "a.txt", "identical content across two files\n")
    make_txt(folder / "b.txt", "identical content across two files\n")  # exact duplicate -- exact-hash path still runs

    disabled_config = dataclasses.replace(config, enable_content_aware_dedup=False)
    run = run_build(folder, config=disabled_config)

    reports_dir = run.output_path / "Reports"
    for filename in (
        "Duplicate_Removal_Log.txt",
        "Document_Version_Report.txt",
        "Merged_Document_Overlap_Report.txt",
        "Processing_Report.txt",
        "Processing_Manifest.json",
    ):
        assert (reports_dir / filename).exists()

    version_report = (reports_dir / "Document_Version_Report.txt").read_text()
    assert "No related document families were identified in this run." in version_report

    overlap_report = (reports_dir / "Merged_Document_Overlap_Report.txt").read_text()
    assert "None found." in overlap_report
    assert "No merged-package containment relationships were found in this run." in overlap_report

    dup_log = (reports_dir / "Duplicate_Removal_Log.txt").read_text()
    assert "EXACT BYTE DUPLICATES" in dup_log
    assert "Total duplicate occurrences removed from Final: 1" in dup_log

    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"
