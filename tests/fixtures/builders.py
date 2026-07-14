"""Synthetic document builders used by the automated test suite.

Every fixture used in tests is generated programmatically here -- no
real borrower data is ever used or required.
"""

from __future__ import annotations

import email.policy
import zipfile
from email.message import EmailMessage
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas


def make_pdf(path: Path, pages: int = 1, text_prefix: str = "Page", metadata: dict | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    for i in range(pages):
        c.setFont("Helvetica", 12)
        c.drawString(72, 700, f"{text_prefix} {i + 1} of {pages}")
        c.showPage()
    c.save()

    if metadata:
        reader = PdfReader(str(path))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.add_metadata(metadata)
        with path.open("wb") as fh:
            writer.write(fh)
    return path


def make_signature_package(path: Path, borrower_name: str, common_pages: int = 19) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    for i in range(common_pages):
        c.setFont("Helvetica", 12)
        c.drawString(72, 700, f"Disclosure page {i + 1} of {common_pages + 1} - shared content")
        c.showPage()
    c.setFont("Helvetica", 12)
    c.drawString(72, 700, f"Signature page - Borrower: {borrower_name}")
    c.showPage()
    c.save()
    return path


def make_corrupt_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\nThis is not a valid PDF body.\n%%EOF-BUT-NOT-REALLY")
    return path


def make_password_protected_pdf(path: Path, password: str = "secret123", pages: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    plain = path.with_suffix(".plain.pdf")
    make_pdf(plain, pages=pages, text_prefix="Protected page")
    reader = PdfReader(str(plain))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(user_password=password, owner_password=None)
    with path.open("wb") as fh:
        writer.write(fh)
    plain.unlink()
    return path


def make_image(path: Path, fmt: str = "PNG", size: tuple[int, int] = (300, 200), color=(200, 30, 30)) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color)
    img.save(path, format=fmt)
    return path


def make_multipage_tiff(path: Path, frames: int = 3, size: tuple[int, int] = (200, 150)) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    images = [Image.new("RGB", size, (10 * i, 100, 200 - 10 * i)) for i in range(frames)]
    images[0].save(path, format="TIFF", save_all=True, append_images=images[1:])
    return path


def make_txt(path: Path, content: str, encoding: str = "utf-8") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode(encoding))
    return path


def make_html(path: Path, body_html: str, title: str = "Test Document") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""<!DOCTYPE html>
<html><head><title>{title}</title>
<script>fetch('https://example.com/track');</script>
</head><body>{body_html}</body></html>"""
    path.write_text(content, encoding="utf-8")
    return path


def make_docx(path: Path, paragraphs: list[str], table_rows: list[list[str]] | None = None) -> Path:
    import docx

    path.parent.mkdir(parents=True, exist_ok=True)
    document = docx.Document()
    document.add_heading(paragraphs[0] if paragraphs else "Document", level=1)
    for para in paragraphs[1:]:
        document.add_paragraph(para)
    if table_rows:
        table = document.add_table(rows=0, cols=len(table_rows[0]))
        for row in table_rows:
            cells = table.add_row().cells
            for i, value in enumerate(row):
                cells[i].text = value
    document.save(str(path))
    return path


def make_xlsx(path: Path, rows: list[list[str]], sheet_name: str = "Sheet1") -> Path:
    import openpyxl

    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    wb.save(str(path))
    return path


def make_eml(
    path: Path,
    subject: str = "Test message",
    from_addr: str = "sender@example.com",
    to_addr: str = "recipient@example.com",
    body: str = "This is the message body.",
    attachments: list[tuple[str, bytes, str, str]] | None = None,
) -> Path:
    """attachments: list of (filename, data, maintype, subtype)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    msg = EmailMessage(policy=email.policy.default)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(body)

    for filename, data, maintype, subtype in attachments or []:
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    path.write_bytes(msg.as_bytes())
    return path


def make_zip(path: Path, entries: list[tuple[str, bytes]]) -> Path:
    """entries preserved in the exact order given."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    return path


def read_pdf_page_count(path: Path) -> int:
    return len(PdfReader(str(path)).pages)


def read_pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
