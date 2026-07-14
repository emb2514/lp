from __future__ import annotations

from pathlib import Path

from fixtures.builders import make_zip

from lender_package_builder.models import IntegrityCheckResult, OutputPart, RunResult


def _minimal_run(tmp_path: Path) -> RunResult:
    output_path = tmp_path / "output"
    output_path.mkdir()
    part = OutputPart(
        package="OG", index=1, file_path=output_path / "OG" / "part1.pdf",
        document_ids=["DOC-000001"], page_count=1, file_size_bytes=100,
    )
    return RunResult(
        input_path=tmp_path / "input.zip",
        output_path=output_path,
        start_time="t0",
        og_parts=[part],
        final_parts=[part],
        integrity_checks=[IntegrityCheckResult(name="c", passed=True, detail="ok")],
    )


# TEST 16 - PROCESS ANOTHER PACKAGE
def test_process_another_resets_to_input_state_and_preserves_previous_output(window, tmp_path, qtbot):
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    run = _minimal_run(tmp_path)
    # Simulate real output already on disk from a prior run.
    (run.output_path / "OG").mkdir(exist_ok=True)
    marker_file = run.output_path / "OG" / "marker.txt"
    marker_file.write_text("previous output")

    window._on_build_finished(run)
    assert window.stack.currentWidget() is window.result_view

    window.result_view.process_another_requested.emit()

    assert window.stack.currentWidget() is window.input_page
    assert window.current_selection is None
    assert window.drop_zone.isVisible()
    assert not window.build_button.isEnabled()

    # Previous output must remain completely untouched.
    assert marker_file.exists()
    assert marker_file.read_text() == "previous output"


def test_change_input_from_failure_view_resets_state(window):
    window._on_build_failed("Something went wrong", "trace")
    assert window.stack.currentWidget() is window.failure_view

    window.failure_view.change_input_requested.emit()

    assert window.stack.currentWidget() is window.input_page
    assert window.current_selection is None


# TEST 17 - CLOSE DURING PROCESSING
def test_close_during_processing_shows_warning_and_does_not_close(window, monkeypatch):
    warnings_shown = []
    monkeypatch.setattr(
        "lender_package_builder.gui.main_window.dialogs.warn_processing_in_progress",
        lambda parent: warnings_shown.append(True),
    )

    window.is_processing = True
    accepted = window.close()

    assert accepted is False  # the close event was ignored, not honored
    assert warnings_shown == [True]


def test_close_when_idle_closes_normally(window, monkeypatch):
    warnings_shown = []
    monkeypatch.setattr(
        "lender_package_builder.gui.main_window.dialogs.warn_processing_in_progress",
        lambda parent: warnings_shown.append(True),
    )

    window.is_processing = False
    accepted = window.close()

    assert accepted is True
    assert warnings_shown == []
