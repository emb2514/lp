"""Tests for MILESTONE 2 -- safe abort (Cancel Processing): the
`CancellationToken`/`check_cancelled()` primitives themselves, and
`build_package()`'s cooperative cancellation behavior at various
pipeline stages -- proving a cancelled run never leaves a partial
package under a real Final-package filename, never touches source
files, always cleans up (or safely quarantines) what it can, and
always allows a fresh run to start immediately afterward.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lender_package_builder import naming
from lender_package_builder.cancellation import CancellationToken, ProcessingCancelled, check_cancelled
from lender_package_builder.exceptions import ProcessingCancelledError
from lender_package_builder.models import PackageIdentity
from lender_package_builder.progress import ProgressStage


# TEST 1 - CancellationToken itself
def test_cancellation_token_starts_unrequested():
    token = CancellationToken()
    assert token.is_requested() is False


def test_cancellation_token_request_is_idempotent_and_sticky():
    token = CancellationToken()
    token.request()
    token.request()
    assert token.is_requested() is True


# TEST 2 - check_cancelled() is a no-op with no token or an unrequested one
def test_check_cancelled_noop_when_token_none():
    check_cancelled(None)  # must not raise


def test_check_cancelled_noop_when_not_requested():
    token = CancellationToken()
    check_cancelled(token)  # must not raise


def test_check_cancelled_raises_when_requested():
    token = CancellationToken()
    token.request()
    with pytest.raises(ProcessingCancelled):
        check_cancelled(token)


def _make_multi_doc_input(tmp_path: Path, count: int) -> Path:
    from fixtures.builders import make_pdf

    folder = tmp_path / "input"
    folder.mkdir()
    for i in range(count):
        make_pdf(folder / f"doc{i:02d}.pdf", pages=1, text_prefix=f"Document {i}")
    return folder


def _cancel_after_n_conversions(token: CancellationToken, n: int):
    seen = {"count": 0}

    def _callback(event):
        if event.stage == ProgressStage.CONVERTING_DOCUMENTS and event.current is not None:
            seen["count"] = max(seen["count"], event.current)
            if event.current >= n:
                token.request()

    return _callback


# TEST 3 - cancelling mid-conversion raises ProcessingCancelledError, not a
# normal success/failure RunResult.
def test_cancel_mid_conversion_raises_processing_cancelled_error(tmp_path, run_build):
    folder = _make_multi_doc_input(tmp_path, 6)
    token = CancellationToken()

    with pytest.raises(ProcessingCancelledError) as excinfo:
        run_build(
            folder,
            identity=PackageIdentity(last_name="True", first_name="Michael"),
            cancellation_token=token,
            progress_callback=_cancel_after_n_conversions(token, 2),
        )

    assert excinfo.value.cleanup_succeeded is True
    assert excinfo.value.output_path is not None


# TEST 4 - a cancelled run never leaves a Final/Original Lender Package
# file behind, and never leaves the normal success-only reports either --
# only a distinct cancellation report.
def test_cancel_leaves_no_partial_package_only_cancellation_report(tmp_path, run_build):
    folder = _make_multi_doc_input(tmp_path, 6)
    token = CancellationToken()
    identity = PackageIdentity(last_name="True", first_name="Michael")

    with pytest.raises(ProcessingCancelledError) as excinfo:
        run_build(
            folder,
            identity=identity,
            cancellation_token=token,
            progress_callback=_cancel_after_n_conversions(token, 2),
        )

    output_path = excinfo.value.output_path
    assert output_path is not None and output_path.exists()

    final_dir = output_path / "Final"
    if final_dir.exists():
        assert list(final_dir.glob("*.pdf")) == []

    reports_dir = output_path / "Reports"
    assert (reports_dir / "Cancellation_Report.txt").exists()
    assert not (reports_dir / "Processing_Report.txt").exists()
    assert not (reports_dir / "Processing_Manifest.json").exists()

    report_text = (reports_dir / "Cancellation_Report.txt").read_text()
    assert "cancelled" in report_text.lower()
    assert "No Final or Original Lender Package files were produced" in report_text


# TEST 5 - source files are never modified by a cancelled run.
def test_cancel_never_modifies_source_files(tmp_path, run_build):
    folder = _make_multi_doc_input(tmp_path, 6)
    original_bytes = {p.name: p.read_bytes() for p in folder.glob("*.pdf")}
    token = CancellationToken()

    with pytest.raises(ProcessingCancelledError):
        run_build(
            folder,
            identity=PackageIdentity(last_name="True", first_name="Michael"),
            cancellation_token=token,
            progress_callback=_cancel_after_n_conversions(token, 2),
        )

    for p in folder.glob("*.pdf"):
        assert p.read_bytes() == original_bytes[p.name]


# TEST 6 - a new package can be started immediately after a cancellation,
# without any leftover state blocking it (the identity-based folder name
# versions automatically, exactly like the normal overwrite-protection
# case).
def test_new_run_succeeds_immediately_after_a_cancelled_run(tmp_path, run_build):
    folder = _make_multi_doc_input(tmp_path, 3)
    identity = PackageIdentity(last_name="True", first_name="Michael")
    token = CancellationToken()

    with pytest.raises(ProcessingCancelledError):
        run_build(
            folder,
            identity=identity,
            cancellation_token=token,
            progress_callback=_cancel_after_n_conversions(token, 1),
        )

    run = run_build(folder, identity=identity)
    assert run.success is True
    assert (run.output_path / "Final").glob("*.pdf")
    assert any((run.output_path / "Final").glob("*.pdf"))


# TEST 7 - cancelling during inventory/discovery (before any document is
# converted) is caught just as safely.
def test_cancel_during_discovery_stage(tmp_path, run_build):
    folder = _make_multi_doc_input(tmp_path, 4)
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

    assert excinfo.value.stage in (ProgressStage.DISCOVERING_FILES.value, ProgressStage.DETECTING_DUPLICATES.value)


# TEST 8 - cancelling after the run has already completed successfully
# (token requested too late to matter) has no effect -- a completed,
# passing run is still returned normally, not retroactively cancelled.
def test_cancellation_requested_after_completion_has_no_effect(tmp_path, run_build):
    folder = _make_multi_doc_input(tmp_path, 2)
    token = CancellationToken()

    def _callback(event):
        if event.stage == ProgressStage.COMPLETE:
            token.request()  # too late -- nothing left to check

    run = run_build(
        folder,
        identity=PackageIdentity(last_name="True", first_name="Michael"),
        cancellation_token=token,
        progress_callback=_callback,
    )
    assert run.success is True


# TEST 9 - naming.py's "Incomplete Cancelled Output" constant follows the
# same no-underscore convention as every other user-facing name.
def test_incomplete_cancelled_output_folder_name_has_no_underscores():
    assert "_" not in naming.INCOMPLETE_CANCELLED_OUTPUT_FOLDER_NAME
    assert naming.INCOMPLETE_CANCELLED_OUTPUT_FOLDER_NAME == "Incomplete Cancelled Output"
