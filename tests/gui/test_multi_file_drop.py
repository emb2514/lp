"""Tests for dragging several loose files (no enclosing folder) into
the app at once to build one package -- real user request: "would it
be possible for me to drag and drop a bunch of files in at once to
make one package? so i can eliminate the step of creating a folder and
putting them all in there first." See `DropZone._handle_paths` (the
in-app drop target) and `state.stage_dropped_files` (the underlying
file-bundling logic, independent of Qt).
"""

from __future__ import annotations

import pytest
from fixtures.builders import make_pdf

from lender_package_builder.gui.state import InputKind, stage_dropped_files


# ---------------------------------------------------------------------
# state.stage_dropped_files -- pure filesystem logic, no Qt
# ---------------------------------------------------------------------


def test_stage_dropped_files_bundles_every_file_into_one_new_folder(tmp_path):
    file_a = tmp_path / "a.pdf"
    file_a.write_bytes(b"A content")
    file_b = tmp_path / "b.pdf"
    file_b.write_bytes(b"B content")

    staged = stage_dropped_files([file_a, file_b])

    assert staged.is_dir()
    assert staged.parent == tmp_path
    assert (staged / "a.pdf").read_bytes() == b"A content"
    assert (staged / "b.pdf").read_bytes() == b"B content"


def test_stage_dropped_files_leaves_originals_untouched(tmp_path):
    file_a = tmp_path / "a.pdf"
    file_a.write_bytes(b"original content")

    stage_dropped_files([file_a])

    # The source file is never moved or modified -- only ever read from.
    assert file_a.exists()
    assert file_a.read_bytes() == b"original content"


def test_stage_dropped_files_hardlinks_when_possible(tmp_path):
    file_a = tmp_path / "a.pdf"
    file_a.write_bytes(b"content")

    staged = stage_dropped_files([file_a])

    # Same inode as the original -- confirms a real hardlink was made,
    # not a byte-for-byte copy (which would be slower for large files).
    assert (staged / "a.pdf").stat().st_ino == file_a.stat().st_ino


def test_stage_dropped_files_falls_back_to_copy_when_hardlink_fails(tmp_path, monkeypatch):
    file_a = tmp_path / "a.pdf"
    file_a.write_bytes(b"cross-device content")

    monkeypatch.setattr(
        "lender_package_builder.gui.state.os.link",
        lambda *a, **k: (_ for _ in ()).throw(OSError("simulated cross-device link failure")),
    )

    staged = stage_dropped_files([file_a])

    assert (staged / "a.pdf").read_bytes() == b"cross-device content"
    assert (staged / "a.pdf").stat().st_ino != file_a.stat().st_ino


def test_stage_dropped_files_disambiguates_same_name_collisions(tmp_path):
    dir_x = tmp_path / "x"
    dir_x.mkdir()
    dir_y = tmp_path / "y"
    dir_y.mkdir()
    file_x = dir_x / "doc.pdf"
    file_x.write_bytes(b"from x")
    file_y = dir_y / "doc.pdf"
    file_y.write_bytes(b"from y")

    staged = stage_dropped_files([file_x, file_y])

    contents = {p.read_bytes() for p in staged.iterdir()}
    assert contents == {b"from x", b"from y"}
    assert len(list(staged.iterdir())) == 2


def test_stage_dropped_files_is_versioned_on_repeated_calls(tmp_path):
    file_a = tmp_path / "a.pdf"
    file_a.write_bytes(b"content")

    first = stage_dropped_files([file_a])
    second = stage_dropped_files([file_a])

    assert first != second
    assert first.exists()
    assert second.exists()


# ---------------------------------------------------------------------
# DropZone -- in-app drag-and-drop wiring
# ---------------------------------------------------------------------


def test_dropping_several_loose_files_emits_multiple_files_selected(window, tmp_path, qtbot):
    file_a = tmp_path / "a.pdf"
    file_a.write_bytes(b"A")
    file_b = tmp_path / "b.pdf"
    file_b.write_bytes(b"B")

    with qtbot.waitSignal(window.drop_zone.multiple_files_selected, timeout=2000) as blocker:
        window.drop_zone._handle_paths([file_a, file_b])

    assert set(blocker.args[0]) == {file_a, file_b}


def test_dropping_several_loose_files_bundles_them_as_one_folder_input(window, tmp_path, qtbot):
    file_a = tmp_path / "a.pdf"
    file_a.write_bytes(b"A")
    file_b = tmp_path / "b.pdf"
    file_b.write_bytes(b"B")

    with qtbot.waitSignal(window.drop_zone.multiple_files_selected, timeout=2000):
        window.drop_zone._handle_paths([file_a, file_b])

    assert window.current_selection is not None
    assert window.current_selection.kind == InputKind.FOLDER
    assert window.current_selection.path.is_dir()
    assert {p.name for p in window.current_selection.path.iterdir()} == {"a.pdf", "b.pdf"}
    assert window.selected_card.isVisible()
    assert window.build_button.isEnabled()


def test_changing_input_after_a_multi_file_drop_cleans_up_the_staged_folder(window, tmp_path, qtbot):
    file_a = tmp_path / "a.pdf"
    file_a.write_bytes(b"A")
    file_b = tmp_path / "b.pdf"
    file_b.write_bytes(b"B")

    with qtbot.waitSignal(window.drop_zone.multiple_files_selected, timeout=2000):
        window.drop_zone._handle_paths([file_a, file_b])

    staged_dir = window.current_selection.path
    assert staged_dir.exists()

    window._on_change_input()

    assert not staged_dir.exists()
    # The real source files the user dropped are never touched.
    assert file_a.exists()
    assert file_b.exists()


def test_closing_the_window_cleans_up_a_staged_multi_file_folder(window, tmp_path, qtbot):
    file_a = tmp_path / "a.pdf"
    file_a.write_bytes(b"A")
    file_b = tmp_path / "b.pdf"
    file_b.write_bytes(b"B")

    with qtbot.waitSignal(window.drop_zone.multiple_files_selected, timeout=2000):
        window.drop_zone._handle_paths([file_a, file_b])

    staged_dir = window.current_selection.path
    window.close()

    assert not staged_dir.exists()


def test_a_single_dropped_file_still_behaves_exactly_as_before(window, tmp_path, qtbot):
    file_a = tmp_path / "a.pdf"
    file_a.write_bytes(b"A")

    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([file_a])

    assert window.current_selection.kind == InputKind.FILE
    assert window.current_selection.path == file_a


# Real end-to-end build from a multi-file drop, through the actual
# background QThread worker (see test_gui_end_to_end.py for the
# equivalent ZIP-based version this mirrors).
@pytest.mark.real_background_thread
def test_multi_file_drop_builds_a_real_package_through_the_gui(window, tmp_path, qtbot):
    doc_a = tmp_path / "doc_a.pdf"
    doc_b = tmp_path / "doc_b.pdf"
    make_pdf(doc_a, pages=2, text_prefix="Document A")
    make_pdf(doc_b, pages=3, text_prefix="Document B")

    with qtbot.waitSignal(window.drop_zone.multiple_files_selected, timeout=2000):
        window.drop_zone._handle_paths([doc_a, doc_b])

    qtbot.waitUntil(lambda: window.current_selection.estimate is not None, timeout=5000)
    assert window.build_button.isEnabled()

    window._on_build_clicked()
    qtbot.waitUntil(lambda: not window.is_processing, timeout=30000)

    assert window.stack.currentWidget() is window.result_view
    run = window.result_view._run
    assert run is not None
    assert run.success is True
    assert run.output_path.exists()
    # Both dropped documents made it into the package -- 2 source
    # occurrences in, neither dropped as a duplicate of the other.
    assert sum(len(p.document_ids) for p in run.og_parts) == 2
