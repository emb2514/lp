"""PDF passthrough "conversion".

A source PDF is already a PDF. This adapter validates it opens, handles
the empty-password-encrypted case, and otherwise copies it byte-for-byte
so that no page is ever rasterized, dropped, or reordered.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from ..models import ConversionOutcome, ConversionResult
from .base import failed_result, validate_pdf

NAME = "pdf-passthrough"


def can_handle(extension: str) -> bool:
    return extension == ".pdf"


def convert(occurrence, dest_path: Path, config, workspace=None, cancellation_token=None) -> ConversionResult:
    source = occurrence.extracted_path
    if source is None or not source.exists():
        return failed_result("Original PDF bytes were not available to convert.")

    try:
        reader = PdfReader(str(source))
    except (PdfReadError, OSError, ValueError) as exc:
        return failed_result(f"Could not open as a valid PDF: {exc}")

    warnings: list[str] = []

    if reader.is_encrypted:
        try:
            result = reader.decrypt("")
        except Exception as exc:  # pypdf raises various error types on bad crypto
            return failed_result(f"PDF is password-protected and could not be opened: {exc}")
        if result == 0:
            return failed_result(
                "PDF is password-protected; an empty password did not open it."
            )
        warnings.append("PDF was encrypted with an empty user password; it was decrypted.")

        try:
            page_count = len(reader.pages)
            if page_count < 1:
                return failed_result("Decrypted PDF has zero pages.")
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with dest_path.open("wb") as fh:
                writer.write(fh)
        except (PdfReadError, OSError, ValueError) as exc:
            return failed_result(f"Could not write decrypted PDF: {exc}")
    else:
        try:
            page_count = len(reader.pages)
        except (PdfReadError, ValueError) as exc:
            return failed_result(f"Could not read PDF page contents: {exc}")
        if page_count < 1:
            return failed_result("PDF has zero pages.")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest_path)

    is_valid, validated_pages, error = validate_pdf(dest_path)
    if not is_valid:
        return failed_result(f"Converted PDF failed validation: {error}", warnings=warnings)

    return ConversionResult(
        outcome=ConversionOutcome.SUCCESS,
        pdf_path=dest_path,
        page_count=validated_pages,
        backend=NAME,
        warnings=warnings,
    )
