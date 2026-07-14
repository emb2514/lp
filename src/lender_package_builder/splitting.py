"""Whole-document output splitting plan.

`max_pages_per_part` and `max_size_bytes_per_part` are MAXIMUM
CONSTRAINTS on an output part, not target sizes to aim for. Complete
source documents are added to the current part, in original order,
until the next complete document would exceed either maximum; the part
is then closed (however far below the maximum it happens to be) and a
new part is started with that document. Parts are never padded,
rearranged, or split to approach either maximum -- see the module
docstring in `merging.py` and README.md ("Choosing the output-part
size defaults") for the full reasoning.

The only exception is a single document that alone exceeds a maximum:
it is kept intact in its own oversized part rather than being split.
"""

from __future__ import annotations

from .models import SourceOccurrence


def plan_parts(
    docs: list[SourceOccurrence], max_pages_per_part: int, max_size_bytes_per_part: int
) -> list[list[SourceOccurrence]]:
    parts: list[list[SourceOccurrence]] = []
    current: list[SourceOccurrence] = []
    current_pages = 0
    current_size = 0

    for doc in docs:
        pages = doc.converted_page_count or 0
        size = doc.converted_size_bytes or 0

        if pages > max_pages_per_part or size > max_size_bytes_per_part:
            if current:
                parts.append(current)
                current, current_pages, current_size = [], 0, 0
            parts.append([doc])
            continue

        if current and (
            current_pages + pages > max_pages_per_part
            or current_size + size > max_size_bytes_per_part
        ):
            parts.append(current)
            current, current_pages, current_size = [], 0, 0

        current.append(doc)
        current_pages += pages
        current_size += size

    if current:
        parts.append(current)

    return parts
