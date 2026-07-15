from __future__ import annotations

from pathlib import Path

from lender_package_builder.models import IntegrityCheckResult, OutputPart, RunResult


def _minimal_run(tmp_path: Path) -> RunResult:
    output_path = tmp_path / "output"
    output_path.mkdir()
    (output_path / "Final").mkdir()
    (output_path / "Reports").mkdir()

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


# TEST 15 - OPEN-FOLDER ACTIONS
def test_result_view_folder_buttons_open_correct_paths(window, tmp_path, monkeypatch):
    run = _minimal_run(tmp_path)

    opened_urls = []
    monkeypatch.setattr(
        "lender_package_builder.gui.os_actions.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url.toLocalFile()) or True,
    )

    window.result_view.set_result(run, is_warning=False)

    window.result_view.open_output_button.click()
    window.result_view.open_final_button.click()
    window.result_view.open_reports_button.click()

    # Compared as Path objects, not raw strings: Qt's QUrl always
    # normalizes local-file paths to forward slashes internally (RFC
    # 3986), even on Windows, so `toLocalFile()` can legitimately
    # differ from `str(path)`'s OS-native separators while still
    # pointing at the exact same location.
    assert [Path(u) for u in opened_urls] == [
        run.output_path,
        run.output_path / "Final",
        run.output_path / "Reports",
    ]


def test_failure_view_open_logs_button_opens_log_dir(window, tmp_path, monkeypatch):
    log_dir = tmp_path / "Logs"
    log_dir.mkdir()

    opened_urls = []
    monkeypatch.setattr(
        "lender_package_builder.gui.os_actions.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url.toLocalFile()) or True,
    )

    window.failure_view.set_error("Something failed", "traceback here", log_dir=log_dir)
    assert window.failure_view.open_logs_button.isEnabled()

    window.failure_view.open_logs_button.click()

    assert [Path(u) for u in opened_urls] == [log_dir]


def test_failure_view_open_logs_disabled_when_no_log_dir(window):
    window.failure_view.set_error("Something failed", "traceback here", log_dir=None)
    assert not window.failure_view.open_logs_button.isEnabled()


def test_copy_error_details_places_text_on_clipboard(window, qapp):
    window.failure_view.set_error("Friendly reason", "Technical stack trace", log_dir=None)
    window.failure_view._copy_details()

    clipboard_text = qapp.clipboard().text()
    assert "Friendly reason" in clipboard_text
    assert "Technical stack trace" in clipboard_text
