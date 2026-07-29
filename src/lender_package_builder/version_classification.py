"""Level 5: document version classification.

Purely descriptive. Runs last, strictly after content_dedup.py and
overlap_detection.py have already made every keep/remove decision --
this module never sets `is_content_duplicate`, `is_contained_in_merged_document`,
`needs_review`, or any other exclusion-relevant field. It only clusters
related occurrences into `DocumentFamily` groups and labels each
member's likely version kind, purely to make `Document_Version_Report.txt`
readable (e.g. "Document family: Borrower Authorization -- kept one
unsigned, one e-signed, one wet-signed version"). Keeping every
safety-critical removal decision in exactly two modules
(content_dedup.py, overlap_detection.py) is much easier to reason about
and test than spreading removal logic across three.

Family "relatedness" deliberately uses a LOOSER structural key than
content_dedup.py's duplicate-candidate bucketing: a family is meant to
span exactly the differences duplicate detection's bucket key excludes
on purpose (signature-field presence, form-field presence) -- an
unsigned, an e-signed, and a wet-signed copy of the same underlying
document naturally differ in those exact structural dimensions, so
grouping them into one family requires NOT bucketing on those fields.
Relatedness is confirmed by first-non-blank-page text similarity (a
cheap proxy for "same underlying document"), plus explicit links from
any content-duplicate group or overlap finding already produced.
"""

from __future__ import annotations

import difflib

from .cancellation import CancellationToken, check_cancelled
from .models import ContentDuplicateGroup, DocumentFamily, OverlapFinding, SourceOccurrence
from .pdf_content import DocumentFingerprint

_FAMILY_RELATEDNESS_THRESHOLD = 0.5

# A page mostly covered by an embedded image with very little
# extractable text is treated as "scan-like" for classification
# purposes.
_SCAN_LIKE_MAX_TEXT_CHARS = 50


class _UnionFind:
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


def classify_version(fp: DocumentFingerprint, family_siblings: tuple[DocumentFingerprint, ...] = ()) -> str:
    """Best-effort label for a document's likely version kind, using
    structural signals already computed by pdf_content.py. Purely
    descriptive -- never used to make a keep/remove decision anywhere.

    `family_siblings` (other fingerprints already grouped into the same
    family) provides context for the otherwise-ambiguous case of a
    document with no signature field, no signed value, and no embedded
    images: in isolation that could be an ordinary unsigned digital
    original with no signature requirement at all ("original_digital"),
    but if a sibling in the same family DOES show signature evidence
    (a signed field, or a wet-signature-like embedded image), this
    member is almost certainly the "not yet signed" counterpart --
    labeled "unsigned" instead.
    """

    if fp.has_signature_field:
        if any(p.has_signed_signature for p in fp.pages):
            return "e_signed"
        return "unsigned"

    non_blank = [p for p in fp.pages if not p.blank.is_blank]
    has_images = any(p.images for p in non_blank)
    if has_images:
        scan_like_pages = sum(1 for p in non_blank if p.images and len(p.normalized_text) < _SCAN_LIKE_MAX_TEXT_CHARS)
        if non_blank and scan_like_pages / len(non_blank) > 0.5:
            return "scanned"
        return "wet_signed"

    if fp.has_form_fields:
        return "unsigned"

    sibling_shows_signature_evidence = any(
        sibling.has_signature_field or any(p.images for p in sibling.pages if not p.blank.is_blank)
        for sibling in family_siblings
    )
    if sibling_shows_signature_evidence:
        return "unsigned"

    return "original_digital"


def _first_page_text_similarity(fp_a: DocumentFingerprint, fp_b: DocumentFingerprint) -> float:
    pages_a = [p for p in fp_a.pages if not p.blank.is_blank]
    pages_b = [p for p in fp_b.pages if not p.blank.is_blank]
    if not pages_a or not pages_b:
        return 0.0
    return difflib.SequenceMatcher(None, pages_a[0].normalized_text, pages_b[0].normalized_text).ratio()


def _relatedness_key(fp: DocumentFingerprint) -> tuple:
    return (fp.non_blank_page_count, fp.page_dims_signature)


def build_document_families(
    occurrences: list[SourceOccurrence],
    fingerprints: dict[str, DocumentFingerprint],
    content_duplicate_groups: list[ContentDuplicateGroup],
    overlap_findings: list[OverlapFinding],
    cancellation_token: CancellationToken | None = None,
) -> list[DocumentFamily]:
    """Clusters related occurrences and labels each member's version.
    Mutates `document_family_id`/`version_classification` on matching
    occurrences (both purely descriptive fields); never touches any
    exclusion-relevant field.
    """

    occurrences_by_id = {o.document_id: o for o in occurrences}
    relevant_ids = [doc_id for doc_id in fingerprints if doc_id in occurrences_by_id]

    uf = _UnionFind()
    for doc_id in relevant_ids:
        uf.find(doc_id)

    buckets: dict[tuple, list[str]] = {}
    for doc_id in relevant_ids:
        buckets.setdefault(_relatedness_key(fingerprints[doc_id]), []).append(doc_id)
    for members in buckets.values():
        for i in range(len(members)):
            check_cancelled(cancellation_token)
            for j in range(i + 1, len(members)):
                similarity = _first_page_text_similarity(fingerprints[members[i]], fingerprints[members[j]])
                if similarity >= _FAMILY_RELATEDNESS_THRESHOLD:
                    uf.union(members[i], members[j])

    for group in content_duplicate_groups:
        present = [doc_id for doc_id in group.document_ids if doc_id in fingerprints]
        for doc_id in present[1:]:
            uf.union(present[0], doc_id)

    for finding in overlap_findings:
        if finding.standalone_document_id in fingerprints and finding.container_document_id in fingerprints:
            uf.union(finding.standalone_document_id, finding.container_document_id)

    families: list[DocumentFamily] = []
    for i, (_, members) in enumerate(sorted(uf.groups().items()), start=1):
        if len(members) < 2:
            continue
        family_id = f"FAMILY-{i:04d}"
        sorted_members = sorted(members, key=lambda doc_id: occurrences_by_id[doc_id].traversal_index)
        versions: dict[str, str] = {}
        for doc_id in sorted_members:
            siblings = tuple(fingerprints[other] for other in sorted_members if other != doc_id)
            classification = classify_version(fingerprints[doc_id], siblings)
            versions[doc_id] = classification
            occurrences_by_id[doc_id].document_family_id = family_id
            occurrences_by_id[doc_id].version_classification = classification
        families.append(DocumentFamily(family_id=family_id, document_ids=sorted_members, versions=versions))

    return families
