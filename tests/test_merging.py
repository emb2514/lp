"""Dedicated safety test proving OG's document set is invariant to every
RC2 Final-exclusion reason.

The core safety rule this file exists to prove: OG (`included_in_og`)
depends ONLY on whether an occurrence is an intentionally-ignored system
artifact -- never on any duplicate/containment/Portfolio decision. Final
(`included_in_final`) is the only package any of those decisions may
affect. This is exercised end-to-end via run_build with a single package
that triggers every current RC2 exclusion reason at once: an exact-hash
duplicate, a content-aware (normalized_pdf) duplicate, a PDF Portfolio
container, and a standalone document safely proven fully contained
inside a separate merged package.
"""

from __future__ import annotations

from fixtures.builders import make_merged_pdf, make_pdf, make_pdf_portfolio, make_txt


def test_og_contains_every_non_ignored_occurrence_regardless_of_final_exclusion_reason(tmp_path, run_build):
    folder = tmp_path / "input"

    # Exact-hash duplicate pair.
    make_txt(folder / "exact_a.txt", "identical content across two files\n")
    make_txt(folder / "exact_b.txt", "identical content across two files\n")

    # Content-aware (normalized_pdf) duplicate pair: same visible content,
    # different PDF metadata -> different source bytes, so this is NOT an
    # exact-hash duplicate, only a content-aware one.
    make_pdf(folder / "content_x.pdf", pages=2, text_prefix="Shared Text",
              metadata={"/CustomTag": "version-x-only"})
    make_pdf(folder / "content_y.pdf", pages=2, text_prefix="Shared Text",
              metadata={"/CustomTag": "version-y-only"})

    # PDF Portfolio container plus its embedded attachment.
    attachment_source = tmp_path / "_attachment_source.pdf"
    make_pdf(attachment_source, pages=1, text_prefix="Disclosure Attachment")
    make_pdf_portfolio(folder / "binder.pdf", [("disclosure.pdf", attachment_source.read_bytes())])

    # A standalone document fully contained inside a separate merged package.
    comp_a = make_pdf(folder / "component_a.pdf", pages=2, text_prefix="Component A Content")
    comp_b = make_pdf(folder / "component_b.pdf", pages=3, text_prefix="Component B Content")
    make_merged_pdf(folder / "merged_package.pdf", [comp_a, comp_b])

    run = run_build(folder)

    non_ignored = [o for o in run.occurrences if not o.is_ignored_artifact]
    assert len(non_ignored) >= 8  # exact x2, content x2, binder + attachment, component x2, merged

    og_ids = {doc_id for part in run.og_parts for doc_id in part.document_ids}
    final_ids = {doc_id for part in run.final_parts for doc_id in part.document_ids}

    # Every single non-ignored occurrence -- regardless of what happens
    # to it in Final -- is present in OG, untouched.
    for occ in non_ignored:
        assert occ.document_id in og_ids, f"{occ.original_filename} missing from OG"

    # Sanity: at least one occurrence of EACH RC2 exclusion reason is
    # actually present in this run and actually excluded from Final --
    # otherwise this test would trivially pass without exercising
    # anything.
    exact_dupes = [o for o in non_ignored if o.is_duplicate]
    content_dupes = [o for o in non_ignored if o.is_content_duplicate]
    portfolio_containers = [o for o in non_ignored if o.is_portfolio_container]
    contained_docs = [o for o in non_ignored if o.is_contained_in_merged_document]

    assert exact_dupes, "expected at least one exact-hash duplicate in this run"
    assert content_dupes, "expected at least one content-aware duplicate in this run"
    assert portfolio_containers, "expected at least one PDF Portfolio container in this run"
    assert contained_docs, "expected at least one merged-package-contained document in this run"

    for occ in exact_dupes + content_dupes + portfolio_containers + contained_docs:
        assert occ.document_id not in final_ids, (
            f"{occ.original_filename} ({occ.document_id}) should be excluded from Final "
            "but was found in a Final part"
        )
        # But it must still be in OG.
        assert occ.document_id in og_ids

    # OG's total page count equals the sum of every non-ignored document's
    # own converted page count -- proving merging never dropped pages
    # while building OG, no matter how many exclusion reasons apply to
    # Final.
    og_page_total = sum(p.page_count for p in run.og_parts)
    expected_og_pages = sum(o.converted_page_count or 0 for o in non_ignored)
    assert og_page_total == expected_og_pages

    for check in run.integrity_checks:
        assert check.passed, f"{check.name}: {check.detail}"


def test_final_excludes_only_occurrences_with_a_recorded_reason(tmp_path, run_build):
    folder = tmp_path / "input"
    make_txt(folder / "unique_one.txt", "first unique content\n")
    make_txt(folder / "unique_two.txt", "second unique content\n")
    make_pdf(folder / "content_x.pdf", pages=2, text_prefix="Shared Text",
              metadata={"/CustomTag": "version-x-only"})
    make_pdf(folder / "content_y.pdf", pages=2, text_prefix="Shared Text",
              metadata={"/CustomTag": "version-y-only"})

    run = run_build(folder)
    final_ids = {doc_id for part in run.final_parts for doc_id in part.document_ids}

    for occ in run.occurrences:
        if occ.is_ignored_artifact:
            continue
        if occ.document_id not in final_ids:
            explained = (
                (occ.is_duplicate and occ.duplicate_of_document_id)
                or (occ.is_content_duplicate and occ.content_duplicate_of_document_id and occ.duplicate_detection_method)
                or occ.is_portfolio_container
                or (occ.is_contained_in_merged_document and occ.contained_in_document_id)
            )
            assert explained, f"{occ.original_filename} excluded from Final with no recorded reason"
