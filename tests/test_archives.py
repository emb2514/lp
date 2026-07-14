from __future__ import annotations

from lender_package_builder import archives


def test_sanitize_normal_path_is_safe():
    safe, unsafe = archives.sanitize_zip_entry_path("folder/file.pdf")
    assert safe == "folder/file.pdf"
    assert unsafe is False


def test_sanitize_detects_dotdot_traversal():
    safe, unsafe = archives.sanitize_zip_entry_path("../../etc/passwd")
    assert unsafe is True
    assert safe.startswith("BLOCKED_UNSAFE_PATH/")
    assert safe.endswith("passwd")


def test_sanitize_detects_absolute_path():
    safe, unsafe = archives.sanitize_zip_entry_path("/etc/passwd")
    assert unsafe is True


def test_sanitize_detects_windows_drive_letter():
    safe, unsafe = archives.sanitize_zip_entry_path("C:\\Windows\\evil.txt")
    assert unsafe is True


def test_is_ignored_system_artifact_matches_known_names():
    assert archives.is_ignored_system_artifact(".DS_Store")[0] is True
    assert archives.is_ignored_system_artifact("Thumbs.db")[0] is True
    assert archives.is_ignored_system_artifact("desktop.ini")[0] is True
    assert archives.is_ignored_system_artifact("__MACOSX/._file.txt")[0] is True
    assert archives.is_ignored_system_artifact("real_document.pdf")[0] is False


def test_estimate_expansion_folder(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.txt").write_text("world!!")
    estimate = archives.estimate_expansion(tmp_path)
    assert estimate.total_entries == 2
    assert estimate.total_uncompressed_bytes == len("hello") + len("world!!")


def test_estimate_expansion_zip_counts_nested_archives(tmp_path):
    import zipfile

    inner = tmp_path / "inner.zip"
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("nested_file.txt", "nested content")
    inner_bytes = inner.read_bytes()

    outer = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer, "w") as zf:
        zf.writestr("top.txt", "top level content")
        zf.writestr("inner.zip", inner_bytes)

    estimate = archives.estimate_expansion(outer)
    # top.txt + the inner.zip container entry itself (conservative) + nested_file.txt
    assert estimate.total_entries == 3
    assert estimate.total_uncompressed_bytes == (
        len("top level content") + len(inner_bytes) + len("nested content")
    )
