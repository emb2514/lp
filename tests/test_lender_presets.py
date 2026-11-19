"""Tests for remembered per-lender output-part size limits.

Real user question, then request: "idk if 750 pages and 100 mb is the
best for every single package you get me?" -- confirmed the right
limit is driven by what a given lender's own systems accept, not by
any package's content, so the fix is to remember whatever limits were
used last time for a lender and offer them again, rather than guess
from the uploaded files. "this would be good ig. its gotta remember?
cause idrk what the presets would be [up front]."
"""

from __future__ import annotations

from lender_package_builder.lender_presets import LenderPreset, lookup_preset, remember_preset


def test_lookup_returns_none_when_nothing_has_ever_been_remembered(tmp_path):
    path = tmp_path / "presets.json"

    assert lookup_preset("UWM", path) is None


def test_lookup_returns_none_for_a_blank_lender(tmp_path):
    path = tmp_path / "presets.json"
    remember_preset("UWM", 650, 80.0, path)

    assert lookup_preset("", path) is None
    assert lookup_preset("   ", path) is None


def test_remember_then_lookup_round_trips(tmp_path):
    path = tmp_path / "presets.json"

    remember_preset("UWM", 650, 80.0, path)

    assert lookup_preset("UWM", path) == LenderPreset(lender_label="UWM", max_pages_per_part=650, max_size_mb_per_part=80.0)


def test_lookup_is_case_and_whitespace_insensitive_but_keeps_the_original_label(tmp_path):
    path = tmp_path / "presets.json"
    remember_preset("  Rocket Mortgage  ", 500, 60.0, path)

    preset = lookup_preset("rocket MORTGAGE", path)

    assert preset is not None
    assert preset.max_pages_per_part == 500
    assert preset.lender_label == "Rocket Mortgage"  # original casing/spacing preserved for display


def test_remembering_the_same_lender_again_overwrites_the_old_limits(tmp_path):
    path = tmp_path / "presets.json"
    remember_preset("UWM", 650, 80.0, path)

    remember_preset("UWM", 700, 90.0, path)

    preset = lookup_preset("UWM", path)
    assert preset.max_pages_per_part == 700
    assert preset.max_size_mb_per_part == 90.0


def test_different_lenders_are_remembered_independently(tmp_path):
    path = tmp_path / "presets.json"
    remember_preset("UWM", 650, 80.0, path)
    remember_preset("Freedom", 400, 50.0, path)

    assert lookup_preset("UWM", path).max_pages_per_part == 650
    assert lookup_preset("Freedom", path).max_pages_per_part == 400


def test_lookup_fails_soft_against_a_corrupt_presets_file(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text("{not valid json", encoding="utf-8")

    assert lookup_preset("UWM", path) is None


def test_lookup_fails_soft_when_the_presets_file_is_not_a_json_object(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    assert lookup_preset("UWM", path) is None


def test_remember_preset_never_raises_even_if_the_parent_directory_must_be_created(tmp_path):
    path = tmp_path / "nested" / "does" / "not" / "exist" / "presets.json"

    remember_preset("UWM", 650, 80.0, path)

    assert lookup_preset("UWM", path) is not None
