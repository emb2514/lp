"""Shared conversion infrastructure: the converter interface, output
validation, and the placeholder-PDF generator used for every source
document that cannot be safely converted.
"""

from __future__ import annotations

import base64
import re
import textwrap
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from ..models import ConversionOutcome, ConversionResult, SourceOccurrence


def text_to_paragraph_chunks(text: str) -> list[str]:
    """Groups raw extracted text into paragraph-sized chunks: consecutive
    non-blank lines are joined into one paragraph, a blank line starts a
    new one. Un-wraps text that was manually line-wrapped by whatever
    produced it (a mail client, a plain-text export, ...) back into
    reflowable prose.

    REAL USER-FACING BUG this exists to fix: raw extracted text used to
    be rendered with a monospace font in a `Preformatted` flowable
    (verbatim line breaks, terminal-style) -- to a real reader that
    looks exactly like a block of code or a data dump, not a document,
    even when the underlying text is perfectly ordinary prose (an email
    body, a paragraph of HTML content with no recognized markup).
    Callers should instead render each returned chunk as a normal
    `Paragraph` with an ordinary proportional font.
    """

    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        if line.strip():
            current.append(line.strip())
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


# REAL, CONFIRMED BUG (reproduced directly): an email attachment with
# NO Content-Type and NO Content-Transfer-Encoding header at all (some
# document-delivery systems produce exactly this, malformed but real)
# defaults to "text/plain" per the MIME spec and is never base64-
# decoded -- its raw, still-encoded text then looks like one very long,
# blank-line-free paragraph and gets rendered verbatim as an unreadable
# page. `decode_if_disguised_binary_attachment` recognizes this
# specific pattern (long base64 that decodes to a known file signature)
# so the caller can route it through the normal attachment pipeline
# instead. `looks_like_garbled_non_prose` is a broader, lower-
# specificity safety net for the same class of failure in general: it
# never identifies WHAT the content is, only that it clearly isn't
# readable prose, so it should never be silently rendered as if it
# were a normal page.

_MIN_BASE64_LIKE_LENGTH = 200

_KNOWN_BINARY_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"%PDF-", ".pdf", "PDF"),
    (b"PK\x03\x04", ".zip", "ZIP/Office document"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", ".doc", "legacy Office document"),
    (b"\xff\xd8\xff", ".jpg", "JPEG image"),
    (b"\x89PNG\r\n\x1a\n", ".png", "PNG image"),
)


def decode_if_disguised_binary_attachment(text: str) -> tuple[bytes, str, str] | None:
    """Returns `(decoded_bytes, file_extension, file_kind)` if `text` is
    raw, undecoded base64 that decodes to a RECOGNIZED binary file
    signature -- never guesses on merely base64-shaped content, since
    plenty of legitimate short strings coincidentally are; only content
    long enough to plausibly BE a whole embedded file, and that
    decodes to an actual known file's magic bytes, counts. Returns
    None for ordinary text.
    """

    compact = re.sub(r"\s+", "", text)
    if len(compact) < _MIN_BASE64_LIKE_LENGTH:
        return None
    if not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact):
        return None
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (ValueError, base64.binascii.Error):
        return None
    for magic, ext, kind in _KNOWN_BINARY_SIGNATURES:
        if decoded.startswith(magic):
            return decoded, ext, kind
    return None


def looks_like_garbled_non_prose(text: str) -> bool:
    """A general, low-false-positive safety net: ordinary prose is
    roughly 15-20% whitespace (average word length ~5 characters plus a
    space); base64/hex/other encoded binary data has almost none, even
    accounting for MIME's traditional 76-character line wrapping (well
    under 3%). Only meaningful on genuinely long text -- a short
    string's whitespace ratio doesn't indicate anything reliably.
    """

    stripped = text.strip()
    if len(stripped) < 200:
        return False
    whitespace_count = sum(1 for ch in stripped if ch.isspace())
    return (whitespace_count / len(stripped)) < 0.03


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
