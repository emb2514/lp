"""Conversion dispatch: routes a source occurrence to the right
format-specific converter by file extension.

`convert_occurrence` is the single entry point used both by the main
orchestration pipeline (for top-level source documents) and, via a
lazy import to avoid a circular dependency, by `email.py` itself
(to convert email attachments using exactly the same logic as
top-level documents of the same type).
"""

from __future__ import annotations

from pathlib import Path

from ..models import ConversionOutcome, ConversionResult, SourceOccurrence
from . import email as email_conv
from . import html as html_conv
from . import images as images_conv
from . import office as office_conv
from . import pdf as pdf_conv
from . import text as text_conv
from .base import failed_result

_MODULES = [pdf_conv, images_conv, text_conv, html_conv, office_conv, email_conv]

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tiff",
    ".tif",
    ".txt",
    ".html",
    ".htm",
    ".docx",
    ".xlsx",
    ".doc",
    ".xls",
    ".eml",
    ".msg",
}


def is_supported(extension: str) -> bool:
    return extension.lower() in SUPPORTED_EXTENSIONS


def convert_occurrence(
    occurrence: SourceOccurrence, dest_path: Path, config, workspace
) -> ConversionResult:
    extension = occurrence.original_extension.lower()

    if not is_supported(extension):
        return failed_result(
            f"File extension {extension or '(none)'!r} is not a supported document type."
        )

    for module in _MODULES:
        if module.can_handle(extension):
            try:
                return module.convert(occurrence, dest_path, config, workspace)
            except Exception as exc:  # a converter must never crash the whole job
                return failed_result(
                    f"Unexpected error in {module.NAME if hasattr(module, 'NAME') else module.__name__} "
                    f"converter: {exc}"
                )

    return failed_result(f"No converter is registered for extension {extension!r}.")
