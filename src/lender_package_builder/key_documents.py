"""Key-document page locator and extraction (MILESTONE 4).

After the deduplicated Final package is built, identifies specific
document types the reports/GUI surface separately:

- Closing Disclosures, with a conservative signature-status
  classification (Signed / E-Sign / Unsigned / Revised / Signature
  Unknown).
- Loan Estimates, reliably told apart from Closing Disclosures despite
  sharing nearly identical section names -- each form's own fixed page
  count (5 pages for a Closing Disclosure, 3 for a Loan Estimate) is
  used as the mutual-exclusion signal, not any single sentence of
  boilerplate text. See the module note above `_page_totals`.
- ALTA Settlement Statements (Buyer / Seller / Combined).
- Government-issued photo ID (Driver's License front/back/combined,
  Passport, State ID Card, or an unspecified-but-clearly-ID-shaped
  document), one borrower or several. Requires an actual embedded
  scanned/photographed image on the page -- text merely mentioning
  "driver's license" (a checklist item, a disclosure listing acceptable
  ID types, a cover letter) is never enough on its own. See
  `_find_government_ids`'s docstring: this was a real, confirmed
  false-positive risk in the original text-only design.
- The Mortgage Unity Privacy Policy specifically (never a generic
  privacy notice from another lender) and the Mortgage Unity
  Massachusetts Broker Addendum specifically (never a generic addendum
  to a Uniform Residential Loan Application).
- Loan non-proceeding documentation (Adverse Action Notice, Withdrawal
  Certification, Denial Notice, Cancellation Notice, Closed for
  Incompleteness, or an unclassified but clearly non-proceeding
  document).

Recognition here is purely descriptive: it NEVER controls duplicate
detection, exclusion, or inclusion in Final -- see
`SourceOccurrence.included_in_final`, which this module never touches.
A "Possible Match" always stays in the package and is reported, never
silently dropped or promoted.

Every detector below is deliberately conservative and keyword/
structure-based (normalized text, PDF signature fields, annotation
subtypes, embedded-image counts -- no OCR, no machine learning). Each
one documents exactly what evidence it requires and what it refuses to
guess, matching this app's existing "when uncertain, don't claim it"
philosophy.
"""

from __future__ import annotations

import dataclasses
import re

from pypdf import PdfReader, PdfWriter

from . import naming
from .models import KeyDocumentMatch, PackageIdentity, RunResult, SourceOccurrence
from .pdf_content import DocumentFingerprint, PageFingerprint, build_document_fingerprint

CONFIRMED = "Confirmed"
STRONG_MATCH = "Strong Match"
POSSIBLE_MATCH = "Possible Match"

# Only these two bands are trusted enough to automatically extract a
# confidently-named standalone file -- a Possible Match stays listed in
# the report/manifest but is never auto-extracted (per the explicit
# instruction: a human should review and confirm it first).
_AUTO_EXTRACT_BANDS = (CONFIRMED, STRONG_MATCH)


def locate_key_documents(run: RunResult) -> list[KeyDocumentMatch]:
    """Runs every detector over every document currently in Final and
    returns all matches found, in a stable, deterministic order. Never
    mutates `run.occurrences` or anything about Final's contents.
    """

    final_occurrences = [o for o in run.occurrences if o.included_in_final]
    matches: list[KeyDocumentMatch] = []
    seq = 1

    for occ in final_occurrences:
        if not occ.converted_pdf_path or not occ.converted_pdf_path.exists():
            continue
        try:
            fingerprint = build_document_fingerprint(occ.document_id, occ.converted_pdf_path)
        except Exception:
            # A single unreadable converted PDF must never crash the
            # whole run -- it simply never participates in key-document
            # detection, exactly like content_dedup.build_fingerprints().
            continue

        for finder in (
            _find_closing_disclosures,
            _find_loan_estimates,
            _find_alta_settlement_statements,
            _find_government_ids,
            _find_mu_privacy_policy,
            _find_mu_ma_broker_addendum,
            _find_non_proceeding_documents,
        ):
            for match in finder(occ, fingerprint, run.identity):
                match.match_id = f"KD-{seq:04d}"
                seq += 1
                _fill_final_page_ranges(match, occ, run)
                matches.append(match)

    return matches


def _fill_final_page_ranges(match: KeyDocumentMatch, occ: SourceOccurrence, run: RunResult) -> None:
    """Fills in the Final-part-local and overall-Final page ranges from
    the document's position within its Final part -- computed fresh
    from `run.final_parts` each time, so it always reflects the
    post-dedup, post-merge, final page numbering (never the source
    document's own original page numbers, which is what
    `document_page_range` already captures separately).
    """

    part = next((p for p in run.final_parts if occ.document_id in p.document_ids), None)
    if part is None:
        return

    occ_by_id = {o.document_id: o for o in run.occurrences}
    offset_in_part = 0
    for doc_id in part.document_ids:
        if doc_id == occ.document_id:
            break
        sibling = occ_by_id.get(doc_id)
        offset_in_part += (sibling.converted_page_count or 0) if sibling else 0

    start_in_part = offset_in_part + match.document_page_range[0]
    end_in_part = offset_in_part + match.document_page_range[1]
    match.final_part_index = part.index
    match.final_part_page_range = (start_in_part, end_in_part)

    offset_overall = 0
    for earlier_part in run.final_parts:
        if earlier_part.index == part.index:
            break
        offset_overall += earlier_part.page_count
    match.overall_final_page_range = (offset_overall + start_in_part, offset_overall + end_in_part)


# ---------------------------------------------------------------------
# Closing Disclosure / Loan Estimate page-count discrimination
# ---------------------------------------------------------------------
#
# Real-world collision, confirmed directly against the actual CFPB model
# forms (not assumed): a Loan Estimate's own page 1 prints the caption
# "Save this Loan Estimate to compare with your Closing Disclosure."
# right above its title -- so a naive `"closing disclosure" in text`
# check matches EVERY Loan Estimate page, not just real Closing
# Disclosures. The forms are also both standardized, fixed-length
# documents with their own page count printed in the footer ("PAGE X OF
# 3" for a Loan Estimate, "PAGE X OF 5" for a Closing Disclosure -- 12
# CFR Part 1026 Appendix H), which is a far more reliable, form-intrinsic
# way to tell them apart than any single sentence of boilerplate text.

_PAGE_TOTAL_PATTERN = re.compile(r"page\s+\d+\s+of\s+(\d+)")
_LE_COMPARISON_CAPTION = "compare with your closing disclosure"
_LOAN_ESTIMATE_PAGE_TOTAL = 3
_CLOSING_DISCLOSURE_PAGE_TOTAL = 5


def _page_totals(pages: tuple[PageFingerprint, ...]) -> set[int]:
    totals: set[int] = set()
    for page in pages:
        match = _PAGE_TOTAL_PATTERN.search(page.normalized_text.casefold())
        if match:
            totals.add(int(match.group(1)))
    return totals


# ---------------------------------------------------------------------
# Closing Disclosure
# ---------------------------------------------------------------------

_CD_TITLE_MARKER = "closing disclosure"
_CD_SECTION_MARKERS = (
    "closing information",
    "transaction information",
    "loan information",
    "loan terms",
    "projected payments",
    "loan costs",
    "loan calculations",
    "cash to close",
    "calculating cash to close",
)
_CD_REVISION_MARKERS = ("revised closing disclosure", "corrected closing disclosure")


def _find_closing_disclosures(
    occ: SourceOccurrence, fp: DocumentFingerprint, identity: PackageIdentity
) -> list[KeyDocumentMatch]:
    marker_pages = [
        i
        for i, page in enumerate(fp.pages)
        if _CD_TITLE_MARKER in page.normalized_text.casefold()
        # A page whose footer says "page X of 3" or that carries the
        # Loan Estimate's own comparison caption is a Loan Estimate that
        # merely mentions "Closing Disclosure" in passing, not a real
        # Closing Disclosure -- see the module note above.
        and _LOAN_ESTIMATE_PAGE_TOTAL not in _page_totals((page,))
        and _LE_COMPARISON_CAPTION not in page.normalized_text.casefold()
    ]
    if not marker_pages:
        return []

    matches: list[KeyDocumentMatch] = []
    for start, end in _group_contiguous(marker_pages, max_gap=1):
        pages = fp.pages[start : end + 1]
        section_hits = sum(
            1
            for marker in _CD_SECTION_MARKERS
            if any(marker in p.normalized_text.casefold() for p in pages)
        )
        if section_hits >= 2:
            band, reason = CONFIRMED, (
                f'"{_CD_TITLE_MARKER.title()}" title found with {section_hits} corroborating CD section '
                "headers (e.g. Loan Terms, Projected Payments, Loan Costs)."
            )
        elif section_hits == 1:
            band, reason = STRONG_MATCH, (
                f'"{_CD_TITLE_MARKER.title()}" title found with 1 corroborating CD section header.'
            )
        else:
            band, reason = POSSIBLE_MATCH, (
                f'"{_CD_TITLE_MARKER.title()}" text found, but no corroborating CD section headers nearby.'
            )

        is_revised = any(
            marker in p.normalized_text.casefold() for marker in _CD_REVISION_MARKERS for p in pages
        ) or any("revised" in p.normalized_text.casefold() or "corrected" in p.normalized_text.casefold() for p in pages)
        signature_status = "Revised" if is_revised else _classify_signature_status(pages)

        matches.append(
            KeyDocumentMatch(
                match_id="",
                category="closing_disclosure",
                subtype=None,
                confidence_band=band,
                confidence=1.0 if band == CONFIRMED else (0.75 if band == STRONG_MATCH else 0.4),
                document_id=occ.document_id,
                original_filename=occ.original_filename,
                borrower_name=None,
                reason=reason,
                document_page_range=(start + 1, end + 1),
                signature_status=signature_status,
            )
        )
    return matches


def _classify_signature_status(pages: tuple[PageFingerprint, ...]) -> str:
    """Conservative, structural signature-status classification.

    - "E-Sign": a real PDF `/Sig` AcroForm field with a value is
      present -- a genuine structural digital-signature signal.
    - "Signed" (wet): an `/Ink` annotation with a real appearance
      stream is present -- freehand pen/stylus input baked into the
      PDF (e.g. Adobe "Fill & Sign"), the closest structural proxy this
      app has for an actual ink signature.
    - "Signature Unknown": the page contains an embedded raster image
      (i.e. it was scanned) with neither signal above -- a wet
      signature on a flat scanned image is structurally
      indistinguishable from an unsigned scan, so this never guesses.
    - "Unsigned": no image, no /Sig field, no /Ink annotation -- a pure
      text/vector page has nowhere for an undetected ink mark to hide.

    Never trusts a filename containing "signed" -- filenames are never
    consulted here at all.
    """

    if any(p.has_signed_signature for p in pages):
        return "E-Sign"
    if any(a.subtype == "/Ink" and a.has_appearance_stream for p in pages for a in p.annotations):
        return "Signed"
    if any(p.images for p in pages):
        return "Signature Unknown"
    return "Unsigned"


# ---------------------------------------------------------------------
# Loan Estimate
# ---------------------------------------------------------------------

_LE_TITLE_MARKER = "loan estimate"
_LE_SECTION_MARKERS = (
    "loan terms",
    "projected payments",
    "costs at closing",
    "closing cost details",
    "calculating cash to close",
    "comparisons",
    "other considerations",
    "confirm receipt",
)


def _find_loan_estimates(
    occ: SourceOccurrence, fp: DocumentFingerprint, identity: PackageIdentity
) -> list[KeyDocumentMatch]:
    """Confirmed directly against the real CFPB H-24 model form and its
    fixed-rate/interest-only-ARM/balloon/refinance variants: page 1
    title "Loan Estimate", page 2 "Closing Cost Details" (Loan Costs /
    Other Costs / Calculating Cash to Close), page 3 "Comparisons" /
    "Other Considerations" / "Confirm Receipt", and a "PAGE X OF 3"
    footer on every page. See the module note above `_page_totals` for
    why a page carrying the Closing Disclosure's own 5-page footer is
    excluded here even if it happens to mention "loan estimate".
    """

    marker_pages = [
        i
        for i, page in enumerate(fp.pages)
        if _LE_TITLE_MARKER in page.normalized_text.casefold()
        and _CLOSING_DISCLOSURE_PAGE_TOTAL not in _page_totals((page,))
    ]
    if not marker_pages:
        return []

    matches: list[KeyDocumentMatch] = []
    for start, end in _group_contiguous(marker_pages, max_gap=1):
        pages = fp.pages[start : end + 1]
        section_hits = sum(
            1
            for marker in _LE_SECTION_MARKERS
            if any(marker in p.normalized_text.casefold() for p in pages)
        )
        page_totals = _page_totals(pages)
        confirmed_by_page_count = _LOAN_ESTIMATE_PAGE_TOTAL in page_totals

        if (confirmed_by_page_count and section_hits >= 1) or section_hits >= 2:
            band, confidence = CONFIRMED, 1.0
            reason = (
                f'"Loan Estimate" title found with {section_hits} corroborating section header(s)'
                + (' and a "page X of 3" footer' if confirmed_by_page_count else "")
                + "."
            )
        elif section_hits == 1 or confirmed_by_page_count:
            band, confidence = STRONG_MATCH, 0.75
            reason = '"Loan Estimate" title found with 1 corroborating signal (section header or page-count footer).'
        else:
            band, confidence = POSSIBLE_MATCH, 0.4
            reason = '"Loan Estimate" text found, but no corroborating section headers or page-count footer nearby.'

        matches.append(
            KeyDocumentMatch(
                match_id="",
                category="loan_estimate",
                subtype=None,
                confidence_band=band,
                confidence=confidence,
                document_id=occ.document_id,
                original_filename=occ.original_filename,
                borrower_name=None,
                reason=reason,
                document_page_range=(start + 1, end + 1),
                signature_status=None,
            )
        )
    return matches


# ---------------------------------------------------------------------
# ALTA Settlement Statement
# ---------------------------------------------------------------------

# "ALTA Settlement Statement" covers the base form and its "- Buyer"/
# "- Seller" suffix variants; "ALTA Combined Settlement Statement" has
# "Combined" inserted between "ALTA" and "Settlement Statement" instead
# of appended as a suffix, so it needs its own literal check.
_ALTA_TITLE_MARKERS = ("alta settlement statement", "alta combined settlement statement")
_ALTA_BYLINE_MARKER = "american land title association"
_ALTA_SECTION_MARKERS = (
    "prorations/adjustments",
    "loan charges to",
    "financial",
)
# Checked in this order -- a Combined statement's own line-item table
# also shows "Buyer"/"Seller" column headers, so "Combined" must be
# checked first or a combined statement would be mislabeled by side.
_ALTA_SIDE_MARKERS = (
    ("combined", "Combined"),
    ("seller", "Seller"),
    ("buyer", "Buyer"),
)


def _find_alta_settlement_statements(
    occ: SourceOccurrence, fp: DocumentFingerprint, identity: PackageIdentity
) -> list[KeyDocumentMatch]:
    """Confirmed directly against a real ALTA Settlement Statement -
    Seller (Adopted 05-01-2015): title "ALTA Settlement Statement"
    (with a "- Buyer"/"- Seller" or "Combined" variant), the "American
    Land Title Association" byline, and a Debit/Credit table grouped
    under section headers including "Financial", "Prorations/
    Adjustments", and "Loan Charges to (lender co.)".
    """

    marker_pages = [
        i
        for i, page in enumerate(fp.pages)
        if any(marker in page.normalized_text.casefold() for marker in _ALTA_TITLE_MARKERS)
    ]
    if not marker_pages:
        return []

    matches: list[KeyDocumentMatch] = []
    for start, end in _group_contiguous(marker_pages, max_gap=1):
        pages = fp.pages[start : end + 1]
        has_byline = any(_ALTA_BYLINE_MARKER in p.normalized_text.casefold() for p in pages)
        section_hits = sum(
            1
            for marker in _ALTA_SECTION_MARKERS
            if any(marker in p.normalized_text.casefold() for p in pages)
        )

        if has_byline and section_hits >= 2:
            band, confidence = CONFIRMED, 1.0
        elif has_byline or section_hits >= 2:
            band, confidence = STRONG_MATCH, 0.75
        else:
            band, confidence = POSSIBLE_MATCH, 0.4

        side = None
        for phrase, label in _ALTA_SIDE_MARKERS:
            if any(phrase in p.normalized_text.casefold() for p in pages):
                side = label
                break

        reason_parts = ['"ALTA Settlement Statement" title found']
        if has_byline:
            reason_parts.append('with the "American Land Title Association" byline')
        if section_hits:
            reason_parts.append(f"and {section_hits} corroborating section header(s)")
        reason = " ".join(reason_parts) + "."

        matches.append(
            KeyDocumentMatch(
                match_id="",
                category="alta_settlement_statement",
                subtype=side,
                confidence_band=band,
                confidence=confidence,
                document_id=occ.document_id,
                original_filename=occ.original_filename,
                borrower_name=None,
                reason=reason,
                document_page_range=(start + 1, end + 1),
                signature_status=None,
            )
        )
    return matches


# ---------------------------------------------------------------------
# Government-issued photo ID (Driver's License, Passport, State ID Card)
# ---------------------------------------------------------------------

_DL_PHRASES = (
    "driver license",
    "driver's license",
    "drivers license",
    "operator license",
    "commercial driver license",
)
_PASSPORT_PHRASES = ("passport",)
_STATE_ID_PHRASES = ("state identification card", "state id card")
_GOV_ID_FIELD_MARKERS = ("dob", "date of birth", "class", "hgt", "eyes", "rstr", "endorsements", "issued", "expires")
_DL_BACK_MARKERS = ("barcode", "pdf417", "organ donor", "reverse side")


def _find_government_ids(
    occ: SourceOccurrence, fp: DocumentFingerprint, identity: PackageIdentity
) -> list[KeyDocumentMatch]:
    """A real government-issued photo ID (driver's license, passport,
    state ID card) is always a photographed or scanned raster image --
    never a page of ordinary vector text. The original text-only design
    here classified ANY page mentioning "driver's license" as a match,
    confirmed as a real false-positive risk: a loan-package checklist
    item ("Please provide a copy of your driver's license"), a
    disclosure listing acceptable ID types, or a cover letter would all
    match with no actual ID ever having been scanned. Requiring at least
    one embedded image on the page before any text scoring even runs
    closes that gap completely -- no image, no match, regardless of what
    words appear or how many field-label markers (DOB, CLASS, HGT, ...)
    are present.
    """

    matches: list[KeyDocumentMatch] = []
    for index, page in enumerate(fp.pages):
        if not page.images:
            continue

        text = page.normalized_text.casefold()
        has_dl_phrase = any(phrase in text for phrase in _DL_PHRASES)
        has_state_id_phrase = any(phrase in text for phrase in _STATE_ID_PHRASES)
        has_passport_phrase = any(phrase in text for phrase in _PASSPORT_PHRASES)
        field_count = sum(1 for marker in _GOV_ID_FIELD_MARKERS if marker in text)

        if has_dl_phrase:
            id_type = "Driver's License"
        elif has_state_id_phrase:
            id_type = "State ID Card"
        elif has_passport_phrase:
            id_type = "Passport"
        elif field_count >= 3:
            id_type = None  # ID-card-like fields on a real scan, but no named document type
        else:
            continue

        if id_type is not None and field_count >= 2:
            band, confidence = CONFIRMED, 1.0
        elif id_type is not None:
            band, confidence = STRONG_MATCH, 0.75
        else:
            band, confidence = POSSIBLE_MATCH, 0.4

        if id_type == "Driver's License":
            image_count = len(page.images)
            if any(marker in text for marker in _DL_BACK_MARKERS):
                side = "Back"
            elif image_count >= 2:
                side = "Front and Back"
            else:
                side = "Front"
            subtype = f"Drivers License {side}"
            reason_id = f"Driver's License ({side})"
        elif id_type is not None:
            subtype = id_type
            reason_id = id_type
        else:
            subtype = "Unknown Government ID Side"
            reason_id = None

        detected_name = next(iter(page.structured_tokens.name_hints), None)
        borrower_name = None
        reason_person = "borrower unknown"
        if detected_name:
            borrower_name = detected_name
            reason_person = f'name "{detected_name}" detected on the page'
        elif identity.last_name:
            reason_person = "no name reliably detected; loan's entered borrower name used"

        matches.append(
            KeyDocumentMatch(
                match_id="",
                category="government_id",
                subtype=subtype,
                confidence_band=band,
                confidence=confidence,
                document_id=occ.document_id,
                original_filename=occ.original_filename,
                borrower_name=borrower_name,
                reason=(
                    f"{reason_id} markers found on a scanned page ({reason_person})."
                    if reason_id
                    else f"Several ID-card-like fields found on a scanned page without an explicit "
                    f"document type ({reason_person})."
                ),
                document_page_range=(index + 1, index + 1),
                signature_status=None,
                person_name_override=detected_name,
            )
        )
    return matches


# ---------------------------------------------------------------------
# Mortgage Unity Privacy Policy
# ---------------------------------------------------------------------

_MU_COMPANY_MARKER = "mortgage unity"

# The real Mortgage Unity privacy notice (a standard GLBA "FACTS" model
# form, confirmed directly against a real sample) never actually
# contains the words "privacy policy" or "privacy notice" anywhere on
# the page -- the original detector's requirement for one of those two
# phrases meant it would never have matched the real document at all.
# The GLBA model form's title is a regulation-mandated phrase
# ("What does [Company] do with your personal information?"), specific
# enough that a mere reference/checklist item is very unlikely to
# reproduce it verbatim, unlike the generic word "privacy".
_PRIVACY_TITLE_PHRASE = "do with your personal information"
_PRIVACY_SECTION_MARKERS = (
    "facts",
    "who we are",
    "reasons we can share",
    "what we do",
)


def _find_mu_privacy_policy(
    occ: SourceOccurrence, fp: DocumentFingerprint, identity: PackageIdentity
) -> list[KeyDocumentMatch]:
    """Requires the company marker plus the GLBA model form's actual,
    regulation-mandated title phrase -- never just a mention of
    "privacy" (a checklist item, a disclosure listing what will be
    provided, a cover letter) -- see the module-level note above.
    """

    matches: list[KeyDocumentMatch] = []
    for index, page in enumerate(fp.pages):
        text = page.normalized_text.casefold()
        if _MU_COMPANY_MARKER not in text:
            continue  # Mortgage Unity-specific evidence is required -- a generic privacy notice never matches.
        if _PRIVACY_TITLE_PHRASE not in text:
            continue

        section_count = sum(1 for marker in _PRIVACY_SECTION_MARKERS if marker in text)
        band, confidence = (CONFIRMED, 1.0) if section_count >= 2 else (STRONG_MATCH, 0.75)

        matches.append(
            KeyDocumentMatch(
                match_id="",
                category="mu_privacy_policy",
                subtype=None,
                confidence_band=band,
                confidence=confidence,
                document_id=occ.document_id,
                original_filename=occ.original_filename,
                borrower_name=None,
                reason='"Mortgage Unity" and the GLBA privacy-notice title phrase both found on the page.',
                document_page_range=(index + 1, index + 1),
                signature_status=None,
            )
        )
    return matches


# ---------------------------------------------------------------------
# Mortgage Unity Massachusetts Broker Addendum
# ---------------------------------------------------------------------

_MA_ADDENDUM_TITLE_PHRASE = "addendum to uniform residential loan application"
_MA_ADDENDUM_SECTION_MARKERS = ("attorney disclosure", "broker license disclosure")


def _find_mu_ma_broker_addendum(
    occ: SourceOccurrence, fp: DocumentFingerprint, identity: PackageIdentity
) -> list[KeyDocumentMatch]:
    """Massachusetts-specific broker/attorney disclosure addendum
    (confirmed directly against a real "Mortgage Unity LLC Combined MA
    Broker Addendum" sample). Requires the company marker, the exact
    "Addendum to Uniform Residential Loan Application" title, AND the
    state name -- a mere reference to Mortgage Unity or to a broker
    addendum in a checklist/cover letter reproduces none of these
    together. Scoped to Massachusetts only, matching the one sample
    provided -- the same addendum for another state would need its own
    sample before this could recognize it without guessing at wording
    that might not match the real form.
    """

    matches: list[KeyDocumentMatch] = []
    for index, page in enumerate(fp.pages):
        text = page.normalized_text.casefold()
        if _MU_COMPANY_MARKER not in text:
            continue
        if _MA_ADDENDUM_TITLE_PHRASE not in text:
            continue
        if "massachusetts" not in text:
            continue

        section_count = sum(1 for marker in _MA_ADDENDUM_SECTION_MARKERS if marker in text)
        band, confidence = (CONFIRMED, 1.0) if section_count >= 1 else (STRONG_MATCH, 0.75)

        matches.append(
            KeyDocumentMatch(
                match_id="",
                category="mu_ma_broker_addendum",
                subtype=None,
                confidence_band=band,
                confidence=confidence,
                document_id=occ.document_id,
                original_filename=occ.original_filename,
                borrower_name=None,
                reason='"Mortgage Unity", the Massachusetts loan-application addendum title, and the '
                "state name all found on the page.",
                document_page_range=(index + 1, index + 1),
                signature_status=None,
            )
        )
    return matches


# ---------------------------------------------------------------------
# Loan non-proceeding documentation
# ---------------------------------------------------------------------

# Order matters: the first subtype whose markers are found wins (most
# regulatory-specific terms first), so a document is never double
# counted under two subtypes.
_NON_PROCEEDING_SUBTYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Adverse Action Notice", ("adverse action notice", "statement of credit denial")),
    ("Withdrawal Certification", ("withdrawal certification", "application withdrawal", "withdrawn loan certification")),
    ("Denial Notice", ("notice of denial", "loan denial notice", "your loan has been denied")),
    ("Cancellation Notice", ("loan has been cancelled", "loan has been canceled", "application has been cancelled", "application has been canceled", "cancellation of your loan", "cancellation of your application")),
    ("Closed for Incompleteness", ("closed for incompleteness", "file closed due to incomplete", "incomplete application")),
)
_OTHER_NON_PROCEEDING_MARKERS = (
    "will not proceed",
    "unable to proceed with your loan",
    "loan will not close",
    "application has been withdrawn",
)
# Ordinary conditions/missing-item requests must never be mistaken for
# a non-proceeding document -- if ONLY these appear (no positive marker
# above), nothing is reported at all.
_CONDITION_ONLY_MARKERS = ("please provide", "outstanding conditions", "stipulation", "suspense", "missing document")


def _find_non_proceeding_documents(
    occ: SourceOccurrence, fp: DocumentFingerprint, identity: PackageIdentity
) -> list[KeyDocumentMatch]:
    matches: list[KeyDocumentMatch] = []
    for index, page in enumerate(fp.pages):
        text = page.normalized_text.casefold()

        subtype = None
        for candidate_subtype, markers in _NON_PROCEEDING_SUBTYPES:
            if any(marker in text for marker in markers):
                subtype = candidate_subtype
                break

        if subtype is not None:
            band, confidence, reason = (
                CONFIRMED,
                1.0,
                f'A "{subtype}" marker phrase was found on the page.',
            )
        elif any(marker in text for marker in _OTHER_NON_PROCEEDING_MARKERS):
            subtype, band, confidence, reason = (
                "Other Non-Proceeding Document",
                POSSIBLE_MATCH,
                0.4,
                "Language suggesting the loan will not proceed was found, but it did not match a specific, "
                "regulatory-standard subtype.",
            )
        else:
            continue  # ordinary condition/missing-item language alone is never classified as non-proceeding

        matches.append(
            KeyDocumentMatch(
                match_id="",
                category="non_proceeding",
                subtype=subtype,
                confidence_band=band,
                confidence=confidence,
                document_id=occ.document_id,
                original_filename=occ.original_filename,
                borrower_name=None,
                reason=reason,
                document_page_range=(index + 1, index + 1),
                signature_status=None,
            )
        )
    return matches


def _group_contiguous(indices: list[int], max_gap: int = 0) -> list[tuple[int, int]]:
    """Groups a sorted list of page indices into (start, end) runs,
    tolerating gaps of up to `max_gap` pages (e.g. a Closing Disclosure
    page that doesn't repeat the title text but sits between two pages
    that do).
    """

    if not indices:
        return []
    groups: list[tuple[int, int]] = []
    start = prev = indices[0]
    for idx in indices[1:]:
        if idx - prev <= max_gap + 1:
            prev = idx
            continue
        groups.append((start, prev))
        start = prev = idx
    groups.append((start, prev))
    return groups


# ---------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------


def extract_key_documents(matches: list[KeyDocumentMatch], run: RunResult, important_docs_dir) -> None:
    """Extracts a standalone PDF for every Confirmed/Strong Match result,
    directly into `important_docs_dir` (never a subfolder, and never the
    "Final" folder -- that folder holds only the OG and Final Lender
    Package PDFs), using `naming.key_document_filename()`. Preserves the
    original page appearance/annotations/signatures exactly -- pages are
    copied from the already-converted PDF via pypdf, never re-rendered
    or OCR'd. Possible Matches are reported but never auto-extracted.
    """

    occ_by_id = {o.document_id: o for o in run.occurrences}
    used_names: dict[str, int] = {}

    for match in matches:
        if match.confidence_band not in _AUTO_EXTRACT_BANDS:
            continue
        occ = occ_by_id.get(match.document_id)
        if occ is None or not occ.converted_pdf_path or not occ.converted_pdf_path.exists():
            continue

        document_name = _DOCUMENT_NAME_BY_CATEGORY.get(match.category, match.category.replace("_", " ").title())
        if match.category == "non_proceeding":
            document_name = match.subtype or document_name

        # Government ID always uses the generic "Govt ID" document name
        # with the specific type/side ("Front", "Passport", ...) as its
        # own segment, and is never attributed to a lender (it
        # identifies the borrower personally, not the loan transaction).
        # The two Mortgage-Unity-specific documents (Privacy Policy, MA
        # Broker Addendum) are likewise never attributed to a lender --
        # they're Mortgage Unity's own company/regulatory documents, not
        # tied to whichever wholesale lender this particular loan went
        # to. ALTA's side (Buyer/Seller/Combined), when identified, is
        # its own segment too, but IS attributed to the lender like a
        # Closing Disclosure or Loan Estimate -- see
        # naming.key_document_filename's `include_lender` docstring.
        subtype_segment = None
        include_lender = True
        if match.category == "closing_disclosure":
            subtype_segment = match.signature_status
        elif match.category == "government_id":
            subtype_segment = match.subtype
            include_lender = False
        elif match.category in ("mu_privacy_policy", "mu_ma_broker_addendum"):
            include_lender = False
        elif match.category == "alta_settlement_statement":
            subtype_segment = match.subtype

        base_filename = naming.key_document_filename(
            run.identity,
            document_name,
            signature_status=subtype_segment,
            person_name_override=match.person_name_override,
            include_lender=include_lender,
        )
        count = used_names.get(base_filename, 0) + 1
        used_names[base_filename] = count
        filename = (
            base_filename
            if count == 1
            else naming.key_document_filename(
                run.identity,
                document_name,
                signature_status=subtype_segment,
                person_name_override=match.person_name_override,
                include_lender=include_lender,
                copy_suffix=f"Copy {count}",
            )
        )

        dest = important_docs_dir / filename
        start, end = match.document_page_range
        reader = PdfReader(str(occ.converted_pdf_path))
        writer = PdfWriter()
        for page_index in range(start - 1, end):
            writer.add_page(reader.pages[page_index])
        with dest.open("wb") as fh:
            writer.write(fh)
        match.extracted_filename = filename


_DOCUMENT_NAME_BY_CATEGORY = {
    "closing_disclosure": "Closing Disclosure",
    "loan_estimate": "Loan Estimate",
    "alta_settlement_statement": "ALTA Settlement Statement",
    "government_id": "Govt ID",
    "mu_privacy_policy": "MU Privacy Policy",
    "mu_ma_broker_addendum": "MU MA Broker Addendum",
}
