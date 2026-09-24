"""Tests for batch.py -- MILESTONE: batch mode. Real user request:
"point the app at a folder-of-folders (one per loan) and build them
all in one run instead of one at a time."
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fixtures.builders import make_pdf_with_pages

from lender_package_builder import batch
from lender_package_builder.cancellation import CancellationToken
from lender_package_builder.config import AppConfig
from lender_package_builder.exceptions import ProcessingCancelledError


# ---------------------------------------------------------------------
# identity_from_folder_name
# ---------------------------------------------------------------------


def test_identity_parses_last_and_first_name():
    identity = batch.identity_from_folder_name("Doe, John")
    assert identity.last_name == "Doe"
    assert identity.first_name == "John"
    assert identity.loan_number == ""


def test_identity_parses_last_first_and_loan_number():
    identity = batch.identity_from_folder_name("Doe, John, 123456")
    assert identity.last_name == "Doe"
    assert identity.first_name == "John"
    assert identity.loan_number == "123456"


def test_identity_parses_with_extra_whitespace():
    identity = batch.identity_from_folder_name("  Doe ,  John  ,  123456  ")
    assert identity.last_name == "Doe"
    assert identity.first_name == "John"
    assert identity.loan_number == "123456"


def test_identity_falls_back_to_last_name_only_when_no_comma():
    identity = batch.identity_from_folder_name("SmithFamily")
    assert identity.last_name == "SmithFamily"
    assert identity.first_name == ""
    assert identity.loan_number == ""


def test_identity_falls_back_to_last_name_only_for_unusual_shapes():
    # More than 3 comma-separated segments -- never guessed at, the
    # whole thing becomes the last name rather than risk a wrong split.
    identity = batch.identity_from_folder_name("Doe, John, 123456, extra, stuff")
    assert identity.last_name == "Doe, John, 123456, extra, stuff"
    assert identity.first_name == ""


# ---------------------------------------------------------------------
# discover_loan_folders
# ---------------------------------------------------------------------


def test_discover_loan_folders_only_includes_directories(tmp_path):
    (tmp_path / "Doe, John").mkdir()
    (tmp_path / "Smith, Jane").mkdir()
    (tmp_path / "not_a_loan.txt").write_text("stray file")

    folders = batch.discover_loan_folders(tmp_path)
    assert [f.name for f in folders] == ["Doe, John", "Smith, Jane"]


def test_discover_loan_folders_sorted_case_insensitively(tmp_path):
    (tmp_path / "zephyr, al").mkdir()
    (tmp_path / "Adams, Bob").mkdir()
    (tmp_path / "middleton, cara").mkdir()

    folders = batch.discover_loan_folders(tmp_path)
    assert [f.name for f in folders] == ["Adams, Bob", "middleton, cara", "zephyr, al"]


def test_discover_loan_folders_empty_parent(tmp_path):
    assert batch.discover_loan_folders(tmp_path) == []


# ---------------------------------------------------------------------
# build_batch
# ---------------------------------------------------------------------


def _make_loan_folder(parent: Path, name: str, content: str = "Some real content") -> Path:
    folder = parent / name
    folder.mkdir(parents=True)
    make_pdf_with_pages(folder / "doc.pdf", [content])
    return folder


def test_build_batch_builds_every_loan_independently(tmp_path):
    parent = tmp_path / "parent"
    _make_loan_folder(parent, "Doe, John, 111111")
    _make_loan_folder(parent, "Smith, Jane, 222222")

    result = batch.build_batch(parent, tmp_path / "out", AppConfig())

    assert len(result.loan_results) == 2
    assert len(result.succeeded) == 2
    assert len(result.failed) == 0
    names = {r.loan_folder.name for r in result.loan_results}
    assert names == {"Doe, John, 111111", "Smith, Jane, 222222"}
    for loan_result in result.loan_results:
        assert loan_result.run is not None
        assert loan_result.run.success is True


def test_build_batch_gives_each_loan_its_own_parsed_identity(tmp_path):
    parent = tmp_path / "parent"
    _make_loan_folder(parent, "Doe, John, 111111")

    result = batch.build_batch(parent, tmp_path / "out", AppConfig())

    loan_result = result.loan_results[0]
    assert loan_result.identity.last_name == "Doe"
    assert loan_result.identity.first_name == "John"
    assert loan_result.identity.loan_number == "111111"
    # The actual build used that identity -- reflected in the real
    # output folder name it produced.
    assert "Doe" in loan_result.run.output_path.name
    assert "111111" in loan_result.run.output_path.name


def test_build_batch_isolates_one_loan_failure_from_the_rest(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    _make_loan_folder(parent, "Doe, John, 111111")
    _make_loan_folder(parent, "Failing, Loan, 999999")
    _make_loan_folder(parent, "Smith, Jane, 222222")

    real_build_package = __import__("lender_package_builder.cli", fromlist=["build_package"]).build_package

    def _flaky_build_package(*args, **kwargs):
        if kwargs.get("input_path") is not None and "Failing" in kwargs["input_path"].name:
            raise RuntimeError("Simulated unexpected failure for this one loan.")
        return real_build_package(*args, **kwargs)

    monkeypatch.setattr("lender_package_builder.cli.build_package", _flaky_build_package)

    result = batch.build_batch(parent, tmp_path / "out", AppConfig())

    assert len(result.loan_results) == 3
    assert len(result.succeeded) == 2
    assert len(result.failed) == 1
    assert result.failed[0].loan_folder.name == "Failing, Loan, 999999"
    assert "Simulated unexpected failure" in result.failed[0].error_message
    # The other two loans still built successfully despite the failure.
    succeeded_names = {r.loan_folder.name for r in result.succeeded}
    assert succeeded_names == {"Doe, John, 111111", "Smith, Jane, 222222"}


def test_build_batch_each_loan_output_lands_in_its_own_subfolder(tmp_path):
    parent = tmp_path / "parent"
    _make_loan_folder(parent, "Doe, John, 111111")
    out_dir = tmp_path / "out"

    result = batch.build_batch(parent, out_dir, AppConfig())

    loan_result = result.loan_results[0]
    assert loan_result.run.output_path.parent == out_dir


def test_build_batch_with_no_output_dir_defaults_next_to_each_loan_input(tmp_path):
    parent = tmp_path / "parent"
    loan_folder = _make_loan_folder(parent, "Doe, John, 111111")

    result = batch.build_batch(parent, None, AppConfig())

    loan_result = result.loan_results[0]
    # Same default-output-location behavior as a single build_package
    # call with no explicit output_dir -- lands alongside the input.
    assert loan_result.run.output_path.parent == loan_folder.parent


def test_build_batch_empty_parent_produces_empty_result(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()

    result = batch.build_batch(parent, tmp_path / "out", AppConfig())

    assert result.loan_results == []
    assert result.succeeded == []
    assert result.failed == []


def test_build_batch_progress_callback_fires_once_per_loan_in_order(tmp_path):
    parent = tmp_path / "parent"
    _make_loan_folder(parent, "Adams, Al, 1")
    _make_loan_folder(parent, "Brown, Bo, 2")

    calls = []
    batch.build_batch(
        parent, tmp_path / "out", AppConfig(),
        progress_callback=lambda folder, current, total: calls.append((folder.name, current, total)),
    )

    assert calls == [("Adams, Al, 1", 1, 2), ("Brown, Bo, 2", 2, 2)]


def test_build_batch_cancellation_aborts_the_whole_batch(tmp_path):
    parent = tmp_path / "parent"
    _make_loan_folder(parent, "Adams, Al, 1")
    _make_loan_folder(parent, "Brown, Bo, 2")
    _make_loan_folder(parent, "Carter, Cy, 3")

    token = CancellationToken()

    def _cancel_after_first(folder, current, total):
        if current == 2:
            token.request()

    with pytest.raises(ProcessingCancelledError):
        batch.build_batch(
            parent, tmp_path / "out", AppConfig(),
            progress_callback=_cancel_after_first,
            cancellation_token=token,
        )


# ---------------------------------------------------------------------
# write_batch_summary
# ---------------------------------------------------------------------


def test_write_batch_summary_reports_success_and_failure(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    _make_loan_folder(parent, "Doe, John, 111111")
    _make_loan_folder(parent, "Failing, Loan, 999999")

    real_build_package = __import__("lender_package_builder.cli", fromlist=["build_package"]).build_package

    def _flaky_build_package(*args, **kwargs):
        if kwargs.get("input_path") is not None and "Failing" in kwargs["input_path"].name:
            raise RuntimeError("Simulated unexpected failure for this one loan.")
        return real_build_package(*args, **kwargs)

    monkeypatch.setattr("lender_package_builder.cli.build_package", _flaky_build_package)

    result = batch.build_batch(parent, tmp_path / "out", AppConfig())
    summary_path = tmp_path / "Batch Summary.txt"
    batch.write_batch_summary(result, summary_path)

    text = summary_path.read_text(encoding="utf-8")
    assert "Loans found: 2" in text
    assert "Succeeded: 1" in text
    assert "Failed: 1" in text
    assert "[SUCCESS] Doe, John, 111111" in text
    assert "[FAILED] Failing, Loan, 999999" in text
