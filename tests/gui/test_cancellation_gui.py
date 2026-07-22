"""GUI tests for MILESTONE 2 -- Cancel Processing: the progress view's
cancel button, the "Stop processing this package?" confirmation dialog,
MainWindow's wiring of the two, and a full real-background-thread
end-to-end cancellation through the actual worker/engine path.
"""

from __future__ import annotations

import pytest

from lender_package_builder.cancellation import CancellationToken
from lender_package_builder.gui.widgets.progress_view import ProgressView


# TEST 1 - the Cancel Processing button exists and emits a signal
def test_progress_view_cancel_button_emits_signal(qtbot):
    view = ProgressView()
    qtbot.addWidget(view)

    received = []
    view.cancel_requested.connect(lambda: received.append(True))
    view.cancel_button.click()

    assert received == [True]


# TEST 2 - set_cancelling() disables the button and gives feedback, and
# start() resets it for the next run
def test_progress_view_set_cancelling_disables_button(qtbot):
    view = ProgressView()
    qtbot.addWidget(view)

    view.set_cancelling()
    assert view.cancel_button.isEnabled() is False
    assert "Cancelling" in view.cancel_button.text()

    view.start()
    assert view.cancel_button.isEnabled() is True
    assert view.cancel_button.text() == "Cancel Processing"


# TEST 3 - clicking Cancel Processing shows a confirmation dialog; only
# an explicit "Stop Processing" actually requests cancellation.
def test_cancel_clicked_requires_explicit_confirmation(window, monkeypatch):
    window.is_processing = True
    window._cancel_token = CancellationToken()
    try:
        monkeypatch.setattr(
            "lender_package_builder.gui.main_window.dialogs.confirm_cancel_processing", lambda parent: False
        )
        window._on_cancel_clicked()
        assert window._cancel_token.is_requested() is False

        monkeypatch.setattr(
            "lender_package_builder.gui.main_window.dialogs.confirm_cancel_processing", lambda parent: True
        )
        window._on_cancel_clicked()
        assert window._cancel_token.is_requested() is True
    finally:
        # Otherwise the `window` fixture's teardown close() sees
        # is_processing still True and blocks on a real "processing in
        # progress" modal warning dialog.
        window.is_processing = False
        window._cancel_token = None


# TEST 4 - clicking Cancel Processing when nothing is running is a no-op
def test_cancel_clicked_noop_when_not_processing(window, monkeypatch):
    window.is_processing = False
    window._cancel_token = None
    shown = []
    monkeypatch.setattr(
        "lender_package_builder.gui.main_window.dialogs.confirm_cancel_processing",
        lambda parent: shown.append(True),
    )
    window._on_cancel_clicked()
    assert shown == []


# TEST 5 - FailureView.set_cancelled() shows a distinct, non-error banner
def test_failure_view_set_cancelled_shows_distinct_state(qtbot):
    from pathlib import Path

    from lender_package_builder.exceptions import ProcessingCancelledError
    from lender_package_builder.gui.widgets.result_view import FailureView

    view = FailureView()
    qtbot.addWidget(view)

    error = ProcessingCancelledError(
        "Processing was cancelled before it finished.",
        stage="converting_documents",
        output_path=Path("/tmp/some-output"),
        cleanup_succeeded=True,
    )
    view.set_cancelled(error)

    assert view.banner_title.text() == "Processing was cancelled"
    assert view.banner.property("status") == "warning"
    assert "converting documents" in view.reason_label.text()
    assert "never modified" in view.reason_label.text()


# TEST 6 - full end-to-end: cancelling mid-run through the real
# background-thread worker path leaves MainWindow in the cancelled
# state, not processing, and produces no Final package on disk.
@pytest.mark.real_background_thread
def test_cancel_mid_run_through_real_worker(window, tmp_path, qtbot, monkeypatch):
    from fixtures.builders import make_pdf

    from lender_package_builder.progress import ProgressStage

    folder = tmp_path / "input"
    folder.mkdir()
    for i in range(8):
        make_pdf(folder / f"doc{i:02d}.pdf", pages=1, text_prefix=f"Document {i}")

    monkeypatch.setattr("lender_package_builder.gui.main_window.dialogs.confirm_cancel_processing", lambda parent: True)

    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([folder])
    qtbot.waitUntil(lambda: window.current_selection.estimate is not None, timeout=5000)

    window._on_build_clicked()
    assert window.is_processing is True
    assert window._build_worker is not None

    # Must hook window._on_progress_event (a bound QObject method, so its
    # connection to the worker-thread signal is properly queued onto the
    # main thread) rather than connect a plain function directly to
    # worker.progress -- PySide6 runs a plain-callable connection
    # synchronously on the EMITTING (worker) thread, and touching a
    # QWidget from there is unsafe and can hang under the offscreen QPA
    # platform.
    original_on_progress_event = window._on_progress_event

    def _wrapped(event):
        original_on_progress_event(event)
        if event.stage == ProgressStage.CONVERTING_DOCUMENTS and (event.current or 0) >= 2:
            window._on_cancel_clicked()

    monkeypatch.setattr(window, "_on_progress_event", _wrapped)

    qtbot.waitUntil(lambda: not window.is_processing, timeout=30000)

    assert window.stack.currentWidget() is window.failure_view
    assert window.failure_view.banner_title.text() == "Processing was cancelled"

    output_dirs = list(tmp_path.glob("Test, Borrower*"))
    assert output_dirs, "expected the identity-named output folder to have been created"
    final_dir = output_dirs[0] / "Final"
    if final_dir.exists():
        assert list(final_dir.glob("*.pdf")) == []
