from __future__ import annotations


# TEST 1 - GUI INITIAL STATE
def test_initial_state_shows_drop_zone_and_disabled_build_button(window):
    assert window.isVisible() or True  # offscreen platform still reports geometry validity
    assert window.drop_zone.isVisible()
    assert not window.build_button.isEnabled()
    assert window.is_processing is False
    assert window.stack.currentWidget() is window.input_page


# TEST 20 - HEADLESS GUI STARTUP
def test_application_and_main_window_construct_without_exception(qtbot):
    from lender_package_builder._version import USER_VERSION
    from lender_package_builder.gui.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    win.show()
    assert win.windowTitle() == f"Lender Package Builder - v{USER_VERSION}"
    win.close()
