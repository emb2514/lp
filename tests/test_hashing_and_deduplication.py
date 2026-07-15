from __future__ import annotations

from fixtures.builders import make_pdf, make_signature_package, make_txt, read_pdf_page_count

from lender_package_builder.hashing import sha256_of_file


def _doc(run, filename):
    matches = [o for o in run.occurrences if o.original_filename == filename]
    assert len(matches) == 1, f"expected exactly one occurrence named {filename}"
    return matches[0]


def _by_relpath(run, relative_path):
    matches = [o for o in run.occurrences if o.original_relative_path == relative_path]
    assert len(matches) == 1, f"expected exactly one occurrence at {relative_path}"
    return matches[0]


# TEST 1 - EXACT DUPLICATE WITH DIFFERENT FILENAMES
def test_exact_duplicate_different_filenames(tmp_path, run_build):
    folder = tmp_path / "input"
    make_txt(folder / "alpha.txt", "identical content across two files\n")
    make_txt(folder / "beta.txt", "identical content across two files\n")

    run = run_build(folder)

    alpha = _doc(run, "alpha.txt")
    beta = _doc(run, "beta.txt")
    assert alpha.original_sha256 == beta.original_sha256

    og_ids = {doc_id for part in run.og_parts for doc_id in part.document_ids}
    final_ids = {doc_id for part in run.final_parts for doc_id in part.document_ids}

    assert alpha.document_id in og_ids and beta.document_id in og_ids
    assert alpha.document_id in final_ids
    assert beta.document_id not in final_ids
    assert beta.is_duplicate is True
    assert beta.duplicate_of_document_id == alpha.document_id

    dup_log = (run.output_path / "Reports" / "Duplicate_Removal_Log.txt").read_text()
    assert "beta.txt" in dup_log
    assert alpha.original_sha256 in dup_log


# TEST 2 - TWO BORROWER SIGNATURE PACKAGES (page-level content must never be deduplicated)
def test_signature_packages_both_kept_in_full(tmp_path, run_build):
    folder = tmp_path / "input"
    make_signature_package(folder / "borrower_a.pdf", "Alice Anderson", common_pages=19)
    make_signature_package(folder / "borrower_b.pdf", "Bob Baker", common_pages=19)

    run = run_build(folder)

    a = _doc(run, "borrower_a.pdf")
    b = _doc(run, "borrower_b.pdf")

    assert a.original_sha256 != b.original_sha256
    assert a.is_duplicate is False
    assert b.is_duplicate is False
    assert a.converted_page_count == 20
    assert b.converted_page_count == 20

    og_ids = {doc_id for part in run.og_parts for doc_id in part.document_ids}
    final_ids = {doc_id for part in run.final_parts for doc_id in part.document_ids}
    assert a.document_id in og_ids and b.document_id in og_ids
    assert a.document_id in final_ids and b.document_id in final_ids

    total_final_pages = sum(p.page_count for p in run.final_parts)
    assert total_final_pages == 40  # both complete 20-page documents, no pages removed


# TEST 3 - DIFFERENT DATES
def test_documents_with_different_dates_both_kept(tmp_path, run_build):
    folder = tmp_path / "input"
    make_txt(folder / "notice_jan.txt", "Notice dated 2026-01-15\nSame boilerplate text.\n")
    make_txt(folder / "notice_feb.txt", "Notice dated 2026-02-20\nSame boilerplate text.\n")

    run = run_build(folder)

    jan = _doc(run, "notice_jan.txt")
    feb = _doc(run, "notice_feb.txt")
    assert jan.original_sha256 != feb.original_sha256
    assert jan.is_duplicate is False
    assert feb.is_duplicate is False

    final_ids = {doc_id for part in run.final_parts for doc_id in part.document_ids}
    assert jan.document_id in final_ids
    assert feb.document_id in final_ids


# TEST 4 - IDENTICAL VISIBLE PAGES BUT DIFFERENT SOURCE BYTES
#
# RC2 CHANGE: this pair (identical visible text/pages, differing only in
# a PDF metadata tag) is the textbook definition of RC2's Level 2
# ("normalized PDF duplicate") -- content-aware detection layered ON TOP
# OF the original exact-SHA-256 pass, not a replacement for it (see
# content_dedup.py). Before RC2, exact-hash-only detection correctly
# left both files alone (their bytes genuinely differ) and this test
# asserted BOTH remained in Final. Since Level 2 now exists specifically
# to catch exactly this case, one copy is correctly excluded from Final
# now -- `is_duplicate` (exact-hash) stays False for both, as it always
# has (this is deliberately NOT an exact-hash duplicate), but exactly
# one is now `is_content_duplicate=True` via the "normalized_pdf"
# method, fully explained in Duplicate_Removal_Log.txt. Both copies
# remain fully present in OG, untouched, as always.
def test_identical_visible_content_different_source_bytes(tmp_path, run_build):
    folder = tmp_path / "input"
    make_pdf(folder / "version_x.pdf", pages=2, text_prefix="Shared Text",
              metadata={"/CustomTag": "version-x-only"})
    make_pdf(folder / "version_y.pdf", pages=2, text_prefix="Shared Text",
              metadata={"/CustomTag": "version-y-only"})

    x = folder / "version_x.pdf"
    y = folder / "version_y.pdf"
    assert sha256_of_file(x) != sha256_of_file(y)

    run = run_build(folder)
    dx = _doc(run, "version_x.pdf")
    dy = _doc(run, "version_y.pdf")

    # Neither is an EXACT-hash duplicate -- their original bytes genuinely differ.
    assert dx.is_duplicate is False
    assert dy.is_duplicate is False

    # Both remain fully present in OG, untouched, regardless of any
    # content-aware exclusion from Final.
    og_ids = {doc_id for part in run.og_parts for doc_id in part.document_ids}
    assert dx.document_id in og_ids
    assert dy.document_id in og_ids

    # Exactly one is excluded from Final via Level 2 content-aware
    # detection -- explained, auditable, and never silent.
    final_ids = {doc_id for part in run.final_parts for doc_id in part.document_ids}
    in_final = [d for d in (dx, dy) if d.document_id in final_ids]
    excluded = [d for d in (dx, dy) if d.document_id not in final_ids]
    assert len(in_final) == 1
    assert len(excluded) == 1
    assert excluded[0].is_content_duplicate is True
    assert excluded[0].duplicate_detection_method == "normalized_pdf"
    assert excluded[0].content_duplicate_of_document_id == in_final[0].document_id


# TEST 5 - EXACT DUPLICATES IN DIFFERENT FOLDERS
def test_exact_duplicates_in_different_folders(tmp_path, run_build):
    folder = tmp_path / "input"
    make_txt(folder / "east/report.txt", "quarterly figures identical everywhere\n")
    make_txt(folder / "west/report.txt", "quarterly figures identical everywhere\n")

    run = run_build(folder)

    east = _by_relpath(run, "east/report.txt")
    west = _by_relpath(run, "west/report.txt")

    assert east.traversal_index < west.traversal_index
    assert east.is_duplicate is False
    assert west.is_duplicate is True
    assert west.duplicate_of_document_id == east.document_id

    final_ids = {doc_id for part in run.final_parts for doc_id in part.document_ids}
    assert east.document_id in final_ids
    assert west.document_id not in final_ids

    og_ids = {doc_id for part in run.og_parts for doc_id in part.document_ids}
    assert east.document_id in og_ids and west.document_id in og_ids


# TEST 6 - SAME FILENAME, DIFFERENT CONTENT
def test_same_filename_different_content_both_kept_with_unique_ids(tmp_path, run_build):
    folder = tmp_path / "input"
    make_txt(folder / "east/statement.txt", "East region statement contents.\n")
    make_txt(folder / "west/statement.txt", "West region statement contents -- different!\n")

    run = run_build(folder)

    east = _by_relpath(run, "east/statement.txt")
    west = _by_relpath(run, "west/statement.txt")

    assert east.document_id != west.document_id
    assert east.original_sha256 != west.original_sha256
    assert east.is_duplicate is False
    assert west.is_duplicate is False

    final_ids = {doc_id for part in run.final_parts for doc_id in part.document_ids}
    assert east.document_id in final_ids
    assert west.document_id in final_ids
