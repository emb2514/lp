from __future__ import annotations

from pypdf import PdfReader

from fixtures.builders import make_pdf, make_txt, make_zip

from lender_package_builder.config import AppConfig


# TEST 18 - SINGLE MERGED PDF SAFE MODE
def test_single_merged_pdf_stays_one_indivisible_document(tmp_path, run_build):
    folder = tmp_path / "input"
    path = folder / "combined_forms.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)

    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=LETTER)
    sections = ["FORM A - APPLICATION", "FORM B - DISCLOSURE", "FORM C - SIGNATURE"]
    for section in sections:
        for i in range(5):
            c.setFont("Helvetica", 12)
            c.drawString(72, 700, f"{section} - page {i + 1}")
            c.showPage()
    c.save()

    run = run_build(folder)

    assert len(run.occurrences) == 1
    occ = run.occurrences[0]
    assert occ.converted_page_count == 15

    og_flat = [doc_id for part in run.og_parts for doc_id in part.document_ids]
    final_flat = [doc_id for part in run.final_parts for doc_id in part.document_ids]
    assert og_flat == [occ.document_id]
    assert final_flat == [occ.document_id]

    assert sum(p.page_count for p in run.og_parts) == 15
    assert sum(p.page_count for p in run.final_parts) == 15
    assert run.success is True


# TEST 22 - FULL END-TO-END RECONCILIATION
def test_full_end_to_end_reconciliation(tmp_path, run_build):
    input_dir = tmp_path / "package_build"
    input_dir.mkdir()

    inner_zip = input_dir / "inner.zip"
    make_zip(
        inner_zip,
        [
            ("nested_unique.txt", b"nested unique content"),
        ],
    )
    inner_bytes = inner_zip.read_bytes()
    inner_zip.unlink()

    oversized_pdf_path = tmp_path / "_oversized_source.pdf"
    make_pdf(oversized_pdf_path, pages=210, text_prefix="Oversized page")
    oversized_bytes = oversized_pdf_path.read_bytes()

    entries = [
        ("unique_one.txt", b"unique document one"),
        ("unique_two.txt", b"unique document two"),
        ("duplicate_original.txt", b"this content repeats exactly"),
        ("duplicate_copy.txt", b"this content repeats exactly"),
        ("version_a.txt", b"version with some content A"),
        ("version_b.txt", b"version with some content B"),
        ("unsupported_file.xyz", b"totally unsupported binary content"),
        ("oversized.pdf", oversized_bytes),
        ("nested.zip", inner_bytes),
    ]
    zip_path = input_dir / "lender_package.zip"
    make_zip(zip_path, entries)

    cfg = AppConfig()
    cfg.page_limit = 200
    cfg.size_limit_mb = 5000

    run = run_build(zip_path, config=cfg)

    by_name = {}
    for occ in run.occurrences:
        by_name.setdefault(occ.original_filename, []).append(occ)

    assert len(by_name["unique_one.txt"]) == 1
    assert len(by_name["duplicate_original.txt"]) == 1
    assert len(by_name["duplicate_copy.txt"]) == 1
    assert by_name["duplicate_copy.txt"][0].is_duplicate is True
    assert by_name["duplicate_original.txt"][0].is_duplicate is False

    assert by_name["version_a.txt"][0].is_duplicate is False
    assert by_name["version_b.txt"][0].is_duplicate is False

    unsupported = by_name["unsupported_file.xyz"][0]
    assert unsupported.status.value == "unconverted_placeholder"
    assert unsupported.unconverted_copy_path.exists()

    oversized = by_name["oversized.pdf"][0]
    assert oversized.converted_page_count == 210

    oversized_parts = [p for p in run.og_parts if oversized.document_id in p.document_ids]
    assert len(oversized_parts) == 1
    assert oversized_parts[0].is_oversized is True
    assert len(oversized_parts[0].document_ids) == 1

    assert "nested_unique.txt" in by_name
    assert by_name["nested_unique.txt"][0].archive_chain_display.startswith(zip_path.name)

    # OG / Final reconciliation
    og_doc_count = sum(len(p.document_ids) for p in run.og_parts)
    final_doc_count = sum(len(p.document_ids) for p in run.final_parts)
    assert og_doc_count == len(run.occurrences)  # nothing ignored in this fixture
    assert final_doc_count == og_doc_count - 1  # exactly one duplicate removed

    # Every generated PDF opens and has pages.
    for part in run.og_parts + run.final_parts:
        reader = PdfReader(str(part.file_path))
        assert len(reader.pages) >= 1

    # Reports reconcile.
    report_text = (run.output_path / "Reports" / "Processing_Report.txt").read_text()
    assert f"OG document count:      {og_doc_count}" in report_text
    assert f"Final document count:   {final_doc_count}" in report_text

    # All required integrity checks pass.
    failed = [c for c in run.integrity_checks if not c.passed]
    assert not failed, f"Integrity checks failed: {[(c.name, c.detail) for c in failed]}"
    assert run.success is True
