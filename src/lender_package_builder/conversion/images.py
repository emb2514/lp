"""Image-to-PDF conversion for JPG/PNG/BMP/TIFF, including multi-frame
TIFF and EXIF orientation.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from ..models import ConversionOutcome, ConversionResult
from .base import failed_result, validate_pdf

NAME = "pillow-image"

_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}


def can_handle(extension: str) -> bool:
    return extension in _EXTENSIONS


def convert(occurrence, dest_path: Path, config, workspace=None) -> ConversionResult:
    source = occurrence.extracted_path
    if source is None or not source.exists():
        return failed_result("Original image bytes were not available to convert.")

    warnings: list[str] = []

    try:
        img = Image.open(source)
    except (UnidentifiedImageError, OSError) as exc:
        return failed_result(f"Could not open as a valid image: {exc}")

    try:
        frames = list(ImageSequence.Iterator(img))
        if not frames:
            return failed_result("Image file contained no readable frames.")
    except (OSError, ValueError) as exc:
        return failed_result(f"Could not read image frames: {exc}")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    page_w, page_h = LETTER
    margin = 0.5 * inch
    max_w = page_w - 2 * margin
    max_h = page_h - 2 * margin

    c = canvas.Canvas(str(dest_path), pagesize=LETTER)
    pages_written = 0

    for frame in frames:
        try:
            oriented = ImageOps.exif_transpose(frame)
            if oriented is None:
                oriented = frame
        except (OSError, ValueError):
            oriented = frame
            warnings.append("Could not apply EXIF orientation to one frame; used as-is.")

        if oriented.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", oriented.size, (255, 255, 255))
            rgba = oriented.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            flat = background
        elif oriented.mode != "RGB":
            flat = oriented.convert("RGB")
        else:
            flat = oriented

        img_w, img_h = flat.size
        if img_w <= 0 or img_h <= 0:
            warnings.append("Skipped a zero-size frame.")
            continue

        scale = min(max_w / img_w, max_h / img_h, 1.0)
        draw_w = img_w * scale
        draw_h = img_h * scale
        x = (page_w - draw_w) / 2
        y = (page_h - draw_h) / 2

        c.drawImage(
            _PilImageReader(flat),
            x,
            y,
            width=draw_w,
            height=draw_h,
            preserveAspectRatio=True,
            anchor="c",
        )
        c.showPage()
        pages_written += 1

    if pages_written == 0:
        return failed_result("No renderable frames were found in this image.", warnings=warnings)

    c.save()

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


def _PilImageReader(pil_image: Image.Image):
    from reportlab.lib.utils import ImageReader

    return ImageReader(pil_image)
