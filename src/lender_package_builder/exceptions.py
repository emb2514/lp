"""Exception hierarchy for Lender Package Builder.

Errors are raised with specific, actionable types instead of being
swallowed. Only a small number of expected, per-document failure modes
(handled in conversion.py / cli.py) are caught and converted into
placeholder documents; everything else propagates.
"""

from __future__ import annotations

from pathlib import Path


class LenderPackageBuilderError(Exception):
    """Base class for all application-specific errors."""


class UnsafeArchiveError(LenderPackageBuilderError):
    """Raised when an archive contains a path-traversal or unsafe entry."""


class ArchiveTooLargeError(LenderPackageBuilderError):
    """Raised when an archive exceeds configured safety thresholds."""


class InsufficientDiskSpaceError(LenderPackageBuilderError):
    """Raised when there is not enough free disk space to proceed safely."""


class InvalidInputError(LenderPackageBuilderError):
    """Raised when the CLI is given an input path that cannot be processed."""


class OutputAlreadyExistsError(LenderPackageBuilderError):
    """Raised when the computed output directory already exists."""


class ConversionError(LenderPackageBuilderError):
    """Raised internally by a converter when a document cannot be converted.

    This is caught by the orchestration layer and turned into a recorded
    placeholder document; it must never crash the overall job.
    """


class IntegrityCheckFailedError(LenderPackageBuilderError):
    """Raised when the CLI must stop because a required integrity check failed."""


class InvalidConfigError(LenderPackageBuilderError):
    """Raised when an external `config.toml` exists but cannot be parsed.

    Carries a friendly, user-facing message; callers (CLI and GUI) catch
    this specifically to fall back to built-in defaults rather than
    crashing outright or silently using unexpected settings.
    """


class ProcessingCancelledError(LenderPackageBuilderError):
    """Raised by `build_package()` when a run was stopped via Cancel
    Processing (see `cancellation.py`). Distinct from every other error
    here: this is never a failure -- it carries enough context (stage,
    output path, cleanup outcome) for the CLI/GUI to show a clear,
    honest "Cancelled" state instead of a success or failure screen.
    """

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        output_path: Path | None = None,
        cleanup_succeeded: bool = True,
        moved_to: Path | None = None,
    ):
        super().__init__(message)
        self.stage = stage
        self.output_path = output_path
        self.cleanup_succeeded = cleanup_succeeded
        self.moved_to = moved_to
