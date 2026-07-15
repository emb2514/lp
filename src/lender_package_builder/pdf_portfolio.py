"""PDF Portfolio and embedded-file detection/extraction.

Called once, at the end of `InventoryBuilder.build()`, mirroring how
nested ZIPs are already expanded during the same traversal: a PDF
Portfolio is just another container format discovered inline, and its
embedded attachments become real, independent `SourceOccurrence`s that
flow through the exact same hashing/conversion/dedup/merge pipeline as
every other discovered file -- never an ephemeral, special-cased object
the way email attachments are today (see conversion/email.py).

Two distinct signals matter here, and conflating them was flagged as a
real risk during design review:

- `/Root/Names/EmbeddedFiles` non-empty means this PDF carries one or
  more embedded/attached files. This is extracted whenever present,
  regardless of whether it's a true Portfolio -- an ordinary PDF that
  merely has a paperclip attachment alongside real content pages must
  still have that attachment discovered (never silently omitted), but
  its own pages must NOT be excluded from Final.
- `/Root/Collection` present means this PDF is a true Portfolio (the
  "browse these files" UI Adobe Acrobat renders instead of a normal
  page view). Only in this case is the PDF's own page content (the
  generic "open this in Acrobat" cover page) excluded from Final via
  `SourceOccurrence.is_portfolio_container` -- it still appears in OG
  untouched, like any other original file.

Attachment order: `PdfReader.attachments` iterates the `/Names` name
tree in the order pypdf walks it, which is used here as the primary,
verified ordering signal ("name_tree_order"). True Portfolio UI ordering
in Adobe Acrobat can additionally be influenced by per-item `/CI`
(Collection Item) metadata with no stable, documented high-level pypdf
API -- attempting to hand-parse that speculatively was judged riskier
than using the verified name-tree order with an honestly-recorded
fallback. This is a known limitation to verify against any real
Adobe-generated Portfolio in manual acceptance testing (synthetic test
fixtures built via pypdf's own writer cannot by themselves prove
Acrobat's own ordering conventions are handled).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .models import ProcessingStatus, SourceOccurrence
from .workspace import Workspace

logger = logging.getLogger(__name__)


def expand_portfolios(occurrences: list[SourceOccurrence], workspace: Workspace) -> list[SourceOccurrence]:
    """Returns a new list with every embedded-file attachment spliced in
    immediately after its parent PDF occurrence, and `traversal_index`
    renumbered 1..N over the final list. `document_id` is left untouched
    on every existing occurrence and assigned a stable `-PF-NNN` suffix
    on new attachment occurrences -- see the module docstring on why
    `document_id` intentionally no longer implies `traversal_index`
    numerically after this runs.
    """

    expanded: list[SourceOccurrence] = []
    for occurrence in occurrences:
        expanded.append(occurrence)
        children = _expand_one(occurrence, workspace)
        expanded.extend(children)

    for index, occurrence in enumerate(expanded, start=1):
        occurrence.traversal_index = index

    return expanded


def _expand_one(occurrence: SourceOccurrence, workspace: Workspace) -> list[SourceOccurrence]:
    if occurrence.is_ignored_artifact or not occurrence.extracted_path:
        return []
    if (occurrence.original_extension or "").lower() != ".pdf":
        return []

    try:
        reader = PdfReader(str(occurrence.extracted_path))
    except (PdfReadError, OSError, ValueError):
        return []

    try:
        root = reader.trailer["/Root"]
    except Exception:
        return []

    try:
        is_collection = "/Collection" in root
    except Exception:
        is_collection = False
    if is_collection:
        occurrence.is_portfolio_container = True

    attachment_names: list[tuple[str, bytes]] = []
    try:
        for name, values in reader.attachments.items():
            for data in values:
                attachment_names.append((name, data))
    except Exception as exc:
        logger.warning(
            "Could not enumerate embedded files in %s: %s", occurrence.original_relative_path, exc
        )
        return []

    if not attachment_names:
        return []

    children: list[SourceOccurrence] = []
    for i, (name, data) in enumerate(attachment_names, start=1):
        child = _build_child_occurrence(occurrence, i, name, data, workspace)
        children.append(child)

    return children


def _build_child_occurrence(
    parent: SourceOccurrence, index: int, name: str, data: bytes, workspace: Workspace
) -> SourceOccurrence:
    document_id = f"{parent.document_id}-PF-{index:03d}"
    safe_name = Path(name).name or f"attachment_{index}"
    extension = Path(safe_name).suffix.lower()
    relative_path = f"{parent.original_relative_path} :: [Portfolio] {safe_name}"
    chain_display = f"{parent.archive_chain_display} -> [Portfolio attachment: {safe_name}]"

    try:
        dest_path = workspace.new_extract_path(safe_name)
        dest_path.write_bytes(data)
        sha256 = hashlib.sha256(data).hexdigest()
        status = ProcessingStatus.DISCOVERED
        failure_reason = None
    except OSError as exc:
        # Never silently omit an embedded file -- if its bytes cannot be
        # written to the workspace, it is still recorded (with no
        # extracted_path), exactly like inventory.py's own
        # _record_unextractable path for an unextractable ZIP entry.
        dest_path = None
        sha256 = None
        status = ProcessingStatus.DISCOVERED
        failure_reason = f"Could not extract this Portfolio attachment: {exc}"

    return SourceOccurrence(
        document_id=document_id,
        traversal_index=0,  # renumbered by expand_portfolios() once the full list is spliced
        original_filename=safe_name,
        original_relative_path=relative_path,
        original_extension=extension,
        original_size_bytes=len(data),
        extracted_path=dest_path,
        archive_chain_display=chain_display,
        original_sha256=sha256,
        status=status,
        conversion_failure_reason=failure_reason,
        portfolio_parent_document_id=parent.document_id,
    )
