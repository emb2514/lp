from __future__ import annotations

import threading
import time

from PySide6.QtCore import QTimer

from lender_package_builder.gui.worker import CallableWorker, start_worker
from lender_package_builder.progress import ProgressEvent, ProgressSeverity, ProgressStage


# TEST 8 - STRUCTURED PROGRESS EVENTS
def test_progress_view_switches_between_determinate_and_indeterminate(window):
    view = window.progress_view
    view.start()

    # No total -> indeterminate (busy) progress bar.
    view.handle_event(
        ProgressEvent(stage=ProgressStage.DISCOVERING_FILES, message="Discovering files...")
    )
    assert view.progress_bar.minimum() == 0
    assert view.progress_bar.maximum() == 0  # Qt's convention for indeterminate

    # A real current/total -> determinate progress bar reflecting it.
    view.handle_event(
        ProgressEvent(
            stage=ProgressStage.CONVERTING_DOCUMENTS,
            message="Converting doc 3 of 10",
            current=3,
            total=10,
            current_item="loan_app.pdf",
        )
    )
    assert view.progress_bar.maximum() == 10
    assert view.progress_bar.value() == 3
    assert view.stage_label.text() == "Converting documents"
    assert "loan_app.pdf" in view.current_item_label.text()
    assert view.count_label.text() == "Document 3 of 10"

    view.handle_event(
        ProgressEvent(
            stage=ProgressStage.CONVERTING_DOCUMENTS,
            message="Placeholder inserted",
            current=4,
            total=10,
            severity=ProgressSeverity.WARNING,
        )
    )
    assert "[Warning]" in view.activity_log.toPlainText()

    view.stop()


def test_progress_events_delivered_through_main_window(window):
    events_seen = []
    window.progress_view.handle_event = lambda e: events_seen.append(e)  # type: ignore[method-assign]

    event = ProgressEvent(stage=ProgressStage.BUILDING_OG, message="Merging OG package...")
    window._on_progress_event(event)

    assert events_seen == [event]


# TEST 9 - RESPONSIVE BACKGROUND WORKER
#
# The QThread/worker are parented to `window` (a QWidget with a stable,
# qtbot-managed lifetime) rather than left as bare local variables --
# an unparented QThread is a known PySide6 crash hazard if its Python
# wrapper is collected while the OS thread is still winding down. This
# mirrors exactly how MainWindow itself owns build/estimate workers.
def test_callable_worker_runs_off_the_main_thread(window, qtbot):
    main_thread_id = threading.get_ident()
    seen_thread_id = {}

    def slow_work():
        seen_thread_id["id"] = threading.get_ident()
        time.sleep(0.05)
        return 42

    worker = CallableWorker()
    worker.set_callable(slow_work)

    results = []
    worker.finished.connect(lambda r: results.append(r))

    thread = start_worker(worker, thread_parent=window)

    with qtbot.waitSignal(worker.finished, timeout=5000):
        pass

    assert results == [42]
    assert seen_thread_id["id"] != main_thread_id

    qtbot.waitUntil(lambda: not thread.isRunning(), timeout=2000)


def test_ui_event_loop_stays_responsive_during_background_work(window, qtbot):
    """Proves the UI thread is not blocked: a QTimer firing on the main
    thread must keep incrementing while a slow callable runs in the
    background -- if the callable ran on the main thread instead, the
    event loop (and this timer) would be frozen until it finished.
    """

    tick_count = {"n": 0}
    timer = QTimer(window)
    timer.setInterval(5)
    timer.timeout.connect(lambda: tick_count.__setitem__("n", tick_count["n"] + 1))
    timer.start()

    def slow_work():
        time.sleep(0.3)
        return "done"

    worker = CallableWorker()
    worker.set_callable(slow_work)
    thread = start_worker(worker, thread_parent=window)

    with qtbot.waitSignal(worker.finished, timeout=5000):
        pass

    timer.stop()
    qtbot.waitUntil(lambda: not thread.isRunning(), timeout=2000)

    # The 300ms sleep happened entirely in the background; the 5ms
    # interval timer on the main thread should have ticked many times.
    assert tick_count["n"] > 5
