from __future__ import annotations

import json

from fixtures.builders import make_pdf, make_txt

from lender_package_builder.config import AppConfig


def test_reports_reconcile_with_run_result(tmp_path, run_build):
    folder = tmp_path / "input"
    make_txt(folder / "one.txt", "unique content one\n")
    make_txt(folder / "two.txt", "unique content one\n")  # duplicate of one.txt
    make_txt(folder / "three.txt", "unique content three\n")

    run = run_build(folder)

    reports_dir = run.output_path / "Reports"
    manifest = json.loads((reports_dir / "Processing_Manifest.json").read_text())

    assert len(manifest["occurrences"]) == len(run.occurrences)
    assert manifest["overall_success"] == run.success
    assert len(manifest["duplicate_groups"]) == len(run.duplicate_groups)

    og_doc_count_manifest = sum(len(p["document_ids"]) for p in manifest["og_parts"])
    final_doc_count_manifest = sum(len(p["document_ids"]) for p in manifest["final_parts"])
    og_doc_count_run = sum(len(p.document_ids) for p in run.og_parts)
    final_doc_count_run = sum(len(p.document_ids) for p in run.final_parts)
    assert og_doc_count_manifest == og_doc_count_run == 3
    assert final_doc_count_manifest == final_doc_count_run == 2

    report_text = (reports_dir / "Processing_Report.txt").read_text()
    assert f"OG document count:      {og_doc_count_run}" in report_text
    assert f"Final document count:   {final_doc_count_run}" in report_text
    assert "OVERALL RESULT: SUCCESS" in report_text

    dup_log = (reports_dir / "Duplicate_Removal_Log.txt").read_text()
    assert "Total duplicate occurrences removed from Final: 1" in dup_log
    assert "two.txt" in dup_log

    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"


def test_manifest_is_valid_json_with_expected_keys(tmp_path, run_build):
    folder = tmp_path / "input"
    make_txt(folder / "solo.txt", "just one file\n")

    run = run_build(folder)
    manifest_path = run.output_path / "Reports" / "Processing_Manifest.json"
    manifest = json.loads(manifest_path.read_text())

    for key in (
        "meta", "input_path", "output_path", "occurrences", "duplicate_groups",
        "og_parts", "final_parts", "integrity_checks", "overall_success",
    ):
        assert key in manifest


def test_report_labels_maximums_actuals_and_split_reasons(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "a_125pages.pdf", pages=125)
    make_pdf(folder / "b_98pages.pdf", pages=98)
    make_pdf(folder / "c_162pages.pdf", pages=162)
    make_pdf(folder / "d_41pages.pdf", pages=41)
    make_pdf(folder / "e_oversized.pdf", pages=450)

    cfg = AppConfig()
    cfg.max_pages_per_part = 400
    cfg.max_size_mb_per_part = 5000

    run = run_build(folder, config=cfg)
    report_text = (run.output_path / "Reports" / "Processing_Report.txt").read_text()

    # Configured maximums are clearly labeled.
    assert "Configured maximum pages per part:  400" in report_text
    assert "Configured maximum MB per part:     5000" in report_text

    # Actual pages and MB are shown for every part (not just page counts).
    assert "MB (" in report_text  # e.g. "0.11 MB (123,456 bytes)"

    # Split reasons are explained in plain language.
    assert "Why this part ended here:" in report_text
    assert "page maximum" in report_text or "end of package" in report_text

    # The oversized single-document part is clearly flagged.
    assert "OVERSIZED SINGLE DOCUMENT" in report_text

    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"
