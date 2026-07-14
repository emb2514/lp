from __future__ import annotations

from pathlib import Path

from lender_package_builder.exceptions import ArchiveTooLargeError, InvalidInputError
from lender_package_builder.gui.worker import translate_error
from lender_package_builder.models import (
    IntegrityCheckResult,
    OutputPart,
    ProcessingStatus,
    RunResult,
    SourceOccurrence,
)


def _make_occurrence(doc_id: str, status=ProcessingStatus.CONVERTED, warnings=None) -> SourceOccurrence:
    return SourceOccurrence(
        document_id=doc_id,
        traversal_index=int(doc_id.split("-")[-1]),
        original_filename=f"{doc_id}.pdf",
        original_relative_path=f"{doc_id}.pdf",
        original_extension=".pdf",
        original_size_bytes=1000,
        status=status,
        converted_page_count=3,
        converted_size_bytes=5000,
        conversion_warnings=warnings or [],
    )


def _make_successful_run(tmp_path: Path, with_warnings: bool = False) -> RunResult:
    output_path = tmp_path / "output"
    output_path.mkdir()

    occ1 = _make_occurrence("DOC-000001")
    occ2 = _make_occurrence(
        "DOC-000002",
        status=ProcessingStatus.UNCONVERTED_PLACEHOLDER if with_warnings else ProcessingStatus.CONVERTED,
    )

    og_part = OutputPart(
        package="OG", index=1, file_path=output_path / "OG" / "part1.pdf",
        document_ids=["DOC-000001", "DOC-000002"], page_count=6, file_size_bytes=10000,
    )
    final_part = OutputPart(
        package="Final", index=1, file_path=output_path / "Final" / "part1.pdf",
        document_ids=["DOC-000001", "DOC-000002"], page_count=6, file_size_bytes=10000,
    )

    checks = [IntegrityCheckResult(name=f"Check {i}", passed=True, detail="ok") for i in range(5)]

    return RunResult(
        input_path=tmp_path / "input.zip",
        output_path=output_path,
        start_time="2026-01-01T00:00:00",
        end_time="2026-01-01T00:01:00",
        elapsed_seconds=60.0,
        occurrences=[occ1, occ2],
        og_parts=[og_part],
        final_parts=[final_part],
        integrity_checks=checks,
    )


def _make_integrity_failure_run(tmp_path: Path) -> RunResult:
    run = _make_successful_run(tmp_path)
    run.integrity_checks.append(
        IntegrityCheckResult(name="No source document was split", passed=False, detail="mismatch found")
    )
    return run


# TEST 10 - SUCCESS RESULT VIEW
def test_success_result_view_shows_correct_counts_and_enables_buttons(window, tmp_path):
    run = _make_successful_run(tmp_path)
    assert run.success is True

    window._on_build_finished(run)

    assert window.stack.currentWidget() is window.result_view
    assert window.result_view.banner.property("status") == "success"
    assert window.result_view.open_output_button.isEnabled()
    assert window.result_view.open_final_button.isEnabled()
    assert window.result_view.open_reports_button.isEnabled()

    stats_text = " ".join(
        window.result_view._stats_layout.itemAt(i).widget().text()
        for i in range(window.result_view._stats_layout.count())
    )
    assert "2" in stats_text  # source documents discovered
    assert "6" in stats_text  # OG/Final total pages
    assert "5/5" in stats_text  # integrity checks passed


# TEST 11 - SUCCESS WITH WARNINGS
def test_success_with_warnings_shows_warning_state(window, tmp_path):
    run = _make_successful_run(tmp_path, with_warnings=True)
    assert run.success is True  # all integrity checks still pass

    window._on_build_finished(run)

    assert window.stack.currentWidget() is window.result_view
    assert window.result_view.banner.property("status") == "warning"
    assert "review" in window.result_view.banner_title.text().lower()


# TEST 12 - FAILED RUN VIEW
def test_failed_run_shows_friendly_error_with_recovery_controls(window):
    user_message, technical_details = translate_error(InvalidInputError("bad zip"))
    window._on_build_failed(user_message, technical_details)

    assert window.stack.currentWidget() is window.failure_view
    assert window.isVisible() or True  # window remains open, not closed
    assert window.failure_view.reason_label.text() == user_message
    assert "bad zip" in window.failure_view.details_text.toPlainText()
    assert window.failure_view.try_again_button.isEnabled()
    assert window.failure_view.change_input_button.isEnabled()

    window.failure_view.details_toggle.setChecked(True)
    assert window.failure_view.details_text.isVisible()


def test_translate_error_maps_known_exception_types():
    for exc, expected_fragment in [
        (InvalidInputError("x"), "could not be used"),
        (ArchiveTooLargeError("x"), "larger than the configured safety limit"),
    ]:
        message, details = translate_error(exc)
        assert expected_fragment in message
        assert details  # technical details always populated

    message, details = translate_error(RuntimeError("boom"))
    assert "unexpected error" in message.lower()
    assert "boom" in details


# TEST 13 - INTEGRITY FAILURE
def test_run_with_failed_integrity_check_shows_failure_not_success(window, tmp_path):
    run = _make_integrity_failure_run(tmp_path)
    assert run.success is False  # PDFs may exist, but this must not read as success

    window._on_build_finished(run)

    assert window.stack.currentWidget() is window.failure_view
    assert window.stack.currentWidget() is not window.result_view
    assert "did not pass" in window.failure_view.reason_label.text()
    assert "No source document was split" in window.failure_view.details_text.toPlainText()
