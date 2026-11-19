"""Tests for the cat companion that idles in the corner while a build
runs, walks to the middle of the screen with a beating heart when it
finishes, and poofs away on click.

Real user request, evolved over several rounds: a hand-drawn pixel cat
never quite landed visually, so the user asked to source pre-made,
properly-licensed sprites instead ("can you just find pixelated ones
already created that can be used? ... without repercussions"), then
redefined the behavior itself: "we can scratch the sleeping [cat] and
just have an idle cat when its working and the cat walk over when its
done ... it stays in the middle till you click on it. once you click
on it, it brings up the LP builder app page and the cat goes *poof*."

Covers the state machine directly (idle -> walking -> celebrating ->
poofing -> hidden, with no manual QTimer waits needed -- the internal
`_advance_*`/`_poof_away` methods are called directly, the same ones
the real QTimers call) and its wiring into MainWindow's build
lifecycle.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from lender_package_builder.gui.widgets.cat_companion import (
    CatCompanionWidget,
    _HEART_BEAT_FRAMES,
    _HEART_GROW_FRAMES,
    _IDLE_FRAMES,
    _POOF_FRAMES,
    _WALK_FRAMES,
    _load,
)


def _run_walk_to_completion(cat: CatCompanionWidget) -> None:
    while cat._state == "walking":
        cat._advance_walk()


def _run_poof_to_completion(cat: CatCompanionWidget, max_ticks: int = 20) -> None:
    for _ in range(max_ticks):
        if cat._state != "poofing":
            return
        cat._advance_cat()


# ---------------------------------------------------------------------
# idle
# ---------------------------------------------------------------------


def test_start_idle_shows_the_cat_in_the_corner(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_idle()

    assert cat._state == "idle"
    assert cat.isVisible()
    assert cat._timer.isActive()


def test_idle_frame_cycles_on_its_own_timer(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_idle()

    assert cat._cat_frame == 0
    cat._advance_cat()
    assert cat._cat_frame == 1
    assert cat._state == "idle"  # still idling, just the next frame


# ---------------------------------------------------------------------
# walking + celebrating
# ---------------------------------------------------------------------


def test_celebrate_walks_then_settles_into_celebrating_with_a_heart(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_idle()
    corner_pos = cat.pos()

    cat.celebrate()
    assert cat._state == "walking"
    assert cat._flipped is True  # faces its direction of travel

    _run_walk_to_completion(cat)

    assert cat._state == "celebrating"
    assert cat.pos() != corner_pos  # it actually moved
    assert cat._heart_label.isVisible()


def test_celebrate_before_start_idle_still_shows_it(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    # celebrate() before start_idle() has ever been called (e.g. a very
    # first build somehow finishing without an explicit start) must
    # still show the widget, not crash.
    cat.celebrate()

    assert cat.isVisible()
    assert cat._state == "walking"


def test_heart_grows_then_loops_the_beat_frames(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_idle()
    cat.celebrate()
    _run_walk_to_completion(cat)

    assert cat._heart_phase == "grow"
    for _ in range(len(_HEART_GROW_FRAMES)):
        cat._advance_heart()
    assert cat._heart_phase == "beat"

    # the beat phase loops forever rather than running out
    for _ in range(10):
        cat._advance_heart()
    assert cat._heart_phase == "beat"
    assert cat._state == "celebrating"  # never advances past celebrating on its own


def test_celebrate_interrupts_an_in_progress_walk_cleanly(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_idle()
    cat.celebrate()
    cat._advance_walk()
    cat._advance_walk()
    assert cat._state == "walking"  # mid-walk

    # a second build finishes before the first celebration was reached
    cat.celebrate()
    assert cat._state == "walking"
    _run_walk_to_completion(cat)
    assert cat._state == "celebrating"  # still resolves cleanly, no stuck state


# ---------------------------------------------------------------------
# click -> poof
# ---------------------------------------------------------------------


def test_clicking_while_celebrating_poofs_the_cat_away(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_idle()
    cat.celebrate()
    _run_walk_to_completion(cat)
    assert cat._state == "celebrating"

    cat._poof_away()
    assert cat._state == "poofing"
    assert not cat._heart_label.isVisible()

    _run_poof_to_completion(cat)
    assert cat._state == "hidden"
    assert not cat.isVisible()


def test_clicking_while_idle_does_not_poof(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_idle()

    qtbot.mouseClick(cat, Qt.MouseButton.LeftButton)

    assert cat._state == "idle"
    assert cat.isVisible()


def test_clicking_while_celebrating_poofs_via_a_real_click(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_idle()
    cat.celebrate()
    _run_walk_to_completion(cat)
    assert cat._state == "celebrating"

    qtbot.mouseClick(cat, Qt.MouseButton.LeftButton)

    assert cat._state == "poofing"


def test_start_idle_after_poofing_brings_the_cat_back(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_idle()
    cat.celebrate()
    _run_walk_to_completion(cat)
    cat._poof_away()
    _run_poof_to_completion(cat)
    assert cat._state == "hidden"

    cat.start_idle()

    assert cat._state == "idle"
    assert cat.isVisible()


# ---------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------


def test_every_sprite_loads_a_non_null_pixmap(qtbot):
    for name in [*_IDLE_FRAMES, *_WALK_FRAMES, *_HEART_GROW_FRAMES, *_HEART_BEAT_FRAMES]:
        pixmap = _load(name, 16)
        assert not pixmap.isNull(), f"{name} loaded a null pixmap"
        assert pixmap.width() > 0 and pixmap.height() > 0
    for name in _POOF_FRAMES:
        pixmap = _load(name, 26)
        assert not pixmap.isNull(), f"{name} loaded a null pixmap"


# ---------------------------------------------------------------------
# MainWindow wiring
# ---------------------------------------------------------------------


def _start_build_without_actually_running_it(window, tmp_path, monkeypatch):
    # conftest.py's autouse fixture makes start_worker run the real
    # pipeline SYNCHRONOUSLY -- fine for most tests, but these only
    # care about the cat-companion side effects of _start_build()
    # itself, not a real build result. A no-op start_worker leaves
    # _start_build()'s own setup (including creating/showing the cat)
    # to run, without ever executing make_build_callable()'s pipeline.
    monkeypatch.setattr("lender_package_builder.gui.main_window.start_worker", lambda worker, thread_parent=None: None)

    from lender_package_builder.config import AppConfig
    from lender_package_builder.models import PackageIdentity

    window.current_selection = type("S", (), {"path": tmp_path, "estimate": None})()
    window._start_build(AppConfig(), False, PackageIdentity(last_name="Test"))
    # _start_build() leaves is_processing=True (no finished/failed/
    # cancelled signal ever fires, since start_worker is a no-op here)
    # -- left set, the window fixture's own teardown close() would hit
    # closeEvent's "processing in progress" guard and pop a real
    # blocking QMessageBox that nothing in an automated test can ever
    # dismiss, hanging the whole run. None of these tests care about
    # is_processing itself, only about the cat-companion side effects.
    window.is_processing = False


def test_cat_companion_is_created_and_idling_once_a_build_starts(window, tmp_path, monkeypatch):
    assert window.cat_companion is None

    _start_build_without_actually_running_it(window, tmp_path, monkeypatch)

    assert window.cat_companion is not None
    assert window.cat_companion._state == "idle"


def test_cat_walks_to_celebrate_on_a_successful_build(window, tmp_path, monkeypatch):
    _start_build_without_actually_running_it(window, tmp_path, monkeypatch)

    from tests.gui.test_results import _make_successful_run  # reuse an existing real-shaped run

    run = _make_successful_run(tmp_path)
    window._on_build_finished(run)

    assert window.cat_companion._state == "walking"


def test_cat_does_not_celebrate_a_failed_build(window, tmp_path, monkeypatch):
    _start_build_without_actually_running_it(window, tmp_path, monkeypatch)

    from lender_package_builder.exceptions import ProcessingCancelledError

    window._on_build_cancelled(ProcessingCancelledError("cancelled", stage="x", output_path=None))

    assert window.cat_companion._state == "idle"


def test_cat_companion_closes_with_the_window(window, tmp_path, monkeypatch):
    _start_build_without_actually_running_it(window, tmp_path, monkeypatch)
    cat = window.cat_companion
    assert cat.isVisible()

    window.close()

    assert not cat.isVisible()


# TEST - REGRESSION: closing the companion must stop every timer it
# owns, not just hide the window -- a leaked, still-running timer on an
# orphaned widget across many tests in one process was a real,
# confirmed contributor to a test-suite-wide segfault found while
# writing the original version of these tests.
def test_closing_stops_every_timer(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_idle()
    cat.celebrate()
    assert cat._walk_timer.isActive() is True

    cat.close()

    assert cat._timer.isActive() is False
    assert cat._heart_timer.isActive() is False
    assert cat._walk_timer.isActive() is False
