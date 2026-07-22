"""GUI tests for the sidebar navigation (Package/Compare/History), the
persistent Progress panel (no longer a page inside `window.stack`), and
the History screen's integration with `history.py`.
"""

from __future__ import annotations

from pathlib import Path

from lender_package_builder import history
from lender_package_builder.models import (
    IntegrityCheckResult,
    OutputPart,
    ProcessingStatus,
    RunResult,
    SourceOccurrence,
)


def _make_occurrence(doc_id: str) -> SourceOccurrence:
    return SourceOccurrence(
        document_id=doc_id,
        traversal_index=1,
        original_filename=f"{doc_id}.pdf",
        original_relative_path=f"{doc_id}.pdf",
        original_extension=".pdf",
        original_size_bytes=1000,
        status=ProcessingStatus.CONVERTED,
        converted_page_count=3,
        converted_size_bytes=5000,
    )


def _make_successful_run(tmp_path: Path) -> RunResult:
    output_path = tmp_path / "output"
    output_path.mkdir()
    occ = _make_occurrence("DOC-000001")
    final_part = OutputPart(
        package="Final", index=1, file_path=output_path / "Final" / "part1.pdf",
        document_ids=["DOC-000001"], page_count=3, file_size_bytes=10000,
    )
    checks = [IntegrityCheckResult(name="Check 1", passed=True, detail="ok")]
    return RunResult(
        input_path=tmp_path / "input.zip",
        output_path=output_path,
        start_time="2026-01-01T00:00:00",
        end_time="2026-01-01T00:01:00",
        elapsed_seconds=60.0,
        occurrences=[occ],
        og_parts=[],
        final_parts=[final_part],
        integrity_checks=checks,
    )


# TEST - clicking each sidebar nav button switches top_level_stack and
# marks exactly that button as the active/checked one
def test_sidebar_nav_switches_pages_and_active_state(window):
    assert window.nav_package_button.isChecked() is True
    assert window.top_level_stack.currentWidget() is window.top_level_stack.widget(0)

    window.compare_packages_button.click()
    assert window.top_level_stack.currentWidget() is window.compare_workspace
    assert window.compare_packages_button.isChecked() is True
    assert window.nav_package_button.isChecked() is False
    assert window.nav_history_button.isChecked() is False

    window.nav_history_button.click()
    assert window.top_level_stack.currentWidget() is window.history_view
    assert window.nav_history_button.isChecked() is True
    assert window.compare_packages_button.isChecked() is False

    window.nav_package_button.click()
    assert window.top_level_stack.currentWidget() is window.top_level_stack.widget(0)
    assert window.nav_package_button.isChecked() is True


# TEST - Compare Packages' own "Back to Build" button also updates the
# sidebar's active nav state, not just the page shown
def test_compare_back_button_restores_package_nav_active_state(window):
    window.compare_packages_button.click()
    assert window.compare_packages_button.isChecked() is True

    window.compare_workspace.back_button.click()

    assert window.top_level_stack.currentWidget() is window.top_level_stack.widget(0)
    assert window.nav_package_button.isChecked() is True
    assert window.compare_packages_button.isChecked() is False


# TEST - the progress panel is a persistent sibling of the input/result/
# failure stack, not one of its pages
def test_progress_view_is_not_a_page_in_the_build_stack(window):
    for i in range(window.stack.count()):
        assert window.stack.widget(i) is not window.progress_view
    assert window.progress_view.isVisible()


# TEST - the progress panel starts idle ("Ready to build") before any
# build has run
def test_progress_panel_starts_in_ready_to_build_state(window):
    assert window.progress_view.stage_label.text() == "Ready to build"
    assert window.progress_view.cancel_button.isVisible() is False


# TEST - starting a build shows the Cancel button and hides it again
# once the run finishes (stop() returns the panel to idle)
def test_progress_panel_shows_cancel_while_running_and_hides_after_stop(window):
    window.progress_view.start()
    assert window.progress_view.cancel_button.isVisible() is True
    assert window.progress_view.stage_label.text() == "Preparing"

    window.progress_view.stop()
    assert window.progress_view.cancel_button.isVisible() is False
    assert window.progress_view.stage_label.text() == "Ready to build"


# TEST - History starts empty, and refresh() picks up newly-written entries
def test_history_view_starts_empty_and_refreshes(window, tmp_path):
    window.nav_history_button.click()
    assert window.history_view.entry_count() == 0
    assert window.history_view.empty_label.isVisible() is True

    history.append_history_entry(
        history.HistoryEntry(
            identity=window.advanced_settings.get_identity(),
            output_path=str(tmp_path),
            status="Success",
            timestamp="2026-07-22T10:00:00",
            document_count=3,
        )
    )

    window.nav_history_button.click()  # re-selecting the tab refreshes it
    assert window.history_view.entry_count() == 1
    assert window.history_view.empty_label.isVisible() is False


# TEST - a successful build is recorded to history with the identity
# and output path used for that run
def test_successful_build_recorded_to_history(window, tmp_path):
    run = _make_successful_run(tmp_path)
    window._last_identity = window.advanced_settings.get_identity()
    window._last_run_config = window.config
    window._on_build_finished(run)

    entries = history.load_history()
    assert len(entries) == 1
    assert entries[0].status == "Success"
    assert entries[0].output_path == str(run.output_path)
    assert entries[0].identity == window._last_identity


# TEST - a cancelled build is recorded with status "Cancelled" and the
# error's output_path, never as a success
def test_cancelled_build_recorded_to_history(window):
    from lender_package_builder.exceptions import ProcessingCancelledError

    error = ProcessingCancelledError(
        "Processing was cancelled before it finished.",
        stage="converting_documents",
        output_path=Path("/tmp/some-cancelled-output"),
    )
    window._last_identity = window.advanced_settings.get_identity()
    window._on_build_cancelled(error)

    entries = history.load_history()
    assert len(entries) == 1
    assert entries[0].status == "Cancelled"
    assert entries[0].output_path == "/tmp/some-cancelled-output"


# TEST - a history-write failure never raises out of the completion
# handler (it is a convenience log, not part of the safety contract)
def test_history_write_failure_does_not_raise(window, tmp_path, monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("lender_package_builder.gui.main_window.history.append_history_entry", _boom)

    run = _make_successful_run(tmp_path)
    window._last_identity = window.advanced_settings.get_identity()
    window._last_run_config = window.config
    window._on_build_finished(run)  # must not raise

    assert window.stack.currentWidget() is window.result_view
