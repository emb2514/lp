"""Core data models shared across the Lender Package Builder engine.

The central object is :class:`SourceOccurrence`, which represents exactly
one occurrence of one source file discovered during inventory. Every rule
in the specification ("one source file equals one indivisible document")
is enforced by treating a `SourceOccurrence` as the atomic unit that flows
through hashing, conversion, deduplication, merging, and splitting.
"""

from __future__ import annotations

import dataclasses
import enum
from pathlib import Path


class ProcessingStatus(str, enum.Enum):
    """Final recorded status of a discovered source occurrence."""

    DISCOVERED = "discovered"
    CONVERTED = "converted"
    UNCONVERTED_PLACEHOLDER = "unconverted_placeholder"
    IGNORED_SYSTEM_ARTIFACT = "ignored_system_artifact"


class ConversionOutcome(str, enum.Enum):
    """Outcome of a single conversion attempt."""

    SUCCESS = "success"
    FALLBACK_SUCCESS = "fallback_success"
    FAILED = "failed"


@dataclasses.dataclass
class ConversionResult:
    """Result returned by a converter for a single source occurrence."""

    outcome: ConversionOutcome
    pdf_path: Path | None = None
    page_count: int | None = None
    backend: str = "unknown"
    warnings: list[str] = dataclasses.field(default_factory=list)
    failure_reason: str | None = None

    # Used only by the email converter: (display_name, path_in_workspace)
    # for each email attachment that failed to convert and must be
    # preserved under Unconverted_Files even though the parent email
    # document itself converted successfully.
    extra_preserved_files: list[tuple[str, Path]] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class SourceOccurrence:
    """One occurrence of one source document, discovered in traversal order.

    A `SourceOccurrence` is never split, never partially deleted, and
    always maps to exactly one converted (or placeholder) PDF document.
    """

    document_id: str
    traversal_index: int
    original_filename: str
    original_relative_path: str
    original_extension: str
    original_size_bytes: int

    # Absolute path to the extracted original bytes inside the temporary
    # workspace. Always present for real files; None only for entries
    # that could not be extracted at all (still recorded, never dropped).
    extracted_path: Path | None = None

    # Human-readable description of where this occurrence came from,
    # e.g. "loans.zip -> attachments.zip -> disclosure.pdf"
    archive_chain_display: str = ""

    original_sha256: str | None = None
    status: ProcessingStatus = ProcessingStatus.DISCOVERED

    is_ignored_artifact: bool = False
    ignored_artifact_reason: str | None = None

    converted_pdf_path: Path | None = None
    converted_page_count: int | None = None
    converted_size_bytes: int | None = None
    conversion_backend: str | None = None
    conversion_warnings: list[str] = dataclasses.field(default_factory=list)
    conversion_failure_reason: str | None = None
    used_fallback_renderer: bool = False

    is_duplicate: bool = False
    duplicate_of_document_id: str | None = None

    og_part_index: int | None = None
    final_part_index: int | None = None

    unconverted_copy_path: Path | None = None

    @property
    def included_in_final(self) -> bool:
        return not self.is_ignored_artifact and not self.is_duplicate

    @property
    def included_in_og(self) -> bool:
        return not self.is_ignored_artifact


@dataclasses.dataclass
class OutputPart:
    """One physical output PDF part (either in OG or Final)."""

    package: str  # "OG" or "Final"
    index: int
    file_path: Path
    document_ids: list[str] = dataclasses.field(default_factory=list)
    page_count: int = 0
    file_size_bytes: int = 0
    is_oversized: bool = False

    # Human-readable reason(s) this part ended where it did:
    # "page_maximum", "size_maximum", "oversized_document", and/or
    # "end_of_package". Derived after final part composition settles
    # (including any actual-size rebuild), for reporting only -- it is
    # not itself relied on by the integrity checks.
    close_reasons: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class DuplicateGroup:
    """A group of source occurrences sharing one original SHA-256."""

    sha256: str
    document_ids: list[str] = dataclasses.field(default_factory=list)

    @property
    def retained_document_id(self) -> str:
        return self.document_ids[0]

    @property
    def duplicate_document_ids(self) -> list[str]:
        return self.document_ids[1:]


@dataclasses.dataclass
class IntegrityCheckResult:
    name: str
    passed: bool
    detail: str


@dataclasses.dataclass
class RunResult:
    """Aggregate result of a full build run, used to drive reporting."""

    input_path: Path
    output_path: Path
    start_time: str
    end_time: str = ""
    elapsed_seconds: float = 0.0

    occurrences: list[SourceOccurrence] = dataclasses.field(default_factory=list)
    duplicate_groups: list[DuplicateGroup] = dataclasses.field(default_factory=list)
    og_parts: list[OutputPart] = dataclasses.field(default_factory=list)
    final_parts: list[OutputPart] = dataclasses.field(default_factory=list)
    integrity_checks: list[IntegrityCheckResult] = dataclasses.field(default_factory=list)
    conversion_backend_usage: dict[str, int] = dataclasses.field(default_factory=dict)
    unsafe_archive_incidents: list[str] = dataclasses.field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(c.passed for c in self.integrity_checks)
