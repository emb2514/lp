from __future__ import annotations

import json

from fixtures.builders import make_txt


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
