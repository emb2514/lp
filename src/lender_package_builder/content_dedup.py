"""Level 2/3/4 content-aware duplicate detection.

Level 2 ("normalized PDF duplicate") is not a separate algorithm from
Level 3 ("content-equivalent") -- it is the case where the same per-page
comparator used for Level 3 finds every page an exact normalized-text
match. Level 4 ("blank-page-tolerant") is the same comparator again,
with conservatively-classified-blank pages stripped from both documents
first. One function, `compare_documents`, underlies all three.

Never touches `SourceOccurrence.is_duplicate` / `models.DuplicateGroup`
-- those stay exact-SHA-256-only (Level 1), so validation.py's strict
exact-hash invariant checks never have to reason about a confidence
score. This module only ever writes the new RC2 fields
(`is_content_duplicate`, `needs_review`, etc.) and produces
`ContentDuplicateGroup` records.

Safety-critical design choice, found necessary during calibration
against the existing `test_signature_packages_both_kept_in_full`
regression test (19 shared boilerplate pages, 1 differing signature
page): whole-document aggregation is the WEAKEST-LINK confidence across
all compared pages, never an average. A document-level average would
let 19 agreeing pages dilute the one real difference into an
artificially high score; the weakest single page must be able to veto
the whole match on its own.
"""

from __future__ import annotations

import dataclasses
import difflib
from pathlib import Path

from . import pdf_render
from .models import ContentDuplicateGroup, ProcessingStatus, SourceOccurrence
from .pdf_content import DocumentFingerprint, PageFingerprint, build_document_fingerprint, hamming_distance

# Confidence bands -- defaults, flagged for empirical tuning against
# real lender packages (see the RC2 deliverable report for details).
AUTO_REMOVE_THRESHOLD = 0.95
NEEDS_REVIEW_THRESHOLD = 0.80

# A page's extracted text is trusted as a real signal once it has at
# least this many normalized characters -- deliberately low. This is
# NOT a "is this text long enough to be precise" bar (a short label like
# "Content A 1 of 2" is exactly as precise/reliable as a long paragraph;
# text extraction doesn't get less accurate just because there's less of
# it) -- it only distinguishes "there is real extracted text here at
# all" from "this page is genuinely text-empty" (a scanned page with no
# OCR layer). Originally set much higher (20) under the assumption that
# short text needed visual corroboration; testing caught this actively
# making things LESS safe: a coarse whole-page perceptual hash (8x8
# downsampled dHash) cannot see a single-character difference like
# "Content A" vs "Content B" at all, so escalating a short-but-precise
# text mismatch to the render tier let the render tier's blind spot
# silently overwrite a signal that was already correct. See
# compare_page()'s escalation guard below, which was changed to match.
_MIN_RELIABLE_TEXT_CHARS = 5

# Beyond this many documents in one structural bucket, full pairwise
# comparison would be O(k^2) on a potentially large k -- fall back to an
# O(k) exact-normalized-hash-only grouping for that bucket instead. The
# caller is told which buckets fell back so it can note this in the
# report (per the "no unbounded quadratic process" performance
# requirement).
DEFAULT_MAX_BUCKET_SIZE = 50

_OUTCOME_RANK = {"no_match": 0, "different_version": 1, "uncertain": 2, "same": 3}


@dataclasses.dataclass
class PageComparisonResult:
    confidence: float
    hard_veto: bool
    veto_reason: str | None


@dataclasses.dataclass
class PairComparison:
    outcome: str  # "same" | "different_version" | "uncertain" | "no_match"
    confidence: float = 0.0
    method: str | None = None
    blank_pages_ignored_count: int = 0
    veto_reasons: tuple[str, ...] = ()


class _UnionFind:
    """Minimal disjoint-set structure for grouping pairwise "same"
    verdicts into full connected components (e.g. three copies of the
    same e-signed document, not just pairs).
    """

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb

    def groups(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for node in self._parent:
            root = self.find(node)
            out.setdefault(root, []).append(node)
        return out


def build_fingerprints(occurrences: list[SourceOccurrence]) -> dict[str, DocumentFingerprint]:
    """Fingerprints every occurrence eligible for content-aware analysis.

    Excludes ignored artifacts and exact-hash duplicates (already fully
    resolved by the cheaper Level 1 pass -- re-analyzing them would be
    wasted work and could only ever agree with Level 1's own decision),
    and excludes anything that is not a real converted PDF: an
    unconverted placeholder's "content" is just an explanation of a
    conversion failure, never real document content, and must never be
    compared against anything or treated as a candidate duplicate.
    """

    fingerprints: dict[str, DocumentFingerprint] = {}
    for occ in occurrences:
        if occ.is_ignored_artifact or occ.is_duplicate:
            continue
        if occ.status != ProcessingStatus.CONVERTED:
            continue
        if not occ.converted_pdf_path:
            continue
        try:
            fingerprints[occ.document_id] = build_document_fingerprint(occ.document_id, occ.converted_pdf_path)
        except Exception:
            # A single unreadable converted PDF must never crash the
            # whole run -- it simply never participates in content-aware
            # comparison. It remains fully present in OG and Final,
            # exactly as it always was before RC2.
            continue
    return fingerprints


def _bucket_key(fp: DocumentFingerprint) -> tuple:
    """Cheap structural key for candidate grouping -- performance only,
    never proof of duplication (per the non-negotiable safety rules,
    filenames and file sizes never participate here either; page counts
    and geometry are structural properties of the actual content, not
    filenames/sizes, and are only ever used to narrow which pairs get
    the expensive real comparison, never to decide the outcome itself).
    """

    return (
        fp.non_blank_page_count,
        fp.page_dims_signature,
        fp.has_signature_field,
        fp.has_form_fields,
    )


def _text_similarity(text_a: str, text_b: str) -> float:
    """Word-level (token-level), not character-level, similarity.

    Deliberately NOT `difflib.SequenceMatcher(None, text_a, text_b)` on
    the raw strings -- found via direct testing to be unsafe for exactly
    the case this whole comparator exists to protect against. A single
    meaningfully different WORD (a page label, a borrower's initial, a
    changed reference number -- anything not already caught by the
    dates/dollar-amounts/name-hints structured-token vetoes above)
    becomes a proportionally SMALLER fraction of the string as the
    surrounding shared text gets longer, so character-level similarity
    trends toward 1.0 for realistic-length lender-document paragraphs
    even when exactly one meaningful word changed -- e.g. "version with
    some content A" vs "...content B" scored 0.963 character-level
    (crossing the 0.95 auto-remove threshold) but only 0.80 word-level.
    Tokenizing into whole words first means one differing word is always
    counted as one non-matching token among N, proportional to the
    document's actual word count rather than its character count, which
    is the more stable and appropriate measure of "how much of the
    content changed" for prose/form text.
    """

    if not text_a and not text_b:
        return 1.0
    return difflib.SequenceMatcher(None, text_a.split(), text_b.split()).ratio()


def _image_similarity(pa: PageFingerprint, pb: PageFingerprint) -> float | None:
    if not pa.images and not pb.images:
        return None
    if len(pa.images) != len(pb.images):
        # Reachable only if called outside compare_page's own hard-veto
        # guard (which already handles this case) -- stay conservative.
        return 0.0
    similarities = []
    for img_a, img_b in zip(pa.images, pb.images):
        if img_a.byte_sha256 == img_b.byte_sha256:
            similarities.append(1.0)
            continue
        components = []
        if img_a.perceptual_hash is not None and img_b.perceptual_hash is not None:
            distance = hamming_distance(img_a.perceptual_hash, img_b.perceptual_hash)
            components.append(1.0 - distance / 64)
        if img_a.average_color is not None and img_b.average_color is not None:
            # A difference-hash alone is blind to absolute color -- two
            # solid, uniform-color images of ANY two different colors
            # produce the identical (all-zero) dHash, since dHash only
            # measures local gradients between adjacent pixels and a
            # solid color has none. Found via direct testing (a solid
            # red swatch and a solid blue swatch hashed identically and
            # were falsely matched). Average-color distance closes this
            # gap; combined via min() with the dHash score, same
            # weakest-link principle as everywhere else in this module.
            components.append(_color_similarity(img_a.average_color, img_b.average_color))
        similarities.append(min(components) if components else 0.5)
    return min(similarities) if similarities else None


def _color_similarity(color_a: tuple[float, float, float], color_b: tuple[float, float, float]) -> float:
    # Euclidean distance in RGB space, normalized by the maximum
    # possible distance (black to white, sqrt(3 * 255^2)).
    max_distance = (3 * 255**2) ** 0.5
    distance = sum((a - b) ** 2 for a, b in zip(color_a, color_b)) ** 0.5
    return 1.0 - (distance / max_distance)


def compare_page(pa: PageFingerprint, pb: PageFingerprint, pdf_path_a: Path, pdf_path_b: Path) -> PageComparisonResult:
    """Compares two pages. Hard vetoes are checked BEFORE any similarity
    scoring: a single differing signature/form-value/date/dollar-amount/
    name-like-text must veto the match regardless of how similar the
    surrounding text looks (see module docstring on why an average
    similarity score is not safe here).
    """

    form_a = {f.name: (f.field_type, f.value) for f in pa.form_fields}
    form_b = {f.name: (f.field_type, f.value) for f in pb.form_fields}
    annots_a = {(a.subtype, a.contents, a.has_appearance_stream) for a in pa.annotations}
    annots_b = {(a.subtype, a.contents, a.has_appearance_stream) for a in pb.annotations}
    same_images = len(pa.images) == len(pb.images) and all(
        ia.byte_sha256 == ib.byte_sha256 for ia, ib in zip(pa.images, pb.images)
    )

    # A fast exact-match shortcut is only safe when EVERY signal this
    # comparator cares about agrees, not just extracted text -- text
    # extraction never reflects AcroForm field values or annotation
    # content at all (they live in annotation dictionaries, not the
    # page's own content stream), so checking text_hash alone here
    # previously let two pages with identical visible text but different
    # form-field values slip through as an "exact match," bypassing the
    # hard-veto checks below entirely. Caught by
    # test_content_dedup.py::test_different_form_field_values_both_retained
    # during development.
    if (
        pa.text_hash == pb.text_hash
        and same_images
        and form_a == form_b
        and annots_a == annots_b
        and pa.has_signature_field == pb.has_signature_field
        and pa.has_signed_signature == pb.has_signed_signature
    ):
        return PageComparisonResult(1.0, False, None)

    if pa.has_signature_field != pb.has_signature_field:
        return PageComparisonResult(0.0, True, "signature field presence differs")
    if pa.has_signed_signature != pb.has_signed_signature:
        return PageComparisonResult(0.0, True, "signed-signature presence differs")
    if len(pa.images) != len(pb.images):
        return PageComparisonResult(0.0, True, "embedded image count differs")
    if form_a != form_b:
        return PageComparisonResult(0.0, True, "form field values differ")
    if annots_a != annots_b:
        return PageComparisonResult(0.0, True, "annotation content differs")
    if pa.structured_tokens.dates != pb.structured_tokens.dates:
        return PageComparisonResult(0.0, True, "dates differ")
    if pa.structured_tokens.dollar_amounts != pb.structured_tokens.dollar_amounts:
        return PageComparisonResult(0.0, True, "dollar amounts differ")
    if pa.structured_tokens.name_hints != pb.structured_tokens.name_hints:
        return PageComparisonResult(0.0, True, "name-like text differs")

    text_similarity = _text_similarity(pa.normalized_text, pb.normalized_text)
    image_similarity = _image_similarity(pa, pb)

    has_reliable_text = (
        len(pa.normalized_text) >= _MIN_RELIABLE_TEXT_CHARS and len(pb.normalized_text) >= _MIN_RELIABLE_TEXT_CHARS
    )

    components = [text_similarity]
    if image_similarity is not None:
        components.append(image_similarity)
    confidence = min(components)

    # Escalate to the last, most expensive tier only when NEITHER text
    # NOR embedded-image extraction found anything usable at all -- a
    # page whose real content isn't captured by ordinary extraction
    # (e.g. vector-drawn scan-like content pypdf's image enumeration
    # doesn't catch). If a reliable text or image signal already exists,
    # it is trusted and never escalated, and the render tier's result --
    # when it does run -- can only ever LOWER the confidence via min(),
    # never raise it. A coarse whole-page perceptual hash (an 8x8
    # downsampled dHash) is fundamentally unable to see a small but
    # meaningful difference like a single-character label change or a
    # short initials field, so it must never be allowed to override or
    # replace a cheaper signal that already caught one -- confirmed by a
    # real false-merge during development when the escalation guard
    # incorrectly treated "short text" as "unreliable text" and let the
    # render tier's blindness to small text differences silently
    # overwrite a correct text-based mismatch.
    if not has_reliable_text and image_similarity is None and NEEDS_REVIEW_THRESHOLD <= confidence < AUTO_REMOVE_THRESHOLD:
        try:
            hash_a = pdf_render.render_page_to_hash(pdf_path_a, pa.page_index)
            hash_b = pdf_render.render_page_to_hash(pdf_path_b, pb.page_index)
            render_confidence = pdf_render.compare_rendered_pages(hash_a, hash_b)
            confidence = min(confidence, render_confidence)
        except Exception:
            pass  # keep the cheaper-tier confidence if rendering fails

    return PageComparisonResult(confidence, False, None)


def compare_documents(
    fp_a: DocumentFingerprint,
    fp_b: DocumentFingerprint,
    pdf_path_a: Path,
    pdf_path_b: Path,
    allow_blank_stripping: bool,
) -> PairComparison:
    """The single comparison function underlying Levels 2, 3, and 4.

    Blank-page tolerance is deliberately NOT general edit-distance/LCS
    alignment: that would permit arbitrary insertion/deletion of ANY
    page, including non-blank ones, which would violate "never delete
    isolated matching pages from the middle of a document." The only
    safe operation is to strip conservatively-classified-blank pages
    from both sides, then require the remaining pages to match 1:1 in
    strict positional order with zero further insertion/deletion
    tolerance -- if lengths still differ after stripping, it's a
    definitive no-match, not a partial one.
    """

    pages_a = [p for p in fp_a.pages if not (allow_blank_stripping and p.blank.is_blank)]
    pages_b = [p for p in fp_b.pages if not (allow_blank_stripping and p.blank.is_blank)]
    if not pages_a or len(pages_a) != len(pages_b):
        return PairComparison(outcome="no_match")

    results = [compare_page(pa, pb, pdf_path_a, pdf_path_b) for pa, pb in zip(pages_a, pages_b)]
    vetoes = tuple(r.veto_reason for r in results if r.hard_veto and r.veto_reason)
    if vetoes:
        return PairComparison(outcome="different_version", veto_reasons=vetoes)

    weakest = min(r.confidence for r in results)
    blank_ignored = (len(fp_a.pages) - len(pages_a)) + (len(fp_b.pages) - len(pages_b))
    all_exact_hash = all(pa.text_hash == pb.text_hash for pa, pb in zip(pages_a, pages_b))

    if weakest >= AUTO_REMOVE_THRESHOLD:
        if blank_ignored > 0:
            method = "blank_page_tolerant"
        elif all_exact_hash:
            method = "normalized_pdf"
        else:
            method = "content_equivalent"
        return PairComparison(
            outcome="same", confidence=weakest, method=method, blank_pages_ignored_count=blank_ignored
        )
    if weakest >= NEEDS_REVIEW_THRESHOLD:
        return PairComparison(outcome="uncertain", confidence=weakest)
    return PairComparison(outcome="no_match", confidence=weakest)


def _best_comparison(fp_a: DocumentFingerprint, fp_b: DocumentFingerprint, path_a: Path, path_b: Path) -> PairComparison:
    strict = compare_documents(fp_a, fp_b, path_a, path_b, allow_blank_stripping=False)
    if strict.outcome == "same":
        return strict
    blank_tolerant = compare_documents(fp_a, fp_b, path_a, path_b, allow_blank_stripping=True)
    if _OUTCOME_RANK[blank_tolerant.outcome] > _OUTCOME_RANK[strict.outcome]:
        return blank_tolerant
    return strict


def _select_canonical(
    document_ids: list[str],
    fingerprints: dict[str, DocumentFingerprint],
    occurrences_by_id: dict[str, SourceOccurrence],
) -> str:
    """Canonical-copy selection WITHIN a confirmed-same-version group
    (never across versions -- documents that differ meaningfully never
    reach this function at all, since compare_documents would have
    returned "different_version" or "no_match" for them). Preference
    order: signature/annotation preservation, fewer accidental blank
    pages, more searchable text (a proxy for a native/digital original
    over a lower-quality scan when content is otherwise equivalent),
    then earliest traversal order as the final tiebreak.
    """

    def sort_key(doc_id: str):
        occ = occurrences_by_id[doc_id]
        fp = fingerprints[doc_id]
        blank_count = sum(1 for p in fp.pages if p.blank.is_blank)
        total_text_len = sum(len(p.normalized_text) for p in fp.pages)
        return (
            not fp.has_signature_field,  # has_signature_field=True sorts first (preferred)
            blank_count,
            -total_text_len,
            occ.traversal_index,
        )

    return min(document_ids, key=sort_key)


def _hash_only_grouping(
    doc_ids: list[str],
    fingerprints: dict[str, DocumentFingerprint],
    occurrences_by_id: dict[str, SourceOccurrence],
) -> list[ContentDuplicateGroup]:
    """O(k) fallback for oversized buckets: groups purely by exact
    normalized-document-hash equality (the Level-2 fast path only, no
    fuzzy/render-tier comparison). Conservative by construction -- a
    hash mismatch never groups anything, it just means that pair isn't
    considered here (it may still be caught by a differently-keyed,
    smaller bucket, or simply remain ungrouped, which is always safe).
    """

    by_hash: dict[str, list[str]] = {}
    for doc_id in doc_ids:
        by_hash.setdefault(fingerprints[doc_id].normalized_document_hash, []).append(doc_id)

    groups: list[ContentDuplicateGroup] = []
    for members in by_hash.values():
        if len(members) < 2:
            continue
        canonical = _select_canonical(members, fingerprints, occurrences_by_id)
        for member in members:
            if member == canonical:
                continue
            occ = occurrences_by_id[member]
            occ.is_content_duplicate = True
            occ.content_duplicate_of_document_id = canonical
            occ.duplicate_detection_method = "normalized_pdf"
            occ.duplicate_confidence = 1.0
        groups.append(
            ContentDuplicateGroup(
                method="normalized_pdf",
                document_ids=[canonical] + [m for m in members if m != canonical],
                retained_document_id=canonical,
                confidence=1.0,
                blank_pages_ignored_count=0,
            )
        )
    return groups


def _pairwise_grouping(
    doc_ids: list[str],
    fingerprints: dict[str, DocumentFingerprint],
    occurrences_by_id: dict[str, SourceOccurrence],
) -> list[ContentDuplicateGroup]:
    uf_same = _UnionFind()
    best_by_pair: dict[frozenset, PairComparison] = {}
    uncertain_pairs: list[tuple[str, str, float]] = []

    for i in range(len(doc_ids)):
        for j in range(i + 1, len(doc_ids)):
            id_a, id_b = doc_ids[i], doc_ids[j]
            occ_a, occ_b = occurrences_by_id[id_a], occurrences_by_id[id_b]
            comparison = _best_comparison(
                fingerprints[id_a], fingerprints[id_b], occ_a.converted_pdf_path, occ_b.converted_pdf_path
            )
            if comparison.outcome == "same":
                uf_same.union(id_a, id_b)
                best_by_pair[frozenset((id_a, id_b))] = comparison
            elif comparison.outcome == "uncertain":
                uncertain_pairs.append((id_a, id_b, comparison.confidence))

    groups: list[ContentDuplicateGroup] = []
    for members in uf_same.groups().values():
        if len(members) < 2:
            continue
        canonical = _select_canonical(members, fingerprints, occurrences_by_id)
        confidences: list[float] = []
        blank_ignored_total = 0
        methods: set[str] = set()

        for member in members:
            if member == canonical:
                continue
            comparison = best_by_pair.get(frozenset((member, canonical)))
            if comparison is None:
                # Transitively grouped (A~B, B~C) but never directly
                # compared against the chosen canonical -- fall back to
                # any confirmed edge touching this member. Comparison is
                # not guaranteed transitive in principle, though in
                # practice the same deterministic comparator applied to
                # the same content makes this a rare edge case; falling
                # back conservatively here (rather than assuming a
                # perfect score) is the safe choice.
                comparison = next((c for pair, c in best_by_pair.items() if member in pair), None)
            occ = occurrences_by_id[member]
            occ.is_content_duplicate = True
            occ.content_duplicate_of_document_id = canonical
            occ.duplicate_detection_method = comparison.method if comparison else "content_equivalent"
            occ.duplicate_confidence = comparison.confidence if comparison else AUTO_REMOVE_THRESHOLD
            occ.blank_pages_ignored_count = comparison.blank_pages_ignored_count if comparison else 0
            if comparison:
                confidences.append(comparison.confidence)
                blank_ignored_total += comparison.blank_pages_ignored_count
                if comparison.method:
                    methods.add(comparison.method)

        groups.append(
            ContentDuplicateGroup(
                method=sorted(methods)[0] if methods else "content_equivalent",
                document_ids=[canonical] + [m for m in members if m != canonical],
                retained_document_id=canonical,
                confidence=min(confidences) if confidences else AUTO_REMOVE_THRESHOLD,
                blank_pages_ignored_count=blank_ignored_total,
            )
        )

    for id_a, id_b, confidence in uncertain_pairs:
        for this_id, other_id in ((id_a, id_b), (id_b, id_a)):
            occ = occurrences_by_id[this_id]
            if not occ.needs_review:
                occ.needs_review = True
                occ.review_reason = (
                    f"uncertain content match against {other_id} (confidence {confidence:.2f}, "
                    f"below the {AUTO_REMOVE_THRESHOLD:.2f} safe auto-removal threshold)"
                )

    return groups


def detect_content_duplicates(
    occurrences: list[SourceOccurrence],
    fingerprints: dict[str, DocumentFingerprint],
    max_bucket_size: int = DEFAULT_MAX_BUCKET_SIZE,
) -> tuple[list[ContentDuplicateGroup], list[str]]:
    """Runs Levels 2/3/4 over every fingerprinted occurrence and mutates
    matching `SourceOccurrence`s in place (is_content_duplicate,
    content_duplicate_of_document_id, duplicate_detection_method,
    duplicate_confidence, blank_pages_ignored_count on confirmed
    duplicates; needs_review/review_reason on uncertain pairs -- never
    both on the same occurrence, and needs_review always means the
    occurrence is guaranteed retained in Final regardless of anything
    else, see SourceOccurrence.included_in_final).

    Returns (groups, oversized_bucket_notes) -- the notes list records
    any structural bucket that exceeded `max_bucket_size` and fell back
    to the cheaper exact-hash-only grouping, for the processing report.
    """

    occurrences_by_id = {o.document_id: o for o in occurrences}
    candidate_ids = [doc_id for doc_id in fingerprints if doc_id in occurrences_by_id]

    buckets: dict[tuple, list[str]] = {}
    for doc_id in candidate_ids:
        key = _bucket_key(fingerprints[doc_id])
        buckets.setdefault(key, []).append(doc_id)

    groups: list[ContentDuplicateGroup] = []
    oversized_notes: list[str] = []

    for doc_ids in buckets.values():
        if len(doc_ids) < 2:
            continue
        if len(doc_ids) > max_bucket_size:
            oversized_notes.append(
                f"A candidate bucket of {len(doc_ids)} documents exceeded the "
                f"{max_bucket_size}-document full-comparison limit; fell back to "
                f"exact-normalized-hash-only grouping for this bucket."
            )
            groups.extend(_hash_only_grouping(doc_ids, fingerprints, occurrences_by_id))
            continue
        groups.extend(_pairwise_grouping(doc_ids, fingerprints, occurrences_by_id))

    return groups, oversized_notes
