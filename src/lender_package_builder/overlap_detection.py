"""Merged-document overlap / containment detection.

Detects when a standalone document (or a PDF Portfolio attachment,
which is just another standalone-shaped occurrence by the time this
runs, see pdf_portfolio.py) is a complete, safely-proven copy of content
already present inside a separate, larger "container" document (a big
merged lender package that already includes it).

Page-level analysis is used here purely for comparison and containment
detection -- never for deletion. A merged PDF's own pages are NEVER
touched, reordered, or split; only the redundant STANDALONE copy is
ever excluded from Final. This is the only safe direction: you cannot
"remove part of" a merged PDF without either deleting isolated pages
from its middle (explicitly forbidden) or risking loss of the merged
PDF's other, unique content, and rule 7 ("do not simply discard every
large merged PDF") forbids discarding the container wholesale just
because part of it is redundant elsewhere.

Reuses the exact same per-page comparator as content_dedup.py
(`compare_page`) so containment and whole-document duplicate detection
never disagree about what "the same page" means. Containment matching
is strictly per-container: a candidate whose content is split across
two DIFFERENT merged PDFs (half in one, half in another) is a partial
overlap against both, never a combined "full match" against either --
chaining matches across containers is not attempted.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from .content_dedup import AUTO_REMOVE_THRESHOLD, NEEDS_REVIEW_THRESHOLD, compare_page
from .models import OverlapFinding, SourceOccurrence
from .pdf_content import DocumentFingerprint, PageFingerprint

# A candidate is only considered to have a meaningful partial overlap
# with a container when at least this fraction of its non-blank pages
# appear as one contiguous matching run somewhere in the container --
# below this, it's simply "no_overlap" (too little in common to be
# worth surfacing in the report as a near-miss).
_PARTIAL_OVERLAP_MIN_RATIO = 0.4

_CLASSIFICATION_RANK = {
    "no_overlap": 0,
    "different_version": 1,
    "partial_overlap": 1,
    "uncertain_overlap": 2,
    "equivalent_contained": 3,
    "exact_contained": 3,
}


@dataclasses.dataclass
class _NonBlankIndex:
    pages: list[PageFingerprint]
    by_text_hash: dict[str, list[int]]


def _build_non_blank_index(fp: DocumentFingerprint) -> _NonBlankIndex:
    non_blank = [p for p in fp.pages if not p.blank.is_blank]
    index: dict[str, list[int]] = {}
    for i, p in enumerate(non_blank):
        index.setdefault(p.text_hash, []).append(i)
    return _NonBlankIndex(pages=non_blank, by_text_hash=index)


def _check_partial_overlap(
    candidate_id: str, cand_nonblank: list[PageFingerprint], container_id: str, container_nonblank: list[PageFingerprint]
) -> OverlapFinding:
    if not cand_nonblank or not container_nonblank:
        return OverlapFinding(candidate_id, container_id, "no_overlap")

    container_hashes = [p.text_hash for p in container_nonblank]
    best_run = 0
    for start_c in range(len(cand_nonblank)):
        target_hash = cand_nonblank[start_c].text_hash
        for pos, hash_at_pos in enumerate(container_hashes):
            if hash_at_pos != target_hash:
                continue
            run = 0
            while (
                start_c + run < len(cand_nonblank)
                and pos + run < len(container_nonblank)
                and cand_nonblank[start_c + run].text_hash == container_hashes[pos + run]
            ):
                run += 1
            best_run = max(best_run, run)

    ratio = best_run / len(cand_nonblank)
    if ratio >= _PARTIAL_OVERLAP_MIN_RATIO:
        return OverlapFinding(candidate_id, container_id, "partial_overlap", confidence=ratio)
    return OverlapFinding(candidate_id, container_id, "no_overlap")


def find_containment(
    candidate_id: str,
    candidate_fp: DocumentFingerprint,
    candidate_path: Path,
    container_id: str,
    container_fp: DocumentFingerprint,
    container_path: Path,
) -> OverlapFinding:
    """Compares `candidate_fp`'s complete non-blank page sequence against
    contiguous runs of `container_fp`'s non-blank pages, using the same
    hard-veto-aware, weakest-link comparator as content_dedup.py.
    """

    cand_nonblank = [p for p in candidate_fp.pages if not p.blank.is_blank]
    if not cand_nonblank:
        return OverlapFinding(candidate_id, container_id, "no_overlap")

    container_index = _build_non_blank_index(container_fp)
    container_nonblank = container_index.pages

    if len(cand_nonblank) > len(container_nonblank):
        return _check_partial_overlap(candidate_id, cand_nonblank, container_id, container_nonblank)

    start_positions = container_index.by_text_hash.get(cand_nonblank[0].text_hash, [])
    best_finding: OverlapFinding | None = None

    for start in start_positions:
        if start + len(cand_nonblank) > len(container_nonblank):
            continue
        span = container_nonblank[start : start + len(cand_nonblank)]
        page_results = [compare_page(pa, pb, candidate_path, container_path) for pa, pb in zip(cand_nonblank, span)]
        page_range = (span[0].page_index, span[-1].page_index)

        if any(r.hard_veto for r in page_results):
            candidate_finding = OverlapFinding(candidate_id, container_id, "different_version", page_range)
            if best_finding is None or _CLASSIFICATION_RANK[candidate_finding.classification] > _CLASSIFICATION_RANK[
                best_finding.classification
            ]:
                best_finding = candidate_finding
            continue

        weakest = min(r.confidence for r in page_results)
        if weakest >= AUTO_REMOVE_THRESHOLD:
            all_exact = all(pa.text_hash == pb.text_hash for pa, pb in zip(cand_nonblank, span))
            classification = "exact_contained" if all_exact else "equivalent_contained"
            # A safe full containment match ends the search for this
            # (candidate, container) pair immediately -- and per the
            # module docstring, matches are never chained across
            # different containers, so the caller moves on once this
            # is found.
            return OverlapFinding(candidate_id, container_id, classification, page_range, weakest)
        if weakest >= NEEDS_REVIEW_THRESHOLD:
            candidate_finding = OverlapFinding(candidate_id, container_id, "uncertain_overlap", page_range, weakest)
            if best_finding is None or _CLASSIFICATION_RANK[candidate_finding.classification] > _CLASSIFICATION_RANK[
                best_finding.classification
            ]:
                best_finding = candidate_finding

    if best_finding is not None:
        return best_finding

    return _check_partial_overlap(candidate_id, cand_nonblank, container_id, container_nonblank)


def detect_overlaps(
    occurrences: list[SourceOccurrence], fingerprints: dict[str, DocumentFingerprint]
) -> list[OverlapFinding]:
    """Runs containment detection over every fingerprinted occurrence not
    already resolved by a cheaper pass (exact-hash or content-aware
    duplicate). Mutates matching occurrences in place for high-confidence
    full containment (`is_contained_in_merged_document`,
    `contained_in_document_id`, `contained_page_range`) or flags
    uncertain containment for review (`needs_review`/`review_reason`,
    never excluded from Final) -- exactly mirroring content_dedup.py's
    own safety guarantees.

    A candidate currently serving as another occurrence's
    `content_duplicate_of_document_id` (i.e. content_dedup.py already
    designated it "the one everyone else duplicates") is never excluded
    here even on a fully-proven containment match -- content_dedup.py
    runs first and has no way to know overlap_detection.py would later
    want to remove its chosen canonical, so excluding it here would
    orphan every occurrence pointing to it (a content-duplicate
    reference to a document no longer in Final at all). Confirmed as a
    real, reachable defect from a real user's package: caught safely by
    validation.py's own integrity check rather than shipping a broken
    package, but the underlying interaction needed fixing at the
    source. The finding is still recorded for the report; the candidate
    and the documents that reference it simply all remain in Final,
    exactly as the "different_version"/"partial_overlap" cases already do.
    """

    occurrences_by_id = {o.document_id: o for o in occurrences}
    candidate_ids = [
        doc_id
        for doc_id in fingerprints
        if doc_id in occurrences_by_id
        and not occurrences_by_id[doc_id].is_duplicate
        and not occurrences_by_id[doc_id].is_content_duplicate
    ]
    retained_content_duplicate_ids = {
        occ.content_duplicate_of_document_id
        for occ in occurrences
        if occ.is_content_duplicate and occ.content_duplicate_of_document_id
    }

    findings: list[OverlapFinding] = []

    for candidate_id in candidate_ids:
        candidate_occ = occurrences_by_id[candidate_id]
        candidate_fp = fingerprints[candidate_id]
        best: OverlapFinding | None = None

        for container_id in candidate_ids:
            if container_id == candidate_id:
                continue
            container_fp = fingerprints[container_id]
            if container_fp.non_blank_page_count <= candidate_fp.non_blank_page_count:
                continue  # a container must genuinely have MORE content than the candidate

            finding = find_containment(
                candidate_id,
                candidate_fp,
                candidate_occ.converted_pdf_path,
                container_id,
                container_fp,
                occurrences_by_id[container_id].converted_pdf_path,
            )
            if finding.classification in ("exact_contained", "equivalent_contained"):
                best = finding
                break  # safely proven -- stop searching, never chain across containers
            if best is None or _CLASSIFICATION_RANK[finding.classification] > _CLASSIFICATION_RANK[best.classification]:
                best = finding

        if best is None or best.classification == "no_overlap":
            continue

        findings.append(best)

        if best.classification in ("exact_contained", "equivalent_contained"):
            if candidate_id in retained_content_duplicate_ids:
                pass  # see the module/function docstring -- never exclude a retained canonical
            else:
                best.excluded = True
                candidate_occ.is_contained_in_merged_document = True
                candidate_occ.contained_in_document_id = best.container_document_id
                candidate_occ.contained_page_range = best.contained_page_range
        elif best.classification == "uncertain_overlap":
            if not candidate_occ.needs_review:
                candidate_occ.needs_review = True
                candidate_occ.review_reason = (
                    f"uncertain containment match inside {best.container_document_id} "
                    f"(confidence {best.confidence:.2f}, below the {AUTO_REMOVE_THRESHOLD:.2f} "
                    "safe auto-exclusion threshold)"
                )
        # "different_version" and "partial_overlap" are recorded in the
        # findings list for the report, but never mutate the occurrence --
        # both documents simply remain in Final, exactly as they always
        # would have without this analysis running at all.

    return findings
