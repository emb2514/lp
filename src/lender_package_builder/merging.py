"""Whole-document PDF merging into OG/Final output parts.

Builds each output part from complete converted documents in order,
then verifies the actual on-disk page count and size: if a
multi-document part exceeds the configured MAXIMUM size after merging,
the last whole document is removed from that part, moved to the next
part, and the part is rebuilt and rechecked -- repeated conservatively
until the part fits or holds exactly one (necessarily oversized)
document. No document is ever split to meet a page or size maximum.

`max_pages_per_part` and `max_size_bytes_per_part` are ceilings, not
targets: parts are expected to vary in size and are never padded or
rearranged to approach either maximum. See `splitting.py`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from . import naming
from .atomic_replace import replace_with_retry
from .cancellation import CancellationToken, check_cancelled
from .models import OutputPart, PackageIdentity, SourceOccurrence
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
    identity: PackageIdentity,
    package_kind: str,
    package_label: str,
    max_pages_per_part: int,
    max_size_bytes_per_part: int,
    cancellation_token: CancellationToken | None = None,
) -> list[OutputPart]:
    """Write `docs` (in order) as one or more PDF parts under `output_dir`.

    `package_kind` is `naming.FINAL_PACKAGE_KIND` ("Lender Package") or
    `naming.OG_PACKAGE_KIND` ("Original Lender Package") -- the actual
    filenames (e.g. "True, Michael, Lender Package, Part 001.pdf") are
    derived from `identity` and `package_kind` via `naming.py`.
    `package_label` ("OG"/"Final") is used only for `OutputPart.package`
    and log messages, not for any filename.
    """

    if not docs:
        return []

    parts = plan_parts(docs, max_pages_per_part, max_size_bytes_per_part)

    # Part filenames depend on the FINAL total part count (single-part
    # packages omit "Part NNN" entirely), which is not known until the
    # size-check rebuild loop below settles -- so parts are written under
    # temporary names first, then renamed to their real filenames once
    # the part count is final.
    temp_stem = f".tmp_{package_label.lower()}_part"

    i = 0
    while i < len(parts):
        check_cancelled(cancellation_token)
        while True:
            temp_dest = output_dir / f"{temp_stem}_{i + 1:03d}.pdf"
            _build_merged_pdf(parts[i], temp_dest)
            actual_size = temp_dest.stat().st_size
            if actual_size <= max_size_bytes_per_part or len(parts[i]) <= 1:
                break
            logger.info(
                "%s part %d exceeded the %d-byte maximum after merging (%d bytes); "
                "moving the last document to the next part and rebuilding.",
                package_label,
                i + 1,
                max_size_bytes_per_part,
                actual_size,
            )
            moved = parts[i].pop()
            if i + 1 < len(parts):
                parts[i + 1].insert(0, moved)
            else:
                parts.append([moved])
        i += 1

    total_parts = len(parts)
    output_parts: list[OutputPart] = []
    for idx, part_docs in enumerate(parts, start=1):
        check_cancelled(cancellation_token)
        temp_dest = output_dir / f"{temp_stem}_{idx:03d}.pdf"
        dest = output_dir / naming.package_part_filename(identity, package_kind, idx, total_parts)
        # Not a plain .replace() -- see atomic_replace.py's docstring for
        # the real Windows crash (antivirus/cloud-sync/indexing briefly
        # locking a freshly-written PDF) this retry exists to survive.
        replace_with_retry(temp_dest, dest)
        size_bytes = dest.stat().st_size
        # Re-read the actual merged file rather than trusting the sum of
        # recorded per-document page counts, so this number is an
        # independent, verifiable fact about the file on disk (see
        # validation.py's page-count integrity checks).
        actual_page_count = len(PdfReader(str(dest)).pages)
        is_oversized = len(part_docs) == 1 and (
            (part_docs[0].converted_page_count or 0) > max_pages_per_part
            or size_bytes > max_size_bytes_per_part
        )
        output_parts.append(
            OutputPart(
                package=package_label,
                index=idx,
                file_path=dest,
                document_ids=[doc.document_id for doc in part_docs],
                page_count=actual_page_count,
                file_size_bytes=size_bytes,
                is_oversized=is_oversized,
            )
        )

    _assign_close_reasons(output_parts, docs, max_pages_per_part, max_size_bytes_per_part)
    return output_parts


def _assign_close_reasons(
    output_parts: list[OutputPart],
    all_docs: list[SourceOccurrence],
    max_pages_per_part: int,
    max_size_bytes_per_part: int,
) -> None:
    """Best-effort, human-readable explanation of why each part ended.

    Derived from the FINAL, settled part composition (after any
    actual-size rebuild), so it reflects what really happened. This is
    for Processing_Report.txt only; correctness does not depend on it.
    """

    by_id = {d.document_id: d for d in all_docs}

    for i, part in enumerate(output_parts):
        reasons: list[str] = []

        if part.is_oversized:
            reasons.append("oversized_document")

        if i == len(output_parts) - 1:
            reasons.append("end_of_package")
        else:
            next_part = output_parts[i + 1]
            if next_part.document_ids:
                next_doc = by_id[next_part.document_ids[0]]
                next_pages = next_doc.converted_page_count or 0
                next_size = next_doc.converted_size_bytes or 0
                if part.page_count + next_pages > max_pages_per_part:
                    reasons.append("page_maximum")
                if part.file_size_bytes + next_size > max_size_bytes_per_part:
                    reasons.append("size_maximum")

        if not reasons:
            reasons.append("end_of_package")

        part.close_reasons = reasons
