"""GUI-side state models.

Nothing here touches Qt. This module holds plain data describing what
the user has selected and what the app is currently doing, so widgets
and the worker layer can be tested without a running event loop.
"""

from __future__ import annotations

import dataclasses
import enum
import os
import shutil
from pathlib import Path

from .. import archives, naming


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


def stage_dropped_files(paths: list[Path]) -> Path:
    """Bundles several loose dropped files into one new folder so they
    can be processed as a single input, exactly like a real folder --
    eliminating the "make a folder first" step for the common case of
    a handful of documents for one loan with no shared folder yet.

    The folder is created next to the first dropped file, named
    "Dropped Files" (versioned on collision, same convention as a
    package's own output folder). Files are hardlinked in when
    possible -- instant, no extra disk space -- and copied only when
    that's not possible (e.g. sources on different drives); either way
    the pipeline only ever reads input files, never modifies them in
    place, so the originals are untouched. Original filenames are kept
    (they matter for document-type detection); a name collision is
    disambiguated with a " (2)", " (3)", ... suffix rather than
    overwriting.
    """

    staging_dir = naming.resolve_versioned_output_dir(paths[0].parent, "Dropped Files")
    staging_dir.mkdir(parents=True)

    used_names: set[str] = set()
    for source in paths:
        dest_name = _unique_filename(source.name, used_names)
        used_names.add(dest_name)
        dest = staging_dir / dest_name
        try:
            os.link(source, dest)
        except OSError:
            shutil.copy2(source, dest)

    return staging_dir


def _unique_filename(name: str, used: set[str]) -> str:
    if name not in used:
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 2
    while True:
        candidate = f"{stem} ({counter}){suffix}"
        if candidate not in used:
            return candidate
        counter += 1


@dataclasses.dataclass
class AdvancedSettingsValues:
    max_pages_per_part: int
    max_size_mb_per_part: float
    enable_content_aware_dedup: bool = True
