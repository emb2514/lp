"""Pipeline-level tests for MILESTONE 1's output folder/file structure:
the main output folder is named from the borrower identity (with
overwrite-safe versioning), only "Final" and "Reports" are always
created (no separate OG or Logs folder -- OG lives inside Final, and
run.log lives inside Reports), and "Unconverted Files" is created only
when something actually needs to go there.
"""

from __future__ import annotations

from lender_package_builder import naming
from lender_package_builder.models import PackageIdentity


def _identity(**kwargs) -> PackageIdentity:
    return PackageIdentity(**kwargs)


# TEST 1 - the main output folder is named from the identity, not the
# input filename, when an identity is provided.
def test_output_dir_uses_identity_naming_when_provided(tmp_path, run_build):
    from fixtures.builders import make_pdf

    input_path = tmp_path / "some_random_upload_name.pdf"
    make_pdf(input_path, pages=1, text_prefix="Doc")
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785")

    run = run_build(input_path, identity=identity)

    assert run.output_path.name == "True, Michael, 6192278785"
    assert run.output_path.parent == tmp_path


# TEST 2 - overwrite protection: a second run with the same identity and
# input location versions the folder rather than colliding/overwriting.
def test_output_dir_versions_on_repeated_identity(tmp_path, run_build):
    from fixtures.builders import make_pdf

    input_path = tmp_path / "upload.pdf"
    make_pdf(input_path, pages=1, text_prefix="Doc")
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785")

    run1 = run_build(input_path, identity=identity)
    run2 = run_build(input_path, identity=identity)

    assert run1.output_path != run2.output_path
    assert run1.output_path.name == "True, Michael, 6192278785"
    assert run2.output_path.name == "True, Michael, 6192278785, v2"
    # Neither run's output was overwritten -- both still exist with their
    # own Final package.
    assert (run1.output_path / "Final").exists()
    assert (run2.output_path / "Final").exists()


# TEST 3 - Final and Original Lender Package files both land directly
# inside "Final"; there is no separate top-level OG folder.
def test_final_folder_contains_both_packages_no_separate_og_folder(tmp_path, run_build):
    from fixtures.builders import make_pdf

    input_path = tmp_path / "input"
    input_path.mkdir()
    make_pdf(input_path / "doc.pdf", pages=1, text_prefix="Doc")
    identity = _identity(last_name="True", first_name="Michael")

    run = run_build(input_path, identity=identity)

    final_dir = run.output_path / "Final"
    assert final_dir.exists()
    assert not (run.output_path / "OG").exists()

    names = {p.name for p in final_dir.glob("*.pdf")}
    assert "True, Michael, Lender Package.pdf" in names
    assert "True, Michael, Original Lender Package.pdf" in names
    for part in run.final_parts:
        assert part.file_path.parent == final_dir
    for part in run.og_parts:
        assert part.file_path.parent == final_dir


# TEST 4 - there is no separate top-level Logs folder; run.log lives
# inside Reports instead.
def test_logs_consolidated_into_reports(tmp_path, run_build):
    from fixtures.builders import make_pdf

    input_path = tmp_path / "input"
    input_path.mkdir()
    make_pdf(input_path / "doc.pdf", pages=1, text_prefix="Doc")

    run = run_build(input_path, identity=_identity(last_name="True"))

    assert not (run.output_path / "Logs").exists()
    assert (run.output_path / "Reports" / "run.log").exists()


# TEST 5 - "Unconverted Files" is never created when nothing failed to
# convert (no empty folder shipped).
def test_empty_unconverted_files_folder_not_created(tmp_path, run_build):
    from fixtures.builders import make_pdf

    input_path = tmp_path / "input"
    input_path.mkdir()
    make_pdf(input_path / "doc.pdf", pages=1, text_prefix="Doc")

    run = run_build(input_path, identity=_identity(last_name="True"))

    assert run.success is True
    assert not (run.output_path / naming.UNCONVERTED_FILES_FOLDER_NAME).exists()


# TEST 6 - "Unconverted Files" (space, not underscore) is created, and
# populated, only when something actually could not be converted.
def test_unconverted_files_folder_created_only_when_needed(tmp_path, run_build):
    input_path = tmp_path / "input"
    input_path.mkdir()
    (input_path / "weird_file.xyz").write_bytes(b"some binary blob that is not a supported type")

    run = run_build(input_path, keep_temp=True, identity=_identity(last_name="True"))

    unconverted_dir = run.output_path / naming.UNCONVERTED_FILES_FOLDER_NAME
    assert unconverted_dir.exists()
    assert any(unconverted_dir.iterdir())
    assert not (run.output_path / "Unconverted_Files").exists()


# TEST 7 - identity-derived filenames use commas and never underscores,
# proven directly against real files written by a real build.
def test_real_build_output_filenames_use_commas_not_underscores(tmp_path, run_build):
    from fixtures.builders import make_pdf

    input_path = tmp_path / "input"
    input_path.mkdir()
    make_pdf(input_path / "doc.pdf", pages=1, text_prefix="Doc")
    identity = _identity(last_name="True", first_name="Michael", loan_number="6192278785", is_adverse=True)

    run = run_build(input_path, identity=identity)

    assert run.output_path.name == "True, Michael, Adverse, 6192278785"
    for part in run.final_parts + run.og_parts:
        assert part.file_path.exists()
        assert "_" not in part.file_path.name
        assert "," in part.file_path.name


# TEST 8 - no identity provided at all (headless/library call) falls
# back to the original input-derived, timestamped naming rather than
# erroring -- this is a defense-in-depth default, not the primary
# user-facing (GUI) path, which always supplies an identity.
def test_no_identity_falls_back_to_timestamped_naming(tmp_path, run_build):
    from fixtures.builders import make_pdf

    input_path = tmp_path / "Loan_Package.pdf"
    make_pdf(input_path, pages=1, text_prefix="Doc")

    run = run_build(input_path)

    assert "_Lender_Package_Output_" in run.output_path.name
