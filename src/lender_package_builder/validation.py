"""Required integrity checks (spec section P, strengthened per the
Stage 1 splitting revision).

Every check returns an explicit PASS/FAIL plus a human-readable detail
string with the relevant counts. The CLI refuses to report overall
success if any check here fails.

Several checks independently RE-READ the actual generated PDF files
(rather than trusting bookkeeping counters computed while building
them) specifically to prove -- not just assume -- that no page was
lost and no source document was split during merging.
"""

from __future__ import annotations

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .hashing import sha256_of_file
from .models import IntegrityCheckResult, OutputPart, ProcessingStatus, RunResult, SourceOccurrence


def run_integrity_checks(
    run: RunResult, max_pages_per_part: int, max_size_bytes_per_part: int
) -> list[IntegrityCheckResult]:
    occ_by_id: dict[str, SourceOccurrence] = {o.document_id: o for o in run.occurrences}
    non_ignored = [o for o in run.occurrences if not o.is_ignored_artifact]
    og_included = [o for o in non_ignored]  # every non-ignored occurrence belongs in OG
    final_included = [o for o in non_ignored if not o.is_duplicate]
    duplicates = [o for o in non_ignored if o.is_duplicate]

    checks: list[IntegrityCheckResult] = []
    checks.append(_check_final_status_recorded(run.occurrences))
    checks.append(_check_no_silent_omission(run.og_parts, og_included))
    checks.append(_check_sha256_present_when_readable(non_ignored))
    checks.append(_check_og_document_count(run.og_parts, og_included))
    checks.append(_check_final_document_count(run.og_parts, run.final_parts, duplicates))

    # Independent, per-document proof that each document's recorded page
    # count matches what its own converted PDF file actually contains.
    checks.append(_check_document_actual_page_counts(non_ignored))

    # Independent, per-part proof that the actual merged PDF's page
    # count equals the sum of its documents' (now-verified) page
    # counts -- i.e. merging did not drop, duplicate, or fragment pages.
    checks.append(_check_part_pages_match_documents(run.og_parts, occ_by_id, "OG"))
    checks.append(_check_part_pages_match_documents(run.final_parts, occ_by_id, "Final"))

    og_page_total = sum(p.page_count for p in run.og_parts)
    checks.append(_check_og_page_total(og_page_total, og_included))
    checks.append(_check_final_page_total(og_page_total, run.final_parts, duplicates))
    checks.append(_check_duplicate_hash_match(duplicates, occ_by_id))
    checks.append(_check_no_nonidentical_removed(final_included, run.final_parts))
    checks.append(_check_order_preserved(run.og_parts, occ_by_id, "OG"))
    checks.append(_check_order_preserved(run.final_parts, occ_by_id, "Final"))
    checks.append(_check_no_document_split_across_parts(run.og_parts, "OG"))
    checks.append(_check_no_document_split_across_parts(run.final_parts, "Final"))
    all_parts = run.og_parts + run.final_parts
    checks.append(_check_pdfs_open(all_parts))
    checks.append(_check_pdfs_have_pages(all_parts))
    checks.append(_check_within_maximums(all_parts, max_pages_per_part, max_size_bytes_per_part))
    checks.append(_check_oversized_parts_valid(all_parts, max_pages_per_part, max_size_bytes_per_part))
    checks.append(_check_unconverted_have_placeholder_and_copy(run.occurrences))
    checks.append(_check_originals_unmodified(run.occurrences))
    return checks


def _check_final_status_recorded(occurrences: list[SourceOccurrence]) -> IntegrityCheckResult:
    valid_statuses = {
        ProcessingStatus.CONVERTED,
        ProcessingStatus.UNCONVERTED_PLACEHOLDER,
        ProcessingStatus.IGNORED_SYSTEM_ARTIFACT,
    }
    missing = [o.document_id for o in occurrences if o.status not in valid_statuses]
    passed = not missing
    detail = (
        f"{len(occurrences)} occurrences all have a final recorded status."
        if passed
        else f"{len(missing)} occurrence(s) missing a final status: {missing[:10]}"
    )
    return IntegrityCheckResult("Every occurrence has exactly one recorded final status", passed, detail)


def _check_no_silent_omission(og_parts: list[OutputPart], og_included: list[SourceOccurrence]) -> IntegrityCheckResult:
    expected = {o.document_id for o in og_included}
    actual: set[str] = set()
    for part in og_parts:
        actual.update(part.document_ids)
    missing = expected - actual
    extra = actual - expected
    passed = not missing and not extra
    detail = (
        f"All {len(expected)} eligible source occurrences are present in OG output."
        if passed
        else f"Missing from OG: {sorted(missing)[:10]}; unexpected in OG: {sorted(extra)[:10]}"
    )
    return IntegrityCheckResult("Every source document appears in OG", passed, detail)


def _check_sha256_present_when_readable(non_ignored: list[SourceOccurrence]) -> IntegrityCheckResult:
    missing = [
        o.document_id for o in non_ignored if o.extracted_path is not None and not o.original_sha256
    ]
    passed = not missing
    detail = (
        "All readable source occurrences have a recorded SHA-256."
        if passed
        else f"{len(missing)} readable occurrence(s) missing SHA-256: {missing[:10]}"
    )
    return IntegrityCheckResult("Every readable source occurrence has a SHA-256", passed, detail)


def _check_og_document_count(og_parts: list[OutputPart], og_included: list[SourceOccurrence]) -> IntegrityCheckResult:
    actual = sum(len(p.document_ids) for p in og_parts)
    expected = len(og_included)
    passed = actual == expected
    detail = f"OG contains {actual} documents; expected {expected} (all non-ignored occurrences)."
    return IntegrityCheckResult("OG document count matches non-ignored occurrences", passed, detail)


def _check_final_document_count(
    og_parts: list[OutputPart], final_parts: list[OutputPart], duplicates: list[SourceOccurrence]
) -> IntegrityCheckResult:
    og_count = sum(len(p.document_ids) for p in og_parts)
    final_count = sum(len(p.document_ids) for p in final_parts)
    expected = og_count - len(duplicates)
    passed = final_count == expected
    detail = (
        f"Final contains {final_count} documents; expected {expected} "
        f"(OG {og_count} minus {len(duplicates)} later duplicate occurrences)."
    )
    return IntegrityCheckResult("Every unique source document appears in Final", passed, detail)


def _check_document_actual_page_counts(non_ignored: list[SourceOccurrence]) -> IntegrityCheckResult:
    """Re-open every document's OWN converted PDF and confirm its actual
    page count matches what was recorded. This is the foundation for
    proving "no source pages disappeared": if this holds for every
    document, and part totals match the sum of these (verified
    elsewhere), then merging cannot have silently dropped pages.
    """

    mismatches = []
    unreadable = []
    checked = 0
    for occ in non_ignored:
        if occ.converted_pdf_path is None or not occ.converted_pdf_path.exists():
            unreadable.append(occ.document_id)
            continue
        try:
            actual_pages = len(PdfReader(str(occ.converted_pdf_path)).pages)
        except (PdfReadError, OSError, ValueError):
            unreadable.append(occ.document_id)
            continue
        checked += 1
        if actual_pages != (occ.converted_page_count or 0):
            mismatches.append(
                f"{occ.document_id} (recorded {occ.converted_page_count}, actual {actual_pages})"
            )
    passed = not mismatches and not unreadable
    detail = (
        f"Re-opened {checked} document PDF(s); every actual page count matched its recorded count."
        if passed
        else f"Mismatches: {mismatches[:10]}; unreadable: {unreadable[:10]}"
    )
    return IntegrityCheckResult("Every document's actual PDF page count matches its recorded count", passed, detail)


def _check_part_pages_match_documents(
    parts: list[OutputPart], occ_by_id: dict[str, SourceOccurrence], label: str
) -> IntegrityCheckResult:
    """Confirm each part's actual page count (re-read from disk when the
    part was written -- see merging.py) equals the sum of its member
    documents' own recorded page counts. This directly proves that
    merging did not split, truncate, or drop any document's pages.
    """

    mismatches = []
    for part in parts:
        expected = sum((occ_by_id[d].converted_page_count or 0) for d in part.document_ids if d in occ_by_id)
        if part.page_count != expected:
            mismatches.append(
                f"{part.package} part {part.index} (actual {part.page_count}, expected {expected})"
            )
    passed = not mismatches
    detail = (
        f"All {len(parts)} {label} part(s) have an actual page count equal to the sum of their "
        "documents' page counts -- no document was split or truncated during merging."
        if passed
        else f"Mismatches: {mismatches[:10]}"
    )
    return IntegrityCheckResult(f"{label}: no source document was split during merging", passed, detail)


def _check_og_page_total(og_page_total: int, og_included: list[SourceOccurrence]) -> IntegrityCheckResult:
    expected = sum(o.converted_page_count or 0 for o in og_included)
    passed = og_page_total == expected
    detail = (
        f"OG total pages is {og_page_total}; expected {expected} (sum of all converted source "
        "documents and placeholders)."
    )
    return IntegrityCheckResult("OG total pages equal converted documents plus placeholders", passed, detail)


def _check_final_page_total(
    og_page_total: int, final_parts: list[OutputPart], duplicates: list[SourceOccurrence]
) -> IntegrityCheckResult:
    final_page_total = sum(p.page_count for p in final_parts)
    dup_pages = sum(o.converted_page_count or 0 for o in duplicates)
    expected = og_page_total - dup_pages
    passed = final_page_total == expected
    detail = (
        f"Final total pages is {final_page_total}; expected {expected} "
        f"(OG {og_page_total} minus {dup_pages} pages from removed exact-duplicate source files)."
    )
    return IntegrityCheckResult(
        "Final total pages equal OG pages minus only removed duplicate page counts", passed, detail
    )


def _check_duplicate_hash_match(
    duplicates: list[SourceOccurrence], occ_by_id: dict[str, SourceOccurrence]
) -> IntegrityCheckResult:
    mismatches = []
    for occ in duplicates:
        retained = occ_by_id.get(occ.duplicate_of_document_id or "")
        if retained is None or retained.original_sha256 != occ.original_sha256:
            mismatches.append(occ.document_id)
    passed = not mismatches
    detail = (
        f"All {len(duplicates)} duplicate occurrence(s) share their retained occurrence's SHA-256."
        if passed
        else f"{len(mismatches)} duplicate(s) had a hash mismatch with their retained occurrence: {mismatches[:10]}"
    )
    return IntegrityCheckResult(
        "Anything excluded from Final matched its retained copy's complete original SHA-256", passed, detail
    )


def _check_no_nonidentical_removed(
    final_included: list[SourceOccurrence], final_parts: list[OutputPart]
) -> IntegrityCheckResult:
    expected = {o.document_id for o in final_included}
    actual: set[str] = set()
    for part in final_parts:
        actual.update(part.document_ids)
    missing = expected - actual
    passed = not missing
    detail = (
        "No non-duplicate (nonidentical) source document is missing from Final."
        if passed
        else f"{len(missing)} nonidentical occurrence(s) missing from Final: {sorted(missing)[:10]}"
    )
    return IntegrityCheckResult("No nonidentical source hash was removed", passed, detail)


def _check_order_preserved(
    parts: list[OutputPart], occ_by_id: dict[str, SourceOccurrence], label: str
) -> IntegrityCheckResult:
    flattened = [doc_id for part in parts for doc_id in part.document_ids]
    indices = [occ_by_id[d].traversal_index for d in flattened if d in occ_by_id]
    passed = indices == sorted(indices)
    detail = (
        f"{label} document order matches ascending source traversal order ({len(indices)} documents)."
        if passed
        else f"{label} document order does NOT match source traversal order."
    )
    return IntegrityCheckResult(f"{label} preserves source order", passed, detail)


def _check_no_document_split_across_parts(parts: list[OutputPart], label: str) -> IntegrityCheckResult:
    seen: set[str] = set()
    dupes: set[str] = set()
    for part in parts:
        for doc_id in part.document_ids:
            if doc_id in seen:
                dupes.add(doc_id)
            seen.add(doc_id)
    passed = not dupes
    detail = (
        f"No document appears in more than one {label} part."
        if passed
        else f"{len(dupes)} document(s) appear in multiple {label} parts: {sorted(dupes)[:10]}"
    )
    return IntegrityCheckResult(f"No source document crosses {label} part boundaries", passed, detail)


def _check_pdfs_open(parts: list[OutputPart]) -> IntegrityCheckResult:
    failures = []
    for part in parts:
        try:
            PdfReader(str(part.file_path))
        except (PdfReadError, OSError, ValueError) as exc:
            failures.append(f"{part.file_path.name}: {exc}")
    passed = not failures
    detail = (
        f"All {len(parts)} output PDFs opened successfully."
        if passed
        else f"{len(failures)} output PDF(s) failed to open: {failures[:5]}"
    )
    return IntegrityCheckResult("Every generated output PDF opens successfully", passed, detail)


def _check_pdfs_have_pages(parts: list[OutputPart]) -> IntegrityCheckResult:
    failures = []
    for part in parts:
        try:
            reader = PdfReader(str(part.file_path))
            if len(reader.pages) < 1:
                failures.append(part.file_path.name)
        except (PdfReadError, OSError, ValueError):
            failures.append(part.file_path.name)
    passed = not failures
    detail = (
        f"All {len(parts)} output PDFs have at least one page."
        if passed
        else f"{len(failures)} output PDF(s) had zero pages or could not be read: {failures[:5]}"
    )
    return IntegrityCheckResult("Every generated output PDF has at least one page", passed, detail)


def _check_within_maximums(
    parts: list[OutputPart], max_pages_per_part: int, max_size_bytes_per_part: int
) -> IntegrityCheckResult:
    violations = []
    for part in parts:
        if part.is_oversized:
            continue
        if part.page_count > max_pages_per_part or part.file_size_bytes > max_size_bytes_per_part:
            violations.append(f"{part.package} part {part.index}")
    passed = not violations
    detail = (
        "All non-oversized parts stay within both configured maximums."
        if passed
        else f"{len(violations)} non-oversized part(s) exceeded a configured maximum: {violations[:10]}"
    )
    return IntegrityCheckResult("Every nonoversized part stays within both configured maximums", passed, detail)


def _check_oversized_parts_valid(
    parts: list[OutputPart], max_pages_per_part: int, max_size_bytes_per_part: int
) -> IntegrityCheckResult:
    invalid = []
    oversized_count = 0
    for part in parts:
        if not part.is_oversized:
            continue
        oversized_count += 1
        genuinely_oversized = (
            part.page_count > max_pages_per_part or part.file_size_bytes > max_size_bytes_per_part
        )
        if len(part.document_ids) != 1 or not genuinely_oversized:
            invalid.append(f"{part.package} part {part.index}")
    passed = not invalid
    detail = (
        f"{oversized_count} oversized part(s) each contain exactly one intact oversized document."
        if passed
        else f"{len(invalid)} oversized part(s) failed validation: {invalid[:10]}"
    )
    return IntegrityCheckResult("Every oversized part contains exactly one intact oversized document", passed, detail)


def _check_unconverted_have_placeholder_and_copy(
    occurrences: list[SourceOccurrence],
) -> IntegrityCheckResult:
    unconverted = [o for o in occurrences if o.status == ProcessingStatus.UNCONVERTED_PLACEHOLDER]
    missing_placeholder = [
        o.document_id for o in unconverted if not o.converted_pdf_path or not o.converted_pdf_path.exists()
    ]
    unpreservable = [o.document_id for o in unconverted if o.extracted_path is None]
    missing_copy = [
        o.document_id
        for o in unconverted
        if o.extracted_path is not None
        and (not o.unconverted_copy_path or not o.unconverted_copy_path.exists())
    ]
    passed = not missing_placeholder and not missing_copy
    detail = (
        f"{len(unconverted)} unconverted source(s) each have a placeholder PDF and a preserved "
        f"original copy."
    )
    if unpreservable:
        detail += (
            f" ({len(unpreservable)} could not be preserved because their original bytes were "
            "never successfully extracted from their source archive; see report.)"
        )
    if not passed:
        detail += f" FAILURES -- missing placeholder: {missing_placeholder[:5]}; missing copy: {missing_copy[:5]}"
    return IntegrityCheckResult("Every unconverted source has a placeholder and preserved copy", passed, detail)


def _check_originals_unmodified(occurrences: list[SourceOccurrence]) -> IntegrityCheckResult:
    mismatches = []
    checked = 0
    for occ in occurrences:
        if occ.extracted_path is None or not occ.original_sha256:
            continue
        if not occ.extracted_path.exists():
            continue
        checked += 1
        try:
            current_hash = sha256_of_file(occ.extracted_path)
        except OSError:
            mismatches.append(occ.document_id)
            continue
        if current_hash != occ.original_sha256:
            mismatches.append(occ.document_id)
    passed = not mismatches
    detail = (
        f"Re-hashed {checked} extracted source file(s); all matched their recorded original SHA-256."
        if passed
        else f"{len(mismatches)} source file(s) no longer match their original SHA-256: {mismatches[:10]}"
    )
    return IntegrityCheckResult("No original source file was modified", passed, detail)
