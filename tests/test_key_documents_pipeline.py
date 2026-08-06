"""Pipeline-level tests for MILESTONE 4's key-document locator:
extraction placement/naming through a real build, page locations after
duplicate removal and after a manual review exclusion, split-package
page numbering, and the wet-signature status messaging in the report.
"""

from __future__ import annotations

from pathlib import Path

from fixtures.builders import make_pdf_with_ink_signature, make_pdf_with_pages

from lender_package_builder import key_documents, naming, review_decisions
from lender_package_builder.config import AppConfig
from lender_package_builder.models import PackageIdentity, UncertainMatch

_CD_TEXT = "Closing Disclosure\nLoan Terms\nProjected Payments\nBorrower: Michael True"


def _identity() -> PackageIdentity:
    return PackageIdentity(last_name="True", first_name="Michael", loan_number="6192278785")


# TEST 1 - extraction lands directly in Important Docs (never Final --
# that folder holds only the OG and Final Lender Package PDFs) with the
# exact required naming convention, for a Closing Disclosure embedded
# inside a larger document (pages 3-4 of a 5-page filing).
def test_extraction_from_a_larger_pdf_uses_exact_filename(tmp_path, run_build):
    folder = tmp_path / "input"
    folder.mkdir()
    make_pdf_with_pages(
        folder / "package.pdf",
        [
            "Cover page",
            "Table of contents",
            _CD_TEXT,
            _CD_TEXT + "\nPage 2 of the disclosure",
            "Final signature page",
        ],
    )

    run = run_build(folder, identity=_identity())
    assert run.success is True

    cd_matches = [m for m in run.key_document_matches if m.category == "closing_disclosure"]
    assert len(cd_matches) == 1
    match = cd_matches[0]
    assert match.document_page_range == (3, 4)
    assert match.extracted_filename == "True, Michael, Closing Disclosure, Unsigned, 6192278785.pdf"

    extracted_path = run.output_path / naming.IMPORTANT_DOCS_FOLDER_NAME / match.extracted_filename
    assert extracted_path.exists()
    from pypdf import PdfReader

    assert len(PdfReader(str(extracted_path)).pages) == 2


# TEST 2 - extraction preserves the original page content (annotations/
# signatures included), never re-rendered or OCR'd.
def test_extraction_preserves_annotations(tmp_path, run_build):
    folder = tmp_path / "input"
    folder.mkdir()
    make_pdf_with_ink_signature(folder / "cd.pdf", [_CD_TEXT])

    run = run_build(folder, identity=_identity())
    cd_matches = [m for m in run.key_document_matches if m.category == "closing_disclosure"]
    assert len(cd_matches) == 1
    assert cd_matches[0].signature_status == "Signed"

    extracted_path = run.output_path / naming.IMPORTANT_DOCS_FOLDER_NAME / cd_matches[0].extracted_filename
    from pypdf import PdfReader

    reader = PdfReader(str(extracted_path))
    annots = reader.pages[0].get("/Annots")
    assert annots is not None and len(annots) >= 1


# TEST 3 - every extracted key-document file lands directly inside
# Important Docs, never a subfolder, and never Final.
def test_extracted_files_land_directly_in_important_docs(tmp_path, run_build):
    folder = tmp_path / "input"
    folder.mkdir()
    make_pdf_with_pages(folder / "cd.pdf", [_CD_TEXT])

    run = run_build(folder, identity=_identity())
    assert run.key_document_matches
    important_docs_dir = run.output_path / naming.IMPORTANT_DOCS_FOLDER_NAME
    for match in run.key_document_matches:
        if match.extracted_filename:
            path = important_docs_dir / match.extracted_filename
            assert path.exists()
            assert path.parent == important_docs_dir


# TEST 3B - the "Final" folder holds only the OG/Final Lender Package
# PDFs -- extracted key documents never land there, and the reverse:
# Important Docs never contains an OG/Final Lender Package PDF.
def test_final_and_important_docs_folders_never_mix_contents(tmp_path, run_build):
    folder = tmp_path / "input"
    folder.mkdir()
    make_pdf_with_pages(folder / "cd.pdf", [_CD_TEXT])

    run = run_build(folder, identity=_identity())
    assert run.key_document_matches
    assert any(m.extracted_filename for m in run.key_document_matches)

    final_dir = run.output_path / "Final"
    important_docs_dir = run.output_path / naming.IMPORTANT_DOCS_FOLDER_NAME

    final_filenames = {p.name for p in final_dir.glob("*.pdf")}
    important_docs_filenames = {p.name for p in important_docs_dir.glob("*.pdf")}

    for part in run.og_parts + run.final_parts:
        assert part.file_path.name in final_filenames
    for match in run.key_document_matches:
        if match.extracted_filename:
            assert match.extracted_filename in important_docs_filenames

    assert final_filenames.isdisjoint(important_docs_filenames)


# TEST 4 - a Possible Match is reported but never auto-extracted.
def test_possible_match_is_never_auto_extracted(tmp_path, run_build):
    folder = tmp_path / "input"
    folder.mkdir()
    make_pdf_with_pages(folder / "vague.pdf", ["Closing Disclosure mentioned here, see attached copy."])

    run = run_build(folder, identity=_identity())
    cd_matches = [m for m in run.key_document_matches if m.category == "closing_disclosure"]
    assert len(cd_matches) == 1
    assert cd_matches[0].confidence_band == "Possible Match"
    assert cd_matches[0].extracted_filename is None


# TEST 5 - page locations after exact-duplicate removal reflect the
# actual post-dedup Final position, not the original inventory order.
def test_page_locations_after_duplicate_removal(tmp_path, run_build):
    folder = tmp_path / "input"
    folder.mkdir()
    make_pdf_with_pages(folder / "a_unique.pdf", ["Unrelated cover page"])
    # An exact duplicate pair -- one copy is excluded from Final, so the
    # CD's actual Final position must skip the removed duplicate.
    dup_content = make_pdf_with_pages(folder / "b_dup1.pdf", [_CD_TEXT])
    (folder / "c_dup2.pdf").write_bytes(dup_content.read_bytes())

    run = run_build(folder, identity=_identity())
    assert run.success is True
    cd_matches = [m for m in run.key_document_matches if m.category == "closing_disclosure"]
    assert len(cd_matches) == 1
    match = cd_matches[0]
    # Only one copy is in Final (2 unique docs total: cover + CD), so the
    # CD (second Final document) starts on Final page 2.
    final_doc_count = sum(len(p.document_ids) for p in run.final_parts)
    assert final_doc_count == 2
    assert match.overall_final_page_range == (2, 2)


# TEST 6 - page locations after a manual review exclusion are
# refreshed to match Final's new contents.
def test_page_locations_refresh_after_manual_exclusion(tmp_path):
    from fixtures.builders import make_pdf

    output_path = tmp_path / "output"
    (output_path / "Final").mkdir(parents=True)
    (output_path / "Reports").mkdir(parents=True)

    from lender_package_builder import merging
    from lender_package_builder.models import IntegrityCheckResult, ProcessingStatus, RunResult, SourceOccurrence

    def occ(doc_id, pdf_path, pages):
        return SourceOccurrence(
            document_id=doc_id,
            traversal_index=int(doc_id[-1]),
            original_filename=f"{doc_id}.pdf",
            original_relative_path=f"{doc_id}.pdf",
            original_extension=".pdf",
            original_size_bytes=1000,
            status=ProcessingStatus.CONVERTED,
            converted_pdf_path=pdf_path,
            converted_page_count=pages,
            needs_review=True,
        )

    identity = _identity()
    config = AppConfig()

    cover_pdf = make_pdf(tmp_path / "cover.pdf", pages=1, text_prefix="Cover")
    cd_pdf = make_pdf_with_pages(tmp_path / "cd.pdf", [_CD_TEXT])
    occ_cover = occ("D1", cover_pdf, 1)
    occ_cd = occ("D2", cd_pdf, 1)

    final_parts = merging.write_package(
        [occ_cover, occ_cd], output_path / "Final", identity, naming.FINAL_PACKAGE_KIND, "Final",
        config.max_pages_per_part, config.max_size_bytes_per_part,
    )
    for part in final_parts:
        for doc_id in part.document_ids:
            {"D1": occ_cover, "D2": occ_cd}[doc_id].final_part_index = part.index

    match = UncertainMatch(
        match_id="UM-0001", kind="content_duplicate", document_id_a="D1", document_id_b="D2",
        confidence=0.85, detail="test", excludable_ids=("D1",),
    )
    run = RunResult(
        input_path=tmp_path, output_path=output_path, start_time="t", identity=identity,
        occurrences=[occ_cover, occ_cd], og_parts=[], final_parts=final_parts,
        integrity_checks=[IntegrityCheckResult("x", True, "ok")], uncertain_matches=[match],
    )
    run.key_document_matches = key_documents.locate_key_documents(run)
    cd_before = [m for m in run.key_document_matches if m.category == "closing_disclosure"]
    assert cd_before[0].overall_final_page_range == (2, 2)  # cover is page 1, CD is page 2

    review_decisions.apply_review_decision(run, config, "UM-0001", "excluded", excluded_document_id="D1")

    cd_after = [m for m in run.key_document_matches if m.category == "closing_disclosure"]
    assert len(cd_after) == 1
    # D1 (cover) is now excluded, so the CD is the only/first Final document.
    assert cd_after[0].overall_final_page_range == (1, 1)


# TEST 7 - "no wet-signed documents" messaging appears when nothing is
# wet-signed.
def test_no_wet_signed_documents_message(tmp_path, run_build):
    folder = tmp_path / "input"
    folder.mkdir()
    make_pdf_with_pages(folder / "cd.pdf", [_CD_TEXT])  # unsigned

    run = run_build(folder, identity=_identity())
    report = (run.output_path / "Reports" / "Key Document Page Locations.txt").read_text()
    assert "No wet-signed documents were found in the Final lender package." in report
    assert "Wet-Signed Closing Disclosure: Not found" in report


# TEST 8 - "Wet-Signed Closing Disclosure: Not found" appears even when
# something else (not the CD) is wet-signed.
def test_wet_signed_closing_disclosure_not_found_when_other_doc_is_signed(tmp_path, run_build):
    folder = tmp_path / "input"
    folder.mkdir()
    make_pdf_with_pages(folder / "cd.pdf", [_CD_TEXT])  # unsigned CD
    make_pdf_with_ink_signature(folder / "other.pdf", ["Some unrelated wet-signed document"])

    run = run_build(folder, identity=_identity())
    wet_signed = [m for m in run.key_document_matches if m.signature_status == "Signed"]
    assert wet_signed == []  # the "other" doc isn't a recognized key-document category at all

    report = (run.output_path / "Reports" / "Key Document Page Locations.txt").read_text()
    assert "Wet-Signed Closing Disclosure: Not found" in report


# TEST 9 - source files are never modified by key-document extraction.
def test_source_files_unchanged_by_extraction(tmp_path, run_build):
    folder = tmp_path / "input"
    folder.mkdir()
    make_pdf_with_pages(folder / "cd.pdf", [_CD_TEXT])
    original_bytes = (folder / "cd.pdf").read_bytes()

    run_build(folder, identity=_identity())

    assert (folder / "cd.pdf").read_bytes() == original_bytes
