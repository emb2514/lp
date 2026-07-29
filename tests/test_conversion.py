from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time

import pytest

from fixtures.builders import (
    make_corrupt_pdf,
    make_docx,
    make_eml,
    make_html,
    make_image,
    make_multipage_tiff,
    make_password_protected_pdf,
    make_pdf,
    make_txt,
    make_xlsx,
    read_pdf_page_count,
)

from lender_package_builder.cancellation import CancellationToken
from lender_package_builder.config import AppConfig
from lender_package_builder.conversion import office
from lender_package_builder.models import ProcessingStatus


def _doc(run, filename):
    matches = [o for o in run.occurrences if o.original_filename == filename]
    assert len(matches) == 1, f"expected exactly one occurrence named {filename}"
    return matches[0]


# TEST 11 - UNSUPPORTED FILE
def test_unsupported_file_becomes_placeholder(tmp_path, run_build):
    folder = tmp_path / "input"
    (folder).mkdir(parents=True, exist_ok=True)
    (folder / "weird_file.xyz").write_bytes(b"some binary blob that is not a supported type")

    run = run_build(folder, keep_temp=True)
    occ = _doc(run, "weird_file.xyz")

    assert occ.status == ProcessingStatus.UNCONVERTED_PLACEHOLDER
    assert occ.converted_pdf_path is not None and occ.converted_pdf_path.exists()
    assert occ.unconverted_copy_path is not None and occ.unconverted_copy_path.exists()
    assert occ.unconverted_copy_path.read_bytes() == (folder / "weird_file.xyz").read_bytes()

    og_ids = {doc_id for part in run.og_parts for doc_id in part.document_ids}
    assert occ.document_id in og_ids

    report = (run.output_path / "Reports" / "Processing_Report.txt").read_text()
    assert "weird_file.xyz" in report


# TEST 12 - CORRUPT PDF
def test_corrupt_pdf_becomes_placeholder_no_crash(tmp_path, run_build):
    folder = tmp_path / "input"
    make_corrupt_pdf(folder / "broken.pdf")

    run = run_build(folder)
    occ = _doc(run, "broken.pdf")

    assert occ.status == ProcessingStatus.UNCONVERTED_PLACEHOLDER
    assert occ.unconverted_copy_path is not None and occ.unconverted_copy_path.exists()
    assert run.success is True  # one bad document must not fail the whole run


# TEST 13 - PASSWORD-PROTECTED PDF
def test_password_protected_pdf_becomes_placeholder(tmp_path, run_build):
    folder = tmp_path / "input"
    make_password_protected_pdf(folder / "locked.pdf", password="not-empty")

    run = run_build(folder)
    occ = _doc(run, "locked.pdf")

    assert occ.status == ProcessingStatus.UNCONVERTED_PLACEHOLDER
    assert occ.unconverted_copy_path is not None and occ.unconverted_copy_path.exists()
    assert run.success is True


# TEST 21 - FAILED CONVERSION CONTINUES, ORDER PRESERVED
def test_failed_conversion_between_two_valid_documents_preserves_order(tmp_path, run_build):
    folder = tmp_path / "input"
    make_txt(folder / "1_first.txt", "first valid document\n")
    make_corrupt_pdf(folder / "2_broken.pdf")
    make_txt(folder / "3_second.txt", "second valid document\n")

    run = run_build(folder)

    first = _doc(run, "1_first.txt")
    broken = _doc(run, "2_broken.pdf")
    second = _doc(run, "3_second.txt")

    assert first.traversal_index < broken.traversal_index < second.traversal_index
    assert first.status == ProcessingStatus.CONVERTED
    assert broken.status == ProcessingStatus.UNCONVERTED_PLACEHOLDER
    assert second.status == ProcessingStatus.CONVERTED

    og_flat = [doc_id for part in run.og_parts for doc_id in part.document_ids]
    assert og_flat.index(first.document_id) < og_flat.index(broken.document_id) < og_flat.index(second.document_id)
    assert run.success is True


# TEST 19 - BASIC CONVERSIONS
def test_basic_conversions_across_formats(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "doc.pdf", pages=2)
    make_image(folder / "photo.jpg", fmt="JPEG")
    make_image(folder / "photo.png", fmt="PNG")
    make_multipage_tiff(folder / "scan.tiff", frames=3)
    make_txt(folder / "notes.txt", "Line one\nLine two\n" + ("x" * 300) + "\n")
    make_html(folder / "page.html", "<h1>Title</h1><p>Some paragraph text.</p>")
    make_docx(folder / "letter.docx", ["Letter Title", "First paragraph.", "Second paragraph."])
    make_xlsx(folder / "sheet.xlsx", [["Name", "Amount"], ["Alice", "100"], ["Bob", "200"]])
    make_eml(folder / "message.eml", subject="Hello", body="Body text of the email.")

    run = run_build(folder, keep_temp=True)

    expected_files = [
        "doc.pdf", "photo.jpg", "photo.png", "scan.tiff",
        "notes.txt", "page.html", "letter.docx", "sheet.xlsx", "message.eml",
    ]
    for filename in expected_files:
        occ = _doc(run, filename)
        assert occ.converted_pdf_path is not None, filename
        assert occ.converted_pdf_path.exists(), filename
        assert occ.converted_page_count and occ.converted_page_count >= 1, filename
        # Never silently omitted: every file has one of the two valid terminal statuses.
        assert occ.status in (ProcessingStatus.CONVERTED, ProcessingStatus.UNCONVERTED_PLACEHOLDER)

    tiff_occ = _doc(run, "scan.tiff")
    assert tiff_occ.converted_page_count == 3  # multi-frame TIFF preserves all frames

    assert run.success is True


# TEST 20 - EMAIL ATTACHMENT BOUNDARY
def test_email_attachments_stay_inside_parent_pdf(tmp_path, run_build):
    folder = tmp_path / "input"
    make_eml(
        folder / "with_attachments.eml",
        subject="Loan documents attached",
        body="Please see the attached documents.",
        attachments=[
            ("attachment_one.txt", b"Attachment one contents.", "text", "plain"),
            ("attachment_two.txt", b"Attachment two contents, different.", "text", "plain"),
        ],
    )

    run = run_build(folder, keep_temp=True)

    email_occ = _doc(run, "with_attachments.eml")
    assert email_occ.status == ProcessingStatus.CONVERTED
    assert email_occ.converted_page_count >= 1

    # Exactly one top-level occurrence exists for the email; attachments never
    # become independent top-level documents.
    assert len(run.occurrences) == 1

    og_flat = [doc_id for part in run.og_parts for doc_id in part.document_ids]
    assert og_flat == [email_occ.document_id]

    text = ""
    from pypdf import PdfReader

    reader = PdfReader(str(email_occ.converted_pdf_path))
    for page in reader.pages:
        text += page.extract_text() or ""
    assert "attachment_one.txt" in text
    assert "attachment_two.txt" in text
    assert "Attachment one contents." in text
    assert "Attachment two contents, different." in text


# Additional coverage: a malformed .msg file must never crash the run.
# Genuine .msg files require Microsoft's binary OLE Compound File format;
# without Outlook or a real-world sample, this test exercises the "cannot
# be parsed" path (extract_msg raises) and confirms the standard
# unconverted-file procedure takes over cleanly.
def test_malformed_msg_becomes_placeholder_no_crash(tmp_path, run_build):
    folder = tmp_path / "input"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "broken.msg").write_bytes(b"not a real compound file msg structure")

    run = run_build(folder)
    occ = _doc(run, "broken.msg")

    assert occ.status == ProcessingStatus.UNCONVERTED_PLACEHOLDER
    assert occ.unconverted_copy_path is not None and occ.unconverted_copy_path.exists()
    assert run.success is True


# Additional coverage: force the pure-Python fallback renderer (no
# LibreOffice/Office backend) and confirm it produces valid output and
# is honestly labeled as a fallback in the report, per spec section I.
def test_docx_xlsx_fallback_renderer_when_no_office_backend(tmp_path, run_build):
    folder = tmp_path / "input"
    make_docx(folder / "letter.docx", ["Letter Title", "First paragraph.", "Second paragraph."],
               table_rows=[["Name", "Amount"], ["Alice", "100"]])
    make_xlsx(folder / "sheet.xlsx", [["Name", "Amount"], ["Alice", "100"], ["Bob", "200"]])

    cfg = AppConfig()
    cfg.office_backend_order = ("fallback",)

    run = run_build(folder, config=cfg)

    docx_occ = _doc(run, "letter.docx")
    xlsx_occ = _doc(run, "sheet.xlsx")

    assert docx_occ.status == ProcessingStatus.CONVERTED
    assert docx_occ.used_fallback_renderer is True
    assert docx_occ.conversion_backend == "fallback-docx"
    assert any("fallback" in w.lower() for w in docx_occ.conversion_warnings)

    assert xlsx_occ.status == ProcessingStatus.CONVERTED
    assert xlsx_occ.used_fallback_renderer is True
    assert xlsx_occ.conversion_backend == "fallback-xlsx"
    assert any("fallback" in w.lower() for w in xlsx_occ.conversion_warnings)

    report = (run.output_path / "Reports" / "Processing_Report.txt").read_text()
    assert "fallback-docx" in report
    assert "fallback-xlsx" in report


# Additional coverage: when LibreOffice IS available (true on this build/
# test machine), DOCX/XLSX should be converted through it for full
# fidelity rather than silently falling back.
@pytest.mark.skipif(
    shutil.which("soffice") is None and shutil.which("libreoffice") is None,
    reason="LibreOffice not installed on this machine",
)
def test_docx_xlsx_use_libreoffice_when_available(tmp_path, run_build):
    folder = tmp_path / "input"
    make_docx(folder / "letter.docx", ["Letter Title", "A paragraph of text."])
    make_xlsx(folder / "sheet.xlsx", [["Name", "Amount"], ["Alice", "100"]])

    run = run_build(folder)  # default backend order prefers libreoffice

    docx_occ = _doc(run, "letter.docx")
    xlsx_occ = _doc(run, "sheet.xlsx")

    assert docx_occ.conversion_backend == "libreoffice"
    assert docx_occ.used_fallback_renderer is False
    assert xlsx_occ.conversion_backend == "libreoffice"
    assert xlsx_occ.used_fallback_renderer is False


# Additional coverage: legacy .doc/.xls binary formats, converted through
# the real local LibreOffice backend (the only converter Stage 1 can
# safely test for this format on a non-Windows machine).
@pytest.mark.skipif(
    shutil.which("soffice") is None and shutil.which("libreoffice") is None,
    reason="LibreOffice not installed on this machine",
)
def test_legacy_doc_and_xls_convert_via_libreoffice(tmp_path, run_build):
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    folder = tmp_path / "input"
    make_docx(folder / "legacy_source.docx", ["Legacy Title", "Some legacy content."])
    make_xlsx(folder / "legacy_source2.xlsx", [["A", "B"], ["1", "2"]])

    subprocess.run(
        [soffice, "--headless", "--convert-to", "doc", "--outdir", str(folder),
         str(folder / "legacy_source.docx")],
        capture_output=True, timeout=60, check=True,
    )
    subprocess.run(
        [soffice, "--headless", "--convert-to", "xls", "--outdir", str(folder),
         str(folder / "legacy_source2.xlsx")],
        capture_output=True, timeout=60, check=True,
    )
    (folder / "legacy_source.docx").unlink()
    (folder / "legacy_source2.xlsx").unlink()
    assert (folder / "legacy_source.doc").exists()
    assert (folder / "legacy_source2.xls").exists()

    run = run_build(folder)

    doc_occ = _doc(run, "legacy_source.doc")
    xls_occ = _doc(run, "legacy_source2.xls")

    assert doc_occ.status == ProcessingStatus.CONVERTED
    assert doc_occ.conversion_backend == "libreoffice"
    assert xls_occ.status == ProcessingStatus.CONVERTED
    assert xls_occ.conversion_backend == "libreoffice"


# CANCELLATION RESPONSIVENESS (real user report): pressing "Cancel
# Processing" while a LibreOffice conversion was running used to leave
# the app showing "Cancelling..." for minutes, because the old
# `subprocess.run(..., timeout=180)` call had no way to notice a
# cancellation request until the whole call returned. `_convert_with_
# libreoffice` now polls the running process every
# `_CANCELLATION_POLL_INTERVAL_SECONDS` and kills it as soon as
# cancellation is requested. `subprocess.Popen` is monkeypatched to spawn
# a long-running, harmless stand-in process instead of the real `cmd`
# passed to it, so this proves the kill-on-cancel behavior directly and
# deterministically without depending on a real LibreOffice install or
# racing how fast an actual conversion happens to run.
def test_libreoffice_conversion_is_killed_promptly_once_cancelled(tmp_path, monkeypatch):
    source = tmp_path / "source.docx"
    source.write_bytes(b"not a real docx -- the stand-in process never reads it")
    dest = tmp_path / "converted.pdf"

    original_popen = subprocess.Popen

    def _fake_popen(cmd, **kwargs):
        return original_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)

    monkeypatch.setattr(office.subprocess, "Popen", _fake_popen)

    token = CancellationToken()
    threading.Timer(0.3, token.request).start()

    start = time.perf_counter()
    result = office._convert_with_libreoffice("soffice-stand-in", source, dest, token)
    elapsed = time.perf_counter() - start

    assert result is None
    assert elapsed < 5.0, (
        f"took {elapsed:.1f}s to notice cancellation -- expected well under the 30s the stand-in "
        f"process sleeps for, and far under the old 180s timeout"
    )


@pytest.mark.skipif(
    shutil.which("soffice") is None and shutil.which("libreoffice") is None,
    reason="LibreOffice not installed on this machine",
)
def test_libreoffice_conversion_completes_normally_without_cancellation(tmp_path):
    # Proves the Popen-based polling rewrite still produces a correct
    # result for a normal, quick, never-cancelled conversion.
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    source = tmp_path / "real.docx"
    make_docx(source, ["Title", "Some paragraph text."])
    dest = tmp_path / "converted.pdf"

    token = CancellationToken()  # never requested
    result = office._convert_with_libreoffice(soffice, source, dest, token)

    assert result is not None
    assert result.outcome.value == "success"
    assert dest.exists()
