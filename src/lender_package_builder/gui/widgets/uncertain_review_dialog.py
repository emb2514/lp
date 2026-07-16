"""Read-only review screen listing every occurrence RC2's content-aware
analysis flagged `needs_review=True` -- inspection only, never an
approval workflow. Nothing the user does here changes what happened:
every flagged occurrence is already, unconditionally, kept in the Final
package (see `SourceOccurrence.included_in_final`'s `needs_review`
guard) precisely because the engine could not confirm a match with high
enough confidence to safely remove anything automatically. This dialog
exists purely so a human can see, at a glance, which pairs were
uncertain and why, and go check them by hand if they choose to -- the
full detail also lives in Merged_Document_Overlap_Report.txt and
Duplicate_Removal_Log.txt for anyone who wants it in writing.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...models import RunResult


class UncertainReviewDialog(QDialog):
    def __init__(self, run: RunResult, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Review Uncertain Matches")
        self.resize(720, 420)

        self.flagged = [o for o in run.occurrences if o.needs_review]

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        if self.flagged:
            heading_text = (
                f"{len(self.flagged)} document(s) had a possible duplicate or containment match that "
                "could not be confirmed with high enough confidence to remove automatically. Both "
                "copies of each pair were kept in the Final package -- nothing listed here was removed. "
                "This list is for your information only; no action is required."
            )
        else:
            heading_text = (
                "No uncertain matches were found in this run. Every duplicate/containment decision the "
                "engine made met its safe confidence threshold."
            )
        self.heading_label = QLabel(heading_text)
        self.heading_label.setObjectName("MutedLabel")
        self.heading_label.setWordWrap(True)
        layout.addWidget(self.heading_label)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["File", "Document ID", "Why it needs review"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setWordWrap(True)

        self.table.setRowCount(len(self.flagged))
        for row, occ in enumerate(self.flagged):
            self.table.setItem(row, 0, QTableWidgetItem(occ.original_relative_path))
            self.table.setItem(row, 1, QTableWidgetItem(occ.document_id))
            self.table.setItem(row, 2, QTableWidgetItem(occ.review_reason or "(no reason recorded)"))

        layout.addWidget(self.table, stretch=1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
