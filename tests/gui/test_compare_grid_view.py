"""Tests for the Compare Packages visual highlight grid (real user
request: "the pages that are in one but not the other are highlighted...
don't try to tell me what is different, just highlight it").
"""

from __future__ import annotations

from fixtures.builders import make_pdf_with_pages

from lender_package_builder import compare_packages as cp
from lender_package_builder.gui.widgets.compare_grid_view import CompareGridView


def _compare(tmp_path, old_pages, new_pages):
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", old_pages)
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", new_pages)
    old_side = cp.load_package_side("Old", [old_pdf])
    new_side = cp.load_package_side("New", [new_pdf])
    return cp.compare_packages(old_side, new_side)


def test_grid_populates_a_cell_for_every_page(qtbot, tmp_path):
    result = _compare(tmp_path, ["Alpha page", "Bravo page"], ["Alpha page"])
    widget = CompareGridView()
    qtbot.addWidget(widget)

    widget.set_result(result)

    assert widget._old_flow.count() == 2
    assert widget._new_flow.count() == 1


def test_page_only_in_old_is_highlighted_unmatched(qtbot, tmp_path):
    result = _compare(
        tmp_path,
        ["Shared page", "Unique old-only content that will never appear in the new package at all, ever."],
        ["Shared page"],
    )
    widget = CompareGridView()
    qtbot.addWidget(widget)
    widget.set_result(result)

    old_cells = [widget._old_flow.itemAt(i).widget() for i in range(widget._old_flow.count())]
    shared_cell = old_cells[0]
    only_old_cell = old_cells[1]

    assert shared_cell.property("unmatched") == "false"
    assert only_old_cell.property("unmatched") == "true"


def test_page_only_in_new_is_highlighted_unmatched(qtbot, tmp_path):
    result = _compare(
        tmp_path,
        ["Shared page"],
        ["Shared page", "Unique new-only content that will never appear in the old package at all, ever."],
    )
    widget = CompareGridView()
    qtbot.addWidget(widget)
    widget.set_result(result)

    new_cells = [widget._new_flow.itemAt(i).widget() for i in range(widget._new_flow.count())]
    assert new_cells[0].property("unmatched") == "false"
    assert new_cells[1].property("unmatched") == "true"


def test_exact_match_pages_are_never_highlighted(qtbot, tmp_path):
    result = _compare(tmp_path, ["Page one text", "Page two text"], ["Page one text", "Page two text"])
    widget = CompareGridView()
    qtbot.addWidget(widget)
    widget.set_result(result)

    all_cells = [widget._old_flow.itemAt(i).widget() for i in range(widget._old_flow.count())]
    all_cells += [widget._new_flow.itemAt(i).widget() for i in range(widget._new_flow.count())]
    assert all(cell.property("unmatched") == "false" for cell in all_cells)


def test_thumbnails_render_progressively_and_finish(qtbot, tmp_path):
    result = _compare(tmp_path, ["Alpha page", "Bravo page", "Charlie page"], ["Alpha page"])
    widget = CompareGridView()
    qtbot.addWidget(widget)
    widget.set_result(result)

    cells = [widget._old_flow.itemAt(i).widget() for i in range(widget._old_flow.count())]
    qtbot.waitUntil(lambda: all(not c.thumbnail_label.pixmap().isNull() for c in cells), timeout=5000)
    assert not widget._render_timer.isActive()


def test_clicking_an_unmatched_cell_shows_finding_detail(qtbot, tmp_path):
    result = _compare(
        tmp_path,
        ["Shared page", "Unique old-only content that will never appear in the new package at all, ever."],
        ["Shared page"],
    )
    widget = CompareGridView()
    qtbot.addWidget(widget)
    widget.set_result(result)

    only_old_cell = widget._old_flow.itemAt(1).widget()
    assert widget.detail_label.text() == "Click a highlighted page to see why it was flagged."

    only_old_cell.clicked.emit(only_old_cell.side, only_old_cell.overall_index)

    assert "Click a highlighted page" not in widget.detail_label.text()
    assert cp.CATEGORY_POSSIBLE_MISSING in widget.detail_label.text() or "Old:" in widget.detail_label.text()


def test_summary_label_reports_highlighted_count(qtbot, tmp_path):
    result = _compare(
        tmp_path,
        ["Shared page", "Unique old-only content that will never appear in the new package at all, ever."],
        ["Shared page"],
    )
    widget = CompareGridView()
    qtbot.addWidget(widget)
    widget.set_result(result)

    assert "1 highlighted" in widget.summary_label.text()


def test_view_list_requested_signal(qtbot, tmp_path):
    result = _compare(tmp_path, ["Page one"], ["Page one"])
    widget = CompareGridView()
    qtbot.addWidget(widget)
    widget.set_result(result)

    with qtbot.waitSignal(widget.view_list_requested, timeout=1000):
        widget.view_list_button.click()


def test_new_comparison_requested_signal(qtbot, tmp_path):
    result = _compare(tmp_path, ["Page one"], ["Page one"])
    widget = CompareGridView()
    qtbot.addWidget(widget)
    widget.set_result(result)

    with qtbot.waitSignal(widget.new_comparison_requested, timeout=1000):
        widget.new_comparison_button.click()


def test_set_result_twice_clears_previous_cells(qtbot, tmp_path):
    first = _compare(tmp_path, ["Page one", "Page two"], ["Page one"])
    widget = CompareGridView()
    qtbot.addWidget(widget)
    widget.set_result(first)
    assert widget._old_flow.count() == 2

    second = _compare(tmp_path, ["Only page"], ["Only page"])
    widget.set_result(second)
    assert widget._old_flow.count() == 1
    assert widget._new_flow.count() == 1
