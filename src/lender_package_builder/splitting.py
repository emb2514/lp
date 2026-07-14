"""Whole-document output splitting plan.

Produces a list of "parts" (each a list of complete source documents,
in order) such that no part exceeds the configured page or size target
-- except a single document that alone exceeds a target, which is kept
intact in its own oversized part. No document is ever split, and
documents are never reordered to fill unused space.
"""

from __future__ import annotations

from .models import SourceOccurrence


def plan_parts(
    docs: list[SourceOccurrence], page_limit: int, size_limit_bytes: int
) -> list[list[SourceOccurrence]]:
    parts: list[list[SourceOccurrence]] = []
    current: list[SourceOccurrence] = []
    current_pages = 0
    current_size = 0

    for doc in docs:
        pages = doc.converted_page_count or 0
        size = doc.converted_size_bytes or 0

        if pages > page_limit or size > size_limit_bytes:
            if current:
                parts.append(current)
                current, current_pages, current_size = [], 0, 0
            parts.append([doc])
            continue

        if current and (current_pages + pages > page_limit or current_size + size > size_limit_bytes):
            parts.append(current)
            current, current_pages, current_size = [], 0, 0

        current.append(doc)
        current_pages += pages
        current_size += size

    if current:
        parts.append(current)

    return parts
