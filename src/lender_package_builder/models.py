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

    # --- RC2: GUI-driven manual review decisions ---
    # Set ONLY by review_decisions.apply_review_decision(), in response
    # to an explicit, confirmed human choice in the "Review Uncertain
    # Matches" dialog -- never by any automated detection pass. This is
    # the ONLY mechanism by which a needs_review=True occurrence can
    # ever be excluded from Final; see included_in_final below and
    # UncertainMatch, which holds the full auditable decision record
    # (timestamp, reason, which document was chosen) this field points
    # back to.
    manually_excluded: bool = False
    manually_excluded_match_id: str | None = None

    @property
    def included_in_final(self) -> bool:
        return (
            not self.is_ignored_artifact
            and not self.is_duplicate
            and not (self.is_content_duplicate and not self.needs_review)
            and not self.is_portfolio_container
            and not (self.is_contained_in_merged_document and not self.needs_review)
            and not self.manually_excluded
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
class UncertainMatch:
    """One human-reviewable uncertain comparison, surfaced by the GUI's
    "Review Uncertain Matches" dialog. Creating this record never
    changes any output by itself -- both `document_id_a` and
    `document_id_b` are guaranteed present in Final until and unless a
    human explicitly records an "excluded" decision through
    `review_decisions.apply_review_decision()`.

    `excludable_ids` lists which of the two documents a human is
    permitted to choose to exclude: both, for an uncertain
    content-duplicate pair (either could reasonably be treated as the
    canonical copy); only the standalone side, for an uncertain
    merged-package containment match (the merged container itself is
    never a valid exclusion target, per the same structural-safety rule
    that governs automated containment decisions).
    """

    match_id: str
    # "content_duplicate" | "merged_containment"
    kind: str
    document_id_a: str
    document_id_b: str
    confidence: float
    # Human-readable explanation of why this pair/relationship is
    # uncertain (method, confidence, threshold) -- shown verbatim in
    # the GUI and in Uncertain_Match_Review_Log.txt.
    detail: str
    excludable_ids: tuple[str, ...] = ()

    # "undecided" | "keep_both" | "excluded" -- set only by
    # review_decisions.apply_review_decision(); a decision, once made,
    # is never silently overwritten (re-deciding raises an error).
    decision: str = "undecided"
    decided_document_id: str | None = None
    decided_at: str | None = None
    decided_reason: str | None = None


@dataclasses.dataclass
class KeyDocumentMatch:
    """One key-document page-locator result, produced by
    key_documents.locate_key_documents() after the deduplicated Final
    package is built. Purely descriptive -- recognition here never
    controls duplicate detection or Final inclusion/exclusion.
    """

    match_id: str
    # "closing_disclosure" | "government_id" | "mu_privacy_policy" | "non_proceeding"
    category: str
    # e.g. "Front"/"Back"/"Front and Back"/"Passport"/"State ID Card"/
    # "Government ID" (government_id), or the specific non-proceeding
    # subtype ("Adverse Action Notice", ...).
    subtype: str | None
    confidence_band: str  # "Confirmed" | "Strong Match" | "Possible Match"
    confidence: float
    document_id: str
    original_filename: str
    # Detected on the page when reliably found (government_id only);
    # None means "borrower unknown", never an invented identity.
    borrower_name: str | None
    reason: str
    # 1-based (start, end) page range within the source document itself.
    document_page_range: tuple[int, int]
    # "Signed" | "E-Sign" | "Unsigned" | "Revised" | "Signature Unknown" | None
    signature_status: str | None

    # Filled in after construction, once the document's position within
    # its Final part is known -- see key_documents._fill_final_page_ranges().
    final_part_index: int | None = None
    final_part_page_range: tuple[int, int] | None = None  # 1-based, within that Final part file
    overall_final_page_range: tuple[int, int] | None = None  # 1-based, across the whole Final package

    # The detected person's name, when used to override the primary
    # borrower's name for this specific extracted file (e.g. a
    # co-borrower's own Driver's License) -- see naming.key_document_filename().
    person_name_override: str | None = None
    # Set only once extract_key_documents() has actually written a
    # standalone file for this match (Confirmed/Strong Match only).
    extracted_filename: str | None = None


@dataclasses.dataclass
class PackageIdentity:
    """Borrower identity used to name the main output folder, the
    Final/Original Lender Package files, and extracted key documents
    (see naming.py). Entered or confirmed by the user before processing
    -- automatic document recognition never controls these values.
    """

    last_name: str = ""
    first_name: str = ""
    loan_number: str = ""
    is_adverse: bool = False


@dataclasses.dataclass
class RunResult:
    """Aggregate result of a full build run, used to drive reporting."""

    input_path: Path
    output_path: Path
    start_time: str
    end_time: str = ""
    elapsed_seconds: float = 0.0
    identity: PackageIdentity = dataclasses.field(default_factory=PackageIdentity)

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
    # RC2: performance-related notes from content-aware analysis, e.g. an
    # oversized structural bucket that fell back to cheaper exact-hash-
    # only grouping (see content_dedup.py). Never affects correctness,
    # only which comparison tier ran for a given candidate set.
    content_dedup_notes: list[str] = dataclasses.field(default_factory=list)
    # RC2: every uncertain comparison surfaced for human review, and its
    # decision (if any) -- see UncertainMatch and review_decisions.py.
    uncertain_matches: list[UncertainMatch] = dataclasses.field(default_factory=list)
    # Every key-document page-locator result found after Final was
    # built -- see key_documents.py.
    key_document_matches: list[KeyDocumentMatch] = dataclasses.field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(c.passed for c in self.integrity_checks)
