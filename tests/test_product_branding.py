"""Tests for MILESTONE 3 -- renaming the visible product to "Document
Merger". This is a branding change only: the internal Python package
(`lender_package_builder`), CLI commands, config folder names, and
report schemas are deliberately untouched -- only user-visible text
(GUI header/title, --version/--about output, generated report/log
headers) changes, all derived from one centralized
`_version.PRODUCT_NAME` constant.
"""

from __future__ import annotations

import pytest

from lender_package_builder._version import PRODUCT_NAME


def test_product_name_constant():
    assert PRODUCT_NAME == "Document Merger"


def test_version_output_shows_renamed_product(capsys):
    from lender_package_builder import app_entry

    app_entry.main(["--version"])
    captured = capsys.readouterr()
    assert captured.out.startswith(PRODUCT_NAME)
    assert "Lender Package Builder" not in captured.out


def test_help_text_shows_renamed_product():
    from lender_package_builder.app_entry import _help_text

    text = _help_text()
    assert text.startswith(PRODUCT_NAME)


def test_diagnostics_report_shows_renamed_product():
    from lender_package_builder.diagnostics import collect_diagnostics

    report = collect_diagnostics().render()
    assert report.startswith(PRODUCT_NAME)
    assert "Lender Package Builder --" not in report


def test_self_test_report_shows_renamed_product():
    from lender_package_builder.self_test import run_self_test

    result = run_self_test()
    report = result.render_report()
    assert report.startswith(PRODUCT_NAME)


def test_crash_log_shows_renamed_product(tmp_path, monkeypatch):
    from lender_package_builder import crash_log, runtime_paths

    monkeypatch.setattr(runtime_paths, "default_log_root", lambda: tmp_path)
    log_path = crash_log.setup_crash_logging()
    text = log_path.read_text(encoding="utf-8")
    assert text.startswith(PRODUCT_NAME)


def test_cancellation_report_shows_renamed_product(tmp_path, run_build):
    from lender_package_builder.cancellation import CancellationToken
    from lender_package_builder.exceptions import ProcessingCancelledError
    from lender_package_builder.models import PackageIdentity
    from lender_package_builder.progress import ProgressStage

    from fixtures.builders import make_pdf

    folder = tmp_path / "input"
    folder.mkdir()
    for i in range(3):
        make_pdf(folder / f"doc{i:02d}.pdf", pages=1, text_prefix=f"Doc {i}")

    token = CancellationToken()

    def _callback(event):
        if event.stage == ProgressStage.DISCOVERING_FILES:
            token.request()

    with pytest.raises(ProcessingCancelledError) as excinfo:
        run_build(
            folder,
            identity=PackageIdentity(last_name="True"),
            cancellation_token=token,
            progress_callback=_callback,
        )

    report_text = (excinfo.value.output_path / "Reports" / "Cancellation_Report.txt").read_text()
    assert report_text.startswith(PRODUCT_NAME)
