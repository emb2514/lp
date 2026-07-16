"""Applies a human's explicit review decision (made in the GUI's
"Review Uncertain Matches" dialog) to an already-completed run.

This is the ONLY place in the entire application where a
`needs_review=True` occurrence can ever be excluded from Final.
Automated code (content_dedup.py, overlap_detection.py) never does
this -- see `SourceOccurrence.included_in_final` and
`validation._check_needs_review_never_excluded`. Every decision applied
here is deliberate and fully auditable:

- "keep_both" (the safe default, and the only decision that can be
  re-applied without any real-world effect) changes nothing about any
  output file -- it only records that a human looked at the match and
  confirmed keeping both copies. Both documents were already present in
  Final; nothing about them changes.
- "excluded" requires the caller to name exactly which of the match's
  `excludable_ids` to exclude. Anything else (an unknown match, an
  already-decided match, a document not in `excludable_ids`) raises
  `ReviewDecisionError` rather than silently no-op'ing or guessing --
  a coding error here must never be able to misfire an exclusion.

Applying an "excluded" decision rebuilds ONLY the Final package (never
OG, and never any original source file -- `OG` is untouched because it
is built from `included_in_og`, which depends only on
`is_ignored_artifact`, never on anything decided here) and rewrites
every report, so the output on disk always reflects the complete,
current set of decisions.

Review decisions are typically applied well after the original build
finished, once its temporary conversion workspace has already been
cleaned up (see `workspace.Workspace.cleanup()`) -- so a document's own
`converted_pdf_path` may no longer exist on disk by the time a decision
is applied. Rather than requiring the temp workspace to be kept around
indefinitely, `_ensure_converted_pdfs_available()` transparently
re-extracts any missing document's exact page range from its own
permanent OG output part instead (OG's page-order and per-document page
count are already independently proven by validation.py's own integrity
checks, so this is exactly as trustworthy as the original converted
file).
"""

from __future__ import annotations

import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from . import __version__, merging, reporting, validation
from .config import AppConfig
from .models import RunResult, SourceOccurrence

VALID_DECISIONS = ("keep_both", "excluded")


class ReviewDecisionError(ValueError):
    """Raised for any invalid or inconsistent review-decision request."""


def apply_review_decision(
    run: RunResult,
    config: AppConfig,
    match_id: str,
    decision: str,
    excluded_document_id: str | None = None,
    reason: str | None = None,
    allow_large_input: bool = False,
) -> None:
    """Applies one decision to `run` in place. See module docstring for
    the exact semantics of each `decision` value.
    """

    if decision not in VALID_DECISIONS:
        raise ReviewDecisionError(f"Unknown decision {decision!r}; must be one of {VALID_DECISIONS}.")

    match = next((m for m in run.uncertain_matches if m.match_id == match_id), None)
    if match is None:
        raise ReviewDecisionError(f"No uncertain match found with id {match_id!r}.")
    if match.decision != "undecided":
        raise ReviewDecisionError(
            f"Match {match_id!r} was already decided ({match.decision!r}); a recorded decision is "
            "never overwritten."
        )

    decided_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if decision == "keep_both":
        match.decision = "keep_both"
        match.decided_at = decided_at
        match.decided_reason = reason or "Reviewed and confirmed: both copies kept."
        return  # nothing about any output file changes

    # decision == "excluded"
    if excluded_document_id not in match.excludable_ids:
        raise ReviewDecisionError(
            f"{excluded_document_id!r} is not a valid exclusion choice for match {match_id!r} "
            f"(allowed: {match.excludable_ids})."
        )
    occ_by_id = {o.document_id: o for o in run.occurrences}
    occ = occ_by_id.get(excluded_document_id)
    if occ is None:
        raise ReviewDecisionError(f"Document {excluded_document_id!r} not found in this run.")

    match.decision = "excluded"
    match.decided_document_id = excluded_document_id
    match.decided_at = decided_at
    match.decided_reason = reason or "Reviewed and confirmed: excluded as a duplicate/redundant copy."

    occ.manually_excluded = True
    occ.manually_excluded_match_id = match.match_id

    _rebuild_final_and_reports(run, config, allow_large_input)


def _rebuild_final_and_reports(run: RunResult, config: AppConfig, allow_large_input: bool) -> None:
    """Rebuilds ONLY the Final package from the current
    `included_in_final` state, reruns every integrity check against the
    updated run, and rewrites every report. OG and every original
    source file are never touched.
    """

    final_dir = run.output_path / "Final"
    reports_dir = run.output_path / "Reports"

    for existing in final_dir.glob("*.pdf"):
        existing.unlink()

    occ_by_id = {o.document_id: o for o in run.occurrences}
    for occ in run.occurrences:
        occ.final_part_index = None

    non_ignored = [o for o in run.occurrences if not o.is_ignored_artifact]
    with tempfile.TemporaryDirectory(prefix="lpb_review_rebuild_") as tmp_dir:
        _ensure_converted_pdfs_available(run, non_ignored, Path(tmp_dir))

        final_docs = [o for o in run.occurrences if o.included_in_final]
        final_parts = merging.write_package(
            final_docs,
            final_dir,
            "Full_Lender_Package_Final_Part",
            "Final",
            config.max_pages_per_part,
            config.max_size_bytes_per_part,
        )
        for part in final_parts:
            for doc_id in part.document_ids:
                occ_by_id[doc_id].final_part_index = part.index
        run.final_parts = final_parts

        run.integrity_checks = validation.run_integrity_checks(
            run, config.max_pages_per_part, config.max_size_bytes_per_part
        )

    meta = {
        "app_version": __version__,
        "os_info": platform.platform(),
        "python_version": platform.python_version(),
        "max_pages_per_part": config.max_pages_per_part,
        "max_size_mb_per_part": config.max_size_mb_per_part,
        "allow_large_input": allow_large_input,
    }
    reporting.write_all_reports(run, config, meta, reports_dir)


def _ensure_converted_pdfs_available(
    run: RunResult, occurrences: list[SourceOccurrence], tmp_dir: Path
) -> None:
    """For any occurrence whose `converted_pdf_path` no longer exists on
    disk (its temporary conversion workspace was already cleaned up),
    re-extracts exactly that document's own pages from its permanent OG
    output part and points `converted_pdf_path` at the extracted copy.
    Both `merging.write_package()` (needs every Final-bound document's
    own standalone PDF) and `validation.run_integrity_checks()` (re-opens
    EVERY non-ignored document's `converted_pdf_path` to independently
    verify its page count) require this for every non-ignored occurrence,
    not just the ones affected by the current decision.
    """

    og_parts_by_index = {p.index: p for p in run.og_parts}
    occ_by_id = {o.document_id: o for o in run.occurrences}

    for occ in occurrences:
        if occ.converted_pdf_path is not None and occ.converted_pdf_path.exists():
            continue

        og_part = og_parts_by_index.get(occ.og_part_index)
        if og_part is None or occ.document_id not in og_part.document_ids:
            raise ReviewDecisionError(
                f"Cannot rebuild Final: {occ.document_id}'s converted PDF no longer exists and its "
                "OG part could not be located to re-extract it."
            )

        start_page = 0
        for doc_id in og_part.document_ids:
            if doc_id == occ.document_id:
                break
            sibling = occ_by_id.get(doc_id)
            start_page += (sibling.converted_page_count or 0) if sibling else 0
        page_count = occ.converted_page_count or 0

        reader = PdfReader(str(og_part.file_path))
        writer = PdfWriter()
        for page_index in range(start_page, start_page + page_count):
            writer.add_page(reader.pages[page_index])
        extracted_path = tmp_dir / f"{occ.document_id}_extracted_from_og.pdf"
        with extracted_path.open("wb") as fh:
            writer.write(fh)
        occ.converted_pdf_path = extracted_path
