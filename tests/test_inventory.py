from __future__ import annotations

from pathlib import Path

from fixtures.builders import make_pdf, make_txt, make_zip

from lender_package_builder.inventory import InventoryBuilder, natural_sort_key
from lender_package_builder.workspace import Workspace


def _build(input_path: Path, config, allow_large_input=False):
    # Note: the workspace is intentionally NOT cleaned up here, since several
    # tests need to inspect `extracted_path` on the returned occurrences
    # after this call returns. Each test uses its own fresh workspace under
    # the system temp directory, and pytest/CI containers are ephemeral.
    ws = Workspace()
    builder = InventoryBuilder(config, ws, allow_large_input=allow_large_input)
    occurrences = builder.build(input_path)
    return occurrences, builder


# TEST 17 - NATURAL FOLDER SORT
def test_natural_sort_key_orders_file2_before_file10():
    names = ["file10.pdf", "file2.pdf", "file1.pdf"]
    ordered = sorted(names, key=natural_sort_key)
    assert ordered == ["file1.pdf", "file2.pdf", "file10.pdf"]


def test_folder_traversal_uses_natural_sort(tmp_path, config):
    folder = tmp_path / "input"
    for name in ["file10.pdf", "file2.pdf", "file1.pdf"]:
        make_pdf(folder / name, pages=1)

    occurrences, _ = _build(folder, config)
    names_in_order = [o.original_filename for o in occurrences]
    assert names_in_order == ["file1.pdf", "file2.pdf", "file10.pdf"]


# TEST 14 - ZIP ENTRY ORDER
def test_zip_entries_preserve_central_directory_order(tmp_path, config):
    zip_path = tmp_path / "input.zip"
    make_zip(
        zip_path,
        [
            ("z_first.txt", b"first"),
            ("a_second.txt", b"second"),
            ("m_third.txt", b"third"),
        ],
    )

    occurrences, _ = _build(zip_path, config)
    names_in_order = [o.original_filename for o in occurrences]
    assert names_in_order == ["z_first.txt", "a_second.txt", "m_third.txt"]


# TEST 15 - NESTED ZIP ORDER
def test_nested_zip_processed_at_its_position(tmp_path, config):
    inner_zip_path = tmp_path / "inner.zip"
    make_zip(
        inner_zip_path,
        [
            ("inner_a.txt", b"inner a"),
            ("inner_b.txt", b"inner b"),
        ],
    )
    inner_bytes = inner_zip_path.read_bytes()

    outer_zip_path = tmp_path / "outer.zip"
    make_zip(
        outer_zip_path,
        [
            ("before.txt", b"before"),
            ("nested.zip", inner_bytes),
            ("after.txt", b"after"),
        ],
    )

    occurrences, _ = _build(outer_zip_path, config)
    names_in_order = [o.original_filename for o in occurrences]
    assert names_in_order == ["before.txt", "inner_a.txt", "inner_b.txt", "after.txt"]

    for occ in occurrences:
        assert occ.document_id
    assert len({o.document_id for o in occurrences}) == len(occurrences)


# TEST 16 - ZIP PATH-TRAVERSAL PROTECTION
def test_zip_slip_paths_are_blocked_and_reported(tmp_path, config):
    zip_path = tmp_path / "malicious.zip"
    make_zip(
        zip_path,
        [
            ("normal.txt", b"normal content"),
            ("../../etc/evil.txt", b"malicious content"),
            ("..\\..\\windows_evil.txt", b"malicious content 2"),
        ],
    )

    occurrences, builder = _build(zip_path, config)

    assert len(occurrences) == 3
    assert len(builder.unsafe_incidents) == 2

    workspace_root_str = None
    for occ in occurrences:
        if occ.extracted_path is not None:
            assert occ.extracted_path.exists()
            workspace_root_str = str(occ.extracted_path.parents[2])

    # None of the extracted files were written outside a workspace-managed directory.
    for occ in occurrences:
        if occ.extracted_path is not None:
            assert "extract" in str(occ.extracted_path)

    unsafe_occurrences = [o for o in occurrences if "BLOCKED_UNSAFE_PATH" in o.original_relative_path]
    assert len(unsafe_occurrences) == 2
    for occ in unsafe_occurrences:
        assert any("unsafe" in w.lower() for w in occ.conversion_warnings)


# Ignored system artifacts must be recorded, never silently dropped.
def test_ignored_system_artifacts_are_recorded_not_dropped(tmp_path, config):
    zip_path = tmp_path / "input.zip"
    make_zip(
        zip_path,
        [
            ("real.txt", b"real content"),
            (".DS_Store", b"macos junk"),
            ("Thumbs.db", b"windows thumbnail cache"),
            ("__MACOSX/._real.txt", b"macos resource fork"),
        ],
    )

    occurrences, _ = _build(zip_path, config)
    assert len(occurrences) == 4
    ignored = [o for o in occurrences if o.is_ignored_artifact]
    assert len(ignored) == 3
    assert all(o.ignored_artifact_reason for o in ignored)


def test_duplicate_filenames_in_zip_do_not_overwrite(tmp_path, config):
    zip_path = tmp_path / "input.zip"
    make_zip(
        zip_path,
        [
            ("dup.txt", b"content A"),
            ("dup.txt", b"content B"),
        ],
    )

    occurrences, _ = _build(zip_path, config)
    assert len(occurrences) == 2
    assert occurrences[0].extracted_path.read_bytes() == b"content A"
    assert occurrences[1].extracted_path.read_bytes() == b"content B"
    assert occurrences[0].document_id != occurrences[1].document_id
