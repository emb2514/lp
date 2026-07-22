"""Compare Packages: a separate top-level workspace (MILESTONE 5B/6)
from the main Build Lender Packages flow. Owns its own input-selection
-> progress -> results state, entirely independent of MainWindow's
build-pipeline stack.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from ...cancellation import CancellationToken
from .. import dialogs
from .compare_progress_view import CompareProgressView
from .compare_results_view import CompareResultsView
from .compare_side_selector import CompareSideSelector


class CompareWorkspace(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._cancel_token: CancellationToken | None = None
        self._compare_thread = None
        self._compare_worker = None
        self.is_comparing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("Compare Packages")
        title.setObjectName("AppTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.back_button = QPushButton("Back to Build")
        header.addWidget(self.back_button)
        layout.addLayout(header)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, stretch=1)

        self.input_page = self._build_input_page()
        self.progress_view = CompareProgressView()
        self.results_view = CompareResultsView()

        self.stack.addWidget(self.input_page)
        self.stack.addWidget(self.progress_view)
        self.stack.addWidget(self.results_view)
        self.stack.setCurrentWidget(self.input_page)

        self.progress_view.cancel_requested.connect(self._on_cancel_clicked)
        self.results_view.new_comparison_requested.connect(self._on_new_comparison)

    def _build_input_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.old_selector = CompareSideSelector("Old / Reference Package")
        self.new_selector = CompareSideSelector("New / Generated Package")
        layout.addWidget(self.old_selector)
        layout.addWidget(self.new_selector)
        layout.addStretch(1)

        self.old_selector.selection_changed.connect(self._update_compare_enabled)
        self.new_selector.selection_changed.connect(self._update_compare_enabled)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.compare_button = QPushButton("Compare Packages")
        self.compare_button.setObjectName("PrimaryButton")
        self.compare_button.setEnabled(False)
        self.compare_button.clicked.connect(self._on_compare_clicked)
        button_row.addWidget(self.compare_button)
        layout.addLayout(button_row)

        return page

    def _update_compare_enabled(self) -> None:
        self.compare_button.setEnabled(self.old_selector.is_valid() and self.new_selector.is_valid())

    # -- comparison lifecycle ----------------------------------------------

    def _on_compare_clicked(self) -> None:
        if self.is_comparing or not (self.old_selector.is_valid() and self.new_selector.is_valid()):
            return
        self._start_comparison(list(self.old_selector.files), list(self.new_selector.files))

    def _start_comparison(self, old_files, new_files) -> None:
        from ..worker import CallableWorker, make_compare_callable, start_worker

        self.is_comparing = True
        self._cancel_token = CancellationToken()
        self.progress_view.start()
        self.stack.setCurrentWidget(self.progress_view)

        worker = CallableWorker()
        worker.set_callable(
            make_compare_callable(old_files, new_files, worker.progress.emit, self._cancel_token)
        )
        worker.progress.connect(self._on_progress_message)
        worker.finished.connect(self._on_compare_finished)
        worker.failed.connect(self._on_compare_failed)
        worker.cancelled.connect(self._on_compare_cancelled)
        self._compare_worker = worker
        self._compare_thread = start_worker(worker, thread_parent=self)

    def _on_progress_message(self, message: object) -> None:
        # emit_progress passes a plain string for this workflow (see
        # make_compare_callable), never a ProgressEvent.
        self.progress_view.set_status(str(message))

    def _on_cancel_clicked(self) -> None:
        if not self.is_comparing or self._cancel_token is None:
            return
        if dialogs.confirm_cancel_comparison(self):
            self.progress_view.set_cancelling()
            self._cancel_token.request()

    def _on_compare_finished(self, result) -> None:
        self.is_comparing = False
        self._cancel_token = None
        self.progress_view.stop()
        self.results_view.set_result(result)
        self.stack.setCurrentWidget(self.results_view)

    def _on_compare_failed(self, user_message: str, _technical_details: str) -> None:
        self.is_comparing = False
        self._cancel_token = None
        self.progress_view.stop()
        self._show_comparison_error(user_message)
        self.stack.setCurrentWidget(self.input_page)

    def _on_compare_cancelled(self, _error) -> None:
        self.is_comparing = False
        self._cancel_token = None
        self.progress_view.stop()
        self.stack.setCurrentWidget(self.input_page)

    def _show_comparison_error(self, message: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Comparison failed")
        box.setText("The comparison could not be completed.")
        box.setInformativeText(message)
        box.exec()

    def _on_new_comparison(self) -> None:
        self.old_selector.clear_selection()
        self.new_selector.clear_selection()
        self.stack.setCurrentWidget(self.input_page)
