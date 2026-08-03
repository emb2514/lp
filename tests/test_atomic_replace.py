"""Tests for atomic_replace.replace_with_retry -- the fix for a real
Windows crash: a merged PDF part written to a user's Downloads folder
hit `PermissionError: [WinError 32] The process cannot access the file
because it is being used by another process` during the rename to its
final filename, almost certainly antivirus/cloud-sync/indexing briefly
holding the freshly-written file open.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lender_package_builder.atomic_replace import replace_with_retry


def _make_files(tmp_path: Path) -> tuple[Path, Path]:
    src = tmp_path / "source.txt"
    dest = tmp_path / "dest.txt"
    src.write_text("content")
    return src, dest


# TEST 1 - the common case: no lock, succeeds on the first attempt
def test_replace_succeeds_immediately_when_unlocked(tmp_path):
    src, dest = _make_files(tmp_path)
    replace_with_retry(src, dest)
    assert dest.read_text() == "content"
    assert not src.exists()


# TEST 2 - a transient lock (a few PermissionErrors) recovers once the
# lock clears, exactly the real-world antivirus/cloud-sync/indexing race
def test_replace_recovers_from_a_transient_permission_error(tmp_path, monkeypatch):
    src, dest = _make_files(tmp_path)

    real_replace = Path.replace
    calls = {"count": 0}

    def _flaky_replace(self, target):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError(32, "The process cannot access the file because it is being used by another process")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", _flaky_replace)
    monkeypatch.setattr("lender_package_builder.atomic_replace.time.sleep", lambda _seconds: None)

    replace_with_retry(src, dest, max_attempts=5, delay_seconds=0.01)

    assert calls["count"] == 3
    assert dest.read_text() == "content"


# TEST 3 - a permanent lock (never clears) still raises after exhausting
# every attempt -- this must never silently drop the file
def test_replace_reraises_after_exhausting_all_attempts(tmp_path, monkeypatch):
    src, dest = _make_files(tmp_path)

    def _always_locked(self, target):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(Path, "replace", _always_locked)
    monkeypatch.setattr("lender_package_builder.atomic_replace.time.sleep", lambda _seconds: None)

    with pytest.raises(PermissionError):
        replace_with_retry(src, dest, max_attempts=4, delay_seconds=0.01)

    # The source file must still exist -- a failed replace must never
    # leave the caller thinking a file vanished.
    assert src.exists()


# TEST 4 - an unrelated OSError (not a sharing-violation-style
# PermissionError) is never retried or masked
def test_replace_does_not_retry_unrelated_errors(tmp_path, monkeypatch):
    src, dest = _make_files(tmp_path)
    calls = {"count": 0}

    def _missing(self, target):
        calls["count"] += 1
        raise FileNotFoundError("source vanished")

    monkeypatch.setattr(Path, "replace", _missing)

    with pytest.raises(FileNotFoundError):
        replace_with_retry(src, dest, max_attempts=5, delay_seconds=0.01)

    assert calls["count"] == 1
