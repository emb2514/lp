"""HTML/HTM-to-PDF conversion.

Renders entirely offline: no network request is ever made, no remote
script/stylesheet/font/image is fetched. Only inline `data:` images and
images referenced by a local relative path that already exists on disk
next to the source file are embedded; anything else produces a recorded
warning rather than a silent gap.
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
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer
from reportlab.platypus import Image as RLImage

from ..models import ConversionOutcome, ConversionResult
from .base import failed_result, validate_pdf

NAME = "reportlab-html-basic"

_BLOCK_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "td", "th"]
_HEADING_SIZES = {"h1": 18, "h2": 16, "h3": 14, "h4": 13, "h5": 12, "h6": 11}


def can_handle(extension: str) -> bool:
    return extension in (".html", ".htm")


def convert(occurrence, dest_path: Path, config, workspace=None) -> ConversionResult:
    source = occurrence.extracted_path
    if source is None or not source.exists():
        return failed_result("Original HTML bytes were not available to convert.")

    warnings: list[str] = []

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
        if plain_text:
            warnings.append(
                "No recognized HTML structure was found; rendered the page's plain text instead."
            )
            style = ParagraphStyle(name="Mono", fontName="Courier", fontSize=9, leading=11)
            flowables = [Preformatted(plain_text, style)]

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
        outcome=ConversionOutcome.SUCCESS,
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
