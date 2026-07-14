"""GUI-side state models.

Nothing here touches Qt. This module holds plain data describing what
the user has selected and what the app is currently doing, so widgets
and the worker layer can be tested without a running event loop.
"""

from __future__ import annotations

import dataclasses
import enum
from pathlib import Path

from .. import archives


class InputKind(str, enum.Enum):
    ZIP = "zip"
    FOLDER = "folder"
    FILE = "file"


class AppPhase(str, enum.Enum):
    IDLE = "idle"
    INPUT_SELECTED = "input_selected"
    PROCESSING = "processing"
    SUCCESS = "success"
    WARNING = "warning"
    FAILURE = "failure"


@dataclasses.dataclass
class InputSelection:
    """One validated top-level input the user has chosen."""

    path: Path
    kind: InputKind
    display_name: str
    original_size_bytes: int | None = None

    # Filled in later, asynchronously, once the background estimate
    # finishes -- may remain None if estimation hasn't completed yet.
    estimate: archives.ExpansionEstimate | None = None
    estimate_error: str | None = None

    @property
    def kind_label(self) -> str:
        return {
            InputKind.ZIP: "ZIP archive",
            InputKind.FOLDER: "Folder",
            InputKind.FILE: "Document",
        }[self.kind]


def classify_input(path: Path) -> InputSelection:
    """Build an `InputSelection` for a single top-level path.

    Accepts anything that exists -- including a file type Stage 1 does
    not know how to convert -- since Stage 1 preserves unsupported
    files as placeholders rather than rejecting them.
    """

    if path.is_dir():
        kind = InputKind.FOLDER
        size = None
    elif path.suffix.lower() == ".zip":
        kind = InputKind.ZIP
        size = _safe_size(path)
    else:
        kind = InputKind.FILE
        size = _safe_size(path)

    return InputSelection(path=path, kind=kind, display_name=path.name or str(path), original_size_bytes=size)


def _safe_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


@dataclasses.dataclass
class AdvancedSettingsValues:
    max_pages_per_part: int
    max_size_mb_per_part: float
