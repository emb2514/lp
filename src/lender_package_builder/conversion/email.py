"""EML/MSG-to-PDF conversion.

One source email always produces exactly one combined, indivisible PDF:
headers, then body, then an attachment list, then each attachment's
converted content (or a clearly labeled placeholder) appended in
original order. Attachments never become independent top-level output
documents -- they only ever exist as pages inside their parent email's
single PDF.

Parsing is entirely local. `.eml` uses the standard-library `email`
package; `.msg` uses the pure-Python `extract_msg` parser (no Outlook
installation required).

REAL, CONFIRMED USER-FACING BUG this module guards against directly:
"i get a full page of [base64 characters]... no one but a computer
could understand that." Reproduced exactly: a MIME part carrying an
attachment with NO Content-Type and NO Content-Transfer-Encoding header
at all (a malformed but real message some document-delivery systems
produce) defaults to "text/plain" per the MIME spec and is never
base64-decoded -- its raw, still-encoded text then looks like one very
long paragraph and would otherwise be rendered verbatim as an
unreadable page. `_parse_eml` now recognizes this pattern (see
`base.decode_if_disguised_binary_attachment`) and routes it through the
normal attachment pipeline instead of treating it as body text, so the
actual embedded document (a PDF, an Office file, an image) shows up as
a real, readable page -- and `_render_header_pdf` refuses to render any
body text that still doesn't look like real prose even after that,
using a clearly labeled placeholder instead (see
`base.looks_like_garbled_non_prose`) rather than ever silently showing
something unreadable.
"""

from __future__ import annotations

import dataclasses
import email as email_lib
import email.policy
import tempfile
from email.parser import BytesParser
from pathlib import Path
from xml.sax.saxutils import escape

from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer

from ..cancellation import check_cancelled
from ..hashing import sha256_of_file
from ..models import ConversionOutcome, ConversionResult, SourceOccurrence
from .base import (
    decode_if_disguised_binary_attachment,
    failed_result,
    looks_like_garbled_non_prose,
    make_placeholder_pdf,
    text_to_paragraph_chunks,
    validate_pdf,
)

NAME = "email-mime"

_EML_EXT = {".eml"}
_MSG_EXT = {".msg"}


def can_handle(extension: str) -> bool:
    return extension in _EML_EXT | _MSG_EXT


@dataclasses.dataclass
class _EmailData:
    subject: str
    from_: str
    to: str
    cc: str
    date: str
    body_text: str
    attachments: list[tuple[str, bytes]]


def convert(occurrence, dest_path: Path, config, workspace=None, cancellation_token=None) -> ConversionResult:
    source = occurrence.extracted_path
    if source is None or not source.exists():
        return failed_result("Original email bytes were not available to convert.")

    extension = occurrence.original_extension
    try:
        if extension in _EML_EXT:
            data = _parse_eml(source)
        else:
            data = _parse_msg(source)
    except Exception as exc:
        return failed_result(f"Could not parse email message: {exc}")

    if workspace is not None:
        work_dir = workspace.convert_dir / f"{occurrence.document_id}_email_work"
        work_dir.mkdir(parents=True, exist_ok=True)
    else:  # pragma: no cover - defensive fallback, always have a workspace in practice
        work_dir = Path(tempfile.mkdtemp(prefix="lpb_email_"))

    warnings: list[str] = []
    preserved: list[tuple[str, Path]] = []

    header_pdf = work_dir / "00_header.pdf"
    header_error, header_warnings = _render_header_pdf(data, header_pdf)
    if header_error:
        return failed_result(f"Could not render email header/body page: {header_error}")
    warnings.extend(header_warnings)

    writer = PdfWriter()
    _append_pdf_pages(writer, header_pdf)

    for i, (att_name, att_bytes) in enumerate(data.attachments, start=1):
        check_cancelled(cancellation_token)
        safe_name = Path(att_name).name or f"attachment_{i}"

        divider_pdf = work_dir / f"{i:03d}_divider.pdf"
        _render_divider_pdf(safe_name, len(att_bytes), divider_pdf)
        _append_pdf_pages(writer, divider_pdf)

        att_path = work_dir / f"{i:03d}_{safe_name}"
        att_path.write_bytes(att_bytes)

        synthetic = SourceOccurrence(
            document_id=f"{occurrence.document_id}-ATT-{i:03d}",
            traversal_index=0,
            original_filename=safe_name,
            original_relative_path=att_name,
            original_extension=Path(safe_name).suffix.lower(),
            original_size_bytes=len(att_bytes),
            extracted_path=att_path,
        )
        try:
            synthetic.original_sha256 = sha256_of_file(att_path)
        except OSError:
            synthetic.original_sha256 = None

        from . import convert_occurrence  # local import: breaks package import cycle

        att_dest = work_dir / f"{i:03d}_converted.pdf"
        att_result = convert_occurrence(synthetic, att_dest, config, workspace, cancellation_token)

        if att_result.outcome == ConversionOutcome.FAILED:
            placeholder_pdf = work_dir / f"{i:03d}_placeholder.pdf"
            make_placeholder_pdf(
                synthetic,
                placeholder_pdf,
                att_result.failure_reason or "Attachment could not be converted.",
                original_preserved=True,
            )
            _append_pdf_pages(writer, placeholder_pdf)
            warnings.append(
                f"Attachment {att_name!r} could not be converted "
                f"({att_result.failure_reason}); inserted a placeholder page and preserved "
                "the original attachment under Unconverted_Files."
            )
            preserved.append((f"{occurrence.document_id}_attachments/{safe_name}", att_path))
        else:
            _append_pdf_pages(writer, att_result.pdf_path)
            for w in att_result.warnings:
                warnings.append(f"Attachment {att_name!r}: {w}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with dest_path.open("wb") as fh:
        writer.write(fh)

    is_valid, page_count, error = validate_pdf(dest_path)
    if not is_valid:
        return failed_result(f"Combined email PDF failed validation: {error}", warnings=warnings)

    return ConversionResult(
        outcome=ConversionOutcome.SUCCESS,
        pdf_path=dest_path,
        page_count=page_count,
        backend=NAME,
        warnings=warnings,
        extra_preserved_files=preserved,
    )


def _append_pdf_pages(writer: PdfWriter, pdf_path: Path) -> None:
    reader = PdfReader(str(pdf_path))
    for page in reader.pages:
        writer.add_page(page)


def _render_header_pdf(data: _EmailData, dest_path: Path) -> tuple[str | None, list[str]]:
    """Returns `(error, warnings)` -- `error` set means the page could
    not be built at all; `warnings` is populated when the body was
    replaced with a placeholder because it didn't look like real text
    (see this module's docstring).
    """

    warnings: list[str] = []
    title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=15, leading=19)
    label_style = ParagraphStyle(name="Label", fontName="Helvetica-Bold", fontSize=10, leading=14)
    body_style = ParagraphStyle(name="Body", fontName="Helvetica", fontSize=10, leading=14)

    flowables = [Paragraph("EMAIL MESSAGE", title_style), Spacer(1, 10)]
    for label, value in (
        ("From", data.from_),
        ("To", data.to),
        ("Cc", data.cc),
        ("Date", data.date),
        ("Subject", data.subject),
    ):
        if value:
            flowables.append(Paragraph(f"<b>{escape(label)}:</b> {escape(value)}", body_style))
    flowables.append(Spacer(1, 12))
    flowables.append(Paragraph("Message body:", label_style))
    flowables.append(Spacer(1, 4))
    body = data.body_text.strip() or "(This message has no text body.)"
    if looks_like_garbled_non_prose(body):
        # General safety net (see this module's docstring): never
        # silently render content that doesn't look like real prose --
        # a clearly labeled placeholder instead, and a warning the
        # report surfaces, so this is never mistaken for a working page.
        warnings.append(
            "This message's body did not look like readable text (it may be corrupted or "
            "mis-encoded) and was not displayed."
        )
        flowables.append(
            Paragraph(
                "(This message's body could not be verified as readable text and was not "
                "displayed. See the processing report.)",
                body_style,
            )
        )
    else:
        # REAL USER-FACING BUG: this used to always render the body with
        # a monospace font in a Preformatted flowable, regardless of
        # content -- an ordinary email body read exactly like a block of
        # code, not a message. Reflowed into normal paragraphs with the
        # same proportional font as everything else on this page. See
        # base.text_to_paragraph_chunks's docstring.
        for chunk in text_to_paragraph_chunks(body):
            flowables.append(Paragraph(escape(chunk), body_style))
            flowables.append(Spacer(1, 4))

    if data.attachments:
        flowables.append(Spacer(1, 14))
        flowables.append(Paragraph(f"Attachments ({len(data.attachments)}):", label_style))
        items = [
            ListItem(Paragraph(escape(Path(name).name or name), body_style))
            for name, _ in data.attachments
        ]
        flowables.append(ListFlowable(items, bulletType="bullet"))

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(dest_path),
        pagesize=LETTER,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    try:
        doc.build(flowables)
    except Exception as exc:
        return str(exc), warnings
    is_valid, _, error = validate_pdf(dest_path)
    return (None, warnings) if is_valid else (error, warnings)


def _render_divider_pdf(name: str, size_bytes: int, dest_path: Path) -> None:
    title_style = ParagraphStyle(name="AttTitle", fontName="Helvetica-Bold", fontSize=13, leading=17)
    body_style = ParagraphStyle(name="AttBody", fontName="Helvetica", fontSize=10, leading=14)
    flowables = [
        Paragraph(f"Attachment: {escape(name)}", title_style),
        Spacer(1, 6),
        Paragraph(f"Size: {size_bytes:,} bytes", body_style),
    ]
    doc = SimpleDocTemplate(str(dest_path), pagesize=LETTER)
    doc.build(flowables)


def _parse_eml(path: Path) -> _EmailData:
    with path.open("rb") as fh:
        msg = BytesParser(policy=email.policy.default).parse(fh)

    subject = str(msg.get("subject", "") or "")
    from_ = str(msg.get("from", "") or "")
    to = str(msg.get("to", "") or "")
    cc = str(msg.get("cc", "") or "")
    date = str(msg.get("date", "") or "")

    body_text = ""
    attachments: list[tuple[str, bytes]] = []

    for part in msg.walk():
        if part.is_multipart():
            continue

        disposition = part.get_content_disposition()
        filename = part.get_filename()
        content_type = part.get_content_type()

        is_attachment = disposition == "attachment" or (
            filename is not None and content_type not in ("text/plain", "text/html")
        )

        if is_attachment:
            try:
                payload = part.get_payload(decode=True) or b""
            except (LookupError, ValueError):
                payload = b""
            attachments.append((filename or f"attachment_{len(attachments) + 1}", payload))
        elif content_type == "text/plain":
            try:
                candidate = part.get_content()
            except (LookupError, ValueError):
                candidate = ""
            # A part with no Content-Type/Content-Transfer-Encoding at
            # all defaults to "text/plain" per the MIME spec and is
            # never base64-decoded -- see this module's docstring for
            # the confirmed real-world failure this guards against.
            # Checked unconditionally (not gated on `not body_text`,
            # unlike the plain body-text assignment below it) -- a
            # disguised attachment can appear anywhere among a
            # message's parts, not only before the real body text, and
            # must never be silently dropped just because an earlier
            # part already supplied the body.
            disguised = decode_if_disguised_binary_attachment(candidate)
            if disguised is not None:
                decoded_bytes, ext, kind = disguised
                attachments.append((f"embedded_{kind.split('/')[0].lower()}_{len(attachments) + 1}{ext}", decoded_bytes))
            elif not body_text:
                body_text = candidate
        elif content_type == "text/html" and not body_text:
            try:
                html_content = part.get_content()
            except (LookupError, ValueError):
                html_content = ""
            body_text = BeautifulSoup(html_content, "html.parser").get_text("\n", strip=True)

    return _EmailData(subject, from_, to, cc, date, body_text, attachments)


def _parse_msg(path: Path) -> _EmailData:
    import extract_msg

    msg = extract_msg.Message(str(path))
    try:
        subject = msg.subject or ""
        from_ = msg.sender or ""
        to = msg.to or ""
        cc = getattr(msg, "cc", "") or ""
        date = str(msg.date or "")
        body_text = msg.body or ""
        if not body_text:
            html_body = getattr(msg, "htmlBody", None)
            if html_body:
                if isinstance(html_body, bytes):
                    html_body = html_body.decode("utf-8", errors="replace")
                body_text = BeautifulSoup(html_body, "html.parser").get_text("\n", strip=True)

        attachments: list[tuple[str, bytes]] = []
        for att in getattr(msg, "attachments", []):
            name = getattr(att, "longFilename", None) or getattr(att, "shortFilename", None)
            name = name or f"attachment_{len(attachments) + 1}"
            data = getattr(att, "data", None)
            if isinstance(data, (bytes, bytearray)):
                attachments.append((name, bytes(data)))

        # Defense in depth -- same guard as _parse_eml, for the (less
        # likely, since .msg properties are normally well-formed, but
        # still worth covering) case body_text itself is disguised
        # undecoded binary data.
        disguised = decode_if_disguised_binary_attachment(body_text)
        if disguised is not None:
            decoded_bytes, ext, kind = disguised
            attachments.insert(0, (f"embedded_{kind.split('/')[0].lower()}_1{ext}", decoded_bytes))
            body_text = ""

        return _EmailData(subject, from_, to, cc, date, body_text, attachments)
    finally:
        msg.close()
