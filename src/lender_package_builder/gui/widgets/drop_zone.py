"""Input selection: the drag-and-drop zone and the selected-input
summary card shown once one valid input has been chosen.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..formatting import format_bytes
from ..state import InputSelection

MULTIPLE_ITEMS_MESSAGE = (
    "Please drop a single ZIP or folder, or drop several loose files to bundle them into one "
    "package -- not a mix of folders and files."
)


class DropZone(QFrame):
    """Large drag-and-drop target with Browse File / Browse Folder
    fallback buttons. Emits `input_selected` for exactly one valid
    path, `multiple_files_selected` when two or more loose files (no
    folders) are dropped at once -- so a loan's documents can be
    bundled into one package without first making a folder for them --
    or `multiple_items_rejected` for anything else ambiguous (a mix of
    files and folders, more than one folder, etc.).
    """

    input_selected = Signal(Path)
    multiple_files_selected = Signal(list)
    multiple_items_rejected = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(220)
        self.setProperty("dragActive", "false")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(10)
        layout.addStretch(1)

        title = QLabel("Drop a lender ZIP, folder, or one or more documents here")
        title.setObjectName("DropZoneTitle")
        title.setWordWrap(True)
        title.setAlignment(_center_alignment())
        layout.addWidget(title)

        hint = QLabel(
            "Accepts a ZIP file, a folder, or one or more documents -- drop several loose files "
            "at once to bundle them into a single package."
        )
        hint.setObjectName("DropZoneHint")
        hint.setWordWrap(True)
        hint.setAlignment(_center_alignment())
        layout.addWidget(hint)

        button_row = QHBoxLayout()
        button_row.setSpacing(12)
        button_row.addStretch(1)

        self.browse_file_button = QPushButton("Browse File")
        self.browse_file_button.setObjectName("BrowseFileButton")
        self.browse_file_button.clicked.connect(self._on_browse_file_clicked)
        button_row.addWidget(self.browse_file_button)

        self.browse_folder_button = QPushButton("Browse Folder")
        self.browse_folder_button.setObjectName("BrowseFolderButton")
        self.browse_folder_button.clicked.connect(self._on_browse_folder_clicked)
        button_row.addWidget(self.browse_folder_button)

        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addStretch(1)

    # -- drag-and-drop -----------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drag_active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._set_drag_active(False)
        urls = event.mimeData().urls()
        local_paths = [Path(u.toLocalFile()) for u in urls if u.isLocalFile()]
        event.acceptProposedAction()
        self._handle_paths(local_paths)

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    # -- browse fallback -----------------------------------------------

    def _on_browse_file_clicked(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "Choose a lender source file")
        if path_str:
            self._handle_paths([Path(path_str)])

    def _on_browse_folder_clicked(self) -> None:
        path_str = QFileDialog.getExistingDirectory(self, "Choose a lender source folder")
        if path_str:
            self._handle_paths([Path(path_str)])

    # -- shared -----------------------------------------------

    def _handle_paths(self, paths: list[Path]) -> None:
        if not paths:
            return

        if len(paths) == 1:
            path = paths[0]
            if not path.exists():
                self.multiple_items_rejected.emit(f"That path could not be found: {path}")
                return
            self.input_selected.emit(path)
            return

        missing = [p for p in paths if not p.exists()]
        if missing:
            self.multiple_items_rejected.emit(f"That path could not be found: {missing[0]}")
            return

        if all(p.is_file() for p in paths):
            self.multiple_files_selected.emit(paths)
            return

        self.multiple_items_rejected.emit(MULTIPLE_ITEMS_MESSAGE)


def _center_alignment():
    from PySide6.QtCore import Qt

    return Qt.AlignmentFlag.AlignHCenter


class SelectedInputCard(QFrame):
    """Summary shown after a valid input has been chosen."""

    change_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(6)

        header_row = QHBoxLayout()
        self.name_label = QLabel()
        self.name_label.setObjectName("SectionHeading")
        header_row.addWidget(self.name_label)
        header_row.addStretch(1)

        self.change_button = QPushButton("Change Input")
        self.change_button.clicked.connect(self.change_requested.emit)
        header_row.addWidget(self.change_button)
        layout.addLayout(header_row)

        self.path_label = QLabel()
        self.path_label.setObjectName("MutedLabel")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        self.type_label = QLabel()
        layout.addWidget(self.type_label)

        self.size_label = QLabel()
        self.size_label.setObjectName("MutedLabel")
        layout.addWidget(self.size_label)

        self.estimate_label = QLabel("Estimating package size...")
        self.estimate_label.setObjectName("MutedLabel")
        self.estimate_label.setWordWrap(True)
        layout.addWidget(self.estimate_label)

        self.warning_label = QLabel()
        self.warning_label.setObjectName("ValidationError")
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        layout.addWidget(self.warning_label)

    def set_selection(self, selection: InputSelection) -> None:
        self.name_label.setText(selection.display_name)
        self.path_label.setText(str(selection.path))
        self.type_label.setText(f"Type: {selection.kind_label}")
        if selection.original_size_bytes is not None:
            self.size_label.setText(f"Original size: {format_bytes(selection.original_size_bytes)}")
            self.size_label.show()
        else:
            self.size_label.hide()
        self.estimate_label.setText("Estimating package size...")
        self.warning_label.hide()

    def set_estimate(
        self,
        entries: int,
        expanded_bytes: int,
        warning_threshold_bytes: float,
        exceeds_hard_limit: bool,
    ) -> None:
        self.estimate_label.setText(
            f"Estimated contents: {entries:,} file entr{'y' if entries == 1 else 'ies'}, "
            f"{format_bytes(expanded_bytes)} expanded."
        )
        if exceeds_hard_limit:
            self.warning_label.setText(
                "This package is larger than the normal safety limit. You will be asked to confirm "
                "before processing begins."
            )
            self.warning_label.show()
        elif expanded_bytes > warning_threshold_bytes:
            self.warning_label.setText(
                "This is a large package. Processing may take longer and use significant disk space."
            )
            self.warning_label.show()
        else:
            self.warning_label.hide()

    def set_estimate_error(self, message: str) -> None:
        self.estimate_label.setText(f"Could not estimate package size: {message}")
