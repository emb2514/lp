"""Tests for MILESTONE 4 -- the key-document page locator and
extraction engine (key_documents.py): Closing Disclosure detection with
conservative signature-status classification, Driver's License
front/back/combined detection, the Mortgage-Unity-specific privacy
policy, and loan non-proceeding documentation. Recognition here is
purely descriptive and never controls duplicate detection or Final
inclusion/exclusion.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from fixtures.builders import make_pdf_with_ink_signature, make_pdf_with_pages, make_signed_pdf_variant

from lender_package_builder import key_documents
from lender_package_builder.key_documents import CONFIRMED, POSSIBLE_MATCH, STRONG_MATCH
from lender_package_builder.models import PackageIdentity, ProcessingStatus, SourceOccurrence
from lender_package_builder.pdf_content import build_document_fingerprint


def _make_pdf_with_text_and_images(path: Path, page_specs: list[tuple[str, int]]) -> Path:
    """`page_specs`: list of (text, image_count) -- direct control over
    both extractable text and embedded-image count per page, needed for
    the Driver's License front/back/combined heuristics. Each image on
    a page uses a distinct color so a PDF writer can never collapse them
    into a single shared XObject (which would silently undercount them).
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=LETTER)
    for text, image_count in page_specs:
        c.setFont("Helvetica", 10)
        y = 700
        for line in text.split("\n"):
            c.drawString(72, y, line)
            y -= 14
        for i in range(image_count):
            img = Image.new("RGB", (200, 300), color=(200 - i * 20, 200, 200 + i * 5))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            c.drawImage(ImageReader(buf), 100 + i * 220, 300, width=200, height=300)
        c.showPage()
    c.save()
    return path


def _occ(document_id: str, pdf_path: Path, pages: int, original_filename: str | None = None) -> SourceOccurrence:
    return SourceOccurrence(
        document_id=document_id,
        traversal_index=1,
        original_filename=original_filename or f"{document_id}.pdf",
        original_relative_path=original_filename or f"{document_id}.pdf",
        original_extension=".pdf",
        original_size_bytes=1000,
        status=ProcessingStatus.CONVERTED,
        converted_pdf_path=pdf_path,
        converted_page_count=pages,
    )


def _fp(document_id: str, pdf_path: Path):
    return build_document_fingerprint(document_id, pdf_path)


_IDENTITY = PackageIdentity(last_name="True", first_name="Michael", loan_number="6192278785")

_CD_UNSIGNED_TEXT = "Closing Disclosure\nLoan Terms\nProjected Payments\nBorrower: Michael True"


# ---------------------------------------------------------------------
# Closing Disclosure
# ---------------------------------------------------------------------


def test_wet_signed_closing_disclosure(tmp_path):
    pdf = make_pdf_with_ink_signature(tmp_path / "cd.pdf", [_CD_UNSIGNED_TEXT])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_closing_disclosures(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 1
    assert matches[0].confidence_band == CONFIRMED
    assert matches[0].signature_status == "Signed"


def test_e_signed_closing_disclosure(tmp_path):
    from pypdf import PdfReader, PdfWriter

    from fixtures.builders import _add_signature_field

    plain = make_pdf_with_pages(tmp_path / "cd_plain.pdf", [_CD_UNSIGNED_TEXT])
    reader = PdfReader(str(plain))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)
    _add_signature_field(writer, writer.pages[0], "borrower_sig", (72, 600, 300, 620))
    dest = tmp_path / "cd_final.pdf"
    with dest.open("wb") as fh:
        writer.write(fh)

    occ = _occ("D1", dest, 1)
    matches = key_documents._find_closing_disclosures(occ, _fp("D1", dest), _IDENTITY)
    assert len(matches) == 1
    assert matches[0].signature_status == "E-Sign"


def test_unsigned_closing_disclosure(tmp_path):
    pdf = make_pdf_with_pages(tmp_path / "cd.pdf", [_CD_UNSIGNED_TEXT])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_closing_disclosures(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 1
    assert matches[0].signature_status == "Unsigned"
    assert matches[0].confidence_band == CONFIRMED


def test_misleading_filename_never_consulted_for_signature_status(tmp_path):
    pdf = make_pdf_with_pages(tmp_path / "cd.pdf", [_CD_UNSIGNED_TEXT])
    occ = _occ("D1", pdf, 1, original_filename="closing_disclosure_SIGNED_FINAL.pdf")
    matches = key_documents._find_closing_disclosures(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 1
    # The filename says "SIGNED" but there is no /Sig field or /Ink
    # annotation anywhere in the actual content -- must not be "Signed".
    assert matches[0].signature_status == "Unsigned"


def test_multiple_closing_disclosure_versions_across_documents(tmp_path):
    unsigned_pdf = make_pdf_with_pages(tmp_path / "unsigned.pdf", [_CD_UNSIGNED_TEXT])
    signed_pdf = make_pdf_with_ink_signature(tmp_path / "signed.pdf", [_CD_UNSIGNED_TEXT])

    occ_a = _occ("D1", unsigned_pdf, 1)
    occ_b = _occ("D2", signed_pdf, 1)
    matches_a = key_documents._find_closing_disclosures(occ_a, _fp("D1", unsigned_pdf), _IDENTITY)
    matches_b = key_documents._find_closing_disclosures(occ_b, _fp("D2", signed_pdf), _IDENTITY)

    assert matches_a[0].signature_status == "Unsigned"
    assert matches_b[0].signature_status == "Signed"
    assert matches_a[0].document_id != matches_b[0].document_id


def test_closing_disclosure_possible_match_without_section_markers(tmp_path):
    pdf = make_pdf_with_pages(tmp_path / "cd.pdf", ["Closing Disclosure mentioned in passing, see attached."])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_closing_disclosures(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 1
    assert matches[0].confidence_band == POSSIBLE_MATCH


def test_revised_closing_disclosure(tmp_path):
    pdf = make_pdf_with_pages(
        tmp_path / "cd.pdf", ["Revised Closing Disclosure\nLoan Terms\nProjected Payments"]
    )
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_closing_disclosures(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 1
    assert matches[0].signature_status == "Revised"


# ---------------------------------------------------------------------
# Driver's License
# ---------------------------------------------------------------------

_DL_FRONT_TEXT = "STATE OF EXAMPLE\nDRIVER LICENSE\nDOB 01/01/1990\nCLASS C\nEXPIRES 01/01/2030\nHGT 5-10 EYES BRN"
_DL_BACK_TEXT = "RESTRICTIONS: NONE\nORGAN DONOR\nBARCODE PDF417 DATA BELOW"


def test_multiple_drivers_licenses_two_documents(tmp_path):
    pdf_a = _make_pdf_with_text_and_images(tmp_path / "dl_a.pdf", [(_DL_FRONT_TEXT, 1)])
    pdf_b = _make_pdf_with_text_and_images(tmp_path / "dl_b.pdf", [(_DL_FRONT_TEXT, 1)])
    occ_a = _occ("D1", pdf_a, 1)
    occ_b = _occ("D2", pdf_b, 1)
    matches_a = key_documents._find_drivers_licenses(occ_a, _fp("D1", pdf_a), _IDENTITY)
    matches_b = key_documents._find_drivers_licenses(occ_b, _fp("D2", pdf_b), _IDENTITY)
    assert len(matches_a) == 1
    assert len(matches_b) == 1
    assert matches_a[0].document_id != matches_b[0].document_id


def test_drivers_license_separate_front_and_back_pages(tmp_path):
    pdf = _make_pdf_with_text_and_images(
        tmp_path / "dl.pdf", [(_DL_FRONT_TEXT, 1), (_DL_BACK_TEXT + "\nDRIVER LICENSE", 0)]
    )
    occ = _occ("D1", pdf, 2)
    matches = key_documents._find_drivers_licenses(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 2
    assert matches[0].subtype == "Front"
    assert matches[1].subtype == "Back"


def test_drivers_license_combined_front_and_back(tmp_path):
    pdf = _make_pdf_with_text_and_images(tmp_path / "dl.pdf", [(_DL_FRONT_TEXT, 2)])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_drivers_licenses(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 1
    assert matches[0].subtype == "Front and Back"


def test_drivers_license_unknown_side(tmp_path):
    # DL-like fields without the explicit license phrase and without an
    # image or a back-of-card marker -- side cannot be determined.
    pdf = _make_pdf_with_text_and_images(
        tmp_path / "dl.pdf", [("DOB 01/01/1990\nCLASS C\nHGT 5-10\nEYES BRN", 0)]
    )
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_drivers_licenses(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 1
    assert matches[0].confidence_band == POSSIBLE_MATCH
    assert matches[0].subtype == "Side Unknown"


def test_drivers_license_detects_name_hint(tmp_path):
    pdf = _make_pdf_with_text_and_images(tmp_path / "dl.pdf", [("DRIVER LICENSE\nJane Smith\n" + _DL_FRONT_TEXT, 1)])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_drivers_licenses(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 1
    assert matches[0].borrower_name == "Jane Smith"
    assert matches[0].person_name_override == "Jane Smith"


# ---------------------------------------------------------------------
# Mortgage Unity Privacy Policy
# ---------------------------------------------------------------------


def test_mortgage_unity_privacy_policy_detected(tmp_path):
    pdf = make_pdf_with_pages(tmp_path / "privacy.pdf", ["Mortgage Unity Privacy Policy\nWe respect your privacy."])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_mu_privacy_policy(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 1
    assert matches[0].confidence_band == CONFIRMED


def test_another_lenders_privacy_policy_not_classified_as_mu(tmp_path):
    pdf = make_pdf_with_pages(tmp_path / "privacy.pdf", ["Acme Lending Privacy Notice\nWe respect your privacy."])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_mu_privacy_policy(occ, _fp("D1", pdf), _IDENTITY)
    assert matches == []


# ---------------------------------------------------------------------
# Loan non-proceeding documentation
# ---------------------------------------------------------------------


def test_adverse_action_notice(tmp_path):
    pdf = make_pdf_with_pages(tmp_path / "aan.pdf", ["Adverse Action Notice\nYour application was not approved."])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_non_proceeding_documents(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 1
    assert matches[0].subtype == "Adverse Action Notice"
    assert matches[0].confidence_band == CONFIRMED


def test_withdrawal_certification(tmp_path):
    pdf = make_pdf_with_pages(tmp_path / "wc.pdf", ["Withdrawal Certification\nApplicant has withdrawn."])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_non_proceeding_documents(occ, _fp("D1", pdf), _IDENTITY)
    assert matches[0].subtype == "Withdrawal Certification"


def test_denial_notice(tmp_path):
    pdf = make_pdf_with_pages(tmp_path / "denial.pdf", ["Notice of Denial\nYour loan application was denied."])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_non_proceeding_documents(occ, _fp("D1", pdf), _IDENTITY)
    assert matches[0].subtype == "Denial Notice"


def test_cancellation_notice(tmp_path):
    pdf = make_pdf_with_pages(tmp_path / "cancel.pdf", ["Your loan has been cancelled effective today."])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_non_proceeding_documents(occ, _fp("D1", pdf), _IDENTITY)
    assert matches[0].subtype == "Cancellation Notice"


def test_cancellation_notice_not_confused_with_trid_right_to_cancel(tmp_path):
    # The standard 3-day rescission disclosure present on nearly every
    # loan -- must never be misclassified as a non-proceeding document.
    pdf = make_pdf_with_pages(tmp_path / "rescission.pdf", ["You have the right to cancel this transaction."])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_non_proceeding_documents(occ, _fp("D1", pdf), _IDENTITY)
    assert matches == []


def test_closed_for_incompleteness(tmp_path):
    pdf = make_pdf_with_pages(tmp_path / "closed.pdf", ["This file has been closed for incompleteness."])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_non_proceeding_documents(occ, _fp("D1", pdf), _IDENTITY)
    assert matches[0].subtype == "Closed for Incompleteness"


def test_ambiguous_non_proceeding_wording_is_possible_match(tmp_path):
    pdf = make_pdf_with_pages(tmp_path / "other.pdf", ["We are unable to proceed with your loan at this time."])
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_non_proceeding_documents(occ, _fp("D1", pdf), _IDENTITY)
    assert len(matches) == 1
    assert matches[0].subtype == "Other Non-Proceeding Document"
    assert matches[0].confidence_band == POSSIBLE_MATCH


def test_ordinary_missing_item_request_produces_no_result(tmp_path):
    pdf = make_pdf_with_pages(
        tmp_path / "conditions.pdf", ["Please provide the following outstanding conditions before closing."]
    )
    occ = _occ("D1", pdf, 1)
    matches = key_documents._find_non_proceeding_documents(occ, _fp("D1", pdf), _IDENTITY)
    assert matches == []


# ---------------------------------------------------------------------
# Multiple categories on one document
# ---------------------------------------------------------------------


def test_multiple_key_document_results_on_one_document(tmp_path):
    pdf = _make_pdf_with_text_and_images(
        tmp_path / "combo.pdf", [(_CD_UNSIGNED_TEXT, 0), (_DL_FRONT_TEXT, 1)]
    )
    occ = _occ("D1", pdf, 2)
    fp = _fp("D1", pdf)
    cd_matches = key_documents._find_closing_disclosures(occ, fp, _IDENTITY)
    dl_matches = key_documents._find_drivers_licenses(occ, fp, _IDENTITY)
    assert len(cd_matches) == 1
    assert len(dl_matches) == 1
