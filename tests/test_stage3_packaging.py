"""Stage 3 automated tests: packaging/portability concerns that do not
require Qt -- versioning, runtime path resolution, friendly config
error handling and its no-overwrite guarantee, the packaged self-test
and diagnostics modules, and the unified CLI-mode entry point.

Numbered independently from the Stage 1 and Stage 2 test suites, as
those files do (each stage restarts its own "TEST N" numbering).
"""

from __future__ import annotations

import re
import sys
from importlib import metadata as importlib_metadata

import pytest

from lender_package_builder import __version__, app_entry, runtime_paths, windows_console
from lender_package_builder._version import RELEASE_LABEL, USER_VERSION, WINDOWS_FILE_VERSION
from lender_package_builder.cli import build_package
from lender_package_builder.config import AppConfig, InvalidConfigError, load_config, load_config_safe
from lender_package_builder.crash_log import install_excepthook, setup_crash_logging
from lender_package_builder.diagnostics import collect_diagnostics
from lender_package_builder.self_test import run_self_test


# STAGE 3 TEST 1 - SINGLE AUTHORITATIVE VERSION SOURCE
def test_single_version_source_matches_installed_package_metadata():
    installed_version = importlib_metadata.version("lender-package-builder")
    assert installed_version == __version__
    assert __version__ == "1.0.0rc1"


# STAGE 3 TEST 2 - USER-FACING AND WINDOWS FILE VERSION FORMAT
def test_user_version_and_windows_file_version_format():
    assert USER_VERSION == "1.0.0 RC1"
    assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+", WINDOWS_FILE_VERSION)
    assert RELEASE_LABEL == "1.0.0_RC1"


# STAGE 3 TEST 3 - NOT FROZEN WHEN RUNNING FROM SOURCE
def test_runtime_paths_not_frozen_in_source_mode():
    assert runtime_paths.is_frozen() is False


# STAGE 3 TEST 4 - APP ROOT RESOLVES TO THE PROJECT ROOT IN SOURCE MODE
def test_runtime_paths_app_root_is_project_root():
    root = runtime_paths.app_root()
    assert (root / "pyproject.toml").exists()


# STAGE 3 TEST 5 - BUNDLED ASSETS ROOT FINDS THE REAL PACKAGE ASSETS
def test_runtime_paths_bundled_assets_root_contains_gui_assets():
    assets_root = runtime_paths.bundled_assets_root()
    icon = assets_root / "gui" / "assets" / "app_icon.svg"
    assert icon.exists(), f"expected {icon} to exist"


# STAGE 3 TEST 6 - EXTERNAL CONFIG PATH IS A SIBLING OF THE APP ROOT
def test_runtime_paths_external_config_path_is_sibling_of_app_root():
    assert runtime_paths.external_config_path() == runtime_paths.app_root() / "config.toml"


# STAGE 3 TEST 7 - LOG ROOT IS PLATFORM-APPROPRIATE
def test_runtime_paths_default_log_root_platform_appropriate():
    log_root = runtime_paths.default_log_root()
    assert log_root.parts[-2:] == ("LenderPackageBuilder", "Logs")
    if sys.platform == "win32":
        assert "AppData" in str(log_root) or "LOCALAPPDATA" in str(log_root)


# STAGE 3 TEST 8 - MALFORMED config.toml RAISES A FRIENDLY ERROR, NOT A RAW PARSER TRACEBACK
def test_load_config_raises_friendly_error_on_malformed_toml(tmp_path):
    bad_config = tmp_path / "config.toml"
    bad_config.write_text("this is not [valid toml", encoding="utf-8")

    with pytest.raises(InvalidConfigError) as exc_info:
        load_config(bad_config)
    assert str(bad_config) in str(exc_info.value)


# STAGE 3 TEST 9 - load_config NEVER WRITES TO A MALFORMED CONFIG FILE
def test_load_config_never_writes_to_malformed_config_file(tmp_path):
    bad_config = tmp_path / "config.toml"
    original_bytes = b"this is not [valid toml"
    bad_config.write_bytes(original_bytes)
    original_mtime = bad_config.stat().st_mtime_ns

    with pytest.raises(InvalidConfigError):
        load_config(bad_config)

    assert bad_config.read_bytes() == original_bytes
    assert bad_config.stat().st_mtime_ns == original_mtime


# STAGE 3 TEST 10 - load_config NEVER WRITES TO A VALID CONFIG FILE
def test_load_config_never_writes_to_valid_config_file(tmp_path):
    good_config = tmp_path / "config.toml"
    original_bytes = b"[splitting]\nmax_pages_per_part = 500\n"
    good_config.write_bytes(original_bytes)
    original_mtime = good_config.stat().st_mtime_ns

    cfg = load_config(good_config)

    assert cfg.max_pages_per_part == 500
    assert good_config.read_bytes() == original_bytes
    assert good_config.stat().st_mtime_ns == original_mtime


# STAGE 3 TEST 11 - load_config_safe FALLS BACK TO DEFAULTS WITH A WARNING, NEVER RAISES
def test_load_config_safe_falls_back_with_warning_on_invalid_file(tmp_path):
    bad_config = tmp_path / "config.toml"
    bad_config.write_text("not valid toml [[[", encoding="utf-8")

    result = load_config_safe(bad_config)

    assert result.used_defaults_due_to_error is True
    assert result.warning is not None
    assert result.config.max_pages_per_part == 750  # built-in default, untouched


# STAGE 3 TEST 12 - load_config_safe RETURNS REAL PARSED VALUES ON A VALID FILE
def test_load_config_safe_returns_parsed_values_on_valid_file(tmp_path):
    good_config = tmp_path / "config.toml"
    good_config.write_text("[splitting]\nmax_size_mb_per_part = 42.0\n", encoding="utf-8")

    result = load_config_safe(good_config)

    assert result.used_defaults_due_to_error is False
    assert result.config.max_size_mb_per_part == 42.0


# STAGE 3 TEST 13 - CLI build COMMAND REPORTS A FRIENDLY ERROR ON A MALFORMED CONFIG, NOT A CRASH
def test_cli_build_reports_friendly_error_not_traceback_on_malformed_config(tmp_path, capsys):
    from lender_package_builder.cli import main

    bad_config = tmp_path / "config.toml"
    bad_config.write_text("not valid toml [[[", encoding="utf-8")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.txt").write_text("hello\n", encoding="utf-8")

    exit_code = main(["build", str(input_dir), "--config", str(bad_config), "--quiet"])

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "FAILED" in captured.err
    assert "Traceback" not in captured.err


# STAGE 3 TEST 14 - PACKAGED SELF-TEST PASSES ON A HEALTHY ENVIRONMENT
def test_self_test_passes_on_healthy_environment():
    result = run_self_test()

    assert result.success is True
    check_names = {c.name for c in result.checks}
    assert "Core engine pipeline runs" in check_names
    assert "Exact-duplicate detection works" in check_names
    assert "Integrity checks pass" in check_names
    assert "Runtime paths resolve" in check_names
    assert "Configuration loads" in check_names


# STAGE 3 TEST 15 - SELF-TEST CLEANS UP ITS OWN TEMP DIRECTORIES
def test_self_test_leaves_no_temp_directories_behind():
    import tempfile
    from pathlib import Path

    system_tmp = Path(tempfile.gettempdir())
    before = set(system_tmp.glob("lpb_selftest_*"))

    run_self_test()

    after = set(system_tmp.glob("lpb_selftest_*"))
    assert after == before


# STAGE 3 TEST 15B - SELF-TEST DETECTS A DELIBERATELY CORRUPTED RESULT
def test_self_test_detects_deliberately_corrupted_result(tmp_path):
    """The self-test module must actually check things, not just
    always print PASS. Runs the real pipeline once, then corrupts the
    resulting RunResult in two different ways and confirms evaluation
    catches each one independently.
    """

    import lender_package_builder.self_test as self_test_module
    from lender_package_builder.cli import build_package

    in_dir = tmp_path / "Self_Test_Input"
    in_dir.mkdir()
    self_test_module._build_self_test_input(in_dir)

    output_dir = tmp_path / "Self_Test_Output"
    run = build_package(
        input_path=in_dir,
        output_dir=output_dir,
        config=AppConfig(),
        progress=False,
    )

    healthy_checks = self_test_module._evaluate_self_test_run(run, output_dir)
    assert all(c.passed for c in healthy_checks)

    # Corruption 1: pretend the duplicate was never detected.
    run.duplicate_groups = []
    corrupted_checks = self_test_module._evaluate_self_test_run(run, output_dir)
    dedup_check = next(c for c in corrupted_checks if c.name == "Exact-duplicate detection works")
    assert dedup_check.passed is False

    # Corruption 2 (independent, on a fresh run): pretend a required
    # integrity check failed.
    run2 = build_package(
        input_path=in_dir,
        output_dir=tmp_path / "Self_Test_Output_2",
        config=AppConfig(),
        progress=False,
    )
    run2.integrity_checks[0].passed = False
    corrupted_checks_2 = self_test_module._evaluate_self_test_run(run2, tmp_path / "Self_Test_Output_2")
    integrity_check = next(c for c in corrupted_checks_2 if c.name == "Integrity checks pass")
    assert integrity_check.passed is False


# STAGE 3 TEST 16 - DIAGNOSTICS REPORT INCLUDES ALL EXPECTED SECTIONS
def test_diagnostics_report_includes_all_expected_sections():
    report = collect_diagnostics().render()

    for heading in (
        "[Version]",
        "[Runtime]",
        "[Configuration]",
        "[System]",
        "[Bundled libraries]",
        "[Document conversion backends]",
    ):
        assert heading in report
    assert __version__ in report


# STAGE 3 TEST 17 - DIAGNOSTICS NEVER RAISES AND CORRECTLY SCOPES OFFICE COM TO WINDOWS
def test_diagnostics_report_never_raises_and_scopes_office_com():
    report = collect_diagnostics().render()

    if sys.platform != "win32":
        assert "not applicable (not running on Windows)" in report


# STAGE 3 TEST 18 - CLI-MODE FLAGS TAKE PRIORITY OVER ANY STRAY PATH ARGUMENTS
def test_app_entry_parse_args_flags_take_priority_over_paths(tmp_path):
    existing = tmp_path / "input.txt"
    existing.write_text("x", encoding="utf-8")

    assert app_entry.parse_args(["--version"]).mode == "version"
    assert app_entry.parse_args(["--self-test"]).mode == "self_test"
    assert app_entry.parse_args(["--diagnostics"]).mode == "diagnostics"
    assert app_entry.parse_args(["--gui-smoke-test"]).mode == "gui_smoke_test"
    assert app_entry.parse_args(["--help"]).mode == "help"
    assert app_entry.parse_args(["--version", str(existing)]).mode == "version"


# STAGE 3 TEST 19 - NO ARGUMENTS LAUNCHES THE PLAIN GUI WITH NO PRESELECTION
def test_app_entry_parse_args_no_args_is_plain_gui_mode():
    parsed = app_entry.parse_args([])
    assert parsed.mode == "gui"
    assert parsed.preselect_path is None
    assert parsed.multiple_items_message is None


# STAGE 3 TEST 20 - ONE EXISTING PATH (DRAG-ONTO-EXE) PRESELECTS IT WITHOUT PROCESSING
def test_app_entry_parse_args_single_existing_path_preselects(tmp_path):
    existing = tmp_path / "input.txt"
    existing.write_text("x", encoding="utf-8")

    parsed = app_entry.parse_args([str(existing)])

    assert parsed.mode == "gui"
    assert parsed.preselect_path == existing
    assert parsed.multiple_items_message is None


# STAGE 3 TEST 21 - ONE MISSING PATH SHOWS A NOT-FOUND MESSAGE, NOT A CRASH
def test_app_entry_parse_args_single_missing_path_shows_not_found_message(tmp_path):
    missing = tmp_path / "does_not_exist.txt"

    parsed = app_entry.parse_args([str(missing)])

    assert parsed.mode == "gui"
    assert parsed.preselect_path is None
    assert "could not be found" in parsed.multiple_items_message


# STAGE 3 TEST 22 - MULTIPLE DROPPED PATHS REUSE THE EXISTING DROP-ZONE REJECTION MESSAGE
def test_app_entry_parse_args_multiple_paths_reuses_dropzone_message(tmp_path):
    from lender_package_builder.gui.widgets.drop_zone import MULTIPLE_ITEMS_MESSAGE

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("x", encoding="utf-8")
    b.write_text("y", encoding="utf-8")

    parsed = app_entry.parse_args([str(a), str(b)])

    assert parsed.mode == "gui"
    assert parsed.preselect_path is None
    assert parsed.multiple_items_message == MULTIPLE_ITEMS_MESSAGE


# STAGE 3 TEST 23 - "--version" PRINTS AND EXITS CLEANLY WITH NO GUI/ENGINE IMPORT REQUIRED
def test_app_entry_main_version_flag_prints_and_returns_zero(capsys):
    exit_code = app_entry.main(["--version"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert USER_VERSION in captured.out
    assert __version__ in captured.out


# STAGE 3 TEST 24 - "--self-test" SUCCEEDS ON A HEALTHY ENVIRONMENT
def test_app_entry_main_self_test_flag_returns_zero_on_healthy_environment(capsys):
    exit_code = app_entry.main(["--self-test"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "OVERALL RESULT: PASS" in captured.out


# STAGE 3 TEST 25 - WINDOWS CONSOLE ATTACHMENT IS A SAFE NO-OP OFF WINDOWS
def test_windows_console_attach_is_noop_on_non_windows():
    if sys.platform == "win32":
        pytest.skip("this check only applies off Windows")

    original_stdout = sys.stdout
    windows_console.attach_parent_console()
    assert sys.stdout is original_stdout


# STAGE 3 TEST 26 - CRASH LOG SETUP WRITES STARTUP INFO TO A READABLE FILE
def test_crash_log_setup_writes_startup_info(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_paths, "default_log_root", lambda: tmp_path / "Logs")

    log_path = setup_crash_logging()

    assert log_path.exists()
    contents = log_path.read_text(encoding="utf-8")
    assert __version__ in contents
    assert "Frozen: False" in contents


# STAGE 3 TEST 27 - UNHANDLED EXCEPTIONS ARE APPENDED TO THE CRASH LOG AND THE PREVIOUS HOOK STILL RUNS
def test_crash_log_excepthook_appends_traceback_and_chains_previous_hook(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_paths, "default_log_root", lambda: tmp_path / "Logs")
    log_path = setup_crash_logging()

    calls = []
    monkeypatch.setattr(sys, "excepthook", lambda *a: calls.append(a))
    install_excepthook(log_path)

    try:
        raise ValueError("synthetic crash for the test")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    assert len(calls) == 1
    contents = log_path.read_text(encoding="utf-8")
    assert "UNHANDLED EXCEPTION" in contents
    assert "synthetic crash for the test" in contents


# STAGE 3 TEST 28 - THE SAMPLE TEST PACKAGE MATCHES ITS DOCUMENTED EXPECTED RESULTS
def test_sample_package_matches_documented_expected_results(tmp_path):
    samples_dir = runtime_paths.app_root() / "samples"
    sys.path.insert(0, str(samples_dir))
    try:
        from generate_sample_package import generate_sample_package
    finally:
        sys.path.remove(str(samples_dir))

    zip_path = generate_sample_package()

    run = build_package(
        input_path=zip_path,
        output_dir=tmp_path / "output",
        config=AppConfig(),
        progress=False,
    )

    assert run.success is True
    assert all(check.passed for check in run.integrity_checks)

    dup_count = sum(len(g.duplicate_document_ids) for g in run.duplicate_groups)
    assert dup_count == 1

    og_count = sum(len(p.document_ids) for p in run.og_parts)
    final_count = sum(len(p.document_ids) for p in run.final_parts)
    assert og_count == 4
    assert final_count == 3
