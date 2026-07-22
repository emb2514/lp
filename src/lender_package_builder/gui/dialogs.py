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


def confirm_cancel_processing(parent: QWidget | None) -> bool:
    """"Stop processing this package?" -- shown when Cancel Processing is
    clicked, so a single accidental click can never cancel a run.
    Returns True only if the user explicitly chose Stop Processing.
    """

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Stop processing?")
    box.setText("Stop processing this package?")
    box.setInformativeText(
        "No Final or Original Lender Package files will be produced from this run. Nothing already "
        "processed is kept; your original files are never changed either way."
    )
    continue_button = box.addButton("Continue Processing", QMessageBox.ButtonRole.RejectRole)
    stop_button = box.addButton("Stop Processing", QMessageBox.ButtonRole.DestructiveRole)
    box.setDefaultButton(continue_button)
    box.exec()
    return box.clickedButton() is stop_button


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


def warn_comparison_in_progress(parent: QWidget | None) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Comparison in progress")
    box.setText("A package comparison is currently running.")
    box.setInformativeText(
        "Please wait until it finishes before closing the application. Neither package being "
        "compared is ever modified either way."
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


def choose_final_or_original_package(parent: QWidget | None, folder_name: str) -> str | None:
    """Shown when a folder selected for Compare Packages contains BOTH
    a Final Lender Package and an Original Lender Package (see
    compare_packages.describe_folder_contents()) -- the choice is never
    guessed. Returns "final", "original", or None if cancelled.
    """

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Which package?")
    box.setText(f'"{folder_name}" contains both a Final and an Original Lender Package.')
    box.setInformativeText("Which one should be used for this comparison?")
    final_button = box.addButton("Use Final (Lender Package)", QMessageBox.ButtonRole.AcceptRole)
    original_button = box.addButton("Use Original Lender Package", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(final_button)
    box.exec()
    clicked = box.clickedButton()
    if clicked is final_button:
        return "final"
    if clicked is original_button:
        return "original"
    return None


def show_no_pdfs_found(parent: QWidget | None, folder_name: str) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle("No PDFs found")
    box.setText(f'No PDF files were found in "{folder_name}".')
    box.exec()


def confirm_cancel_comparison(parent: QWidget | None) -> bool:
    """"Stop comparing these packages?" -- shown when Cancel Comparison
    is clicked. Returns True only if the user explicitly confirmed.
    Comparison is analysis-only, so cancelling never risks any output
    file -- this confirmation exists only to avoid losing progress on
    an accidental click for a comparison that may have taken a while.
    """

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Stop comparing?")
    box.setText("Stop comparing these packages?")
    box.setInformativeText("Neither package is ever modified by a comparison, whether you stop it or not.")
    continue_button = box.addButton("Continue Comparing", QMessageBox.ButtonRole.RejectRole)
    stop_button = box.addButton("Stop Comparing", QMessageBox.ButtonRole.DestructiveRole)
    box.setDefaultButton(continue_button)
    box.exec()
    return box.clickedButton() is stop_button


def show_config_warning(parent: QWidget | None, message: str) -> None:
    """Shown once, after the window is already up, when config.toml
    exists but could not be parsed. Built-in defaults are already in
    effect by the time this appears -- the app is never blocked from
    starting because of a bad config file.
    """

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Configuration file problem")
    box.setText("Your config.toml could not be used, so built-in defaults were used instead.")
    box.setInformativeText(message)
    box.exec()
