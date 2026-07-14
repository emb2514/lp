"""Modal dialogs: large-input confirmation and the close-while-
processing warning.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from .formatting import format_bytes


class LargeInputConfirmDialog(QMessageBox):
    """Shown when an input exceeds Stage 1's hard archive safety limit.

    Only clicking "Process This Known Large Package" results in
    `allow_large_input=True` being passed to the engine -- there is no
    silent bypass.
    """

    def __init__(self, entries: int, expanded_bytes: int, limit_message: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setIcon(QMessageBox.Icon.Warning)
        self.setWindowTitle("Large package detected")
        self.setText("This package is larger than the normal safety limit.")
        self.setInformativeText(
            f"Estimated size: {entries:,} file entries, {format_bytes(expanded_bytes)} expanded.\n\n"
            f"{limit_message}\n\n"
            "You can go back and choose a different input, or continue and process this known "
            "large package. Processing may take longer and require substantial disk space."
        )
        self.go_back_button = self.addButton("Go Back", QMessageBox.ButtonRole.RejectRole)
        self.process_button = self.addButton(
            "Process This Known Large Package", QMessageBox.ButtonRole.AcceptRole
        )
        self.setDefaultButton(self.go_back_button)

    def confirmed(self) -> bool:
        return self.clickedButton() is self.process_button


def warn_processing_in_progress(parent: QWidget | None) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Processing in progress")
    box.setText("A lender package is currently being built.")
    box.setInformativeText(
        "Please wait until processing finishes before closing the application. Closing now could "
        "leave a partially written package."
    )
    box.exec()


def show_multiple_items_message(parent: QWidget | None, message: str) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("One input at a time")
    box.setText(message)
    box.exec()


def show_insufficient_disk_space(parent: QWidget | None, message: str) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("Not enough disk space")
    box.setText("Processing cannot begin.")
    box.setInformativeText(message)
    box.exec()
