"""Structured progress-event API for `build_package()`.

This lets any caller -- the CLI, the Stage 2 GUI, or a test -- observe
processing progress as typed events instead of parsing printed text.
It is purely additive: `build_package()` continues to work exactly as
before for callers that do not pass a `progress_callback`, and passing
one never changes what gets processed or what the final `RunResult`
contains.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Callable


class ProgressStage(str, enum.Enum):
    """One of the fixed pipeline stages, in the order they occur."""

    PREFLIGHT = "preflight"
    DISCOVERING_FILES = "discovering_files"
    DETECTING_DUPLICATES = "detecting_duplicates"
    CONVERTING_DOCUMENTS = "converting_documents"
    BUILDING_OG = "building_og"
    # RC2: content-aware duplicate detection (Levels 2-4), merged-
    # document overlap detection, and version classification (Level 5)
    # -- all run over already-converted documents, between OG and Final.
    FINGERPRINTING_CONTENT = "fingerprinting_content"
    DETECTING_CONTENT_DUPLICATES = "detecting_content_duplicates"
    ANALYZING_MERGED_PACKAGES = "analyzing_merged_packages"
    CLASSIFYING_VERSIONS = "classifying_versions"
    BUILDING_FINAL = "building_final"
    RUNNING_INTEGRITY_CHECKS = "running_integrity_checks"
    WRITING_REPORTS = "writing_reports"
    COMPLETE = "complete"
    CANCELLED = "cancelled"


class ProgressSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclasses.dataclass(frozen=True)
class ProgressEvent:
    """One immutable progress notification.

    `current`/`total` are only set when a meaningful determinate
    count exists (e.g. "document 7 of 42"); both are `None` for stages
    where no reliable count is available, so a UI can tell a
    determinate progress bar from an indeterminate one.
    """

    stage: ProgressStage
    message: str
    current: int | None = None
    total: int | None = None
    current_item: str | None = None
    severity: ProgressSeverity = ProgressSeverity.INFO
    detail: str | None = None


ProgressCallback = Callable[[ProgressEvent], None]
