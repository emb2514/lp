"""Pre-build dialog: collects the borrower identity (last name, first
name, loan number, adverse/non-proceeding status) that drives every
user-facing output name -- the main output folder, the Final/Original
Lender Package filenames, and (once built) any extracted key-document
filenames. Shown once, right before a build starts, with a live
preview of the exact main output folder name so the user can confirm
it before anything is written to disk. Automatic document recognition
never supplies these values on its own.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ... import naming
from ...models import PackageIdentity


class PackageIdentityDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, initial: PackageIdentity | None = None):
        super().__init__(parent)
        self.setWindowTitle("Confirm package details")
        self.setModal(True)
        self.setMinimumWidth(420)

        initial = initial or PackageIdentity()

        layout = QVBoxLayout(self)

        intro = QLabel(
            "These details name the output folder and the lender package files. Confirm or "
            "correct them before processing begins."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.last_name_edit = QLineEdit(initial.last_name)
        self.last_name_edit.setPlaceholderText("Required, e.g. True")
        form.addRow("Last name:", self.last_name_edit)

        self.first_name_edit = QLineEdit(initial.first_name)
        self.first_name_edit.setPlaceholderText("e.g. Michael")
        form.addRow("First name:", self.first_name_edit)

        self.loan_number_edit = QLineEdit(initial.loan_number)
        self.loan_number_edit.setPlaceholderText("e.g. 6192278785")
        form.addRow("Loan number:", self.loan_number_edit)
        layout.addLayout(form)

        self.adverse_checkbox = QCheckBox(
            "This is an adverse, withdrawn, denied, or cancelled (non-proceeding) file"
        )
        self.adverse_checkbox.setChecked(initial.is_adverse)
        layout.addWidget(self.adverse_checkbox)

        preview_caption = QLabel("Output folder will be named:")
        preview_caption.setObjectName("MutedLabel")
        layout.addWidget(preview_caption)

        self.preview_label = QLabel()
        self.preview_label.setObjectName("SectionHeading")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Continue")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        for edit in (self.last_name_edit, self.first_name_edit, self.loan_number_edit):
            edit.textChanged.connect(self._update_preview)
        self.adverse_checkbox.toggled.connect(self._update_preview)

        self._update_preview()

    def _current_identity(self) -> PackageIdentity:
        return PackageIdentity(
            last_name=self.last_name_edit.text(),
            first_name=self.first_name_edit.text(),
            loan_number=self.loan_number_edit.text(),
            is_adverse=self.adverse_checkbox.isChecked(),
        )

    def _update_preview(self) -> None:
        identity = self._current_identity()
        self.preview_label.setText(naming.main_folder_name(identity))
        ok_button = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        ok_button.setEnabled(bool(naming.sanitize_component(identity.last_name)))

    def identity(self) -> PackageIdentity:
        return self._current_identity()
