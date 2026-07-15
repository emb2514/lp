"""Source inventory discovery.

Walks the input (a single file, a folder, or a ZIP -- possibly with
ZIPs nested inside ZIPs) and produces an ordered list of
`SourceOccurrence` objects. Order is everything here: folders use a
deterministic natural sort, and ZIPs are walked in central-directory
order, recursing into nested ZIPs at the exact position they appear.

No conversion or hashing decisions happen here beyond computing the
original SHA-256 (which must happen on the untouched original bytes,
so it belongs at discovery time, before anything else touches the
file).
"""

from __future__ import annotations

import logging
import re
import shutil
import zipfile
from pathlib import Path

from . import archives, pdf_portfolio
from .config import AppConfig
from .exceptions import ArchiveTooLargeError, InvalidInputError
from .hashing import sha256_of_file
from .models import ProcessingStatus, SourceOccurrence
from .workspace import Workspace

logger = logging.getLogger(__name__)

_NATURAL_SORT_RE = re.compile(r"(\d+)")


def natural_sort_key(value: str) -> tuple:
    """Case-insensitive natural sort key: 'file2' sorts before 'file10'."""

    normalized = value.replace("\\", "/")
    parts = _NATURAL_SORT_RE.split(normalized)
    return tuple(int(p) if p.isdigit() else p.lower() for p in parts)


class InventoryBuilder:
    """Builds the ordered list of `SourceOccurrence` for one input."""

    def __init__(self, config: AppConfig, workspace: Workspace, allow_large_input: bool = False):
        self.config = config
        self.workspace = workspace
        self.allow_large_input = allow_large_input
        self._next_index = 1
        self.occurrences: list[SourceOccurrence] = []
        self.unsafe_incidents: list[str] = []
        self._running_bytes = 0
        self._running_entries = 0

    # -- public API ---------------------------------------------------

    def build(self, input_path: Path) -> list[SourceOccurrence]:
        if input_path.is_dir():
            self._process_folder(input_path)
        elif input_path.is_file() and zipfile.is_zipfile(input_path):
            self._process_zip_path(input_path, chain=[input_path.name], depth=0, top_level=True)
        elif input_path.is_file():
            self._process_single_file(
                source_path=input_path,
                basename=input_path.name,
                relative_path=input_path.name,
                chain_display=input_path.name,
            )
        else:
            raise InvalidInputError(
                f"Input path does not exist or is not a file/folder: {input_path}"
            )
        # RC2: PDF Portfolio expansion is a discrete post-pass, not
        # threaded into the traversal above -- Portfolio detection needs
        # full PDF structural parsing, which the traversal above never
        # otherwise does (it only hashes raw bytes). Renumbers
        # traversal_index over the final spliced list; see
        # pdf_portfolio.expand_portfolios()'s own docstring.
        self.occurrences = pdf_portfolio.expand_portfolios(self.occurrences, self.workspace)
        return self.occurrences

    # -- folder traversal ----------------------------------------------

    def _process_folder(self, root: Path) -> None:
        entries: list[tuple[str, Path]] = []
        for child in root.rglob("*"):
            if child.is_file():
                rel = child.relative_to(root).as_posix()
                entries.append((rel, child))

        entries.sort(key=lambda item: natural_sort_key(item[0]))

        for rel_path, abs_path in entries:
            ignored, reason = archives.is_ignored_system_artifact(rel_path)
            if ignored:
                self._record_ignored(rel_path, rel_path, reason, size_hint=_safe_size(abs_path))
                continue

            if abs_path.suffix.lower() == ".zip" and zipfile.is_zipfile(abs_path):
                self._process_zip_path(abs_path, chain=[rel_path], depth=0, top_level=False)
                continue

            self._process_single_file(
                source_path=abs_path,
                basename=abs_path.name,
                relative_path=rel_path,
                chain_display=rel_path,
            )

    # -- zip traversal ---------------------------------------------------

    def _process_zip_path(
        self, zip_path: Path, chain: list[str], depth: int, top_level: bool
    ) -> None:
        if depth > archives.MAX_ZIP_NESTING_DEPTH:
            self._record_single_placeholder_source(
                source_path=zip_path,
                basename=zip_path.name,
                relative_path="/".join(chain),
                chain_display=" -> ".join(chain),
                reason=(
                    f"Maximum nested ZIP depth ({archives.MAX_ZIP_NESTING_DEPTH}) exceeded; "
                    "this archive was not opened."
                ),
            )
            return

        try:
            zf = zipfile.ZipFile(zip_path)
        except (zipfile.BadZipFile, OSError) as exc:
            if top_level:
                raise InvalidInputError(f"Input ZIP file is corrupt or unreadable: {exc}") from exc
            self._record_single_placeholder_source(
                source_path=zip_path,
                basename=zip_path.name,
                relative_path="/".join(chain),
                chain_display=" -> ".join(chain),
                reason=f"Nested ZIP archive is corrupt or unreadable: {exc}",
            )
            return

        with zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue

                ignored, ignore_reason = archives.is_ignored_system_artifact(info.filename)
                display_path = "/".join(chain[1:] + [info.filename.replace("\\", "/")])
                chain_display = " -> ".join(chain + [info.filename])

                if ignored:
                    self._record_ignored(
                        display_path or info.filename,
                        chain_display,
                        ignore_reason,
                        size_hint=info.file_size,
                    )
                    continue

                safe_rel, unsafe = archives.sanitize_zip_entry_path(info.filename)
                if unsafe:
                    incident = (
                        f"Blocked unsafe archive path in {' -> '.join(chain)}: "
                        f"{info.filename!r}"
                    )
                    self.unsafe_incidents.append(incident)
                    logger.warning(incident)

                basename = safe_rel.rsplit("/", 1)[-1]
                dest = self.workspace.new_extract_path(basename)

                try:
                    with zf.open(info) as src, dest.open("wb") as out:
                        shutil.copyfileobj(src, out)
                except (OSError, zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
                    self._record_unextractable(
                        basename,
                        "/".join(chain[1:] + [safe_rel]) if len(chain) > 1 else safe_rel,
                        " -> ".join(chain + [info.filename]),
                        str(exc),
                    )
                    continue

                self._enforce_running_limits(dest.stat().st_size)

                relative_path = (
                    "/".join(chain[1:] + [safe_rel]) if len(chain) > 1 else safe_rel
                )
                nested_chain = chain + [info.filename]

                if basename.lower().endswith(".zip") and zipfile.is_zipfile(dest):
                    self._process_zip_path(dest, chain=nested_chain, depth=depth + 1, top_level=False)
                else:
                    self._finalize_occurrence(
                        source_path=dest,
                        basename=basename,
                        relative_path=relative_path,
                        chain_display=" -> ".join(nested_chain),
                        unsafe_path=unsafe,
                        raw_relative_path=display_path,
                    )

    # -- shared record helpers ------------------------------------------

    def _process_single_file(
        self, source_path: Path, basename: str, relative_path: str, chain_display: str
    ) -> None:
        try:
            size = source_path.stat().st_size
        except OSError:
            size = 0
        self._enforce_running_limits(size)
        self._finalize_occurrence(
            source_path=source_path,
            basename=basename,
            relative_path=relative_path,
            chain_display=chain_display,
            unsafe_path=False,
            raw_relative_path=relative_path,
        )

    def _finalize_occurrence(
        self,
        source_path: Path,
        basename: str,
        relative_path: str,
        chain_display: str,
        unsafe_path: bool,
        raw_relative_path: str,
    ) -> None:
        doc_id = f"DOC-{self._next_index:06d}"
        index = self._next_index
        self._next_index += 1

        try:
            size = source_path.stat().st_size
        except OSError:
            size = 0

        sha256: str | None
        try:
            sha256 = sha256_of_file(source_path)
        except OSError as exc:
            sha256 = None
            logger.warning("Could not hash %s: %s", relative_path, exc)

        occurrence = SourceOccurrence(
            document_id=doc_id,
            traversal_index=index,
            original_filename=basename,
            original_relative_path=relative_path,
            original_extension=Path(basename).suffix.lower(),
            original_size_bytes=size,
            extracted_path=source_path,
            archive_chain_display=chain_display,
            original_sha256=sha256,
            status=ProcessingStatus.DISCOVERED,
        )
        if unsafe_path:
            occurrence.conversion_warnings.append(
                f"Original archive path was unsafe (path traversal): {raw_relative_path!r}. "
                "Extracted using a sanitized filename only; no file was written outside the "
                "temporary workspace."
            )
        self.occurrences.append(occurrence)

    def _record_ignored(
        self, relative_path: str, chain_display: str, reason: str | None, size_hint: int
    ) -> None:
        doc_id = f"DOC-{self._next_index:06d}"
        index = self._next_index
        self._next_index += 1

        basename = relative_path.rsplit("/", 1)[-1]
        occurrence = SourceOccurrence(
            document_id=doc_id,
            traversal_index=index,
            original_filename=basename,
            original_relative_path=relative_path,
            original_extension=Path(basename).suffix.lower(),
            original_size_bytes=size_hint,
            extracted_path=None,
            archive_chain_display=chain_display,
            original_sha256=None,
            status=ProcessingStatus.IGNORED_SYSTEM_ARTIFACT,
            is_ignored_artifact=True,
            ignored_artifact_reason=reason,
        )
        self.occurrences.append(occurrence)

    def _record_unextractable(
        self, basename: str, relative_path: str, chain_display: str, error: str
    ) -> None:
        doc_id = f"DOC-{self._next_index:06d}"
        index = self._next_index
        self._next_index += 1

        occurrence = SourceOccurrence(
            document_id=doc_id,
            traversal_index=index,
            original_filename=basename,
            original_relative_path=relative_path,
            original_extension=Path(basename).suffix.lower(),
            original_size_bytes=0,
            extracted_path=None,
            archive_chain_display=chain_display,
            original_sha256=None,
            status=ProcessingStatus.DISCOVERED,
            conversion_failure_reason=f"Could not extract this entry from its archive: {error}",
        )
        self.occurrences.append(occurrence)

    def _record_single_placeholder_source(
        self, source_path: Path, basename: str, relative_path: str, chain_display: str, reason: str
    ) -> None:
        doc_id = f"DOC-{self._next_index:06d}"
        index = self._next_index
        self._next_index += 1

        try:
            size = source_path.stat().st_size
        except OSError:
            size = 0
        try:
            sha256 = sha256_of_file(source_path)
        except OSError:
            sha256 = None

        occurrence = SourceOccurrence(
            document_id=doc_id,
            traversal_index=index,
            original_filename=basename,
            original_relative_path=relative_path,
            original_extension=Path(basename).suffix.lower(),
            original_size_bytes=size,
            extracted_path=source_path,
            archive_chain_display=chain_display,
            original_sha256=sha256,
            status=ProcessingStatus.DISCOVERED,
            conversion_failure_reason=reason,
        )
        self.occurrences.append(occurrence)

    def _enforce_running_limits(self, added_bytes: int) -> None:
        self._running_bytes += added_bytes
        self._running_entries += 1
        if self.allow_large_input:
            return
        if self._running_bytes > self.config.max_expanded_size_bytes:
            raise ArchiveTooLargeError(
                "Expanded input size exceeds the configured safety limit of "
                f"{self.config.max_expanded_size_mb:.0f} MB. Re-run with "
                "--allow-large-input if this is a known, intentional large package."
            )
        if self._running_entries > self.config.max_archive_entries:
            raise ArchiveTooLargeError(
                "Number of archive entries exceeds the configured safety limit of "
                f"{self.config.max_archive_entries}. Re-run with --allow-large-input if this "
                "is a known, intentional large package."
            )


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
