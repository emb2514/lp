"""Whole-document PDF merging into OG/Final output parts.

Builds each output part from complete converted documents in order,
then enforces the actual on-disk size target: if a multi-document part
exceeds the target, the last whole document is moved to the next part
and the part is rebuilt, repeated conservatively until the part fits or
holds exactly one (necessarily oversized) document. No document is ever
split to meet a size or page target.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .models import OutputPart, SourceOccurrence
from .splitting import plan_parts

logger = logging.getLogger(__name__)


def _build_merged_pdf(docs: list[SourceOccurrence], dest_path: Path) -> None:
    writer = PdfWriter()
    for doc in docs:
        reader = PdfReader(str(doc.converted_pdf_path))
        for page in reader.pages:
            writer.add_page(page)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with dest_path.open("wb") as fh:
        writer.write(fh)


def write_package(
    docs: list[SourceOccurrence],
    output_dir: Path,
    file_prefix: str,
    package_label: str,
    page_limit: int,
    size_limit_bytes: int,
) -> list[OutputPart]:
    """Write `docs` (in order) as one or more PDF parts under `output_dir`.

    `file_prefix` is the filename stem before `_NNN.pdf`, e.g.
    "Full_Lender_Package_OG_Files_Part".
    """

    if not docs:
        return []

    parts = plan_parts(docs, page_limit, size_limit_bytes)

    i = 0
    while i < len(parts):
        while True:
            dest = output_dir / f"{file_prefix}_{i + 1:03d}.pdf"
            _build_merged_pdf(parts[i], dest)
            actual_size = dest.stat().st_size
            if actual_size <= size_limit_bytes or len(parts[i]) <= 1:
                break
            logger.info(
                "%s part %d exceeded the %d-byte size target after merging (%d bytes); "
                "moving the last document to the next part and rebuilding.",
                package_label,
                i + 1,
                size_limit_bytes,
                actual_size,
            )
            moved = parts[i].pop()
            if i + 1 < len(parts):
                parts[i + 1].insert(0, moved)
            else:
                parts.append([moved])
        i += 1

    output_parts: list[OutputPart] = []
    for idx, part_docs in enumerate(parts, start=1):
        dest = output_dir / f"{file_prefix}_{idx:03d}.pdf"
        size_bytes = dest.stat().st_size
        page_count = sum(doc.converted_page_count or 0 for doc in part_docs)
        is_oversized = len(part_docs) == 1 and (
            (part_docs[0].converted_page_count or 0) > page_limit or size_bytes > size_limit_bytes
        )
        output_parts.append(
            OutputPart(
                package=package_label,
                index=idx,
                file_path=dest,
                document_ids=[doc.document_id for doc in part_docs],
                page_count=page_count,
                file_size_bytes=size_bytes,
                is_oversized=is_oversized,
            )
        )

    return output_parts
