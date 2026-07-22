"""Build history: a small, local, append-only log of past builds this
GUI has run, so the "History" screen can list them without re-scanning
the filesystem for output folders.

Pure Python, no Qt -- the GUI's History screen only calls into this
module and renders what it returns, matching the same GUI/engine
separation `compare_packages.py` and `naming.py` already establish.
Never touched by the CLI or by anything that decides Final-package
contents; a corrupt or missing history file only affects this list, so
every function here fails soft (never raises) rather than blocking a
build or crashing the GUI.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from . import runtime_paths
from .models import PackageIdentity

_MAX_ENTRIES = 500


@dataclasses.dataclass
class HistoryEntry:
    """One past build attempt, successful or not."""

    identity: PackageIdentity
    output_path: str
    status: str  # "Success", "Warning", "Failed", or "Cancelled"
    timestamp: str  # ISO 8601, local time
    document_count: int = 0

    def display_name(self) -> str:
        from . import naming

        parts = [p for p in (self.identity.last_name, self.identity.first_name) if naming.sanitize_component(p)]
        return ", ".join(parts) if parts else "(no name entered)"


def _entry_to_dict(entry: HistoryEntry) -> dict:
    return {
        "last_name": entry.identity.last_name,
        "first_name": entry.identity.first_name,
        "loan_number": entry.identity.loan_number,
        "is_adverse": entry.identity.is_adverse,
        "output_path": entry.output_path,
        "status": entry.status,
        "timestamp": entry.timestamp,
        "document_count": entry.document_count,
    }


def _entry_from_dict(data: dict) -> HistoryEntry | None:
    try:
        return HistoryEntry(
            identity=PackageIdentity(
                last_name=str(data.get("last_name", "")),
                first_name=str(data.get("first_name", "")),
                loan_number=str(data.get("loan_number", "")),
                is_adverse=bool(data.get("is_adverse", False)),
            ),
            output_path=str(data.get("output_path", "")),
            status=str(data.get("status", "")),
            timestamp=str(data.get("timestamp", "")),
            document_count=int(data.get("document_count", 0)),
        )
    except (TypeError, ValueError):
        return None


def load_history(path: Path | None = None) -> list[HistoryEntry]:
    """Newest first. Returns an empty list if the file is missing,
    unreadable, or corrupted -- history is a convenience, never a
    dependency for processing.
    """

    target = path if path is not None else runtime_paths.history_file_path()
    if not target.exists():
        return []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    entries = [e for e in (_entry_from_dict(item) for item in raw if isinstance(item, dict)) if e is not None]
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries


def append_history_entry(entry: HistoryEntry, path: Path | None = None) -> None:
    """Best-effort. A history-write failure (e.g. a locked or
    unwritable file) is logged-and-ignored by the caller, never allowed
    to affect the build it's recording.
    """

    target = path if path is not None else runtime_paths.history_file_path()
    existing = load_history(target)
    existing.insert(0, entry)
    del existing[_MAX_ENTRIES:]

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps([_entry_to_dict(e) for e in existing], indent=2), encoding="utf-8")
    tmp.replace(target)
