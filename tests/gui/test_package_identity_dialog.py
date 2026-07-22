"""Tests for PackageIdentityDialog -- the pre-build "confirm package
details" dialog that collects the borrower identity driving every
output name. Constructs the real widget directly (bypassing the
autouse auto-confirm patch in conftest.py, which only fakes out
MainWindow's reference to this class).
"""

from __future__ import annotations

from lender_package_builder.gui.widgets.package_identity_dialog import PackageIdentityDialog
from lender_package_builder.models import PackageIdentity


# TEST 1 - live preview reflects the current form values
def test_preview_updates_live_as_fields_change(qtbot):
    dialog = PackageIdentityDialog()
    qtbot.addWidget(dialog)

    dialog.last_name_edit.setText("True")
    assert dialog.preview_label.text() == "True"

    dialog.first_name_edit.setText("Michael")
    assert dialog.preview_label.text() == "True, Michael"

    dialog.loan_number_edit.setText("6192278785")
    assert dialog.preview_label.text() == "True, Michael, 6192278785"

    dialog.adverse_checkbox.setChecked(True)
    assert dialog.preview_label.text() == "True, Michael, Adverse, 6192278785"
    dialog.close()


# TEST 2 - Continue (OK) is disabled until a last name is entered
def test_continue_disabled_until_last_name_entered(qtbot):
    from PySide6.QtWidgets import QDialogButtonBox

    dialog = PackageIdentityDialog()
    qtbot.addWidget(dialog)
    ok_button = dialog.button_box.button(QDialogButtonBox.StandardButton.Ok)

    assert ok_button.isEnabled() is False
    dialog.last_name_edit.setText("True")
    assert ok_button.isEnabled() is True
    dialog.last_name_edit.setText("   ")
    assert ok_button.isEnabled() is False
    dialog.close()


# TEST 3 - identity() reflects exactly what was entered
def test_identity_reflects_form_values(qtbot):
    dialog = PackageIdentityDialog()
    qtbot.addWidget(dialog)

    dialog.last_name_edit.setText("True")
    dialog.first_name_edit.setText("Michael")
    dialog.loan_number_edit.setText("6192278785")
    dialog.adverse_checkbox.setChecked(True)

    identity = dialog.identity()
    assert identity == PackageIdentity(
        last_name="True", first_name="Michael", loan_number="6192278785", is_adverse=True
    )
    dialog.close()


# TEST 4 - constructing with an initial identity pre-fills the form
def test_initial_identity_prefills_form(qtbot):
    initial = PackageIdentity(last_name="Smith", first_name="Jane", loan_number="42", is_adverse=False)
    dialog = PackageIdentityDialog(initial=initial)
    qtbot.addWidget(dialog)

    assert dialog.last_name_edit.text() == "Smith"
    assert dialog.first_name_edit.text() == "Jane"
    assert dialog.loan_number_edit.text() == "42"
    assert dialog.preview_label.text() == "Smith, Jane, 42"
    dialog.close()


# TEST 5 - Cancel rejects the dialog without requiring any field
def test_cancel_rejects_dialog(qtbot):
    from PySide6.QtWidgets import QDialog

    dialog = PackageIdentityDialog()
    qtbot.addWidget(dialog)
    dialog.button_box.rejected.emit()
    assert dialog.result() == QDialog.DialogCode.Rejected
