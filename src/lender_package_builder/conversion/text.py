"""Plain-text-to-PDF conversion.

Line breaks are preserved exactly (a `Preformatted` flowable), long
lines are safely wrapped, and pagination is handled automatically by
reportlab's Platypus document flow.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Preformatted, SimpleDocTemplate

from ..models import ConversionOutcome, ConversionResult
from .base import failed_result, validate_pdf

NAME = "reportlab-text"

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
_WRAP_WIDTH = 100


def can_handle(extension: str) -> bool:
    return extension == ".txt"


def _decode(raw: bytes) -> tuple[str, str]:
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8 (with replacement characters)"


def _wrap_preserving_breaks(text: str, width: int) -> str:
    out_lines: list[str] = []
    for line in text.splitlines():
        line = line.rstrip("\r")
        if len(line) <= width:
            out_lines.append(line if line else " ")
            continue
        start = 0
        while start < len(line):
            out_lines.append(line[start : start + width])
            start += width
    if not out_lines:
        out_lines = [" "]
    return "\n".join(out_lines)


def convert(occurrence, dest_path: Path, config, workspace=None, cancellation_token=None) -> ConversionResult:
    source = occurrence.extracted_path
    if source is None or not source.exists():
        return failed_result("Original text bytes were not available to convert.")

    try:
        raw = source.read_bytes()
    except OSError as exc:
        return failed_result(f"Could not read text file: {exc}")

    warnings: list[str] = []
    if len(raw) == 0:
        text, encoding = "(This text file is empty.)", "n/a"
        warnings.append("Source text file was empty.")
    else:
        text, encoding = _decode(raw)
        if "replacement" in encoding:
            warnings.append(
                "Could not confidently detect text encoding; some characters may have "
                "been replaced."
            )

    wrapped = _wrap_preserving_breaks(text, _WRAP_WIDTH)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(dest_path),
        pagesize=LETTER,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )
    style = ParagraphStyle(
        name="MonoBody",
        fontName="Courier",
        fontSize=9,
        leading=11,
    )

    try:
        doc.build([Preformatted(wrapped, style)])
    except Exception as exc:  # reportlab can raise assorted layout errors
        return failed_result(f"Could not lay out text content as PDF: {exc}")

    is_valid, page_count, error = validate_pdf(dest_path)
    if not is_valid:
        return failed_result(f"Converted PDF failed validation: {error}", warnings=warnings)

    return ConversionResult(
        outcome=ConversionOutcome.SUCCESS,
        pdf_path=dest_path,
        page_count=page_count,
        backend=NAME,
        warnings=warnings,
    )
