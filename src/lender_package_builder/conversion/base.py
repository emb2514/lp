"""Shared conversion infrastructure: the converter interface, output
validation, and the placeholder-PDF generator used for every source
document that cannot be safely converted.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from ..models import ConversionOutcome, ConversionResult, SourceOccurrence


class Converter(Protocol):
    """Interface implemented by every format-specific converter."""

    name: str

    def can_handle(self, extension: str) -> bool: ...

    def convert(
        self, occurrence: SourceOccurrence, dest_path: Path, config, workspace
    ) -> ConversionResult: ...


def validate_pdf(path: Path) -> tuple[bool, int | None, str | None]:
    """Validate a produced PDF: exists, non-empty, opens, has >=1 page."""

    if not path.exists():
        return False, None, "Output file does not exist."
    if path.stat().st_size == 0:
        return False, None, "Output file is zero bytes."
    try:
        reader = PdfReader(str(path))
        page_count = len(reader.pages)
    except (PdfReadError, OSError, ValueError) as exc:
        return False, None, f"Output file could not be opened as a PDF: {exc}"

    if page_count < 1:
        return False, None, "Output PDF has zero pages."
    return True, page_count, None


def make_placeholder_pdf(
    occurrence: SourceOccurrence,
    dest_path: Path,
    reason: str,
    original_preserved: bool = True,
) -> int:
    """Render a placeholder PDF describing an unconverted source document.

    Returns the page count of the placeholder (always 1).
    """

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(dest_path), pagesize=LETTER)
    width, height = LETTER
    margin = 0.75 * inch
    y = height - margin

    def write_line(text: str, font: str = "Helvetica", size: int = 11, gap: float = 16):
        nonlocal y
        c.setFont(font, size)
        c.drawString(margin, y, text)
        y -= gap

    def write_wrapped(label: str, value: str, font: str = "Helvetica", size: int = 10):
        nonlocal y
        wrapped = textwrap.wrap(f"{label}: {value}", width=95) or [f"{label}: {value}"]
        c.setFont(font, size)
        for line in wrapped:
            c.drawString(margin, y, line)
            y -= 14

    write_line("UNCONVERTED SOURCE DOCUMENT", font="Helvetica-Bold", size=16, gap=28)
    write_line(
        "This source file could not be safely converted to PDF. It has NOT been",
        size=10,
    )
    write_line(
        "omitted -- it is accounted for below and in the processing report.", size=10, gap=22
    )

    write_wrapped("Original filename", occurrence.original_filename)
    write_wrapped("Original relative path", occurrence.original_relative_path)
    write_wrapped("File type", occurrence.original_extension or "(none)")
    write_wrapped("Original size (bytes)", str(occurrence.original_size_bytes))
    write_wrapped("SHA-256", occurrence.original_sha256 or "(could not be computed)")
    write_wrapped("Internal document ID", occurrence.document_id)
    y -= 6
    write_wrapped("Reason conversion failed", reason)
    y -= 6
    if original_preserved:
        write_wrapped(
            "Original file preserved",
            "Yes -- a copy of the original, unmodified file is stored in the "
            "Unconverted_Files folder of this output package.",
        )
    else:
        write_wrapped(
            "Original file preserved",
            "No -- the original bytes could not be extracted from their source "
            "archive, so no copy could be preserved. See the processing report.",
        )

    c.showPage()
    c.save()
    return 1


def failed_result(reason: str, warnings: list[str] | None = None) -> ConversionResult:
    return ConversionResult(
        outcome=ConversionOutcome.FAILED,
        failure_reason=reason,
        warnings=warnings or [],
    )
