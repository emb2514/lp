"""Tests for the circular progress indicator's spin animation.

A real user complaint: a static indeterminate indicator gave no visual
sign the app was still working during the long content-analysis and
comparison stages versus having silently frozen. These tests lock in
that the indicator now visibly animates while indeterminate, and stops
changing once real progress data arrives.
"""

from __future__ import annotations

from lender_package_builder.gui.widgets.circular_progress import CircularProgressIndicator


def test_indicator_starts_indeterminate(qtbot):
    widget = CircularProgressIndicator()
    qtbot.addWidget(widget)
    assert widget._indeterminate is True


def test_spin_angle_advances_while_indeterminate_and_visible(qtbot):
    widget = CircularProgressIndicator()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)

    start_angle = widget._spin_angle
    qtbot.wait(250)  # several timer ticks at the 40ms interval
    assert widget._spin_angle != start_angle, "indeterminate indicator did not animate"


def test_spin_does_not_advance_once_hidden(qtbot):
    widget = CircularProgressIndicator()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)
    widget.hide()

    start_angle = widget._spin_angle
    qtbot.wait(250)
    assert widget._spin_angle == start_angle, "hidden indicator should not keep animating"


def test_spin_stops_advancing_once_a_real_value_is_set(qtbot):
    widget = CircularProgressIndicator()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)

    widget.set_value(42)
    assert widget._indeterminate is False
    assert widget._percent == 42

    angle_after_set = widget._spin_angle
    qtbot.wait(250)
    assert widget._spin_angle == angle_after_set, "determinate indicator should not keep animating"


def test_set_indeterminate_resumes_the_spin(qtbot):
    widget = CircularProgressIndicator()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitExposed(widget)

    widget.set_value(42)
    widget.set_indeterminate()
    assert widget._indeterminate is True

    start_angle = widget._spin_angle
    qtbot.wait(250)
    assert widget._spin_angle != start_angle
