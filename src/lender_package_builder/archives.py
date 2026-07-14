"""ZIP archive safety helpers: path sanitization, ignored-artifact
detection, and expansion-size estimation used for ZIP-bomb protection.

Nothing in this module writes files to disk; extraction itself happens
in `inventory.py`, which always writes extracted bytes to a fresh,
UUID-named directory using only the entry's basename (never the
archive-provided directory path). That design choice is what makes
path-traversal ("zip-slip") structurally impossible regardless of what
an archive entry's name claims to be -- the sanitization performed here
exists to additionally *detect and report* the attempt, per spec.
"""

from __future__ import annotations

import dataclasses
import io
import zipfile
from pathlib import PurePosixPath

_IGNORED_ARTIFACT_BASENAMES = {".ds_store", "thumbs.db", "desktop.ini"}
_MACOSX_DIR = "__macosx"

MAX_ZIP_NESTING_DEPTH = 25


def is_ignored_system_artifact(entry_name: str) -> tuple[bool, str | None]:
    """Return (True, reason) for known OS/archive metadata artifacts.

    These are recorded in the manifest as intentionally ignored, never
    silently dropped.
    """

    normalized = entry_name.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    if not parts:
        return False, None

    basename = parts[-1].lower()
    if basename in _IGNORED_ARTIFACT_BASENAMES:
        return True, f"Known system artifact ({parts[-1]})"

    if any(part.lower() == _MACOSX_DIR for part in parts[:-1]) or basename == _MACOSX_DIR:
        return True, "macOS archive metadata (__MACOSX)"

    return False, None


def sanitize_zip_entry_path(entry_name: str) -> tuple[str, bool]:
    """Return (safe_relative_path, was_unsafe).

    Detects absolute paths, drive letters, and ".." traversal segments.
    When unsafe, returns a sanitized display path built only from the
    entry's basename so callers never need the original attacker-
    controlled path for anything filesystem-related.
    """

    normalized = entry_name.replace("\\", "/")

    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return _blocked_display(normalized), True

    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return _blocked_display(normalized), True
        parts.append(part)

    if not parts:
        return _blocked_display(normalized), True

    return "/".join(parts), False


def _blocked_display(normalized: str) -> str:
    basename = PurePosixPath(normalized).name or "unnamed_entry"
    return f"BLOCKED_UNSAFE_PATH/{basename}"


@dataclasses.dataclass
class ExpansionEstimate:
    total_uncompressed_bytes: int = 0
    total_entries: int = 0
    truncated: bool = False


def estimate_expansion(
    input_path,
    max_depth: int = MAX_ZIP_NESTING_DEPTH,
) -> ExpansionEstimate:
    """Best-effort pre-flight estimate of expanded size and entry count.

    Reads ZIP central-directory metadata only; for nested ZIPs, the
    nested archive's compressed bytes are read once into memory to
    inspect its own central directory. This is cheap for ordinary lender
    packages. Extremely large nested archives may make this pre-flight
    pass itself slow -- that is a known Stage 1 limitation, documented
    in the README.
    """

    estimate = ExpansionEstimate()

    if input_path.is_dir():
        for child in input_path.rglob("*"):
            if child.is_file():
                estimate.total_entries += 1
                try:
                    estimate.total_uncompressed_bytes += child.stat().st_size
                except OSError:
                    pass
        return estimate

    if zipfile.is_zipfile(input_path):
        with input_path.open("rb") as fh:
            _estimate_zip_stream(fh, estimate, depth=0, max_depth=max_depth)
        return estimate

    try:
        estimate.total_entries = 1
        estimate.total_uncompressed_bytes = input_path.stat().st_size
    except OSError:
        pass
    return estimate


def _estimate_zip_stream(
    fileobj,
    estimate: ExpansionEstimate,
    depth: int,
    max_depth: int,
) -> None:
    if depth > max_depth:
        estimate.truncated = True
        return

    try:
        zf = zipfile.ZipFile(fileobj)
    except (zipfile.BadZipFile, OSError):
        return

    for info in zf.infolist():
        if info.is_dir():
            continue
        estimate.total_entries += 1
        estimate.total_uncompressed_bytes += info.file_size

        if info.filename.lower().endswith(".zip"):
            try:
                nested_bytes = zf.read(info)
            except (zipfile.BadZipFile, OSError, RuntimeError):
                continue
            _estimate_zip_stream(
                io.BytesIO(nested_bytes), estimate, depth=depth + 1, max_depth=max_depth
            )
