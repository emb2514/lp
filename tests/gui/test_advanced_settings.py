from __future__ import annotations

from PySide6.QtCore import Qt

from fixtures.builders import make_zip
from lender_package_builder import lender_presets
from lender_package_builder.models import PackageIdentity


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


# Package Details -- inline identity fields inside Advanced Settings
# (replaced the old modal "Confirm package details" dialog; see
# CHECKPOINT.md). Ported from the deleted test_package_identity_dialog.py.


# TEST - the output-folder preview updates live as the identity fields change
def test_identity_preview_updates_live_as_fields_change(window):
    settings = window.advanced_settings
    settings.last_name_edit.setText("")
    settings.first_name_edit.setText("")
    settings.loan_number_edit.setText("")
    settings.adverse_checkbox.setChecked(False)

    settings.last_name_edit.setText("True")
    assert settings.identity_preview_label.text() == "True"

    settings.first_name_edit.setText("Michael")
    assert settings.identity_preview_label.text() == "True, Michael"

    settings.loan_number_edit.setText("6192278785")
    assert settings.identity_preview_label.text() == "True, Michael, 6192278785"

    settings.adverse_checkbox.setChecked(True)
    assert settings.identity_preview_label.text() == "True, Michael, Adverse, 6192278785"

    # REGRESSION: the Lender field used to be left out of the
    # textChanged wiring entirely, so typing into it never updated this
    # preview -- a user watching the preview would conclude lender
    # wasn't being saved at all, even though the real build included it.
    settings.lender_edit.setText("UWM")
    assert settings.identity_preview_label.text() == "True, Michael, Adverse, UWM, 6192278785"


# TEST - get_identity()/set_identity() round-trip exactly what was entered
def test_get_identity_and_set_identity_round_trip(window):
    settings = window.advanced_settings
    identity = PackageIdentity(
        last_name="Smith", first_name="Jane", loan_number="42", is_adverse=True, lender="UWM"
    )

    settings.set_identity(identity)

    assert settings.last_name_edit.text() == "Smith"
    assert settings.first_name_edit.text() == "Jane"
    assert settings.loan_number_edit.text() == "42"
    assert settings.adverse_checkbox.isChecked() is True
    assert settings.lender_edit.text() == "UWM"
    assert settings.get_identity() == identity


# ---------------------------------------------------------------------
# remembered per-lender presets -- real user request: "idk if 750 pages
# and 100 mb is the best for every single package... this would be good
# ig. its gotta remember? cause idrk what the presets would be"
# ---------------------------------------------------------------------


def test_no_suggestion_when_the_lender_has_never_been_seen_before(window):
    settings = window.advanced_settings

    settings.lender_edit.setText("Some New Lender")

    assert settings.preset_suggestion_label.isVisible() is False
    assert settings.preset_suggestion_button.isVisible() is False


def test_typing_a_remembered_lender_shows_the_suggestion(window, tmp_path, qtbot):
    lender_presets.remember_preset("UWM", 650, 80.0)
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])
    settings = window.advanced_settings
    settings.toggle_button.setChecked(True)
    settings.max_pages_spin.setValue(750)
    settings.max_size_spin.setValue(100.0)

    settings.lender_edit.setText("UWM")

    assert settings.preset_suggestion_label.isVisible() is True
    assert "UWM" in settings.preset_suggestion_label.text()
    assert "650" in settings.preset_suggestion_label.text()
    assert "80.0" in settings.preset_suggestion_label.text()


def test_suggestion_lookup_is_case_insensitive(window, tmp_path, qtbot):
    lender_presets.remember_preset("Rocket Mortgage", 500, 60.0)
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])
    settings = window.advanced_settings
    settings.toggle_button.setChecked(True)

    settings.lender_edit.setText("rocket mortgage")

    assert settings.preset_suggestion_label.isVisible() is True


def test_no_suggestion_when_current_values_already_match_the_preset(window):
    lender_presets.remember_preset("UWM", 750, 100.0)
    settings = window.advanced_settings
    settings.max_pages_spin.setValue(750)
    settings.max_size_spin.setValue(100.0)

    settings.lender_edit.setText("UWM")

    # nothing to suggest -- the current values are already what would be suggested
    assert settings.preset_suggestion_label.isVisible() is False


def test_clicking_use_these_applies_the_suggestion_and_hides_it(window, tmp_path, qtbot):
    lender_presets.remember_preset("UWM", 650, 80.0)
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])
    settings = window.advanced_settings
    settings.toggle_button.setChecked(True)
    settings.lender_edit.setText("UWM")
    assert settings.preset_suggestion_button.isVisible() is True

    qtbot.mouseClick(settings.preset_suggestion_button, Qt.MouseButton.LeftButton)

    assert settings.max_pages_spin.value() == 650
    assert settings.max_size_spin.value() == 80.0
    assert settings.preset_suggestion_label.isVisible() is False


def test_clearing_the_lender_field_hides_the_suggestion(window, tmp_path, qtbot):
    lender_presets.remember_preset("UWM", 650, 80.0)
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])
    settings = window.advanced_settings
    settings.toggle_button.setChecked(True)
    settings.lender_edit.setText("UWM")
    assert settings.preset_suggestion_label.isVisible() is True

    settings.lender_edit.setText("")

    assert settings.preset_suggestion_label.isVisible() is False


# TEST - REGRESSION: a successful build-click actually remembers the
# lender + limits used, so the NEXT time that lender is typed in (even
# in a brand new AdvancedSettingsWidget instance), the suggestion shows
# up -- this is the whole point of the feature, exercised end to end
# rather than just unit-testing lender_presets.py in isolation.
def test_build_click_remembers_the_lender_preset_for_next_time(window, tmp_path, qtbot):
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    settings = window.advanced_settings
    settings.last_name_edit.setText("True")
    settings.lender_edit.setText("UWM")
    settings.max_pages_spin.setValue(650)
    settings.max_size_spin.setValue(80.0)

    window._on_build_clicked()

    preset = lender_presets.lookup_preset("UWM")
    assert preset is not None
    assert preset.max_pages_per_part == 650
    assert preset.max_size_mb_per_part == 80.0


# TEST - Build is blocked (with an auto-expanded validation message)
# until a last name is entered, exactly like the old modal's Continue
# button used to require -- now enforced by validate() instead
def test_missing_last_name_blocks_build_and_shows_validation_message(window, tmp_path, qtbot, monkeypatch):
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    window.advanced_settings.toggle_button.setChecked(False)
    window.advanced_settings.last_name_edit.setText("")

    started = []
    monkeypatch.setattr(window, "_start_build", lambda *a, **k: started.append(True))

    window._on_build_clicked()

    assert started == []
    assert window.advanced_settings.validation_label.isVisible()
    assert "Last name" in window.advanced_settings.validation_label.text()
    assert window.advanced_settings.is_expanded() is True

    window.advanced_settings.last_name_edit.setText("   ")
    valid, _ = window.advanced_settings.validate()
    assert valid is False


# TEST - a filled-in last name (whitespace stripped by naming.sanitize_component)
# lets validate() pass on the identity check
def test_last_name_present_passes_identity_validation(window):
    settings = window.advanced_settings
    settings.last_name_edit.setText("True")

    valid, _ = settings.validate()

    assert valid is True


# TEST - the identity currently in Advanced Settings flows straight
# into _start_build without any modal dialog in between
def test_build_clicked_uses_advanced_settings_identity_directly(window, tmp_path, qtbot, monkeypatch):
    zip_path = tmp_path / "sample.zip"
    make_zip(zip_path, [("a.txt", b"hello")])
    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    window.advanced_settings.set_identity(
        PackageIdentity(last_name="True", first_name="Michael", loan_number="6192278785")
    )

    captured = {}
    monkeypatch.setattr(
        window, "_start_build", lambda run_config, allow_large_input, identity: captured.update(identity=identity)
    )

    window._on_build_clicked()

    assert captured["identity"] == PackageIdentity(
        last_name="True", first_name="Michael", loan_number="6192278785"
    )
