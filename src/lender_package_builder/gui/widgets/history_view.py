"""History: lists past builds this GUI has run (newest first), each
with an Open Folder action. Read-only -- it never affects processing
or duplicate detection, and a missing/corrupted history log only means
an empty list, never a crash (see `history.py`).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import history
from .. import os_actions

_COLUMNS = ["Name", "Loan Number", "Date", "Status", ""]


class HistoryView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        heading = QLabel("Build History")
        heading.setObjectName("SectionHeading")
        layout.addWidget(heading)

        self.empty_label = QLabel("No packages built yet -- packages you build will be listed here.")
        self.empty_label.setObjectName("MutedLabel")
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, stretch=1)

        self.refresh()

    def refresh(self) -> None:
        entries = history.load_history()
        self.table.setRowCount(0)
        self.empty_label.setVisible(not entries)
        self.table.setVisible(bool(entries))

        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(entry.display_name()))
            self.table.setItem(row, 1, QTableWidgetItem(entry.identity.loan_number or "--"))
            self.table.setItem(row, 2, QTableWidgetItem(_format_timestamp(entry.timestamp)))
            self.table.setItem(row, 3, QTableWidgetItem(entry.status))

            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            output_path = Path(entry.output_path) if entry.output_path else None
            open_button = QPushButton("Open Folder")
            open_button.setEnabled(bool(output_path and output_path.exists()))
            open_button.clicked.connect(lambda _checked=False, p=output_path: p and os_actions.open_folder(p))
            cell_layout.addWidget(open_button)
            self.table.setCellWidget(row, 4, cell)

    def entry_count(self) -> int:
        return self.table.rowCount()


def _format_timestamp(timestamp: str) -> str:
    if not timestamp:
        return "--"
    # Keep only the human-relevant prefix of an ISO 8601 timestamp
    # ("2026-07-22 19:09") without depending on any particular
    # sub-second/timezone suffix format.
    return timestamp.replace("T", " ")[:16]
