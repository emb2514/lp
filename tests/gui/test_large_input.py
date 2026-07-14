from __future__ import annotations

from fixtures.builders import make_zip

from lender_package_builder import archives


# TEST 14 - LARGE-INPUT CONFIRMATION
def test_large_input_requires_explicit_confirmation_before_allow_large_input(window, tmp_path, qtbot, monkeypatch):
    zip_path = tmp_path / "big.zip"
    make_zip(zip_path, [("a.txt", b"hello")])

    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    # Simulate the background estimate coming back far above the hard limit.
    huge_estimate = archives.ExpansionEstimate(
        total_uncompressed_bytes=window.config.max_expanded_size_bytes * 5,
        total_entries=10,
    )
    window._on_estimate_ready(huge_estimate)
    assert window.selected_card.warning_label.isVisible()

    captured_calls = []

    def fake_start_build(run_config, allow_large_input):
        captured_calls.append(allow_large_input)

    monkeypatch.setattr(window, "_start_build", fake_start_build)

    # Case 1: user clicks "Go Back" -> must NOT proceed, must NOT allow_large_input.
    class FakeDialogGoBack:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return None

        def confirmed(self):
            return False

    monkeypatch.setattr("lender_package_builder.gui.main_window.dialogs.LargeInputConfirmDialog", FakeDialogGoBack)
    window._on_build_clicked()
    assert captured_calls == []

    # Case 2: user explicitly confirms -> proceeds with allow_large_input=True.
    class FakeDialogConfirm:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return None

        def confirmed(self):
            return True

    monkeypatch.setattr("lender_package_builder.gui.main_window.dialogs.LargeInputConfirmDialog", FakeDialogConfirm)
    window._on_build_clicked()
    assert captured_calls == [True]


def test_small_input_does_not_trigger_confirmation_dialog(window, tmp_path, qtbot, monkeypatch):
    zip_path = tmp_path / "small.zip"
    make_zip(zip_path, [("a.txt", b"hello")])

    with qtbot.waitSignal(window.drop_zone.input_selected, timeout=2000):
        window.drop_zone._handle_paths([zip_path])

    small_estimate = archives.ExpansionEstimate(total_uncompressed_bytes=1000, total_entries=1)
    window._on_estimate_ready(small_estimate)
    assert not window.selected_card.warning_label.isVisible()

    dialog_shown = []
    monkeypatch.setattr(
        "lender_package_builder.gui.main_window.dialogs.LargeInputConfirmDialog",
        lambda *a, **k: dialog_shown.append(True),
    )
    captured_calls = []
    monkeypatch.setattr(window, "_start_build", lambda run_config, allow_large_input: captured_calls.append(allow_large_input))

    window._on_build_clicked()

    assert dialog_shown == []
    assert captured_calls == [False]
