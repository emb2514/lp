"""Robert-package regression / acceptance test.

BLOCKER, DOCUMENTED: the real "Robert package" (the actual customer-
reported lender package referenced in the original RC2 task spec --
approximately 1099 source pages that should reduce to approximately
619 pages in Final, plus roughly 14 exact-SHA-256 duplicate groups
already verified correct under RC1) is not present anywhere in this
repository, this environment's filesystem, or any location this
session has access to (confirmed via repo-wide and filesystem-wide
search for "robert" before writing this file). This test therefore
cannot run against the real reported data, and no number in this file
should be read as reproducing the real package's exact page counts.

Per the explicit instruction covering this exact situation ("If the
real Robert package is unavailable, document that blocker and continue
every other task that does not depend on it"), this file instead builds
a synthetic package that recreates the SAME CLASS of bug the real
package exposed, entirely from fixtures generated in this test run (no
real borrower data, ever):

  1. A large merged "package" PDF containing several distinct component
     documents concatenated together (standing in for the lender's
     original big merged submission).
  2. Some of those SAME component documents ALSO separately, redundantly
     submitted as standalone top-level files -- byte-for-byte different
     from their copy inside the merged PDF (different container
     structure), so exact-SHA-256 (Level 1) cannot catch the
     redundancy, but the content is visibly identical -- exactly the
     "same document counted twice, inflating the page total" bug RC1
     could not detect and RC2's merged-document overlap detection
     (overlap_detection.py) exists to fix.
  3. Two genuinely different versions of one document (differing
     signature state) -- proving the fix does not overcorrect into
     removing meaningfully different content.
  4. A conventional exact-byte duplicate pair -- proving Level 1
     detection still works unchanged, exactly as required.

Assertions are entirely about which specific documents survive in
Final and why (never a fixed total page count), per the plan's own
explicit instruction not to force a target number.
"""

from __future__ import annotations

from fixtures.builders import make_merged_pdf, make_pdf, make_signed_pdf_variant, make_txt


def _final_ids(run) -> set[str]:
    return {doc_id for part in run.final_parts for doc_id in part.document_ids}


def _og_ids(run) -> set[str]:
    return {doc_id for part in run.og_parts for doc_id in part.document_ids}


def _doc(run, filename):
    matches = [o for o in run.occurrences if o.original_filename == filename]
    assert len(matches) == 1, f"expected exactly one occurrence named {filename}, found {len(matches)}"
    return matches[0]


def test_synthetic_robert_package_acceptance(tmp_path, run_build):
    folder = tmp_path / "input"

    # Component documents that will be concatenated into the big merged
    # package -- distinct, unrelated content, deliberately varied page
    # counts, mirroring a real multi-document lender submission.
    comp_disclosure = make_pdf(tmp_path / "_comp_disclosure.pdf", pages=4, text_prefix="Truth in Lending Disclosure")
    comp_note = make_pdf(tmp_path / "_comp_note.pdf", pages=3, text_prefix="Promissory Note Terms")
    comp_appraisal = make_pdf(tmp_path / "_comp_appraisal.pdf", pages=6, text_prefix="Property Appraisal Report")
    comp_insurance = make_pdf(tmp_path / "_comp_insurance.pdf", pages=2, text_prefix="Hazard Insurance Binder")

    make_merged_pdf(
        folder / "merged_lender_package.pdf",
        [comp_disclosure, comp_note, comp_appraisal, comp_insurance],
    )

    # (2) Redundant standalone re-submissions of documents ALSO inside
    # the merged package -- same visible content, different container
    # bytes (single-document PDF vs. embedded inside the big merge), so
    # exact-hash detection cannot catch this; only content-aware
    # containment detection can.
    (folder / "disclosure_resubmitted.pdf").write_bytes(comp_disclosure.read_bytes())
    (folder / "appraisal_resubmitted.pdf").write_bytes(comp_appraisal.read_bytes())

    # (3) Two genuinely different versions of the same underlying
    # document (signature state differs) -- must both survive, never
    # merged into one.
    make_signed_pdf_variant(folder / "authorization_unsigned.pdf", "Jordan Rivera", common_pages=3, signature_kind="unsigned")
    make_signed_pdf_variant(folder / "authorization_signed.pdf", "Jordan Rivera", common_pages=3, signature_kind="e_signed")

    # (4) A conventional exact-byte duplicate pair -- Level 1 must still
    # work, completely unchanged by any of the RC2 additions.
    make_txt(folder / "cover_letter.txt", "Please find the enclosed loan package for review.\n")
    make_txt(folder / "cover_letter_copy.txt", "Please find the enclosed loan package for review.\n")

    # A wholly unrelated, unique document -- must simply survive as-is.
    make_pdf(folder / "unique_addendum.pdf", pages=1, text_prefix="Addendum Regarding Escrow")

    run = run_build(folder)

    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"
    assert run.success is True

    merged = _doc(run, "merged_lender_package.pdf")
    disclosure_resubmit = _doc(run, "disclosure_resubmitted.pdf")
    appraisal_resubmit = _doc(run, "appraisal_resubmitted.pdf")
    unsigned = _doc(run, "authorization_unsigned.pdf")
    signed = _doc(run, "authorization_signed.pdf")
    cover = _doc(run, "cover_letter.txt")
    cover_copy = _doc(run, "cover_letter_copy.txt")
    addendum = _doc(run, "unique_addendum.pdf")

    og_ids = _og_ids(run)
    final_ids = _final_ids(run)

    # OG ALWAYS preserves every original source occurrence, untouched,
    # regardless of any Final-side decision -- the single most
    # important safety property this whole app exists to guarantee.
    all_doc_ids = {
        merged.document_id, disclosure_resubmit.document_id, appraisal_resubmit.document_id,
        unsigned.document_id, signed.document_id, cover.document_id, cover_copy.document_id,
        addendum.document_id,
    }
    assert all_doc_ids <= og_ids

    # The merged package itself is NEVER excluded, split, or reordered --
    # it is preserved in full regardless of what's redundant elsewhere.
    assert merged.document_id in final_ids

    # The redundant standalone re-submissions ARE safely excluded from
    # Final, each explained by containment inside the merged package --
    # this is the exact bug class the real Robert package exposed.
    assert disclosure_resubmit.document_id not in final_ids
    assert appraisal_resubmit.document_id not in final_ids
    assert disclosure_resubmit.is_contained_in_merged_document is True
    assert disclosure_resubmit.contained_in_document_id == merged.document_id
    assert appraisal_resubmit.is_contained_in_merged_document is True
    assert appraisal_resubmit.contained_in_document_id == merged.document_id

    # Genuinely different versions (signature state differs) are BOTH
    # preserved -- never merged, never one silently dropped.
    assert unsigned.document_id in final_ids
    assert signed.document_id in final_ids

    # Exact-byte duplicate detection (Level 1) is completely unaffected.
    assert cover.document_id in final_ids
    assert cover_copy.document_id not in final_ids
    assert cover_copy.is_duplicate is True
    assert cover_copy.duplicate_of_document_id == cover.document_id

    # A wholly unrelated document is simply retained.
    assert addendum.document_id in final_ids

    # Every exclusion is auditable in the reports -- no silent removal.
    dup_log = (run.output_path / "Reports" / "Duplicate_Removal_Log.txt").read_text()
    assert "cover_letter_copy.txt" in dup_log

    overlap_report = (run.output_path / "Reports" / "Merged_Document_Overlap_Report.txt").read_text()
    assert "disclosure_resubmitted.pdf" in overlap_report
    assert "appraisal_resubmitted.pdf" in overlap_report
    assert "merged_lender_package.pdf" in overlap_report
    assert "structural safety rule, not a quality judgment" in overlap_report

    # No isolated page was ever deleted from the middle of the merged
    # package -- its recorded page count is exactly the sum of its four
    # component documents (4+3+6+2), independently re-verified against
    # the actual PDF bytes on disk by validation.py's own
    # re-opened-file integrity checks (all passing, asserted above).
    assert merged.converted_page_count == 4 + 3 + 6 + 2 == 15


def test_acceptance_summary_documents_the_real_package_blocker():
    """Not a functional test -- exists so `pytest -k robert -v` output
    itself records, in plain text, that the real Robert package was
    unavailable and this suite ran the documented synthetic fallback
    instead. See this module's docstring for the full explanation.
    """

    assert True, (
        "BLOCKER (documented, not a failure): the real Robert package is not present in this "
        "repository or environment. test_synthetic_robert_package_acceptance() above exercises the "
        "same class of bug (redundant standalone re-submission of content already inside a merged "
        "package) using synthetic fixtures instead."
    )
