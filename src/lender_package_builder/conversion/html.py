"""HTML/HTM-to-PDF conversion.

REAL USER REPORT: "i need the HTML files to be 'printed' to PDF. i DO
NOT want those strings of codes... i need the actual file, like the one
that looks like the file... this needs to be a legible document" -- the
same thing a browser's own "Print to PDF" does. A hand-reconstructed
render (extract text, lay it back out with a generic PDF library) can
never really be that, no matter how well the text extraction works --
it throws away layout, colors, table borders, images-in-place, fonts.

So LibreOffice -- already a hard dependency for DOCX/XLSX, see
office.py -- is now tried FIRST for every HTML file, via the same
`office.convert_with_libreoffice` used there (it's format-agnostic;
LibreOffice picks its own import filter from the file extension). That
gives a real, faithful, "print to PDF"-quality render: actual layout,
table borders, background colors, fonts. `HTML_BATCHABLE_EXTENSIONS`
lets HTML files join the same one-LibreOffice-process-per-batch speed
path DOCX/XLSX already use (see office.convert_batch_with_libreoffice).

The BeautifulSoup/reportlab renderer below (`_render_with_fallback`) is
now ONLY a fallback for a machine with no LibreOffice install -- it
always adds an explicit "reduced fidelity" warning when used, exactly
like the DOCX/XLSX fallback already does, so a report never implies
this achieved the same quality as a real render. Renders entirely
offline either way: no network request is ever made, no remote script/
stylesheet/font/image is fetched. Only inline `data:` images and images
referenced by a local relative path that already exists on disk next to
the source file are embedded; anything else produces a recorded warning
rather than a silent gap.
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from xml.sax.saxutils import escape

from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.platypus import Image as RLImage

from ..models import ConversionOutcome, ConversionResult
from . import office as office_conv
from .base import failed_result, looks_like_garbled_non_prose, text_to_paragraph_chunks, validate_pdf

NAME = "fallback-html"

# Same set `can_handle` recognizes -- lets html files join office.py's
# one-LibreOffice-process batch pre-pass (cli.py) instead of each
# spawning its own fresh process.
HTML_BATCHABLE_EXTENSIONS = {".html", ".htm"}

# Handles real-world HTML the fallback renderer's block-tag detection
# would otherwise miss entirely -- Outlook/Word "Save As HTML" exports
# especially wrap nearly everything in <div>/<span> and rarely use <p>
# at all. Only exercised when the fallback renderer runs (no LibreOffice
# available); "div" is handled specially in the main loop (see
# `_is_content_leaf`): only a div with no nested block-tag descendant of
# its own is rendered directly, so a layout wrapper `<div>` full of
# nested `<div>`/`<p>` content is never ALSO rendered (which would
# duplicate every word).
_BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "td", "th", "div"]
_HEADING_SIZES = {"h1": 18, "h2": 16, "h3": 14, "h4": 13, "h5": 12, "h6": 11}


def _is_content_leaf(element) -> bool:
    """A block element is only rendered directly if it has no nested
    block-tag descendant of its own -- otherwise its content is what
    those descendants already render, and rendering the ancestor too
    would duplicate every word inside it. Matters most for <div> (real-
    world HTML nests it constantly), but applied to every block tag so
    e.g. a <td>/<li>/<blockquote> wrapping a <div> or <p> is never
    double-rendered either.
    """

    return element.find(_BLOCK_TAGS) is None


def can_handle(extension: str) -> bool:
    return extension in (".html", ".htm")


def convert(occurrence, dest_path: Path, config, workspace=None, cancellation_token=None) -> ConversionResult:
    """Tries a real, faithful LibreOffice render first -- the actual
    document, laid out the way "Print to PDF" would show it -- and only
    falls back to the hand-reconstructed renderer below if LibreOffice
    isn't available on this machine (or that attempt itself fails). See
    this module's docstring for the real user report behind this order.
    """

    source = occurrence.extracted_path
    if source is None or not source.exists():
        return failed_result("Original HTML bytes were not available to convert.")

    soffice = office_conv.find_libreoffice()
    if soffice:
        result = office_conv.convert_with_libreoffice(soffice, source, dest_path, cancellation_token)
        if result is not None:
            return result
        # Falls through to the fallback renderer below -- LibreOffice
        # being installed but failing on this specific file must never
        # be treated as "this file cannot be converted at all."

    return _convert_with_fallback_renderer(source, dest_path)


def _convert_with_fallback_renderer(source: Path, dest_path: Path) -> ConversionResult:
    """Hand-reconstructed HTML render: extracts text/structure and lays
    it back out with reportlab. Used ONLY when LibreOffice isn't
    available -- see this module's docstring. Always warns that this
    achieves lower fidelity than a real render (no layout, no table
    borders, no background colors), the same way the DOCX/XLSX fallback
    renderer already warns in office.py.
    """

    warnings: list[str] = [
        "High-fidelity conversion (LibreOffice) was not available. Used the basic fallback "
        "renderer: extracted text and images only. Original layout, table borders, background "
        "colors, and fonts are NOT preserved."
    ]

    try:
        raw = source.read_bytes()
    except OSError as exc:
        return failed_result(f"Could not read HTML file: {exc}")

    text: str
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
        warnings.append("Could not confidently detect HTML encoding; used UTF-8 with replacement.")

    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "head"]):
        tag.decompose()

    body = soup.body or soup

    body_style = ParagraphStyle(name="Body", fontName="Helvetica", fontSize=10, leading=13)
    heading_styles = {
        tag: ParagraphStyle(
            name=f"Heading_{tag}", fontName="Helvetica-Bold", fontSize=size, leading=size + 4
        )
        for tag, size in _HEADING_SIZES.items()
    }

    flowables = []
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        title_style = ParagraphStyle(name="Title", fontName="Helvetica-Bold", fontSize=15, leading=19)
        flowables.append(Paragraph(escape(title_tag.get_text(strip=True)), title_style))
        flowables.append(Spacer(1, 10))

    saw_table = False
    for element in body.find_all(_BLOCK_TAGS + ["img"]):
        if element.name == "img":
            image_flowable, warn = _resolve_image(element, source)
            if warn:
                warnings.append(warn)
            if image_flowable:
                flowables.append(image_flowable)
                flowables.append(Spacer(1, 6))
            continue

        if not _is_content_leaf(element):
            continue

        if element.name in ("td", "th"):
            saw_table = True

        content = element.get_text(" ", strip=True)
        if not content:
            continue
        style = heading_styles.get(element.name, body_style)
        flowables.append(Paragraph(escape(content), style))
        flowables.append(Spacer(1, 4))

    if saw_table:
        warnings.append(
            "This document contains one or more HTML tables. The local fallback renderer "
            "shows table cell text sequentially rather than as a formatted grid."
        )

    if not flowables:
        plain_text = body.get_text(separator="\n", strip=True)
        if plain_text and looks_like_garbled_non_prose(plain_text):
            # General safety net (see this module's docstring): never
            # silently render content that doesn't look like real prose
            # -- treat it the same as "nothing renderable was found"
            # rather than showing an unreadable page.
            warnings.append(
                "This page's extracted content did not look like readable text (it may be "
                "corrupted or mis-encoded) and was not displayed."
            )
            plain_text = ""
        if plain_text:
            warnings.append(
                "No recognized HTML structure was found; rendered the page's extracted text instead."
            )
            # REAL USER-FACING BUG: this used to render with a monospace
            # font in a Preformatted flowable -- ordinary prose came out
            # looking like a block of code. See
            # base.text_to_paragraph_chunks's docstring.
            flowables = []
            for chunk in text_to_paragraph_chunks(plain_text):
                flowables.append(Paragraph(escape(chunk), body_style))
                flowables.append(Spacer(1, 4))

    if not flowables:
        return failed_result(
            "HTML document contained no renderable text or embeddable local content.",
            warnings=warnings,
        )

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
        return failed_result(f"Could not lay out HTML content as PDF: {exc}", warnings=warnings)

    is_valid, page_count, error = validate_pdf(dest_path)
    if not is_valid:
        return failed_result(f"Converted PDF failed validation: {error}", warnings=warnings)

    return ConversionResult(
        outcome=ConversionOutcome.FALLBACK_SUCCESS,
        pdf_path=dest_path,
        page_count=page_count,
        backend=NAME,
        warnings=warnings,
    )


def _resolve_image(img_tag, source_path: Path):
    src = img_tag.get("src", "")
    if not src:
        return None, None

    max_w = 6.0 * inch
    max_h = 8.0 * inch

    try:
        if src.startswith("data:"):
            header, _, b64data = src.partition(",")
            if "base64" not in header:
                return None, f"Skipped a non-base64 data: image reference: {src[:40]}..."
            raw = base64.b64decode(b64data)
            pil_img = Image.open(io.BytesIO(raw))
            pil_img.load()
        elif src.startswith(("http://", "https://", "//")):
            return None, f"External image not fetched (network access is disabled): {src}"
        else:
            candidate = (source_path.parent / src).resolve()
            try:
                candidate.relative_to(source_path.parent.resolve())
            except ValueError:
                return None, f"Skipped a local image path outside the document folder: {src}"
            if not candidate.exists():
                return None, f"Referenced local image was not found: {src}"
            pil_img = Image.open(candidate)
            pil_img.load()
    except (UnidentifiedImageError, OSError, ValueError, base64.binascii.Error) as exc:
        return None, f"Could not load referenced image ({src}): {exc}"

    if pil_img.mode not in ("RGB", "L"):
        pil_img = pil_img.convert("RGB")

    w, h = pil_img.size
    scale = min(max_w / w, max_h / h, 1.0)
    return RLImage(io.BytesIO(_to_png_bytes(pil_img)), width=w * scale, height=h * scale), None


def _to_png_bytes(pil_img: Image.Image) -> bytes:
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    return buf.getvalue()
