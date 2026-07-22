"""One side (Old/Reference or New/Generated) of the Compare Packages
input screen: Select PDF / Select Multiple Parts / Select Folder /
Clear Selection, plus a summary of what's currently selected.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ... import compare_packages
from .. import dialogs


class CompareSideSelector(QFrame):
    """`side_label` is the exact user-facing label ("Old / Reference
    Package" or "New / Generated Package"); `files` is always kept
    sorted in natural part order (see compare_packages.sort_part_files).
    """

    selection_changed = Signal()

    def __init__(self, side_label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.side_label = side_label
        self.files: list[Path] = []

        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        title = QLabel(side_label)
        title.setObjectName("SectionHeading")
        layout.addWidget(title)

        self.summary_label = QLabel("No selection")
        self.summary_label.setObjectName("MutedLabel")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        self.select_pdf_button = QPushButton("Select PDF")
        self.select_pdf_button.clicked.connect(self._select_pdf)
        button_row.addWidget(self.select_pdf_button)

        self.select_multiple_button = QPushButton("Select Multiple Parts")
        self.select_multiple_button.clicked.connect(self._select_multiple_parts)
        button_row.addWidget(self.select_multiple_button)

        self.select_folder_button = QPushButton("Select Folder")
        self.select_folder_button.clicked.connect(self._select_folder)
        button_row.addWidget(self.select_folder_button)

        self.clear_button = QPushButton("Clear Selection")
        self.clear_button.clicked.connect(self.clear_selection)
        button_row.addWidget(self.clear_button)

        layout.addLayout(button_row)

    # -- selection actions ----------------------------------------------

    def _select_pdf(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, f"Select {self.side_label} PDF", filter="PDF Files (*.pdf)")
        if path_str:
            self._set_files([Path(path_str)])

    def _select_multiple_parts(self) -> None:
        path_strs, _ = QFileDialog.getOpenFileNames(
            self, f"Select {self.side_label} Parts", filter="PDF Files (*.pdf)"
        )
        if path_strs:
            self._set_files([Path(p) for p in path_strs])

    def _select_folder(self) -> None:
        folder_str = QFileDialog.getExistingDirectory(self, f"Select {self.side_label} Folder")
        if not folder_str:
            return
        folder = Path(folder_str)
        contents = compare_packages.describe_folder_contents(folder)

        if contents.final_files and contents.original_files:
            choice = dialogs.choose_final_or_original_package(self, folder.name)
            if choice is None:
                return
            files = contents.final_files if choice == "final" else contents.original_files
        elif contents.final_files:
            files = contents.final_files
        elif contents.original_files:
            files = contents.original_files
        else:
            files = contents.other_pdf_files

        if not files:
            dialogs.show_no_pdfs_found(self, folder.name)
            return
        self._set_files(files)

    def clear_selection(self) -> None:
        self._set_files([])

    def _set_files(self, files: list[Path]) -> None:
        self.files = compare_packages.sort_part_files(files)
        if not self.files:
            self.summary_label.setText("No selection")
        elif len(self.files) == 1:
            self.summary_label.setText(self.files[0].name)
        else:
            names = ", ".join(f.name for f in self.files[:3])
            more = f" (+{len(self.files) - 3} more)" if len(self.files) > 3 else ""
            self.summary_label.setText(f"{len(self.files)} files: {names}{more}")
        self.selection_changed.emit()

    def is_valid(self) -> bool:
        return bool(self.files) and all(f.exists() for f in self.files)
