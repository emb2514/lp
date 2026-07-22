from __future__ import annotations

import gc
import os
import sys
from pathlib import Path

# Must run before PySide6 is imported anywhere. On a real Windows
# desktop with a display, Qt's native "windows" platform plugin is
# used normally; this only forces the offscreen platform in headless
# Linux environments (like this test container) that have no DISPLAY.
if "QT_QPA_PLATFORM" not in os.environ and sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6.QtWidgets import QApplication

from lender_package_builder.gui.theme import apply_theme


class _FakeThread:
    """Stand-in returned by the synchronous fake `start_worker`."""

    def isRunning(self) -> bool:
        return False

    def quit(self) -> None:
        pass

    def wait(self, _ms: int = 0) -> bool:
        return True


@pytest.fixture(autouse=True)
def _synchronous_background_workers(request, monkeypatch):
    """Run MainWindow's background jobs synchronously by default.

    Spinning up a real QThread on every single input selection (the
    size estimate fires automatically) across ~30 GUI tests in one
    process is a known source of cumulative instability under the
    offscreen QPA platform used here. The actual threading contract
    (real QThread, UI responsiveness, cleanup) is verified directly and
    thoroughly in test_progress_worker.py (which calls `worker.py`'s
    `start_worker` directly, bypassing this patch) and in the full
    real-worker integration test in test_gui_end_to_end.py (marked
    `real_background_thread` to opt out of this fixture).
    """

    if request.node.get_closest_marker("real_background_thread"):
        yield
        return

    def fake_start_worker(worker, thread_parent=None):
        worker.run()
        return _FakeThread()

    monkeypatch.setattr("lender_package_builder.gui.main_window.start_worker", fake_start_worker)
    yield


@pytest.fixture(autouse=True)
def _auto_confirm_package_identity_dialog(monkeypatch):
    """Auto-accepts MainWindow's pre-build "confirm package details"
    dialog with a default identity, so any test driving
    `_on_build_clicked()` doesn't block on a real modal `.exec()`
    waiting for a human. The dialog's own behavior (validation, live
    preview, cancel) is tested directly against the real widget in
    test_package_identity_dialog.py, which never goes through
    `_on_build_clicked()` and so is unaffected by this patch.
    """

    from PySide6.QtWidgets import QDialog

    from lender_package_builder.models import PackageIdentity

    class _AutoAcceptPackageIdentityDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def identity(self):
            return PackageIdentity(last_name="Test", first_name="Borrower", loan_number="0000000000")

    monkeypatch.setattr(
        "lender_package_builder.gui.main_window.PackageIdentityDialog", _AutoAcceptPackageIdentityDialog
    )
    yield


@pytest.fixture
def window(qtbot):
    from lender_package_builder.gui.main_window import MainWindow

    app = QApplication.instance()
    if app is not None:
        apply_theme(app)

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)
    yield win

    # A test may have kicked off a real background QThread (e.g. the
    # size estimate fires on every input selection) without waiting for
    # it to finish. Destroying a QWidget while a QThread it parents is
    # still running is a known crash hazard -- wait for anything
    # in-flight before closing the window.
    for attr in ("_estimate_thread", "_build_thread"):
        thread = getattr(win, attr, None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(5000)
    win.close()
    win.deleteLater()

    # Let Qt actually process the deferred deleteLater() deletion (of the
    # window and everything it parents) and let Python collect the
    # resulting garbage before the next test constructs a new MainWindow.
    # Without this, deferred C++ object destruction can pile up across
    # dozens of tests in one process and destabilize later, unrelated
    # tests under the offscreen QPA platform.
    app = QApplication.instance()
    if app is not None:
        for _ in range(5):
            app.processEvents()
    gc.collect()
