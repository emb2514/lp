"""Tests for history.py -- the local build-history log behind the GUI's
"History" screen. Pure Python, no Qt.
"""

from __future__ import annotations

from lender_package_builder import history
from lender_package_builder.models import PackageIdentity


def _entry(**kwargs) -> history.HistoryEntry:
    defaults = dict(
        identity=PackageIdentity(last_name="True", first_name="Michael", loan_number="6192278785"),
        output_path="/tmp/output",
        status="Success",
        timestamp="2026-07-22T10:00:00",
        document_count=7,
    )
    defaults.update(kwargs)
    return history.HistoryEntry(**defaults)


# TEST 1 - a missing history file is an empty list, not an error
def test_load_history_missing_file_returns_empty_list(tmp_path):
    assert history.load_history(tmp_path / "does_not_exist.json") == []


# TEST 2 - append then load round-trips every field
def test_append_and_load_round_trips_entry(tmp_path):
    path = tmp_path / "history.json"
    history.append_history_entry(_entry(), path)

    loaded = history.load_history(path)
    assert len(loaded) == 1
    entry = loaded[0]
    assert entry.identity == PackageIdentity(last_name="True", first_name="Michael", loan_number="6192278785")
    assert entry.output_path == "/tmp/output"
    assert entry.status == "Success"
    assert entry.timestamp == "2026-07-22T10:00:00"
    assert entry.document_count == 7


# TEST 3 - newest entry (by timestamp) sorts first regardless of append order
def test_load_history_sorts_newest_first(tmp_path):
    path = tmp_path / "history.json"
    history.append_history_entry(_entry(timestamp="2026-07-22T10:00:00", status="Success"), path)
    history.append_history_entry(_entry(timestamp="2026-07-22T12:00:00", status="Cancelled"), path)
    history.append_history_entry(_entry(timestamp="2026-07-22T11:00:00", status="Failed"), path)

    loaded = history.load_history(path)
    assert [e.status for e in loaded] == ["Cancelled", "Failed", "Success"]


# TEST 4 - a corrupted (not valid JSON) history file fails soft, never raises
def test_load_history_corrupted_file_returns_empty_list(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("not valid json {{{", encoding="utf-8")

    assert history.load_history(path) == []


# TEST 5 - a history file that is valid JSON but not the expected shape
# (e.g. a single object instead of a list) also fails soft
def test_load_history_wrong_shape_returns_empty_list(tmp_path):
    path = tmp_path / "history.json"
    path.write_text('{"not": "a list"}', encoding="utf-8")

    assert history.load_history(path) == []


# TEST 6 - a corrupted entry inside an otherwise-valid list is skipped,
# not allowed to blank out every other real entry
def test_load_history_skips_individually_corrupt_entries(tmp_path):
    import json

    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(
            [
                {"last_name": "True", "output_path": "/tmp/a", "status": "Success", "timestamp": "2026-07-22T10:00:00"},
                "not a dict at all",
            ]
        ),
        encoding="utf-8",
    )

    loaded = history.load_history(path)
    assert len(loaded) == 1
    assert loaded[0].identity.last_name == "True"


# TEST 7 - the history file itself is never modified in place -- writes
# go through a temp file first, so a crash mid-write can never corrupt
# the previously-good history
def test_append_history_entry_writes_atomically(tmp_path):
    path = tmp_path / "history.json"
    history.append_history_entry(_entry(), path)

    assert not path.with_suffix(".json.tmp").exists()
    assert path.exists()


# TEST 8 - display_name() joins last/first name with a comma, matching
# naming.py's own convention, and has a clear fallback when both are blank
def test_display_name_matches_naming_convention_and_has_fallback():
    entry = _entry(identity=PackageIdentity(last_name="True", first_name="Michael"))
    assert entry.display_name() == "True, Michael"

    blank_entry = _entry(identity=PackageIdentity())
    assert blank_entry.display_name() == "(no name entered)"


# TEST 9 - very old entries beyond the retention cap are dropped, newest
# entries are always kept
def test_append_history_entry_caps_total_entries(tmp_path):
    path = tmp_path / "history.json"
    for i in range(history._MAX_ENTRIES + 5):
        history.append_history_entry(_entry(timestamp=f"2026-07-22T{i:05d}"), path)

    loaded = history.load_history(path)
    assert len(loaded) == history._MAX_ENTRIES
