"""Tests for FlowLayout -- the button-row layout that wraps onto
additional rows instead of shrinking/clipping its items, used anywhere
a row of buttons must stay fully readable no matter how narrow the
window gets (ResultView, FailureView, CompareResultsView).
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QWidget

from lender_package_builder.gui.widgets.flow_layout import FlowLayout


def _make_row(labels: list[str]) -> tuple[QWidget, FlowLayout, list[QPushButton]]:
    container = QWidget()
    layout = FlowLayout(container, spacing=8)
    buttons = [QPushButton(label) for label in labels]
    for button in buttons:
        layout.addWidget(button)
    return container, layout, buttons


# TEST 1 - every added widget keeps its full, untruncated text -- a
# FlowLayout only ever repositions items, it never resizes a button
# smaller than its own size hint (the whole point: no clipping).
def test_buttons_keep_full_text_at_any_width(qtbot):
    labels = [
        "Open Output Folder",
        "Open Final Package",
        "Open Final Package Folder",
        "Open Reports",
        "Review Uncertain Matches",
        "Process Another Package",
    ]
    container, layout, buttons = _make_row(labels)
    qtbot.addWidget(container)

    for width in (150, 300, 600, 1200):
        container.resize(width, 400)
        container.show()
        for button, label in zip(buttons, labels):
            assert button.text() == label
            # A button's geometry, once laid out, must be at least as
            # wide as its own size hint -- never squeezed narrower.
            assert button.geometry().width() >= button.sizeHint().width()


# TEST 2 - a narrow container wraps buttons onto more than one row
def test_narrow_width_wraps_onto_multiple_rows(qtbot):
    labels = ["Open Output Folder", "Open Final Package", "Open Final Package Folder", "Open Reports"]
    container, layout, buttons = _make_row(labels)
    qtbot.addWidget(container)

    container.resize(180, 400)  # narrower than any single button
    container.show()

    y_positions = {button.geometry().y() for button in buttons}
    assert len(y_positions) > 1, "buttons should wrap onto more than one row when the container is narrow"


# TEST 3 - a wide container keeps every button on a single row
def test_wide_width_keeps_single_row(qtbot):
    labels = ["Open Output Folder", "Open Final Package", "Open Reports"]
    container, layout, buttons = _make_row(labels)
    qtbot.addWidget(container)

    container.resize(2000, 400)
    container.show()

    y_positions = {button.geometry().y() for button in buttons}
    assert len(y_positions) == 1, "buttons should stay on one row when there is ample width"


# TEST 4 - heightForWidth grows as the container narrows (more wrapped
# rows need more vertical space) -- this is what makes the surrounding
# QScrollArea correctly reserve room instead of clipping the last row.
def test_height_for_width_grows_as_width_shrinks():
    container, layout, buttons = _make_row(
        ["Open Output Folder", "Open Final Package", "Open Final Package Folder", "Open Reports"]
    )
    wide_height = layout.heightForWidth(2000)
    narrow_height = layout.heightForWidth(180)
    assert narrow_height > wide_height
