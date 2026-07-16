"""Tests for pdf_portfolio.py -- PDF Portfolio and embedded-file
detection/extraction, both at the module level directly and through the
real InventoryBuilder (since expand_portfolios() is wired into
InventoryBuilder.build() as a post-pass).
"""

from __future__ import annotations

from pathlib import Path

from fixtures import builders
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from lender_package_builder import pdf_portfolio
from lender_package_builder.inventory import InventoryBuilder
from lender_package_builder.models import ProcessingStatus, SourceOccurrence
from lender_package_builder.workspace import Workspace


def _build(input_path: Path, config):
    ws = Workspace()
    builder = InventoryBuilder(config, ws)
    return builder.build(input_path), ws


def _occ(path: Path, doc_id: str = "DOC-000001") -> SourceOccurrence:
    return SourceOccurrence(
        document_id=doc_id,
        traversal_index=1,
        original_filename=path.name,
        original_relative_path=path.name,
        original_extension=".pdf",
        original_size_bytes=path.stat().st_size,
        extracted_path=path,
        archive_chain_display=path.name,
        original_sha256="fakehash",
        status=ProcessingStatus.DISCOVERED,
    )


# TEST 1 - a PDF Portfolio's embedded attachments are extracted and the
# generic cover page is excluded from lender content (via is_portfolio_container)
def test_portfolio_attachments_extracted_and_cover_excluded(tmp_path: Path):
    portfolio = builders.make_pdf_portfolio(
        tmp_path / "binder.pdf",
        [("disclosure.pdf", b"%PDF-1.4 disclosure bytes"), ("addendum.pdf", b"%PDF-1.4 addendum bytes")],
    )
    ws = Workspace()
    expanded = pdf_portfolio.expand_portfolios([_occ(portfolio)], ws)

    assert len(expanded) == 3
    parent = expanded[0]
    assert parent.is_portfolio_container is True

    children = expanded[1:]
    assert {c.original_filename for c in children} == {"disclosure.pdf", "addendum.pdf"}
    for child in children:
        assert child.portfolio_parent_document_id == parent.document_id
        assert child.extracted_path is not None
        assert child.extracted_path.exists()
        assert child.original_sha256 is not None
    ws.cleanup()


# TEST 2 - a plain PDF with a loose attachment (no /Collection) keeps its
# own pages -- must NOT be treated as a portfolio container
def test_plain_pdf_with_attachment_keeps_own_pages(tmp_path: Path):
    path = tmp_path / "plain.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(100, 700, "Real lender content")
    c.showPage()
    c.save()
    reader = PdfReader(str(path))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    writer.add_attachment("loose_note.txt", b"just an attachment")
    with path.open("wb") as fh:
        writer.write(fh)

    ws = Workspace()
    expanded = pdf_portfolio.expand_portfolios([_occ(path)], ws)
    assert len(expanded) == 2
    assert expanded[0].is_portfolio_container is False
    ws.cleanup()


# TEST 3 - attachment order is recorded/derivable (name-tree order preserved)
def test_attachment_order_preserved(tmp_path: Path):
    portfolio = builders.make_pdf_portfolio(
        tmp_path / "binder.pdf",
        [("a_first.pdf", b"first"), ("b_second.pdf", b"second"), ("c_third.pdf", b"third")],
    )
    ws = Workspace()
    expanded = pdf_portfolio.expand_portfolios([_occ(portfolio)], ws)
    names = [o.original_filename for o in expanded[1:]]
    assert names == ["a_first.pdf", "b_second.pdf", "c_third.pdf"]
    ws.cleanup()


# TEST 4 - traversal_index is renumbered 1..N after splicing, document_id stays stable
def test_traversal_index_renumbered_document_id_stable(tmp_path: Path):
    portfolio = builders.make_pdf_portfolio(tmp_path / "binder.pdf", [("att.pdf", b"data")])
    other = builders.make_pdf(tmp_path / "other.pdf", pages=1)
    occ_portfolio = _occ(portfolio, doc_id="DOC-000001")
    occ_other = SourceOccurrence(
        document_id="DOC-000002",
        traversal_index=2,
        original_filename="other.pdf",
        original_relative_path="other.pdf",
        original_extension=".pdf",
        original_size_bytes=other.stat().st_size,
        extracted_path=other,
        archive_chain_display="other.pdf",
        original_sha256="fakehash2",
        status=ProcessingStatus.DISCOVERED,
    )
    ws = Workspace()
    expanded = pdf_portfolio.expand_portfolios([occ_portfolio, occ_other], ws)
    assert [o.traversal_index for o in expanded] == [1, 2, 3]
    assert expanded[0].document_id == "DOC-000001"
    assert expanded[1].document_id == "DOC-000001-PF-001"
    assert expanded[2].document_id == "DOC-000002"
    ws.cleanup()


# TEST 5 - non-PDF and PDFs without any embedded files pass through unchanged
def test_non_portfolio_pdf_unchanged(tmp_path: Path):
    path = builders.make_pdf(tmp_path / "ordinary.pdf", pages=2)
    ws = Workspace()
    expanded = pdf_portfolio.expand_portfolios([_occ(path)], ws)
    assert len(expanded) == 1
    assert expanded[0].is_portfolio_container is False
    ws.cleanup()


# TEST 6 - a corrupt/malformed PDF never crashes expansion -- treated as
# an ordinary (non-portfolio) file
def test_corrupt_pdf_does_not_crash_expansion(tmp_path: Path):
    path = tmp_path / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.4\nnot a valid pdf body\n%%EOF")
    ws = Workspace()
    expanded = pdf_portfolio.expand_portfolios([_occ(path)], ws)
    assert len(expanded) == 1
    ws.cleanup()


# TEST 6b - REGRESSION (real user-reported bug): a PDF whose /Root
# carries /Collection (marking it a Portfolio in Adobe's UI sense) but
# where pypdf's `.attachments` enumeration finds ZERO actual embedded
# files must NOT be excluded from Final -- it has no replacement
# content, so treating it as a portfolio container here would silently
# discard the entire document. This exact shape (a "binder"/merged PDF
# produced by some document-assembly tool that leaves a /Collection
# entry set without true separate attachment streams) is realistic,
# not a contrived edge case: it was the root cause of a real report of
# "packaged successfully but the Final folder was empty."
def test_collection_present_with_zero_attachments_is_not_treated_as_portfolio(tmp_path: Path):
    portfolio = builders.make_pdf_portfolio(tmp_path / "binder.pdf", [])
    ws = Workspace()
    occ = _occ(portfolio)
    expanded = pdf_portfolio.expand_portfolios([occ], ws)

    assert len(expanded) == 1
    assert occ.is_portfolio_container is False
    assert occ.included_in_final is True
    ws.cleanup()


# TEST 6c - same regression, but through the real end-to-end pipeline:
# a package consisting SOLELY of such a PDF must produce a non-empty
# Final folder containing that document, and every integrity check
# must pass.
def test_full_pipeline_zero_attachment_collection_pdf_is_not_dropped_from_final(tmp_path, run_build):
    folder = tmp_path / "input"
    builders.make_pdf_portfolio(folder / "loan_binder.pdf", [])

    run = run_build(folder)

    assert run.success is True
    final_flat = [doc_id for part in run.final_parts for doc_id in part.document_ids]
    assert len(final_flat) == 1
    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"


# TEST 7 - full integration through InventoryBuilder: a Portfolio inside
# the real discovery pipeline produces real, independently-hashed occurrences
def test_portfolio_expansion_via_inventory_builder(tmp_path: Path, config):
    folder = tmp_path / "input"
    builders.make_pdf_portfolio(
        folder / "binder.pdf", [("embedded_disclosure.pdf", b"%PDF-1.4 embedded content bytes")]
    )
    occurrences, ws = _build(folder, config)
    filenames = [o.original_filename for o in occurrences]
    assert "binder.pdf" in filenames
    assert "embedded_disclosure.pdf" in filenames
    embedded = next(o for o in occurrences if o.original_filename == "embedded_disclosure.pdf")
    assert embedded.original_sha256 is not None
    assert embedded.portfolio_parent_document_id is not None
    ws.cleanup()


# TEST 8 - a Portfolio attachment that is also supplied separately gets
# caught by exact-hash dedup automatically once it's a real occurrence
def test_portfolio_attachment_matches_separately_supplied_copy_via_exact_hash(tmp_path: Path, config):
    from lender_package_builder import deduplication

    shared_bytes = b"%PDF-1.4 identical content shared between portfolio and standalone"
    folder = tmp_path / "input"
    builders.make_pdf_portfolio(folder / "binder.pdf", [("shared.pdf", shared_bytes)])
    (folder / "shared_standalone.pdf").write_bytes(shared_bytes)

    occurrences, ws = _build(folder, config)
    duplicate_groups = deduplication.find_duplicates(occurrences)
    assert len(duplicate_groups) == 1
    assert len(duplicate_groups[0].document_ids) == 2
    ws.cleanup()
