"""Exception hierarchy for Lender Package Builder.

Errors are raised with specific, actionable types instead of being
swallowed. Only a small number of expected, per-document failure modes
(handled in conversion.py / cli.py) are caught and converted into
placeholder documents; everything else propagates.
"""

from __future__ import annotations


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
