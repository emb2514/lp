"""Regression tests for two related real user reports about how HTML
and email content gets turned into PDF pages.

Report 1 ("majority of those pages turned into like code"): ordinary
HTML documents and email bodies were rendering with a monospace font
(Courier, inside a `Preformatted` flowable) instead of normal
proportional-font paragraphs -- reads exactly like a block of code to
anyone looking at the actual page. Two independent causes:
  - `conversion/html.py`'s block-tag detection never recognized <div>,
    so real-world HTML (Outlook/Word "Save As HTML" especially, which
    wraps nearly everything in <div>/<span>) fell through to the
    monospace last-resort branch every time.
  - `conversion/email.py` rendered EVERY email's body with a monospace
    font unconditionally -- not a fallback, the only path that existed.

Report 2, after report 1's fix ("i need the HTML files to be 'printed'
to PDF... i need the actual file, like the one that looks like the
file... this needs to be a legible document"): even with a normal font,
a hand-reconstructed text-extraction render is NOT the same as a real
"Print to PDF" render -- no layout, no table borders, no background
colors. `html.py`'s `convert()` now tries a real LibreOffice render
FIRST (the same mechanism DOCX/XLSX already use), and only falls back
to the hand-reconstructed renderer if LibreOffice isn't available.
"""

from __future__ import annotations

from pathlib import Path

from fixtures.builders import make_eml, make_html, read_pdf_text
from pypdf import PdfReader

from lender_package_builder.config import AppConfig
from lender_package_builder.conversion import email as email_conv
from lender_package_builder.conversion import html as html_conv
from lender_package_builder.conversion import office as office_conv
from lender_package_builder.models import ProcessingStatus, SourceOccurrence


def _fonts_used(pdf_path: Path) -> set[str]:
    reader = PdfReader(str(pdf_path))
    fonts: set[str] = set()
    for page in reader.pages:
        resources = page.get("/Resources")
        if not resources:
            continue
        font_dict = resources.get("/Font")
        if not font_dict:
            continue
        for font_ref in font_dict.values():
            base_font = font_ref.get_object().get("/BaseFont")
            if base_font:
                fonts.add(str(base_font))
    return fonts


def _html_occurrence(path: Path) -> SourceOccurrence:
    return SourceOccurrence(
        document_id="D1",
        traversal_index=1,
        original_filename=path.name,
        original_relative_path=path.name,
        original_extension=".html",
        original_size_bytes=path.stat().st_size,
        status=ProcessingStatus.DISCOVERED,
        extracted_path=path,
    )


def _eml_occurrence(path: Path) -> SourceOccurrence:
    return SourceOccurrence(
        document_id="D1",
        traversal_index=1,
        original_filename=path.name,
        original_relative_path=path.name,
        original_extension=".eml",
        original_size_bytes=path.stat().st_size,
        status=ProcessingStatus.DISCOVERED,
        extracted_path=path,
    )


# ---------------------------------------------------------------------
# convert() dispatcher -- prefers a real LibreOffice render, falls back
# only when LibreOffice genuinely isn't available.
# ---------------------------------------------------------------------


def test_convert_prefers_a_real_libreoffice_render_when_available(tmp_path):
    body_html = (
        "<style>.hdr{background:#003366;color:#fff;padding:6px;}</style>"
        "<div class='hdr'><h2>Lender Correspondence</h2></div>"
        "<div>Dear Borrower,</div>"
        "<table><tr><th>Item</th><th>Amount</th></tr>"
        "<tr><td>Loan Amount</td><td>$350,000.00</td></tr></table>"
    )
    source = make_html(tmp_path / "letter.html", body_html)
    occ = _html_occurrence(source)
    dest = tmp_path / "out.pdf"

    result = html_conv.convert(occ, dest, AppConfig())

    assert result.outcome.value == "success"
    assert result.backend == "libreoffice"
    text = read_pdf_text(dest)
    assert "Lender Correspondence" in text
    assert "Loan Amount" in text
    assert "$350,000.00" in text


def test_convert_falls_back_when_libreoffice_is_not_available(tmp_path, monkeypatch):
    monkeypatch.setattr(office_conv, "find_libreoffice", lambda: None)
    source = make_html(tmp_path / "letter.html", "<h1>Title</h1><p>A paragraph of real content.</p>")
    occ = _html_occurrence(source)
    dest = tmp_path / "out.pdf"

    result = html_conv.convert(occ, dest, AppConfig())

    assert result.outcome.value == "fallback_success"
    assert result.backend == html_conv.NAME
    assert any("High-fidelity conversion (LibreOffice) was not available" in w for w in result.warnings)
    text = read_pdf_text(dest)
    assert "A paragraph of real content" in text


def test_convert_falls_back_when_libreoffice_is_present_but_fails_this_file(tmp_path, monkeypatch):
    monkeypatch.setattr(office_conv, "find_libreoffice", lambda: "soffice-stand-in")
    monkeypatch.setattr(office_conv, "convert_with_libreoffice", lambda *a, **k: None)
    source = make_html(tmp_path / "letter.html", "<h1>Title</h1><p>A paragraph of real content.</p>")
    occ = _html_occurrence(source)
    dest = tmp_path / "out.pdf"

    result = html_conv.convert(occ, dest, AppConfig())

    assert result.outcome.value == "fallback_success"
    text = read_pdf_text(dest)
    assert "A paragraph of real content" in text


# ---------------------------------------------------------------------
# _convert_with_fallback_renderer -- exercised directly so its own
# div-handling/font behavior is covered regardless of whether this test
# machine happens to have LibreOffice installed.
# ---------------------------------------------------------------------


def test_fallback_renderer_handles_div_based_html_not_monospace(tmp_path):
    # Real-world Outlook/Word HTML export shape: everything in <div>,
    # no <p> at all.
    body_html = (
        "<div>Dear Borrower,</div>"
        "<div>Please find enclosed your final Closing Disclosure for review.</div>"
        "<div>Let us know if you have any questions.</div>"
    )
    source = make_html(tmp_path / "letter.html", body_html)
    dest = tmp_path / "out.pdf"

    result = html_conv._convert_with_fallback_renderer(source, dest)

    assert result.outcome.value == "fallback_success"
    assert not any("No recognized HTML structure" in w for w in result.warnings)

    text = read_pdf_text(dest)
    assert "Dear Borrower" in text
    assert "Closing Disclosure for review" in text

    fonts = _fonts_used(dest)
    assert not any("Courier" in f for f in fonts), f"expected no monospace font, got {fonts}"


def test_fallback_renderer_nested_divs_do_not_duplicate_content(tmp_path):
    # A layout wrapper div containing nested divs -- the wrapper must
    # never ALSO render its full text (which would duplicate every
    # nested div's content).
    body_html = (
        "<div class='wrapper'>"
        "<div>First unique sentence about the loan terms.</div>"
        "<div>Second unique sentence about the closing date.</div>"
        "</div>"
    )
    source = make_html(tmp_path / "nested.html", body_html)
    dest = tmp_path / "out.pdf"

    result = html_conv._convert_with_fallback_renderer(source, dest)
    assert result.outcome.value == "fallback_success"

    text = read_pdf_text(dest)
    assert text.count("First unique sentence about the loan terms") == 1
    assert text.count("Second unique sentence about the closing date") == 1


def test_fallback_renderer_with_no_block_tags_at_all_still_avoids_monospace_font(tmp_path):
    # No div, no p, no heading -- text sits directly in <body>. Must
    # still hit the last-resort branch, but that branch must no longer
    # use a monospace font either.
    source = make_html(tmp_path / "plain.html", "Just some bare text with no wrapping tags at all.")
    dest = tmp_path / "out.pdf"

    result = html_conv._convert_with_fallback_renderer(source, dest)
    assert result.outcome.value == "fallback_success"
    assert any("No recognized HTML structure" in w for w in result.warnings)

    text = read_pdf_text(dest)
    assert "Just some bare text" in text

    fonts = _fonts_used(dest)
    assert not any("Courier" in f for f in fonts), f"expected no monospace font, got {fonts}"


def test_fallback_renderer_ordinary_paragraph_html_still_works(tmp_path):
    # The original, already-working structured case (h1/p) must keep
    # working exactly as before.
    source = make_html(tmp_path / "structured.html", "<h1>Title</h1><p>A paragraph of real content.</p>")
    dest = tmp_path / "out.pdf"

    result = html_conv._convert_with_fallback_renderer(source, dest)
    assert result.outcome.value == "fallback_success"
    text = read_pdf_text(dest)
    assert "Title" in text
    assert "A paragraph of real content" in text


# ---------------------------------------------------------------------
# email.py -- message body rendering
# ---------------------------------------------------------------------


def test_email_body_renders_with_proportional_font_not_monospace(tmp_path):
    source = make_eml(
        tmp_path / "message.eml",
        subject="Loan update",
        body="Hi there,\n\nYour loan is progressing well. We expect to close next week.\n\nThanks.",
    )
    occ = _eml_occurrence(source)
    dest = tmp_path / "out.pdf"

    result = email_conv.convert(occ, dest, AppConfig())
    assert result.outcome.value == "success"

    text = read_pdf_text(dest)
    assert "progressing well" in text

    fonts = _fonts_used(dest)
    assert not any("Courier" in f for f in fonts), f"expected no monospace font, got {fonts}"


def test_email_body_with_manual_line_wrapping_is_reflowed_into_one_paragraph(tmp_path):
    # Simulates a mail client's manual word-wrap: one logical sentence
    # split across several short lines with no blank line between them
    # -- must be rejoined into one paragraph, not kept as separate
    # preformatted lines.
    wrapped_body = "This is a single long sentence\nthat was manually wrapped\nacross several short lines."
    source = make_eml(tmp_path / "wrapped.eml", subject="Wrapped", body=wrapped_body)
    occ = _eml_occurrence(source)
    dest = tmp_path / "out.pdf"

    result = email_conv.convert(occ, dest, AppConfig())
    assert result.outcome.value == "success"

    text = read_pdf_text(dest).replace("\n", " ")
    assert "This is a single long sentence" in text
    assert "that was manually wrapped" in text
    assert "across several short lines" in text
