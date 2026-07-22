"""Main application window: wires the input, progress, and result
widgets together and owns the background worker lifecycle.

No processing logic lives here -- this module only calls into the
Stage 1 engine via `worker.py`'s background-thread helpers and reacts
to the structured events/results they emit.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import archives, runtime_paths
from .._version import PRODUCT_NAME, USER_VERSION
from ..cancellation import CancellationToken
from ..cli import _default_config_path
from ..config import AppConfig, load_config_safe
from ..models import PackageIdentity
from ..progress import ProgressEvent, ProgressStage
from . import dialogs
from .formatting import format_bytes
from .state import InputSelection, classify_input
from .widgets.advanced_settings import AdvancedSettingsWidget
from .widgets.compare_workspace import CompareWorkspace
from .widgets.drop_zone import DropZone, SelectedInputCard
from .widgets.package_identity_dialog import PackageIdentityDialog
from .widgets.progress_view import ProgressView
from .widgets.result_view import FailureView, ResultView
from .worker import CallableWorker, make_build_callable, make_estimate_callable, start_worker

_ASSETS_DIR = runtime_paths.bundled_assets_root() / "gui" / "assets"


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: AppConfig | None = None,
        parent: QWidget | None = None,
        preselect_path: Path | None = None,
        startup_multiple_items_message: str | None = None,
    ):
        super().__init__(parent)
        self._preselect_path = preselect_path
        self._startup_multiple_items_message = startup_multiple_items_message
        self._config_warning: str | None = None
        if config is not None:
            self.config = config
        else:
            result = load_config_safe(_default_config_path())
            self.config = result.config
            if result.used_defaults_due_to_error:
                self._config_warning = result.warning

        self.current_selection: InputSelection | None = None
        self.is_processing = False

        self._estimate_thread = None
        self._estimate_worker = None
        self._build_thread = None
        self._build_worker = None
        self._last_run_config: AppConfig | None = None
        self._last_allow_large_input = False
        self._last_identity: PackageIdentity | None = None
        self._cancel_token: CancellationToken | None = None

        self.setWindowTitle(f"{PRODUCT_NAME} - v{USER_VERSION}")
        icon_path = _ASSETS_DIR / "app_icon.svg"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(900, 650)
        self.setMinimumSize(760, 560)

        self._build_ui()
        self._center_on_screen()

        if self._config_warning:
            QTimer.singleShot(0, self._show_config_warning)
        if self._startup_multiple_items_message:
            QTimer.singleShot(0, self._show_startup_multiple_items_message)
        elif self._preselect_path is not None:
            QTimer.singleShot(0, self._apply_preselect_path)

    def _show_config_warning(self) -> None:
        dialogs.show_config_warning(self, self._config_warning or "")

    def _show_startup_multiple_items_message(self) -> None:
        dialogs.show_multiple_items_message(self, self._startup_multiple_items_message or "")

    def _apply_preselect_path(self) -> None:
        # Preselects the dragged-onto-the-.exe input, exactly like a
        # drag onto the in-app drop zone -- it never starts processing
        # on its own; the user still clicks "Build Lender Packages".
        if self._preselect_path is not None and self._preselect_path.exists():
            self._on_input_selected(self._preselect_path)

    # -- construction ----------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(18)

        root.addWidget(self._build_header())

        self.top_level_stack = QStackedWidget()
        root.addWidget(self.top_level_stack, stretch=1)

        build_page = QWidget()
        build_layout = QVBoxLayout(build_page)
        build_layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        build_layout.addWidget(self.stack)

        self.input_page = self._build_input_page()
        self.progress_view = ProgressView()
        self.result_view = ResultView()
        self.failure_view = FailureView()

        self.stack.addWidget(self.input_page)
        self.stack.addWidget(self.progress_view)
        self.stack.addWidget(self.result_view)
        self.stack.addWidget(self.failure_view)
        self.stack.setCurrentWidget(self.input_page)

        self.result_view.process_another_requested.connect(self._on_process_another)
        self.failure_view.change_input_requested.connect(self._on_process_another)
        self.failure_view.try_again_requested.connect(self._on_try_again)
        self.progress_view.cancel_requested.connect(self._on_cancel_clicked)

        self.compare_workspace = CompareWorkspace()
        self.compare_workspace.back_button.clicked.connect(self._show_build_workspace)

        self.top_level_stack.addWidget(build_page)
        self.top_level_stack.addWidget(self.compare_workspace)
        self.top_level_stack.setCurrentWidget(build_page)

    def _show_compare_workspace(self) -> None:
        self.top_level_stack.setCurrentWidget(self.compare_workspace)

    def _show_build_workspace(self) -> None:
        self.top_level_stack.setCurrentWidget(self.top_level_stack.widget(0))

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title = QLabel(PRODUCT_NAME)
        title.setObjectName("AppTitle")
        text_col.addWidget(title)
        subtitle = QLabel(f"Build complete and deduplicated lender PDF packages  ·  v{USER_VERSION}")
        subtitle.setObjectName("AppSubtitle")
        text_col.addWidget(subtitle)
        layout.addLayout(text_col)

        layout.addStretch(1)

        self.compare_packages_button = QPushButton("Compare Packages")
        self.compare_packages_button.clicked.connect(self._show_compare_workspace)
        layout.addWidget(self.compare_packages_button, alignment=Qt.AlignmentFlag.AlignTop)

        privacy_badge = QLabel("Local processing only")
        privacy_badge.setObjectName("PrivacyBadge")
        layout.addWidget(privacy_badge, alignment=Qt.AlignmentFlag.AlignTop)
        return header

    def _build_input_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)

        self.drop_zone = DropZone()
        self.drop_zone.input_selected.connect(self._on_input_selected)
        self.drop_zone.multiple_items_rejected.connect(self._on_multiple_items_rejected)
        layout.addWidget(self.drop_zone)

        self.selected_card = SelectedInputCard()
        self.selected_card.change_requested.connect(self._on_change_input)
        self.selected_card.hide()
        layout.addWidget(self.selected_card)

        self.advanced_settings = AdvancedSettingsWidget(
            self.config.max_pages_per_part,
            self.config.max_size_mb_per_part,
            self.config.enable_content_aware_dedup,
        )
        self.advanced_settings.hide()
        layout.addWidget(self.advanced_settings)

        self.output_hint_label = QLabel("Output will be saved next to the selected input.")
        self.output_hint_label.setObjectName("MutedLabel")
        self.output_hint_label.hide()
        layout.addWidget(self.output_hint_label)

        layout.addStretch(1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.build_button = QPushButton("Build Lender Packages")
        self.build_button.setObjectName("PrimaryButton")
        self.build_button.setEnabled(False)
        self.build_button.clicked.connect(self._on_build_clicked)
        button_row.addWidget(self.build_button)
        layout.addLayout(button_row)

        return page

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(available.center())
        self.move(frame.topLeft())

    # -- input selection ----------------------------------------------

    def _on_input_selected(self, path: Path) -> None:
        self.current_selection = classify_input(path)
        self.selected_card.set_selection(self.current_selection)
        self.drop_zone.hide()
        self.selected_card.show()
        self.advanced_settings.show()
        self.output_hint_label.show()
        self.build_button.setEnabled(True)
        self._start_estimate(path)

    def _on_multiple_items_rejected(self, message: str) -> None:
        dialogs.show_multiple_items_message(self, message)

    def _on_change_input(self) -> None:
        self.current_selection = None
        self.selected_card.hide()
        self.advanced_settings.hide()
        self.output_hint_label.hide()
        self.drop_zone.show()
        self.build_button.setEnabled(False)
        self.stack.setCurrentWidget(self.input_page)

    def _start_estimate(self, path: Path) -> None:
        worker = CallableWorker()
        worker.set_callable(make_estimate_callable(path))
        worker.finished.connect(self._on_estimate_ready)
        worker.failed.connect(self._on_estimate_failed)
        self._estimate_worker = worker
        self._estimate_thread = start_worker(worker, thread_parent=self)

    def _on_estimate_ready(self, estimate: archives.ExpansionEstimate) -> None:
        if self.current_selection is None:
            return
        self.current_selection.estimate = estimate
        exceeds_hard_limit = (
            estimate.total_uncompressed_bytes > self.config.max_expanded_size_bytes
            or estimate.total_entries > self.config.max_archive_entries
        )
        self.selected_card.set_estimate(
            estimate.total_entries,
            estimate.total_uncompressed_bytes,
            self.config.large_input_warning_bytes,
            exceeds_hard_limit,
        )

    def _on_estimate_failed(self, user_message: str, _technical_details: str) -> None:
        if self.current_selection is not None:
            self.current_selection.estimate_error = user_message
            self.selected_card.set_estimate_error(user_message)

    # -- build ----------------------------------------------

    def _on_build_clicked(self) -> None:
        if self.current_selection is None or self.is_processing:
            return
        valid, _ = self.advanced_settings.validate()
        if not valid:
            return

        values = self.advanced_settings.get_values()
        run_config = dataclasses.replace(
            self.config,
            max_pages_per_part=values.max_pages_per_part,
            max_size_mb_per_part=values.max_size_mb_per_part,
            enable_content_aware_dedup=values.enable_content_aware_dedup,
        )

        allow_large_input = False
        estimate = self.current_selection.estimate
        if estimate is not None:
            exceeds_hard_limit = (
                estimate.total_uncompressed_bytes > run_config.max_expanded_size_bytes
                or estimate.total_entries > run_config.max_archive_entries
            )
            if exceeds_hard_limit:
                limit_message = (
                    f"The safety limit is {run_config.max_expanded_size_mb:.0f} MB expanded or "
                    f"{run_config.max_archive_entries:,} entries, whichever is reached first."
                )
                dialog = dialogs.LargeInputConfirmDialog(
                    estimate.total_entries, estimate.total_uncompressed_bytes, limit_message, self
                )
                dialog.exec()
                if not dialog.confirmed():
                    return
                allow_large_input = True

        identity_dialog = PackageIdentityDialog(self, self._last_identity)
        if identity_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        identity = identity_dialog.identity()

        self._start_build(run_config, allow_large_input, identity)

    def _start_build(
        self, run_config: AppConfig, allow_large_input: bool, identity: PackageIdentity
    ) -> None:
        self._last_run_config = run_config
        self._last_allow_large_input = allow_large_input
        self._last_identity = identity
        self.is_processing = True
        self._cancel_token = CancellationToken()
        self._set_input_controls_enabled(False)
        self.progress_view.start()
        self.stack.setCurrentWidget(self.progress_view)

        worker = CallableWorker()
        worker.set_callable(
            make_build_callable(
                self.current_selection.path,
                None,
                run_config,
                allow_large_input,
                worker.progress.emit,
                identity,
                self._cancel_token,
            )
        )
        worker.progress.connect(self._on_progress_event)
        worker.finished.connect(self._on_build_finished)
        worker.failed.connect(self._on_build_failed)
        worker.cancelled.connect(self._on_build_cancelled)
        self._build_worker = worker
        self._build_thread = start_worker(worker, thread_parent=self)

    def _on_progress_event(self, event: ProgressEvent) -> None:
        self.progress_view.handle_event(event)

    def _on_cancel_clicked(self) -> None:
        if not self.is_processing or self._cancel_token is None:
            return
        if dialogs.confirm_cancel_processing(self):
            self.progress_view.set_cancelling()
            self._cancel_token.request()

    def _on_build_finished(self, run) -> None:
        self.is_processing = False
        self._cancel_token = None
        self.progress_view.stop()
        self._set_input_controls_enabled(True)

        if not run.success:
            failed_checks = [c for c in run.integrity_checks if not c.passed]
            lines = [f"[FAIL] {c.name}: {c.detail}" for c in failed_checks]
            technical_details = "\n".join(lines) if lines else "No further detail is available."
            self.failure_view.set_error(
                "Processing finished, but one or more required integrity checks did not pass. "
                "This output should not be treated as reliable -- see the technical details below "
                "and the Reports folder.",
                technical_details,
                log_dir=run.output_path / "Reports",
            )
            self.stack.setCurrentWidget(self.failure_view)
            return

        is_warning = _has_warnings(run)
        self.result_view.set_result(run, is_warning, self._last_run_config, self._last_allow_large_input)
        self.stack.setCurrentWidget(self.result_view)

    def _on_build_failed(self, user_message: str, technical_details: str) -> None:
        self.is_processing = False
        self._cancel_token = None
        self.progress_view.stop()
        self._set_input_controls_enabled(True)
        self.failure_view.set_error(user_message, technical_details, log_dir=None)
        self.stack.setCurrentWidget(self.failure_view)

    def _on_build_cancelled(self, error) -> None:
        self.is_processing = False
        self._cancel_token = None
        self.progress_view.stop()
        self._set_input_controls_enabled(True)
        self.failure_view.set_cancelled(error)
        self.stack.setCurrentWidget(self.failure_view)

    def _on_process_another(self) -> None:
        self._on_change_input()

    def _on_try_again(self) -> None:
        if self.current_selection is not None:
            self._on_build_clicked()

    def _set_input_controls_enabled(self, enabled: bool) -> None:
        self.drop_zone.setEnabled(enabled)
        self.selected_card.setEnabled(enabled)
        self.advanced_settings.setEnabled(enabled)
        self.build_button.setEnabled(enabled and self.current_selection is not None)

    # -- window lifecycle ----------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if self.is_processing:
            dialogs.warn_processing_in_progress(self)
            event.ignore()
            return
        if self.compare_workspace.is_comparing:
            dialogs.warn_comparison_in_progress(self)
            event.ignore()
            return
        event.accept()


def _has_warnings(run) -> bool:
    from ..models import ProcessingStatus

    non_ignored = [o for o in run.occurrences if not o.is_ignored_artifact]
    has_placeholders = any(o.status == ProcessingStatus.UNCONVERTED_PLACEHOLDER for o in non_ignored)
    has_warnings = any(o.conversion_warnings for o in non_ignored)
    return has_placeholders or has_warnings
