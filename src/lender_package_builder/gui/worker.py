"""Background worker/thread layer.

The Stage 1 engine (`build_package()`) must never run on the Qt main
thread. `CallableWorker` wraps any zero-argument callable; `start_worker()`
moves it onto a fresh `QThread` and starts it. The same worker class is
reused for the (cheap) input-size estimate and the (potentially long)
build job.

Because a build's `progress_callback` needs a live signal to emit
through, the worker is constructed FIRST (its `progress` signal exists
immediately), and the callable is built afterwards using
`worker.progress.emit` as the callback -- before the worker is moved to
its thread or started.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal

from ..config import AppConfig
from ..exceptions import (
    ArchiveTooLargeError,
    InsufficientDiskSpaceError,
    InvalidInputError,
    LenderPackageBuilderError,
    OutputAlreadyExistsError,
)
from ..progress import ProgressCallback


class CallableWorker(QObject):
    """Runs one zero-argument callable on a worker thread."""

    progress = Signal(object)  # ProgressEvent
    finished = Signal(object)  # result
    failed = Signal(str, str)  # user_message, technical_details

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._fn: Callable[[], object] | None = None

    def set_callable(self, fn: Callable[[], object]) -> None:
        self._fn = fn

    def run(self) -> None:
        if self._fn is None:  # pragma: no cover - programming error guard
            self.failed.emit("Internal error: no work was configured.", "CallableWorker.run() with no callable set")
            return
        try:
            result = self._fn()
        except Exception as exc:  # the worker thread must never crash silently
            user_message, technical_details = translate_error(exc)
            self.failed.emit(user_message, technical_details)
            return
        self.finished.emit(result)


def start_worker(worker: CallableWorker, thread_parent: QObject | None = None) -> QThread:
    """Move `worker` to a new QThread and start it.

    `thread_parent` should be a long-lived QObject (typically the
    QWidget that owns the job, e.g. the main window) so the QThread's
    lifetime is governed by Qt's parent/child ownership rather than by
    Python reference-counting timing -- an unparented QThread whose
    Python wrapper happens to be garbage-collected while its worker
    thread is still finishing up is a known source of crashes.

    Regardless of `thread_parent`, the caller should still keep a
    reference to the returned QThread and to `worker` until the job's
    `finished`/`failed` signal has been handled.
    """

    thread = QThread(thread_parent)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.start()
    return thread


def make_build_callable(
    input_path: Path,
    output_dir: Path | None,
    config: AppConfig,
    allow_large_input: bool,
    emit_progress: ProgressCallback,
) -> Callable[[], object]:
    """Build the zero-arg callable that runs the real Stage 1 engine.

    `build_package` is imported lazily (function-local) to keep this
    module importable without pulling in the full engine at GUI
    startup time, and to make the dependency explicit at the call site.
    """

    from ..cli import build_package

    def _run():
        return build_package(
            input_path=input_path,
            output_dir=output_dir,
            config=config,
            allow_large_input=allow_large_input,
            keep_temp=False,
            verbose=False,
            progress=False,
            progress_callback=emit_progress,
        )

    return _run


def make_estimate_callable(input_path: Path) -> Callable[[], object]:
    from .. import archives

    def _run():
        return archives.estimate_expansion(input_path)

    return _run


def translate_error(exc: Exception) -> tuple[str, str]:
    """Map an exception to (friendly_user_message, technical_details)."""

    technical_details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    if isinstance(exc, InvalidInputError):
        return (
            "That input could not be used. Please choose a different ZIP, folder, or file.",
            technical_details,
        )
    if isinstance(exc, OutputAlreadyExistsError):
        return (
            "An output folder with that name already exists. Please try again in a moment, or "
            "choose a different input.",
            technical_details,
        )
    if isinstance(exc, ArchiveTooLargeError):
        return (
            "This package is larger than the configured safety limit.",
            technical_details,
        )
    if isinstance(exc, InsufficientDiskSpaceError):
        return (
            "There is not enough free disk space to safely process this package.",
            technical_details,
        )
    if isinstance(exc, LenderPackageBuilderError):
        return (f"Processing could not continue: {exc}", technical_details)

    return (
        "An unexpected error occurred while processing this package.",
        technical_details,
    )
