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

    # --- RC2: content-aware duplicate detection (Levels 2-4) ---
    # Deliberately separate from is_duplicate/duplicate_of_document_id
    # above, which stay exact-SHA-256-only so validation.py's strict
    # exact-hash invariant checks never need to reason about anything
    # but byte-for-byte identity. needs_review=True is a hard guarantee
    # that this occurrence is NOT excluded from Final (see
    # included_in_final below) -- "when confidence is uncertain, keep
    # both and report the uncertainty" is enforced structurally here,
    # not just by convention.
    needs_review: bool = False
    review_reason: str | None = None

    is_content_duplicate: bool = False
    content_duplicate_of_document_id: str | None = None
    # "exact_sha256" | "normalized_pdf" | "content_equivalent" | "blank_page_tolerant"
    duplicate_detection_method: str | None = None
    duplicate_confidence: float | None = None
    blank_pages_ignored_count: int = 0

    # --- RC2: PDF Portfolio support ---
    # True only when this occurrence's own PDF catalog has a /Collection
    # entry (a real Portfolio, not just a PDF that happens to carry a
    # loose file attachment) -- its own pages (the Adobe "open this in
    # Acrobat" cover/UI page) are excluded from Final, but it still
    # appears in OG untouched like any other original file.
    is_portfolio_container: bool = False
    # Set only on occurrences synthesized from a parent PDF's embedded
    # files (document_id suffix "-PF-NNN"); None for everything else.
    portfolio_parent_document_id: str | None = None

    # --- RC2: merged-document overlap / containment ---
    is_contained_in_merged_document: bool = False
    contained_in_document_id: str | None = None
    # Inclusive, 0-based page range within the container's page list.
    contained_page_range: tuple[int, int] | None = None

    # --- RC2: document version classification (Level 5, descriptive only) ---
    document_family_id: str | None = None
    # "unsigned" | "e_signed" | "wet_signed" | "scanned" | "dated_version" |
    # "annotated" | "original_digital" | None (unclassified)
    version_classification: str | None = None

    @property
    def included_in_final(self) -> bool:
        return (
            not self.is_ignored_artifact
            and not self.is_duplicate
            and not (self.is_content_duplicate and not self.needs_review)
            and not self.is_portfolio_container
            and not (self.is_contained_in_merged_document and not self.needs_review)
        )

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
class ContentDuplicateGroup:
    """A group of occurrences found to be the same document version via
    content-aware comparison (Levels 2-4), as opposed to `DuplicateGroup`
    which is exact-SHA-256 only. Kept as a separate dataclass so the
    exact-hash grouping's shape (and validation.py's checks built on it)
    never has to account for a confidence score or detection method.
    """

    # "normalized_pdf" | "content_equivalent" | "blank_page_tolerant"
    method: str
    document_ids: list[str] = dataclasses.field(default_factory=list)
    retained_document_id: str = ""
    confidence: float = 0.0
    blank_pages_ignored_count: int = 0


@dataclasses.dataclass
class DocumentFamily:
    """A cluster of occurrences judged similar enough to be versions of
    the same underlying document (Level 5). Purely descriptive -- no
    keep/remove decision is ever derived from family membership alone.
    """

    family_id: str
    document_ids: list[str] = dataclasses.field(default_factory=list)
    # document_id -> version_classification
    versions: dict[str, str] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class OverlapFinding:
    """Result of comparing one standalone/Portfolio-attachment document
    against one candidate merged-PDF container.
    """

    standalone_document_id: str
    container_document_id: str
    # "exact_contained" | "equivalent_contained" | "different_version" |
    # "partial_overlap" | "uncertain_overlap" | "no_overlap"
    classification: str
    contained_page_range: tuple[int, int] | None = None
    confidence: float = 0.0
    excluded: bool = False


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
    content_duplicate_groups: list[ContentDuplicateGroup] = dataclasses.field(default_factory=list)
    document_families: list[DocumentFamily] = dataclasses.field(default_factory=list)
    overlap_findings: list[OverlapFinding] = dataclasses.field(default_factory=list)
    og_parts: list[OutputPart] = dataclasses.field(default_factory=list)
    final_parts: list[OutputPart] = dataclasses.field(default_factory=list)
    integrity_checks: list[IntegrityCheckResult] = dataclasses.field(default_factory=list)
    conversion_backend_usage: dict[str, int] = dataclasses.field(default_factory=dict)
    unsafe_archive_incidents: list[str] = dataclasses.field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(c.passed for c in self.integrity_checks)
