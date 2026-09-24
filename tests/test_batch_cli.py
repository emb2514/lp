"""Tests for the `batch` CLI subcommand (cli.py's build_arg_parser /
main / _run_batch_command) -- the command-line entry point for batch
mode (see batch.py for the underlying engine).
"""

from __future__ import annotations

from pathlib import Path

from fixtures.builders import make_pdf_with_pages

from lender_package_builder import cli


def _make_loan_folder(parent, name, content="Some real content"):
    folder = parent / name
    folder.mkdir(parents=True)
    make_pdf_with_pages(folder / "doc.pdf", [content])
    return folder


def test_batch_subcommand_is_registered():
    parser = cli.build_arg_parser()
    args = parser.parse_args(["batch", "/some/parent/folder"])
    assert args.command == "batch"
    assert args.parent_folder == "/some/parent/folder"


def test_batch_subcommand_accepts_the_same_kind_of_overrides_as_build():
    parser = cli.build_arg_parser()
    args = parser.parse_args(
        [
            "batch",
            "/some/parent",
            "--output",
            "/some/output",
            "--max-pages-per-part",
            "50",
            "--allow-large-input",
            "--disable-content-aware-dedup",
            "--quiet",
        ]
    )
    assert args.output == Path("/some/output")
    assert args.max_pages_per_part == 50
    assert args.allow_large_input is True
    assert args.disable_content_aware_dedup is True
    assert args.quiet is True


def test_main_dispatches_batch_command_and_builds_every_loan(tmp_path, capsys):
    parent = tmp_path / "parent"
    _make_loan_folder(parent, "Doe, John, 111111")
    _make_loan_folder(parent, "Smith, Jane, 222222")
    out_dir = tmp_path / "out"

    exit_code = cli.main(["batch", str(parent), "--output", str(out_dir), "--quiet"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "2/2 loan(s) succeeded" in captured.out
    assert (out_dir / "Doe, John, 111111").exists()
    assert (out_dir / "Smith, Jane, 222222").exists()


def test_main_batch_command_nonexistent_parent_folder_fails_cleanly(tmp_path, capsys):
    missing = tmp_path / "does_not_exist"
    exit_code = cli.main(["batch", str(missing), "--quiet"])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "FAILED" in captured.err


def test_main_batch_command_reports_per_loan_progress(tmp_path, capsys):
    parent = tmp_path / "parent"
    _make_loan_folder(parent, "Adams, Al, 1")
    out_dir = tmp_path / "out"

    exit_code = cli.main(["batch", str(parent), "--output", str(out_dir)])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "[1/1] Building: Adams, Al, 1" in captured.out
