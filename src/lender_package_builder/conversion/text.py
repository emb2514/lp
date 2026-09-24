"""Plain-text-to-PDF conversion.

Line breaks are preserved exactly (a `Preformatted` flowable), long
lines are safely wrapped, and pagination is handled automatically by
reportlab's Platypus document flow.

REAL USER-FACING BUG this module guards against: MISMO/ULDD loan-data
XML (and similar machine-to-machine data files, e.g. a Loan Quality
Advisor request) is routinely delivered as a `.txt` file that is one
single line tens of thousands of characters long, with no whitespace
at all. Wrapping that blindly at a fixed character width -- this
module's normal behavior for ordinary text -- chops tags and values at
arbitrary points with no relationship to the document's actual
structure, producing something "no one but a computer could
understand." `_pretty_print_if_xml` detects real XML content and
reformats it with proper indentation first (exactly like any XML
viewer/editor would show it) -- the data is completely unchanged, only
its whitespace/layout is.
"""

from __future__ import annotations

import xml.dom.minidom as minidom
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


def _pretty_print_if_xml(text: str) -> str | None:
    """Returns an indented, human-scannable rendering of `text` if it
    parses as well-formed XML; None for anything else (never guesses --
    a file that merely starts with "<" but isn't real XML, or any other
    plain text, is left completely untouched by this function).
    """

    if not text.strip().startswith("<"):
        return None
    try:
        dom = minidom.parseString(text)
    except Exception:
        return None
    pretty = dom.toprettyxml(indent="  ")
    # minidom emits a blank line for every whitespace-only text node
    # between sibling elements -- stripped so the result reads like a
    # real formatted document, not one with a blank line after every
    # single tag.
    lines = [line for line in pretty.split("\n") if line.strip()]
    return "\n".join(lines)


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
        pretty_xml = _pretty_print_if_xml(text)
        if pretty_xml is not None:
            text = pretty_xml
            warnings.append(
                "This text file contains XML data -- reformatted with indentation for "
                "readability (the underlying data is unchanged, only its layout is)."
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
