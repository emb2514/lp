"""Stage 3 automated tests: GUI-facing packaging concerns -- version
display, frozen-aware asset resolution, drag-onto-exe preselection
(and its "never auto-processes" safety guarantee), the reused
multiple-items rejection dialog, the config-warning dialog, and the
packaged `--gui-smoke-test` entry point.

Numbered independently, continuing the "STAGE 3 TEST" series started
in tests/test_stage3_packaging.py.
"""

from __future__ import annotations

from lender_package_builder import runtime_paths
from lender_package_builder._version import PRODUCT_NAME, USER_VERSION
from lender_package_builder.gui.main_window import MainWindow


# STAGE 3 TEST 28 - WINDOW TITLE AND HEADER SUBTITLE SHOW THE SINGLE-SOURCE VERSION
def test_window_title_and_subtitle_include_user_version(window):
    from PySide6.QtWidgets import QLabel

    assert window.windowTitle() == f"{PRODUCT_NAME} - v{USER_VERSION}"
    subtitle = window.findChild(QLabel, "AppSubtitle")
    assert subtitle is not None
    assert USER_VERSION in subtitle.text()


# MILESTONE 3 TEST - the large visible header shows the renamed product,
# not the old "Lender Package Builder" branding (the internal Python
# package/module name is deliberately untouched -- see naming.py's
# PRODUCT_NAME docstring).
def test_header_title_shows_renamed_product(window):
    from PySide6.QtWidgets import QLabel

    title = window.findChild(QLabel, "AppTitle")
    assert title is not None
    assert title.text() == PRODUCT_NAME
    assert title.text() == "Document Merger"


# STAGE 3 TEST 29 - APP ICON RESOLVES VIA THE FROZEN-AWARE RUNTIME PATH, NOT A HARDCODED ONE
def test_app_icon_resolves_via_runtime_paths():
    from lender_package_builder.gui.main_window import _ASSETS_DIR

    assert _ASSETS_DIR == runtime_paths.bundled_assets_root() / "gui" / "assets"
    assert (_ASSETS_DIR / "app_icon.svg").exists()


# STAGE 3 TEST 30 - DRAG-ONTO-EXE PRESELECTION SELECTS THE INPUT WITHOUT STARTING A BUILD
def test_preselect_path_selects_input_without_starting_build(qtbot, tmp_path):
    source = tmp_path / "dragged_input"
    source.mkdir()
    (source / "a.txt").write_text("hello\n", encoding="utf-8")

    win = MainWindow(preselect_path=source)
    qtbot.addWidget(win)
    win.show()
    qtbot.wait(50)  # let the QTimer.singleShot(0, ...) preselect callback fire

    try:
        assert win.current_selection is not None
        assert win.current_selection.path == source
        assert win.build_button.isEnabled()
        # The core safety rule this feature must never violate: a
        # preselected input is shown to the user, never auto-built.
        assert win.is_processing is False
        assert win.stack.currentWidget() is win.input_page
    finally:
        win.close()


# STAGE 3 TEST 31 - A MISSING PRESELECT PATH IS IGNORED, NOT A CRASH
def test_preselect_missing_path_is_ignored_safely(qtbot, tmp_path):
    missing = tmp_path / "does_not_exist"

    win = MainWindow(preselect_path=missing)
    qtbot.addWidget(win)
    win.show()
    qtbot.wait(50)

    try:
        assert win.current_selection is None
        assert not win.build_button.isEnabled()
    finally:
        win.close()


# STAGE 3 TEST 32 - MULTIPLE DROPPED-ON-EXE PATHS SHOW THE SAME DIALOG THE IN-APP DROP ZONE USES
def test_startup_multiple_items_message_reuses_dropzone_dialog(qtbot, monkeypatch):
    from lender_package_builder.gui.widgets.drop_zone import MULTIPLE_ITEMS_MESSAGE

    shown = []
    monkeypatch.setattr(
        "lender_package_builder.gui.main_window.dialogs.show_multiple_items_message",
        lambda parent, message: shown.append(message),
    )

    win = MainWindow(startup_multiple_items_message=MULTIPLE_ITEMS_MESSAGE)
    qtbot.addWidget(win)
    win.show()
    qtbot.wait(50)

    try:
        assert shown == [MULTIPLE_ITEMS_MESSAGE]
        assert win.current_selection is None
    finally:
        win.close()


# STAGE 3 TEST 33 - AN INVALID config.toml SHOWS THE WARNING DIALOG EXACTLY ONCE AND STILL STARTS
def test_config_warning_shown_once_when_config_toml_invalid(qtbot, tmp_path, monkeypatch):
    bad_config = tmp_path / "config.toml"
    bad_config.write_text("not valid toml [[[", encoding="utf-8")
    monkeypatch.setattr(
        "lender_package_builder.gui.main_window._default_config_path", lambda: bad_config
    )

    shown = []
    monkeypatch.setattr(
        "lender_package_builder.gui.main_window.dialogs.show_config_warning",
        lambda parent, message: shown.append(message),
    )

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    qtbot.wait(50)

    try:
        assert len(shown) == 1
        # Defaults were used -- the app is never blocked from starting.
        assert win.config.max_pages_per_part == 750
    finally:
        win.close()


# STAGE 3 TEST 34 - THE PACKAGED --gui-smoke-test ENTRY POINT CONSTRUCTS AND CLOSES THE REAL GUI
def test_gui_smoke_test_entry_point_passes(capsys):
    from lender_package_builder.app_entry import _run_gui_smoke_test

    exit_code = _run_gui_smoke_test()

    assert exit_code == 0
    assert "GUI SMOKE TEST: PASS" in capsys.readouterr().out
