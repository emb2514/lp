"""Exact whole-source-file deduplication.

Two source occurrences are duplicates of each other only when their
original SHA-256 (computed on the untouched extracted bytes, before any
conversion) is identical. Nothing else -- not filename, not extracted
text, not converted-PDF hash -- ever participates in this decision.

This module never deletes or mutates a `SourceOccurrence`; it only
annotates `is_duplicate` / `duplicate_of_document_id` and returns the
list of duplicate groups for reporting.
"""

from __future__ import annotations

from .models import DuplicateGroup, SourceOccurrence


def find_duplicates(occurrences: list[SourceOccurrence]) -> list[DuplicateGroup]:
    """Group occurrences by original SHA-256 and mark later occurrences.

    `occurrences` must already be in traversal order. Ignored system
    artifacts and occurrences with no readable hash are excluded from
    duplicate consideration entirely (an unhashed file can never be
    proven identical to anything).
    """

    groups_by_hash: dict[str, DuplicateGroup] = {}
    ordered_hashes: list[str] = []

    for occurrence in occurrences:
        if occurrence.is_ignored_artifact or not occurrence.original_sha256:
            continue

        sha = occurrence.original_sha256
        group = groups_by_hash.get(sha)
        if group is None:
            group = DuplicateGroup(sha256=sha)
            groups_by_hash[sha] = group
            ordered_hashes.append(sha)
        group.document_ids.append(occurrence.document_id)

    by_id = {o.document_id: o for o in occurrences}
    duplicate_groups: list[DuplicateGroup] = []

    for sha in ordered_hashes:
        group = groups_by_hash[sha]
        if len(group.document_ids) < 2:
            continue
        duplicate_groups.append(group)
        retained_id = group.retained_document_id
        for dup_id in group.duplicate_document_ids:
            occ = by_id[dup_id]
            occ.is_duplicate = True
            occ.duplicate_of_document_id = retained_id

    return duplicate_groups
