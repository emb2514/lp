from __future__ import annotations

from pathlib import Path

from fixtures.builders import make_zip

from lender_package_builder.gui.state import InputKind
from lender_package_builder.gui.widgets.drop_zone import MULTIPLE_ITEMS_MESSAGE


# TEST 2 - VALID FILE DROP
def test_valid_zip_drop_is_accepted(window, tmp_path, qtbot):
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello"), ("b.txt", b"world")])

    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    assert window.current_selection is not None
    assert window.current_selection.kind == InputKind.ZIP
    assert window.current_selection.path == zip_path
    assert window.selected_card.isVisible()
    assert window.build_button.isEnabled()


# TEST 3 - VALID FOLDER DROP
def test_valid_folder_drop_is_accepted_as_one_input(window, tmp_path, qtbot):
    folder = tmp_path / "lender_docs"
    folder.mkdir()
    (folder / "note.txt").write_text("hello")

    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([folder])

    assert window.current_selection is not None
    assert window.current_selection.kind == InputKind.FOLDER
    assert window.current_selection.path == folder
    assert window.build_button.isEnabled()


# TEST 4 - MULTIPLE INPUTS REJECTED
def test_multiple_dropped_items_are_rejected_not_silently_chosen(window, tmp_path, qtbot, monkeypatch):
    file_a = tmp_path / "a.txt"
    file_a.write_text("a")
    file_b = tmp_path / "b.txt"
    file_b.write_text("b")

    shown_messages = []
    monkeypatch.setattr(
        "lender_package_builder.gui.dialogs.show_multiple_items_message",
        lambda parent, message: shown_messages.append(message),
    )

    with qtbot.waitSignal(window.drop_zone.multiple_items_rejected, timeout=2000):
        window.drop_zone._handle_paths([file_a, file_b])

    assert window.current_selection is None
    assert not window.build_button.isEnabled()
    assert shown_messages == [MULTIPLE_ITEMS_MESSAGE]


# TEST 5 - BROWSE FALLBACK
def test_browse_file_fallback_displays_selected_input(window, tmp_path, monkeypatch, qtbot):
    chosen_file = tmp_path / "chosen.pdf"
    chosen_file.write_bytes(b"%PDF-1.4\n%%EOF")

    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.drop_zone.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(chosen_file), ""),
    )

    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone.browse_file_button.click()

    assert window.current_selection is not None
    assert window.current_selection.path == chosen_file
    assert window.selected_card.name_label.text() == chosen_file.name
    assert str(chosen_file) in window.selected_card.path_label.text()


def test_browse_folder_fallback_displays_selected_input(window, tmp_path, monkeypatch, qtbot):
    chosen_folder = tmp_path / "chosen_folder"
    chosen_folder.mkdir()

    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.drop_zone.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: str(chosen_folder),
    )

    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone.browse_folder_button.click()

    assert window.current_selection is not None
    assert window.current_selection.kind == InputKind.FOLDER
    assert window.current_selection.path == chosen_folder
