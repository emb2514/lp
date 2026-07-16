"""Completion views: success/warning (`ResultView`) and failure
(`FailureView`), both driven by real engine output -- never a fake
"SUCCESS" label when Stage 1 says otherwise.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import os_actions
from ..formatting import format_elapsed
from ...models import ProcessingStatus, RunResult
from .uncertain_review_dialog import UncertainReviewDialog


class ResultView(QWidget):
    """Success or success-with-warning completion state."""

    process_another_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._run: RunResult | None = None
        self._config = None
        self._allow_large_input = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.banner = QFrame()
        self.banner.setObjectName("StatusBanner")
        banner_layout = QVBoxLayout(self.banner)
        banner_layout.setContentsMargins(20, 16, 20, 16)

        self.banner_title = QLabel()
        self.banner_title.setObjectName("StatusBannerTitle")
        banner_layout.addWidget(self.banner_title)

        self.banner_message = QLabel()
        self.banner_message.setWordWrap(True)
        banner_layout.addWidget(self.banner_message)
        layout.addWidget(self.banner)

        stats_card = QFrame()
        stats_card.setObjectName("Card")
        self._stats_layout = QGridLayout(stats_card)
        self._stats_layout.setContentsMargins(20, 16, 20, 16)
        self._stats_layout.setHorizontalSpacing(24)
        self._stats_layout.setVerticalSpacing(6)
        layout.addWidget(stats_card)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        self.open_output_button = QPushButton("Open Output Folder")
        self.open_output_button.clicked.connect(self._open_output_folder)
        button_row.addWidget(self.open_output_button)

        self.open_final_button = QPushButton("Open Final Package Folder")
        self.open_final_button.clicked.connect(self._open_final_folder)
        button_row.addWidget(self.open_final_button)

        self.open_reports_button = QPushButton("Open Reports")
        self.open_reports_button.clicked.connect(self._open_reports_folder)
        button_row.addWidget(self.open_reports_button)

        self.review_uncertain_button = QPushButton("Review Uncertain Matches")
        self.review_uncertain_button.clicked.connect(self._open_uncertain_review_dialog)
        button_row.addWidget(self.review_uncertain_button)

        button_row.addStretch(1)

        self.process_another_button = QPushButton("Process Another Package")
        self.process_another_button.setObjectName("PrimaryButton")
        self.process_another_button.clicked.connect(self.process_another_requested.emit)
        button_row.addWidget(self.process_another_button)

        layout.addLayout(button_row)
        layout.addStretch(1)

    def set_result(self, run: RunResult, is_warning: bool, config=None, allow_large_input: bool = False) -> None:
        self._run = run
        self._config = config
        self._allow_large_input = allow_large_input
        status = "warning" if is_warning else "success"
        self.banner.setProperty("status", status)
        self.banner_title.setProperty("status", status)
        self.banner_title.setText(
            "Completed with items to review" if is_warning else "Lender packages built successfully"
        )
        if is_warning:
            self.banner_message.setText(
                "Processing completed and every integrity check passed, but some source files need "
                "review (see the placeholder/warning counts below and the Reports folder)."
            )
        else:
            self.banner_message.setText(
                "All source documents were processed and every integrity check passed."
            )
        for widget in (self.banner, self.banner_title):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        self._populate_stats(run)

    def _populate_stats(self, run: RunResult) -> None:
        while self._stats_layout.count():
            item = self._stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        non_ignored = [o for o in run.occurrences if not o.is_ignored_artifact]
        duplicate_count = sum(1 for o in non_ignored if o.is_duplicate)
        placeholder_count = sum(
            1 for o in non_ignored if o.status == ProcessingStatus.UNCONVERTED_PLACEHOLDER
        )
        final_doc_count = sum(len(p.document_ids) for p in run.final_parts)
        og_pages = sum(p.page_count for p in run.og_parts)
        final_pages = sum(p.page_count for p in run.final_parts)
        checks_passed = sum(1 for c in run.integrity_checks if c.passed)

        content_duplicate_count = sum(1 for o in non_ignored if o.is_content_duplicate)
        merged_overlap_count = sum(1 for o in non_ignored if o.is_contained_in_merged_document)
        portfolio_count = sum(1 for o in non_ignored if o.is_portfolio_container)
        needs_review_count = sum(1 for o in non_ignored if o.needs_review)

        rows = [
            ("Source documents discovered", str(len(run.occurrences))),
            ("Exact duplicates excluded from Final", str(duplicate_count)),
            ("Content-aware duplicates excluded from Final", str(content_duplicate_count)),
            ("Merged-package duplicates excluded from Final", str(merged_overlap_count)),
            ("PDF Portfolio containers detected", str(portfolio_count)),
            ("Document families identified", str(len(run.document_families))),
            ("Uncertain matches retained for review", str(needs_review_count)),
            ("Unique documents in Final", str(final_doc_count)),
            ("Unconverted placeholders", str(placeholder_count)),
            ("OG output parts", str(len(run.og_parts))),
            ("Final output parts", str(len(run.final_parts))),
            ("OG total pages", str(og_pages)),
            ("Final total pages", str(final_pages)),
            ("Elapsed time", format_elapsed(run.elapsed_seconds)),
            ("Integrity checks passed", f"{checks_passed}/{len(run.integrity_checks)}"),
        ]
        for row, (label_text, value_text) in enumerate(rows):
            label = QLabel(label_text)
            label.setObjectName("MutedLabel")
            value = QLabel(value_text)
            value.setObjectName("SectionHeading")
            self._stats_layout.addWidget(label, row, 0)
            self._stats_layout.addWidget(value, row, 1)

    def _open_output_folder(self) -> None:
        if self._run is not None:
            os_actions.open_folder(self._run.output_path)

    def _open_final_folder(self) -> None:
        if self._run is not None:
            os_actions.open_folder(self._run.output_path / "Final")

    def _open_reports_folder(self) -> None:
        if self._run is not None:
            os_actions.open_folder(self._run.output_path / "Reports")

    def _open_uncertain_review_dialog(self) -> None:
        if self._run is None or self._config is None:
            return
        dialog = UncertainReviewDialog(self._run, self._config, self._allow_large_input, self)
        dialog.decisions_applied.connect(self._on_review_decisions_applied)
        dialog.exec()

    def _on_review_decisions_applied(self) -> None:
        if self._run is not None:
            self._populate_stats(self._run)


class FailureView(QWidget):
    """Failure state: friendly headline, expandable technical details,
    and recovery actions. The application stays open and no diagnostic
    information is discarded.
    """

    change_input_requested = Signal()
    try_again_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._log_dir: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.banner = QFrame()
        self.banner.setObjectName("StatusBanner")
        self.banner.setProperty("status", "error")
        banner_layout = QVBoxLayout(self.banner)
        banner_layout.setContentsMargins(20, 16, 20, 16)

        self.banner_title = QLabel("Processing did not complete")
        self.banner_title.setObjectName("StatusBannerTitle")
        self.banner_title.setProperty("status", "error")
        banner_layout.addWidget(self.banner_title)

        self.reason_label = QLabel()
        self.reason_label.setWordWrap(True)
        banner_layout.addWidget(self.reason_label)
        layout.addWidget(self.banner)

        self.details_toggle = QToolButton()
        self.details_toggle.setText("▸ Technical details")
        self.details_toggle.setCheckable(True)
        self.details_toggle.toggled.connect(self._on_details_toggled)
        layout.addWidget(self.details_toggle)

        self.details_text = QPlainTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setVisible(False)
        self.details_text.setMinimumHeight(150)
        layout.addWidget(self.details_text)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        self.copy_button = QPushButton("Copy Error Details")
        self.copy_button.clicked.connect(self._copy_details)
        button_row.addWidget(self.copy_button)

        self.open_logs_button = QPushButton("Open Logs")
        self.open_logs_button.clicked.connect(self._open_logs)
        self.open_logs_button.setEnabled(False)
        button_row.addWidget(self.open_logs_button)

        button_row.addStretch(1)

        self.change_input_button = QPushButton("Change Input")
        self.change_input_button.clicked.connect(self.change_input_requested.emit)
        button_row.addWidget(self.change_input_button)

        self.try_again_button = QPushButton("Try Again")
        self.try_again_button.setObjectName("PrimaryButton")
        self.try_again_button.clicked.connect(self.try_again_requested.emit)
        button_row.addWidget(self.try_again_button)

        layout.addLayout(button_row)
        layout.addStretch(1)

    def set_error(self, user_message: str, technical_details: str, log_dir: Path | None = None) -> None:
        self.reason_label.setText(user_message)
        self.details_text.setPlainText(technical_details)
        self._log_dir = log_dir
        self.open_logs_button.setEnabled(log_dir is not None and log_dir.exists())
        self.details_toggle.setChecked(False)

    def _on_details_toggled(self, checked: bool) -> None:
        self.details_text.setVisible(checked)
        self.details_toggle.setText(("▾" if checked else "▸") + " Technical details")

    def _copy_details(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(f"{self.reason_label.text()}\n\n{self.details_text.toPlainText()}")

    def _open_logs(self) -> None:
        if self._log_dir is not None:
            os_actions.open_folder(self._log_dir)
