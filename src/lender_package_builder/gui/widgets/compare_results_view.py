"""Compare Packages results screen: summary totals, a filterable/
searchable findings list, a side-by-side detail panel for the selected
finding, and the Previous/Next/Open Old/Open New/Export Report actions.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import compare_packages
from .. import os_actions

_ALL_CATEGORIES = "All categories"


class CompareResultsView(QWidget):
    new_comparison_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._result: compare_packages.ComparisonResult | None = None
        self._visible_findings: list[compare_packages.ComparisonFinding] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        summary_card = QFrame()
        summary_card.setObjectName("Card")
        self._summary_layout = QGridLayout(summary_card)
        self._summary_layout.setContentsMargins(16, 14, 16, 14)
        self._summary_layout.setHorizontalSpacing(24)
        layout.addWidget(summary_card)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        filter_row.addWidget(QLabel("Filter:"))
        self.category_filter = QComboBox()
        self.category_filter.addItem(_ALL_CATEGORIES)
        self.category_filter.currentIndexChanged.connect(self._apply_filters)
        filter_row.addWidget(self.category_filter)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search file names or explanation text...")
        self.search_box.textChanged.connect(self._apply_filters)
        filter_row.addWidget(self.search_box, stretch=1)
        layout.addLayout(filter_row)

        self.findings_table = QTableWidget(0, 4)
        self.findings_table.setHorizontalHeaderLabels(["ID", "Category", "Old", "New"])
        self.findings_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.findings_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.findings_table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.findings_table, stretch=1)

        detail_card = QFrame()
        detail_card.setObjectName("Card")
        detail_layout = QVBoxLayout(detail_card)
        self.detail_label = QLabel("Select a finding to see details.")
        self.detail_label.setWordWrap(True)
        detail_layout.addWidget(self.detail_label)
        layout.addWidget(detail_card)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.previous_button = QPushButton("Previous Finding")
        self.previous_button.clicked.connect(self._select_previous)
        button_row.addWidget(self.previous_button)

        self.next_button = QPushButton("Next Finding")
        self.next_button.clicked.connect(self._select_next)
        button_row.addWidget(self.next_button)

        self.open_old_button = QPushButton("Open Old Package")
        self.open_old_button.clicked.connect(self._open_old)
        button_row.addWidget(self.open_old_button)

        self.open_new_button = QPushButton("Open New Package")
        self.open_new_button.clicked.connect(self._open_new)
        button_row.addWidget(self.open_new_button)

        self.export_button = QPushButton("Export Report")
        self.export_button.clicked.connect(self._export_report)
        button_row.addWidget(self.export_button)

        button_row.addStretch(1)

        self.new_comparison_button = QPushButton("New Comparison")
        self.new_comparison_button.setObjectName("PrimaryButton")
        self.new_comparison_button.clicked.connect(self.new_comparison_requested.emit)
        button_row.addWidget(self.new_comparison_button)

        layout.addLayout(button_row)

    # -- populating ----------------------------------------------

    def set_result(self, result: compare_packages.ComparisonResult) -> None:
        self._result = result
        self._populate_summary(result)
        self._populate_category_filter(result)
        self.search_box.clear()
        self._apply_filters()

    def _populate_summary(self, result: compare_packages.ComparisonResult) -> None:
        while self._summary_layout.count():
            item = self._summary_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        counts = result.counts_by_category()
        rows = [
            ("Old package pages", str(result.old_page_count)),
            ("New package pages", str(result.new_page_count)),
            ("Exact Match", str(counts.get(compare_packages.CATEGORY_EXACT_MATCH, 0))),
            ("Equivalent Content", str(counts.get(compare_packages.CATEGORY_EQUIVALENT_CONTENT, 0))),
            ("Likely Duplicate Removed", str(counts.get(compare_packages.CATEGORY_LIKELY_DUPLICATE_REMOVED, 0))),
            ("Meaningful Difference", str(counts.get(compare_packages.CATEGORY_MEANINGFUL_DIFFERENCE, 0))),
            ("Only in Old", str(counts.get(compare_packages.CATEGORY_ONLY_IN_OLD, 0))),
            ("Only in New", str(counts.get(compare_packages.CATEGORY_ONLY_IN_NEW, 0))),
            ("Possible Missing Document", str(counts.get(compare_packages.CATEGORY_POSSIBLE_MISSING, 0))),
            (
                "Needs Review",
                str(sum(1 for f in result.findings if f.review_recommended)),
            ),
        ]
        for row, (label_text, value_text) in enumerate(rows):
            label = QLabel(label_text)
            label.setObjectName("MutedLabel")
            value = QLabel(value_text)
            value.setObjectName("SectionHeading")
            self._summary_layout.addWidget(label, row % 5, (row // 5) * 2)
            self._summary_layout.addWidget(value, row % 5, (row // 5) * 2 + 1)

    def _populate_category_filter(self, result: compare_packages.ComparisonResult) -> None:
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem(_ALL_CATEGORIES)
        for category in sorted(result.counts_by_category()):
            self.category_filter.addItem(category)
        self.category_filter.blockSignals(False)

    # -- filtering ----------------------------------------------

    def _apply_filters(self) -> None:
        if self._result is None:
            return
        category = self.category_filter.currentText()
        search = self.search_box.text().strip().casefold()

        visible = []
        for finding in self._result.findings:
            if category != _ALL_CATEGORIES and finding.category != category:
                continue
            if search:
                haystack = " ".join(
                    filter(None, [finding.old_ref, finding.new_ref, finding.explanation, finding.finding_id])
                ).casefold()
                if search not in haystack:
                    continue
            visible.append(finding)

        self._visible_findings = visible
        self._populate_table(visible)

    def _populate_table(self, findings: list[compare_packages.ComparisonFinding]) -> None:
        self.findings_table.setRowCount(len(findings))
        for row, finding in enumerate(findings):
            self.findings_table.setItem(row, 0, QTableWidgetItem(finding.finding_id))
            self.findings_table.setItem(row, 1, QTableWidgetItem(finding.category))
            self.findings_table.setItem(row, 2, QTableWidgetItem(finding.old_ref or "(not present)"))
            self.findings_table.setItem(row, 3, QTableWidgetItem(finding.new_ref or "(not present)"))
        if findings:
            self.findings_table.selectRow(0)
        else:
            self.detail_label.setText("No findings match the current filter/search.")

    # -- selection / detail panel ----------------------------------------------

    def _on_selection_changed(self) -> None:
        finding = self._current_finding()
        if finding is None:
            return
        lines = [
            f"{finding.finding_id}: {finding.category} (confidence {finding.confidence:.2f})",
            f"Old: {finding.old_ref or '(not present)'}",
            f"New: {finding.new_ref or '(not present)'}",
        ]
        if finding.protected_differences:
            lines.append(f"Protected differences: {', '.join(finding.protected_differences)}")
        lines.append(finding.explanation)
        if finding.review_recommended:
            lines.append("Recommendation: review this finding directly before relying on it.")
        self.detail_label.setText("\n".join(lines))

    def _current_finding(self) -> compare_packages.ComparisonFinding | None:
        row = self.findings_table.currentRow()
        if row < 0 or row >= len(self._visible_findings):
            return None
        return self._visible_findings[row]

    def _select_previous(self) -> None:
        row = self.findings_table.currentRow()
        if row > 0:
            self.findings_table.selectRow(row - 1)

    def _select_next(self) -> None:
        row = self.findings_table.currentRow()
        if row < self.findings_table.rowCount() - 1:
            self.findings_table.selectRow(row + 1)

    # -- actions ----------------------------------------------

    def _open_old(self) -> None:
        if self._result is not None and self._result.old_files:
            os_actions.open_file(self._result.old_files[0])

    def _open_new(self) -> None:
        if self._result is not None and self._result.new_files:
            os_actions.open_file(self._result.new_files[0])

    def _export_report(self) -> None:
        if self._result is None:
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Export Package Comparison Report", "Package Comparison Report.txt", filter="Text Files (*.txt)"
        )
        if path_str:
            compare_packages.write_comparison_report(self._result, Path(path_str))
