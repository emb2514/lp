"""GUI tests for MILESTONE 5B/6 -- the Compare Packages workspace:
navigation to/from the main build workflow, side selectors (PDF/
multiple parts/folder/clear), enabling the Compare button only once
both sides are valid, folder disambiguation when both Final and
Original Lender Package files are present, and a real end-to-end
comparison (including cancellation) through the actual background
worker.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.builders import make_pdf_with_pages


def test_compare_packages_button_switches_workspace_and_back_returns(window):
    assert window.top_level_stack.currentWidget() is window.top_level_stack.widget(0)

    window.compare_packages_button.click()
    assert window.top_level_stack.currentWidget() is window.compare_workspace

    window.compare_workspace.back_button.click()
    assert window.top_level_stack.currentWidget() is window.top_level_stack.widget(0)


def test_side_selector_select_pdf_updates_summary_and_enables_compare(window, tmp_path, monkeypatch):
    workspace = window.compare_workspace
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Page one"])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", ["Page one"])

    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.compare_side_selector.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(old_pdf), ""),
    )
    workspace.old_selector._select_pdf()
    assert workspace.old_selector.files == [old_pdf]
    assert workspace.old_selector.summary_label.text() == "old.pdf"
    assert not workspace.compare_button.isEnabled()

    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.compare_side_selector.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(new_pdf), ""),
    )
    workspace.new_selector._select_pdf()
    assert workspace.compare_button.isEnabled()


def test_side_selector_select_multiple_parts(window, tmp_path, monkeypatch):
    selector = window.compare_workspace.old_selector
    part1 = make_pdf_with_pages(tmp_path / "Package, Part 002.pdf", ["Page"])
    part2 = make_pdf_with_pages(tmp_path / "Package, Part 001.pdf", ["Page"])

    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.compare_side_selector.QFileDialog.getOpenFileNames",
        lambda *a, **k: ([str(part1), str(part2)], ""),
    )
    selector._select_multiple_parts()
    # Sorted into natural part order regardless of dialog return order.
    assert [f.name for f in selector.files] == ["Package, Part 001.pdf", "Package, Part 002.pdf"]


def test_side_selector_clear_selection(window, tmp_path, monkeypatch):
    selector = window.compare_workspace.old_selector
    pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Page"])
    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.compare_side_selector.QFileDialog.getOpenFileName",
        lambda *a, **k: (str(pdf), ""),
    )
    selector._select_pdf()
    assert selector.is_valid()

    selector.clear_selection()
    assert not selector.is_valid()
    assert selector.summary_label.text() == "No selection"


def test_select_folder_with_both_final_and_original_asks_which(window, tmp_path, monkeypatch):
    from lender_package_builder.models import PackageIdentity
    from lender_package_builder import naming

    output_dir = tmp_path / "True, Michael, 123"
    final_dir = output_dir / "Final"
    final_dir.mkdir(parents=True)
    identity = PackageIdentity(last_name="True", first_name="Michael")
    make_pdf_with_pages(final_dir / naming.package_part_filename(identity, naming.FINAL_PACKAGE_KIND, 1, 1), ["A"])
    make_pdf_with_pages(final_dir / naming.package_part_filename(identity, naming.OG_PACKAGE_KIND, 1, 1), ["A"])

    selector = window.compare_workspace.old_selector
    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.compare_side_selector.QFileDialog.getExistingDirectory",
        lambda *a, **k: str(output_dir),
    )
    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.compare_side_selector.dialogs.choose_final_or_original_package",
        lambda *a, **k: "original",
    )
    selector._select_folder()
    assert len(selector.files) == 1
    assert "Original Lender Package" in selector.files[0].name


def test_new_comparison_clears_selectors_and_returns_to_input(window, tmp_path, monkeypatch):
    workspace = window.compare_workspace
    from lender_package_builder import compare_packages

    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Page one"])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", ["Page one"])
    old_side = compare_packages.load_package_side("Old", [old_pdf])
    new_side = compare_packages.load_package_side("New", [new_pdf])
    result = compare_packages.compare_packages(old_side, new_side)

    workspace.old_selector._set_files([old_pdf])
    workspace.results_view.set_result(result)
    workspace.stack.setCurrentWidget(workspace.results_view)

    workspace.results_view.new_comparison_button.click()
    assert workspace.stack.currentWidget() is workspace.input_page
    assert not workspace.old_selector.is_valid()


@pytest.mark.real_background_thread
def test_full_comparison_through_real_worker_shows_results(window, tmp_path, qtbot):
    workspace = window.compare_workspace
    old_pdf = make_pdf_with_pages(tmp_path / "old.pdf", ["Shared page", "Only in old, a fairly long unique sentence."])
    new_pdf = make_pdf_with_pages(tmp_path / "new.pdf", ["Shared page"])

    workspace.old_selector._set_files([old_pdf])
    workspace.new_selector._set_files([new_pdf])
    assert workspace.compare_button.isEnabled()

    workspace._on_compare_clicked()
    assert workspace.is_comparing is True

    qtbot.waitUntil(lambda: not workspace.is_comparing, timeout=15000)

    assert workspace.stack.currentWidget() is workspace.results_view
    assert workspace.results_view._result is not None
    assert workspace.results_view._result.old_page_count == 2
    assert workspace.results_view._result.new_page_count == 1


@pytest.mark.real_background_thread
def test_cancel_comparison_through_real_worker(window, tmp_path, qtbot, monkeypatch):
    workspace = window.compare_workspace
    # Deliberately unequal page counts with fully disjoint text: this
    # forces the pages into compare_packages()'s unresolved_old/new
    # queue (see the "else" branch in compare_packages()) rather than
    # the equal-length "replace" fast path that pairs pages directly
    # without ever emitting a "Resolving ..." progress message -- this
    # test's cancellation hook only fires on that message.
    old_pdf = make_pdf_with_pages(
        tmp_path / "old.pdf", [f"Old page {i} with enough unique text to avoid the extra-page heuristic here." for i in range(8)]
    )
    new_pdf = make_pdf_with_pages(
        tmp_path / "new.pdf", [f"New page {i} with enough unique text to avoid the extra-page heuristic here." for i in range(5)]
    )

    monkeypatch.setattr(
        "lender_package_builder.gui.widgets.compare_workspace.dialogs.confirm_cancel_comparison",
        lambda parent: True,
    )

    workspace.old_selector._set_files([old_pdf])
    workspace.new_selector._set_files([new_pdf])
    workspace._on_compare_clicked()
    assert workspace._compare_worker is not None

    original_on_progress = workspace._on_progress_message

    def _wrapped(message):
        original_on_progress(message)
        if "Resolving" in str(message):
            workspace._on_cancel_clicked()

    monkeypatch.setattr(workspace, "_on_progress_message", _wrapped)
    workspace._compare_worker.progress.connect(workspace._on_progress_message)

    qtbot.waitUntil(lambda: not workspace.is_comparing, timeout=15000)
    assert workspace.stack.currentWidget() is workspace.input_page
