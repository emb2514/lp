from __future__ import annotations

from fixtures.builders import make_zip


# TEST 6 - ADVANCED SETTINGS DEFAULTS
def test_advanced_settings_load_stage1_defaults_and_start_collapsed(window):
    settings = window.advanced_settings

    assert settings.is_expanded() is False
    assert settings.max_pages_spin.value() == 750
    assert settings.max_size_spin.value() == 100.0

    from lender_package_builder.gui.widgets.advanced_settings import EXPLANATION_TEXT

    assert "upper boundaries" in EXPLANATION_TEXT
    assert "not exact target sizes" in EXPLANATION_TEXT
    assert "never split" in EXPLANATION_TEXT
    assert "3,000+ pages" in EXPLANATION_TEXT


def test_advanced_settings_toggle_expands_and_collapses(window, tmp_path, qtbot):
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    settings = window.advanced_settings
    assert settings.isVisible()  # shown once an input is selected
    assert settings.content.isVisible() is False

    settings.toggle_button.setChecked(True)
    assert settings.content.isVisible() is True
    assert settings.toggle_button.text().startswith("▾")

    settings.toggle_button.setChecked(False)
    assert settings.content.isVisible() is False
    assert settings.toggle_button.text().startswith("▸")


def test_reset_to_recommended_defaults(window):
    settings = window.advanced_settings
    settings.max_pages_spin.setValue(42)
    settings.max_size_spin.setValue(5.0)

    settings.reset_button.click()

    assert settings.max_pages_spin.value() == 750
    assert settings.max_size_spin.value() == 100.0


# TEST 7 - ADVANCED SETTINGS VALIDATION
def test_zero_page_maximum_is_invalid_and_shows_message(window, tmp_path, qtbot):
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    settings = window.advanced_settings
    settings.max_pages_spin.setValue(0)

    valid, message = settings.validate()

    assert valid is False
    assert message
    assert settings.validation_label.isVisible()
    assert settings.is_expanded() is True  # auto-expanded so the error is seen


def test_zero_size_maximum_is_invalid_and_shows_message(window, tmp_path, qtbot):
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    settings = window.advanced_settings
    settings.max_size_spin.setValue(0.0)

    valid, message = settings.validate()

    assert valid is False
    assert message
    assert settings.validation_label.isVisible()
    assert settings.is_expanded() is True


# RC2 - content-aware dedup toggle
def test_content_aware_dedup_checkbox_defaults_to_config_value(window):
    settings = window.advanced_settings
    assert settings.content_aware_dedup_checkbox.isChecked() is window.config.enable_content_aware_dedup
    assert settings.content_aware_dedup_checkbox.isChecked() is True  # AppConfig default


def test_content_aware_dedup_checkbox_included_in_get_values():
    from lender_package_builder.gui.widgets.advanced_settings import AdvancedSettingsWidget

    widget = AdvancedSettingsWidget(750, 100.0, default_enable_content_aware_dedup=False)
    values = widget.get_values()
    assert values.enable_content_aware_dedup is False

    widget.content_aware_dedup_checkbox.setChecked(True)
    assert widget.get_values().enable_content_aware_dedup is True


def test_reset_to_recommended_defaults_restores_content_aware_dedup_checkbox(window):
    settings = window.advanced_settings
    settings.content_aware_dedup_checkbox.setChecked(False)

    settings.reset_button.click()

    assert settings.content_aware_dedup_checkbox.isChecked() is True


def test_disabling_content_aware_dedup_checkbox_flows_into_run_config(window, tmp_path, qtbot, monkeypatch):
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    window.advanced_settings.content_aware_dedup_checkbox.setChecked(False)

    captured = {}
    monkeypatch.setattr(
        window, "_start_build", lambda run_config, allow_large_input, identity: captured.update(cfg=run_config)
    )

    window._on_build_clicked()

    assert captured["cfg"].enable_content_aware_dedup is False


def test_invalid_advanced_settings_prevent_processing(window, tmp_path, qtbot, monkeypatch):
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])

    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    window.advanced_settings.max_pages_spin.setValue(0)

    started = []
    monkeypatch.setattr(window, "_start_build", lambda *a, **k: started.append(True))

    window._on_build_clicked()

    assert started == []
    assert window.is_processing is False
    assert window.advanced_settings.validation_label.isVisible()
