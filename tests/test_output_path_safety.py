"""Regression tests for a real user-reported crash: a downloaded file
with a very long, URL-derived filename (e.g. from a browser saving a
document served from an API endpoint with a long query string) caused
`FileNotFoundError: [WinError 3]` on `Path.mkdir()` when the output
directory name derived from it exceeded Windows' classic 260-character
MAX_PATH limit -- even though `packaging/app.manifest` already declares
`longPathAware="true"`, which real-world evidence (this exact crash)
proved is not sufficient on its own.

These tests run on Linux (no MAX_PATH limit here), so they cannot
reproduce the actual OS-level failure directly. Instead they pin down
the actual fix -- every filesystem name this app derives from an
arbitrary input filename is proactively kept short -- so a regression
here is caught regardless of platform.
"""

from __future__ import annotations

from pathlib import Path

from lender_package_builder.cli import (
    _MAX_SAFE_PATH_LENGTH,
    _MIN_DERIVED_NAME_LENGTH,
    _compute_output_dir,
    _copy_extra_preserved_file,
    _shorten_for_filesystem,
    _unique_destination,
)

# The exact shape of the real user-reported filename (a browser-saved
# download from an API endpoint URL, sanitized into a filename) --
# roughly 245 characters for the name alone, before any extension.
_REAL_WORLD_LONG_NAME = (
    "_https___api2.fhmc.cloud_edm-download-service_api_v1_document_download_docurl_"
    "correlationid=2ea34a77-b96a-44ef-915e-4b63d5422f2f&params=aqicahgrj0x7gcxzhiwze4"
    "osp_ugu_aucso64czrwvl3pnrymgfqngwuy5l4bdhqa9rznca"
)


# TEST 1 - the exact reported scenario: a very long downloaded-file name
# no longer produces an output directory path anywhere near Windows'
# 260-character MAX_PATH limit.
def test_compute_output_dir_shortens_extremely_long_downloaded_filename(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    input_path = downloads / f"{_REAL_WORLD_LONG_NAME}.pdf"
    input_path.write_bytes(b"%PDF-1.4 fake")

    result = _compute_output_dir(input_path, None)

    assert len(str(result)) <= _MAX_SAFE_PATH_LENGTH
    # Comfortable headroom below the real 260-char Windows limit for
    # subfolders/files created inside the output directory afterward
    # (e.g. "\Reports\Uncertain_Match_Review_Log.txt").
    assert len(str(result)) <= 210
    assert result.parent == downloads
    assert "_Lender_Package_Output_" in result.name


# TEST 2 - a normal, reasonably-named input is completely unaffected --
# the fix must never alter the common case.
def test_compute_output_dir_leaves_normal_filenames_unchanged(tmp_path):
    input_path = tmp_path / "Loan_Package.zip"
    input_path.write_bytes(b"PK\x03\x04fake zip")

    result = _compute_output_dir(input_path, None)

    assert result.name.startswith("Loan_Package_Lender_Package_Output_")
    assert ".zip" not in result.name  # the extension is stripped via .stem, as before


# TEST 3 - a folder input (not a file) is also unaffected in the normal
# case, and shortened the same way in the pathological case.
def test_compute_output_dir_handles_folder_input(tmp_path):
    folder = tmp_path / "MyLoanFolder"
    folder.mkdir()
    result = _compute_output_dir(folder, None)
    assert result.name.startswith("MyLoanFolder_Lender_Package_Output_")

    long_folder = tmp_path / _REAL_WORLD_LONG_NAME
    long_folder.mkdir()
    long_result = _compute_output_dir(long_folder, None)
    assert len(str(long_result)) <= 210


# TEST 4 - an explicit output_dir override is passed through completely
# untouched (the shortening logic only ever applies to the auto-derived
# default, never to a path the caller explicitly chose).
def test_compute_output_dir_explicit_override_is_never_shortened(tmp_path):
    explicit = tmp_path / (_REAL_WORLD_LONG_NAME + "_my_chosen_output_folder")
    result = _compute_output_dir(tmp_path / "input.zip", explicit)
    assert result == explicit.expanduser().resolve()


# TEST 5 - _shorten_for_filesystem: the core truncation helper directly
def test_shorten_for_filesystem_preserves_short_extension():
    long_filename = "a" * 300 + ".pdf"
    result = _shorten_for_filesystem(long_filename, reserved_length=50)
    assert result.endswith(".pdf")
    assert len(result) <= 150  # 200 - 50 reserved


def test_shorten_for_filesystem_leaves_short_names_unchanged():
    assert _shorten_for_filesystem("short_name.txt", reserved_length=50) == "short_name.txt"


def test_shorten_for_filesystem_never_truncates_below_minimum():
    result = _shorten_for_filesystem("x" * 500, reserved_length=1000)
    assert len(result) >= _MIN_DERIVED_NAME_LENGTH


def test_shorten_for_filesystem_does_not_treat_arbitrary_dots_as_extensions():
    # A long name with an internal "sentence-like" dot but no real
    # trailing extension should not have an oversized "extension"
    # preserved -- only short, real-looking extensions are special-cased.
    name = "a" * 200 + ".verylongwordthatisnotarealextension"
    result = _shorten_for_filesystem(name, reserved_length=50)
    assert len(result) <= 150


# TEST 6 - _unique_destination (used to preserve unconverted originals)
# shortens every path segment, including the filename, and preserves
# extensions.
def test_unique_destination_shortens_long_relative_path(tmp_path):
    unconverted_dir = tmp_path / "Unconverted Files"
    unconverted_dir.mkdir()

    long_relpath = _REAL_WORLD_LONG_NAME + ".docx"
    dest = _unique_destination(unconverted_dir, long_relpath, "DOC-000042")

    assert len(str(dest)) <= 210
    assert dest.suffix == ".docx"
    assert dest.parent == unconverted_dir


def test_unique_destination_leaves_normal_relative_paths_unchanged(tmp_path):
    unconverted_dir = tmp_path / "Unconverted Files"
    unconverted_dir.mkdir()
    dest = _unique_destination(unconverted_dir, "subfolder/normal_file.txt", "DOC-000001")
    assert dest == unconverted_dir / "subfolder" / "normal_file.txt"


# TEST 7 - _copy_extra_preserved_file (used for email attachments that
# fail to convert) shortens an overly long relative name too.
def test_copy_extra_preserved_file_shortens_long_name(tmp_path):
    unconverted_dir = tmp_path / "Unconverted Files"
    unconverted_dir.mkdir()
    source = tmp_path / "source_attachment.pdf"
    source.write_bytes(b"%PDF-1.4 fake attachment")

    long_name = _REAL_WORLD_LONG_NAME + ".pdf"
    _copy_extra_preserved_file(long_name, source, unconverted_dir)

    written = list(unconverted_dir.iterdir())
    assert len(written) == 1
    assert len(str(written[0])) <= 210
    assert written[0].suffix == ".pdf"
    assert written[0].read_bytes() == source.read_bytes()


# TEST 8 - full pipeline: a real build where the TOP-LEVEL input itself
# is a single file with a pathologically long name (exactly the reported
# scenario -- a file dragged directly onto the app, not a folder/zip
# containing it) succeeds end to end through the real build_package()
# entry point, not just the isolated helper functions.
def test_full_pipeline_succeeds_with_extremely_long_input_filename(tmp_path, run_build):
    from fixtures.builders import make_pdf

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    long_input = downloads / f"{_REAL_WORLD_LONG_NAME}.pdf"
    make_pdf(long_input, pages=1, text_prefix="Downloaded Document")

    run = run_build(long_input)

    assert run.success is True
    assert len(str(run.output_path)) <= 210
    assert run.output_path.exists()
    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"
