"""Tests for the pixel-cat build-complete companion. Real user request:
"add a little pop up notification for when its done. the pop up should
be a pixelated cat or smth" -- refined to "the continuous sleeping
kitty in the corner or the screen then when its done it wakes up
stretches and does a lil dance."

Covers the animation state machine directly (sleep -> wake -> stretch
-> dance -> back to sleep, with no manual QTimer waits needed --
`_advance()` is called directly, the same method the real QTimer
calls) and its wiring into MainWindow's build lifecycle.
"""

from __future__ import annotations

from lender_package_builder.gui.widgets.cat_companion import CatCompanionWidget, _render_frame


def _run_to_sleep(cat: CatCompanionWidget, max_ticks: int = 50) -> list[str]:
    poses = [cat._pose]
    for _ in range(max_ticks):
        cat._advance()
        poses.append(cat._pose)
        if not cat._queue and cat._pose == "sleep" and len(poses) > 2:
            break
    return poses


# ---------------------------------------------------------------------
# animation state machine
# ---------------------------------------------------------------------


def test_starts_sleeping(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_sleeping()

    assert cat._pose == "sleep"
    assert cat.isVisible()


def test_sleep_frame_alternates_on_its_own_timer(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_sleeping()

    assert cat._frame == 0
    cat._advance()
    assert cat._frame == 1
    assert cat._pose == "sleep"


def test_wake_and_celebrate_runs_the_full_sequence_and_returns_to_sleep(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_sleeping()

    cat.wake_and_celebrate()
    assert cat._pose == "wake"  # the first frame shows immediately, no tick needed

    poses_seen = set(_run_to_sleep(cat))
    assert poses_seen == {"wake", "stretch", "dance", "sleep"}


def test_sequence_visits_poses_in_order(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_sleeping()
    cat.wake_and_celebrate()

    order: list[str] = []
    for _ in range(50):
        if not order or cat._pose != order[-1]:
            order.append(cat._pose)
        cat._advance()
        if not cat._queue and cat._pose == "sleep":
            order.append("sleep")
            break

    assert order == ["wake", "stretch", "dance", "sleep"]


def test_calling_wake_while_already_sleeping_still_shows_it(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    # wake_and_celebrate() before start_sleeping() has ever been called
    # (e.g. a very first build) must still show the widget, not crash.
    cat.wake_and_celebrate()

    assert cat.isVisible()
    assert cat._pose == "wake"


def test_wake_interrupts_an_in_progress_celebration_cleanly(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_sleeping()
    cat.wake_and_celebrate()
    cat._advance()  # -> stretch[0]
    cat._advance()  # -> stretch[1]
    cat._advance()  # -> dance[0]
    assert cat._pose == "dance"  # mid-celebration

    # A second build finishes before the first celebration ended.
    cat.wake_and_celebrate()
    assert cat._pose == "wake"
    poses_seen = set(_run_to_sleep(cat))
    assert "sleep" in poses_seen  # still resolves cleanly, no stuck state


# ---------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------


def test_every_pose_renders_a_non_null_pixmap(qtbot):
    for pose, frame in [("sleep", 0), ("sleep", 1), ("wake", 0), ("stretch", 0), ("stretch", 1),
                         ("dance", 0), ("dance", 1), ("dance", 2), ("dance", 3)]:
        pixmap = _render_frame(pose, frame)
        assert not pixmap.isNull(), f"{pose}[{frame}] rendered a null pixmap"
        assert pixmap.width() > 0 and pixmap.height() > 0


# ---------------------------------------------------------------------
# MainWindow wiring
# ---------------------------------------------------------------------


def _start_build_without_actually_running_it(window, tmp_path, monkeypatch):
    # conftest.py's autouse fixture makes start_worker run the real
    # pipeline SYNCHRONOUSLY -- fine for most tests, but these only
    # care about the cat-companion side effects of _start_build()
    # itself, not a real build result. A no-op start_worker leaves
    # _start_build()'s own setup (including creating/waking the cat)
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


def test_cat_companion_is_created_and_sleeping_once_a_build_starts(window, tmp_path, monkeypatch):
    assert window.cat_companion is None

    _start_build_without_actually_running_it(window, tmp_path, monkeypatch)

    assert window.cat_companion is not None
    assert window.cat_companion._pose == "sleep"


def test_cat_wakes_up_on_a_successful_build(window, tmp_path, monkeypatch):
    _start_build_without_actually_running_it(window, tmp_path, monkeypatch)

    from tests.gui.test_results import _make_successful_run  # reuse an existing real-shaped run

    run = _make_successful_run(tmp_path)
    window._on_build_finished(run)

    assert window.cat_companion._pose == "wake"


def test_cat_does_not_celebrate_a_failed_build(window, tmp_path, monkeypatch):
    _start_build_without_actually_running_it(window, tmp_path, monkeypatch)

    from lender_package_builder.exceptions import ProcessingCancelledError

    window._on_build_cancelled(ProcessingCancelledError("cancelled", stage="x", output_path=None))

    assert window.cat_companion._pose == "sleep"


def test_cat_companion_closes_with_the_window(window, tmp_path, monkeypatch):
    _start_build_without_actually_running_it(window, tmp_path, monkeypatch)
    cat = window.cat_companion
    assert cat.isVisible()

    window.close()

    assert not cat.isVisible()


# TEST - REGRESSION: closing the companion must stop its own QTimer, not
# just hide the window -- a leaked, still-running timer on an orphaned
# widget across many tests in one process was a real, confirmed
# contributor to a test-suite-wide segfault found while writing these
# tests (a different test here originally never registered its widget
# with qtbot at all, leaving its timer running for the rest of the run).
def test_closing_stops_the_animation_timer(qtbot):
    cat = CatCompanionWidget()
    qtbot.addWidget(cat)
    cat.start_sleeping()
    assert cat._timer.isActive() is True

    cat.close()

    assert cat._timer.isActive() is False
