"""Plain-text and JSON report generation.

Six files are produced per run: `Processing_Report.txt` (the main
human-readable summary), `Duplicate_Removal_Log.txt` (full detail on
every duplicate excluded from Final, exact-byte AND content-aware),
`Document_Version_Report.txt` (RC2: per-family version breakdown),
`Merged_Document_Overlap_Report.txt` (RC2: merged-package containment
findings), `Uncertain_Match_Review_Log.txt` (RC2: the full audit trail
of every uncertain comparison surfaced for human review and its
decision, if any -- see `review_decisions.py`), and
`Processing_Manifest.json` (a complete machine-readable record).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .models import ProcessingStatus, RunResult, SourceOccurrence

_METHOD_SECTION_TITLES = {
    "normalized_pdf": "NORMALIZED PDF DUPLICATES",
    "content_equivalent": "CONTENT-EQUIVALENT DUPLICATES",
    "blank_page_tolerant": "BLANK-PAGE-TOLERANT DUPLICATES",
}

_METHOD_DESCRIPTIONS = {
    "normalized_pdf": (
        "Same visible/interactive content despite differences in filename, PDF metadata, "
        "creation software, compression, object ordering, or other non-visible technical "
        "PDF structure -- every page matched by exact normalized content."
    ),
    "content_equivalent": (
        "Same complete document content confirmed via multi-signal comparison (text, form "
        "fields, annotations, signature state, and/or rendered visual appearance for pages "
        "without reliable extractable text), within the app's high-confidence threshold."
    ),
    "blank_page_tolerant": (
        "Same complete document content once verified-blank pages (no meaningful text, "
        "images, form fields, annotations, or marks) are ignored on either side; the "
        "remaining non-blank pages matched in strict order."
    ),
}


def write_all_reports(run: RunResult, config, meta: dict, reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    write_duplicate_removal_log(run, reports_dir / "Duplicate_Removal_Log.txt")
    write_document_version_report(run, reports_dir / "Document_Version_Report.txt")
    write_merged_overlap_report(run, reports_dir / "Merged_Document_Overlap_Report.txt")
    write_uncertain_match_review_log(run, reports_dir / "Uncertain_Match_Review_Log.txt")
    write_key_document_report(run, reports_dir / "Key Document Page Locations.txt")
    write_processing_report(run, config, meta, reports_dir / "Processing_Report.txt")
    write_processing_manifest(run, meta, reports_dir / "Processing_Manifest.json")


_CATEGORY_LABELS = {
    "closing_disclosure": "Closing Disclosure",
    "loan_estimate": "Loan Estimate",
    "alta_settlement_statement": "ALTA Settlement Statement",
    "government_id": "Government ID",
    "mu_privacy_policy": "MU Privacy Policy",
    "mu_ma_broker_addendum": "MU MA Broker Addendum",
    "non_proceeding": "Loan Non-Proceeding Documentation",
}


def wet_signed_matches(run: RunResult) -> list:
    """Every key-document match with reliable wet-signature evidence
    (`signature_status == "Signed"`) -- used by both the report below
    and the GUI/manifest so all three always agree.
    """

    return [m for m in run.key_document_matches if m.signature_status == "Signed"]


def write_key_document_report(run: RunResult, path: Path) -> None:
    """Human-readable key-document page-locator results (MILESTONE 4):
    Closing Disclosures, Government IDs, the Mortgage Unity Privacy
    Policy, and loan non-proceeding documentation found in Final, plus
    a dedicated wet-signed-document status section. Recognition here is
    purely descriptive -- nothing in this report ever affected which
    documents are in Final.
    """

    occ_by_id = {o.document_id: o for o in run.occurrences}
    lines: list[str] = []
    lines.append("KEY DOCUMENT PAGE LOCATIONS")
    lines.append("=" * 70)
    lines.append(
        "Automatic recognition of specific document types within the Final package. "
        "Recognition never excludes, reorders, or otherwise changes anything in Final -- "
        "a \"Possible Match\" stays in the package exactly like every other document."
    )
    lines.append(f"Total key-document matches: {len(run.key_document_matches)}")
    lines.append("")

    wet_signed = wet_signed_matches(run)
    lines.append("-" * 70)
    lines.append("WET-SIGNED DOCUMENT STATUS")
    lines.append("-" * 70)
    if wet_signed:
        lines.append(f"Wet-Signed Documents Found: {len(wet_signed)}")
        for match in wet_signed:
            occ = occ_by_id.get(match.document_id)
            lines.append(
                f"    - {_CATEGORY_LABELS.get(match.category, match.category)}: "
                f"{occ.original_filename if occ else match.document_id}"
            )
            if match.extracted_filename:
                lines.append(f"        Extracted file: {match.extracted_filename}")
            if match.final_part_index is not None and match.final_part_page_range is not None:
                lines.append(
                    f"        Final part {match.final_part_index}, pages "
                    f"{match.final_part_page_range[0]}-{match.final_part_page_range[1]}"
                )
    else:
        lines.append("No wet-signed documents were found in the Final lender package.")

    wet_signed_cds = [m for m in wet_signed if m.category == "closing_disclosure"]
    if not wet_signed_cds:
        lines.append("Wet-Signed Closing Disclosure: Not found")
    lines.append("")

    if not run.key_document_matches:
        lines.append("No key documents were identified in this Final package.")
        path.write_text("\n".join(lines), encoding="utf-8")
        return

    for match in run.key_document_matches:
        occ = occ_by_id.get(match.document_id)
        lines.append("=" * 70)
        label = _CATEGORY_LABELS.get(match.category, match.category)
        if match.subtype:
            label = f"{label} ({match.subtype})"
        lines.append(f"{match.match_id}: {label} -- {match.confidence_band}")
        lines.append("=" * 70)
        lines.append(f"    Original file: {occ.original_filename if occ else match.document_id} ({match.document_id})")
        lines.append(f"    Page range in source document: {match.document_page_range[0]}-{match.document_page_range[1]}")
        if match.final_part_index is not None and match.final_part_page_range is not None:
            lines.append(
                f"    Final package part {match.final_part_index}, pages "
                f"{match.final_part_page_range[0]}-{match.final_part_page_range[1]}"
            )
        if match.overall_final_page_range is not None:
            lines.append(
                f"    Overall Final package pages: {match.overall_final_page_range[0]}-"
                f"{match.overall_final_page_range[1]}"
            )
        if match.signature_status:
            lines.append(f"    Signature/version status: {match.signature_status}")
        if match.borrower_name:
            lines.append(f"    Borrower: {match.borrower_name}")
        if match.extracted_filename:
            lines.append(f"    Extracted standalone file: {match.extracted_filename}")
        else:
            lines.append("    Extracted standalone file: (none -- Possible Match requires human review first)")
        lines.append(f"    Reason: {match.reason}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_duplicate_removal_log(run: RunResult, path: Path) -> None:
    occ_by_id = {o.document_id: o for o in run.occurrences}
    duplicates = [o for o in run.occurrences if o.is_duplicate]
    # A group's non-canonical members are only actually removed from
    # Final if needs_review is False -- a member that ALSO has an
    # unrelated uncertain pairwise result (needs_review=True, set
    # independently by a different comparison within the same
    # structural bucket) stays in Final regardless of this "same" group
    # membership (see SourceOccurrence.included_in_final). Counting/
    # listing every group member here unconditionally would misreport a
    # document as removed when it was actually retained.
    content_dup_removed = [
        doc_id
        for g in run.content_duplicate_groups
        for doc_id in g.document_ids
        if doc_id != g.retained_document_id
        and doc_id in occ_by_id
        and not occ_by_id[doc_id].needs_review
    ]
    total_removed = len(duplicates) + len(content_dup_removed)

    lines: list[str] = []
    lines.append("DUPLICATE REMOVAL LOG")
    lines.append("=" * 70)
    lines.append(
        "Lists every source occurrence excluded from the Final package because it was "
        "identified as a duplicate of an earlier occurrence, by detection method. Every "
        "occurrence remains fully present in OG regardless of anything below."
    )
    lines.append(f"Total duplicate occurrences removed from Final: {total_removed}")
    lines.append("")

    lines.append("=" * 70)
    lines.append("EXACT BYTE DUPLICATES")
    lines.append("=" * 70)
    lines.append(
        "Byte-for-byte exact duplicates (identical SHA-256 of the original, untouched "
        "source file) -- the fastest and safest detection method, always run first."
    )
    lines.append(f"Count: {len(duplicates)}")
    lines.append("")
    if not duplicates:
        lines.append("None found.")
        lines.append("")
    else:
        for i, occ in enumerate(duplicates, start=1):
            retained = occ_by_id.get(occ.duplicate_of_document_id or "")
            lines.append(f"[{i}] Duplicate occurrence")
            lines.append(f"    Removed filename:  {occ.original_filename}")
            lines.append(f"    Removed path:      {occ.original_relative_path}")
            lines.append(f"    Removed document ID: {occ.document_id}")
            if retained:
                lines.append(f"    Retained filename: {retained.original_filename}")
                lines.append(f"    Retained path:     {retained.original_relative_path}")
                lines.append(f"    Retained document ID: {retained.document_id}")
            lines.append("    Detection method:  exact_sha256")
            lines.append("    Confidence:        1.00 (byte-identical)")
            lines.append(f"    Shared SHA-256:    {occ.original_sha256}")
            lines.append(f"    Page count:        {occ.converted_page_count}")
            lines.append(
                f"    Reason:            Original file bytes are identical (same SHA-256) to the "
                "retained occurrence."
            )
            lines.append("")

    for method in ("normalized_pdf", "content_equivalent", "blank_page_tolerant"):
        groups = [g for g in run.content_duplicate_groups if g.method == method]
        lines.append("=" * 70)
        lines.append(_METHOD_SECTION_TITLES[method])
        lines.append("=" * 70)
        lines.append(_METHOD_DESCRIPTIONS[method])
        removed_count = sum(
            1
            for g in groups
            for doc_id in g.document_ids
            if doc_id != g.retained_document_id
            and doc_id in occ_by_id
            and not occ_by_id[doc_id].needs_review
        )
        lines.append(f"Count: {removed_count}")
        lines.append("")
        if removed_count == 0:
            lines.append("None found.")
            lines.append("")
            continue
        i = 0
        for group in groups:
            retained = occ_by_id.get(group.retained_document_id)
            for doc_id in group.document_ids:
                if doc_id == group.retained_document_id:
                    continue
                occ = occ_by_id.get(doc_id)
                if occ is None:
                    continue
                if occ.needs_review:
                    continue  # protected -- actually still retained in Final, not removed
                i += 1
                lines.append(f"[{i}] Duplicate occurrence")
                lines.append(f"    Removed filename:  {occ.original_filename}")
                lines.append(f"    Removed path:      {occ.original_relative_path}")
                lines.append(f"    Removed document ID: {occ.document_id}")
                if retained:
                    lines.append(f"    Retained filename: {retained.original_filename}")
                    lines.append(f"    Retained path:     {retained.original_relative_path}")
                    lines.append(f"    Retained document ID: {retained.document_id}")
                lines.append(f"    Detection method:  {occ.duplicate_detection_method or method}")
                confidence = occ.duplicate_confidence if occ.duplicate_confidence is not None else group.confidence
                lines.append(f"    Confidence:        {confidence:.2f}")
                lines.append(f"    Page count:        {occ.converted_page_count}")
                if occ.blank_pages_ignored_count:
                    lines.append(f"    Blank pages ignored: {occ.blank_pages_ignored_count}")
                lines.append(f"    Reason:            {_METHOD_DESCRIPTIONS[method]}")
                lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def write_document_version_report(run: RunResult, path: Path) -> None:
    occ_by_id = {o.document_id: o for o in run.occurrences}
    match_by_id = {m.match_id: m for m in run.uncertain_matches}

    lines: list[str] = []
    lines.append("DOCUMENT VERSION REPORT")
    lines.append("=" * 70)
    lines.append(
        "Groups related occurrences into document families and shows which distinct "
        "version(s) of each were kept, and why repeated copies within the same version were "
        "excluded. Grouping into a family never removes anything by itself -- it is purely "
        "descriptive; the actual keep/remove decision was already made by content-aware "
        "duplicate detection and merged-package overlap analysis (see the other reports)."
    )
    lines.append(f"Document families identified: {len(run.document_families)}")
    lines.append("")

    if not run.document_families:
        lines.append("No related document families were identified in this run.")
        path.write_text("\n".join(lines), encoding="utf-8")
        return

    for i, family in enumerate(run.document_families, start=1):
        lines.append("=" * 70)
        lines.append(f"FAMILY {i}: {family.family_id}")
        lines.append("=" * 70)
        members = [occ_by_id[d] for d in family.document_ids if d in occ_by_id]
        by_version: dict[str, list[SourceOccurrence]] = {}
        for occ in members:
            version = family.versions.get(occ.document_id) or "unclassified"
            by_version.setdefault(version, []).append(occ)

        lines.append(f"Versions found: {', '.join(sorted(by_version))}")
        lines.append("")
        for version, occs in sorted(by_version.items()):
            lines.append(f"  Version: {version}")
            for occ in occs:
                status = "RETAINED in Final" if occ.included_in_final else "EXCLUDED from Final"
                lines.append(f"    - [{status}] {occ.original_filename} ({occ.document_id})")
                if not occ.included_in_final:
                    reason = _final_exclusion_reason(occ, occ_by_id, match_by_id)
                    lines.append(f"        Reason: {reason}")
                if occ.needs_review:
                    lines.append(f"        Uncertain: {occ.review_reason}")
            lines.append("")

        lines.append(
            "  Repeated copies within the same version above were excluded because their "
            "content was confirmed identical to another occurrence of the same version (see "
            "Duplicate_Removal_Log.txt for the exact method/confidence). Documents kept as "
            "separate versions differ meaningfully -- e.g. signature state, dates, form "
            "values, or other content -- and are never merged."
        )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _final_exclusion_reason(
    occ: SourceOccurrence, occ_by_id: dict[str, SourceOccurrence], match_by_id: dict[str, object] | None = None
) -> str:
    # Checked first: a manual review decision is the actual causal reason
    # for this exclusion whenever present -- content_duplicate/
    # contained_in_merged_document alone would NOT have excluded this
    # occurrence (both are guarded by needs_review), so reporting either
    # of those instead would misattribute the real reason.
    if occ.manually_excluded:
        match = (match_by_id or {}).get(occ.manually_excluded_match_id or "")
        if match is not None:
            other_id = match.document_id_b if match.document_id_a == occ.document_id else match.document_id_a
            other = occ_by_id.get(other_id)
            other_name = other.original_filename if other else other_id
            return (
                f"manually excluded during human review (match {match.match_id}, vs. {other_name}): "
                f"{match.decided_reason or 'no reason recorded'} (decided {match.decided_at or 'unknown time'})"
            )
        return f"manually excluded during human review (match {occ.manually_excluded_match_id})"
    if occ.is_duplicate:
        retained = occ_by_id.get(occ.duplicate_of_document_id or "")
        name = retained.original_filename if retained else occ.duplicate_of_document_id
        return f"exact byte duplicate of {name}"
    if occ.is_content_duplicate:
        retained = occ_by_id.get(occ.content_duplicate_of_document_id or "")
        name = retained.original_filename if retained else occ.content_duplicate_of_document_id
        return f"content-aware duplicate ({occ.duplicate_detection_method}) of {name}"
    if occ.is_portfolio_container:
        return "PDF Portfolio container page(s) -- its embedded attachments are included separately"
    if occ.is_contained_in_merged_document:
        container = occ_by_id.get(occ.contained_in_document_id or "")
        name = container.original_filename if container else occ.contained_in_document_id
        return f"content safely proven fully contained inside merged package {name}"
    if occ.is_ignored_artifact:
        return occ.ignored_artifact_reason or "ignored system artifact"
    return "no reason recorded (this should never happen -- see integrity checks)"


def write_merged_overlap_report(run: RunResult, path: Path) -> None:
    occ_by_id = {o.document_id: o for o in run.occurrences}

    lines: list[str] = []
    lines.append("MERGED DOCUMENT OVERLAP REPORT")
    lines.append("=" * 70)
    lines.append(
        "Shows every comparison between a standalone document (or PDF Portfolio attachment) "
        "and a candidate merged-package container, and every PDF Portfolio detected. A merged "
        "package's own pages are NEVER modified, reordered, or removed by this analysis -- "
        "only a redundant standalone copy is ever excluded from Final, and only when safely "
        "proven to be fully contained."
    )
    lines.append("")

    portfolios = [o for o in run.occurrences if o.is_portfolio_container]
    lines.append("=" * 70)
    lines.append("PDF PORTFOLIOS DETECTED")
    lines.append("=" * 70)
    lines.append(f"Count: {len(portfolios)}")
    lines.append("")
    if not portfolios:
        lines.append("None found.")
        lines.append("")
    else:
        for portfolio in portfolios:
            attachments = [
                o for o in run.occurrences if o.portfolio_parent_document_id == portfolio.document_id
            ]
            lines.append(f"  {portfolio.original_filename} ({portfolio.document_id})")
            lines.append(
                "    Its own page content (the generic 'open this in Acrobat' cover/UI page) is "
                "excluded from Final; it remains untouched in OG."
            )
            lines.append(f"    Embedded attachments extracted: {len(attachments)}")
            for att in attachments:
                lines.append(f"      - {att.original_filename} ({att.document_id})")
            lines.append("")

    lines.append("=" * 70)
    lines.append("MERGED-PACKAGE CONTAINMENT FINDINGS")
    lines.append("=" * 70)
    lines.append(f"Total comparisons resulting in a finding: {len(run.overlap_findings)}")
    lines.append("")
    if not run.overlap_findings:
        lines.append("No merged-package containment relationships were found in this run.")
        lines.append("")
    else:
        classifications = ("exact_contained", "equivalent_contained", "different_version", "partial_overlap", "uncertain_overlap")
        for classification in classifications:
            findings = [f for f in run.overlap_findings if f.classification == classification]
            if not findings:
                continue
            lines.append(f"--- {classification.upper()} ({len(findings)}) ---")
            for finding in findings:
                standalone = occ_by_id.get(finding.standalone_document_id)
                container = occ_by_id.get(finding.container_document_id)
                s_name = standalone.original_filename if standalone else finding.standalone_document_id
                c_name = container.original_filename if container else finding.container_document_id
                lines.append(f"  Standalone: {s_name} ({finding.standalone_document_id})")
                lines.append(f"  Container:  {c_name} ({finding.container_document_id})")
                if finding.contained_page_range:
                    lines.append(
                        f"  Container page range: {finding.contained_page_range[0]}-{finding.contained_page_range[1]} "
                        "(0-based, inclusive)"
                    )
                lines.append(f"  Confidence: {finding.confidence:.2f}")
                if finding.excluded:
                    lines.append(
                        "  Outcome: standalone copy safely proven contained -- excluded from Final. "
                        "The merged package is preserved in full regardless of the standalone copy's "
                        "relative quality; this is a structural safety rule, not a quality judgment."
                    )
                elif classification == "different_version":
                    lines.append(
                        "  Outcome: content differs meaningfully (signature state, dates, form "
                        "values, or other content) -- BOTH retained."
                    )
                elif classification == "uncertain_overlap":
                    lines.append(
                        "  Outcome: confidence below the safe auto-exclusion threshold -- BOTH "
                        "retained and flagged for review."
                    )
                elif classification == "partial_overlap":
                    lines.append(
                        "  Outcome: only part of the standalone document matches the container -- "
                        "not classified as a full duplicate; BOTH retained (no unsafe removal)."
                    )
                lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


_MATCH_KIND_LABELS = {
    "content_duplicate": "Content-duplicate comparison",
    "merged_containment": "Merged-package containment comparison",
}


def write_uncertain_match_review_log(run: RunResult, path: Path) -> None:
    """The complete audit trail of every uncertain comparison the engine
    could not decide automatically, and its decision, if any. This is
    the durable, on-disk record of every "Review Uncertain Matches"
    decision made in the GUI (see review_decisions.py) -- rewritten in
    full every time a decision is applied, so it always reflects the
    complete, current state.
    """

    occ_by_id = {o.document_id: o for o in run.occurrences}

    lines: list[str] = []
    lines.append("UNCERTAIN MATCH REVIEW LOG")
    lines.append("=" * 70)
    lines.append(
        "Lists every comparison the engine could not confirm automatically with high enough "
        "confidence to remove anything -- both documents in every pair below were kept in Final "
        "by default (\"when uncertain, keep both\") unless a human explicitly, and separately, "
        "recorded a decision to exclude one specific document. No automated process in this "
        "application can ever exclude anything listed here."
    )
    lines.append(f"Total uncertain matches: {len(run.uncertain_matches)}")
    decided = sum(1 for m in run.uncertain_matches if m.decision != "undecided")
    lines.append(f"Reviewed and decided: {decided}")
    lines.append(f"Awaiting review: {len(run.uncertain_matches) - decided}")
    lines.append("")

    if not run.uncertain_matches:
        lines.append("No uncertain matches were found in this run.")
        path.write_text("\n".join(lines), encoding="utf-8")
        return

    for match in run.uncertain_matches:
        occ_a = occ_by_id.get(match.document_id_a)
        occ_b = occ_by_id.get(match.document_id_b)
        lines.append("=" * 70)
        lines.append(f"MATCH {match.match_id}: {_MATCH_KIND_LABELS.get(match.kind, match.kind)}")
        lines.append("=" * 70)
        lines.append(f"    Document A: {occ_a.original_relative_path if occ_a else match.document_id_a} "
                     f"({match.document_id_a})")
        if occ_a:
            lines.append(f"        Page count: {occ_a.converted_page_count}")
        lines.append(f"    Document B: {occ_b.original_relative_path if occ_b else match.document_id_b} "
                     f"({match.document_id_b})")
        if occ_b:
            lines.append(f"        Page count: {occ_b.converted_page_count}")
        lines.append(f"    Confidence: {match.confidence:.2f}")
        lines.append(f"    Detail: {match.detail}")
        excludable_names = [
            (occ_by_id[d].original_filename if d in occ_by_id else d) for d in match.excludable_ids
        ]
        lines.append(f"    Documents eligible for exclusion if a human chooses to: {', '.join(excludable_names)}")

        if match.decision == "undecided":
            lines.append("    Decision: AWAITING REVIEW -- both documents remain in Final by default.")
        elif match.decision == "keep_both":
            lines.append("    Decision: KEEP BOTH (explicitly reviewed and confirmed by a human)")
            lines.append(f"        Decided at: {match.decided_at}")
            lines.append(f"        Reason: {match.decided_reason}")
        elif match.decision == "excluded":
            excluded_occ = occ_by_id.get(match.decided_document_id or "")
            excluded_name = excluded_occ.original_filename if excluded_occ else match.decided_document_id
            lines.append(f"    Decision: EXCLUDED -- {excluded_name} was removed from Final by explicit human review.")
            lines.append(f"        Decided at: {match.decided_at}")
            lines.append(f"        Reason: {match.decided_reason}")
            lines.append(
                "        Both documents remain fully present in OG regardless of this decision, and "
                "the original source files were never modified."
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


_CLOSE_REASON_TEXT = {
    "page_maximum": "closed at the configured page maximum",
    "size_maximum": "closed at the configured MB maximum",
    "oversized_document": "contains one oversized document that alone exceeds a maximum",
    "end_of_package": "end of package (no more documents to add)",
}


def _format_close_reasons(reasons: list[str]) -> str:
    if not reasons:
        return "unknown"
    return "; ".join(_CLOSE_REASON_TEXT.get(r, r) for r in reasons)


def _format_part_line(part) -> str:
    oversized = " [OVERSIZED SINGLE DOCUMENT]" if part.is_oversized else ""
    size_mb = part.file_size_bytes / (1024 * 1024)
    reason = _format_close_reasons(part.close_reasons)
    return (
        f"    {part.file_path.name}: {len(part.document_ids)} document(s), "
        f"{part.page_count} page(s), {size_mb:.2f} MB ({part.file_size_bytes:,} bytes){oversized}\n"
        f"        Why this part ended here: {reason}"
    )


def write_processing_report(run: RunResult, config, meta: dict, path: Path) -> None:
    occurrences = run.occurrences
    non_ignored = [o for o in occurrences if not o.is_ignored_artifact]
    ignored = [o for o in occurrences if o.is_ignored_artifact]
    converted_real = [
        o for o in non_ignored if o.status == ProcessingStatus.CONVERTED and not o.used_fallback_renderer
    ]
    converted_fallback = [
        o for o in non_ignored if o.status == ProcessingStatus.CONVERTED and o.used_fallback_renderer
    ]
    placeholders = [o for o in non_ignored if o.status == ProcessingStatus.UNCONVERTED_PLACEHOLDER]
    duplicates = [o for o in non_ignored if o.is_duplicate]
    unique_hashes = {o.original_sha256 for o in non_ignored if o.original_sha256}

    og_page_total = sum(p.page_count for p in run.og_parts)
    final_page_total = sum(p.page_count for p in run.final_parts)
    dup_pages = sum(o.converted_page_count or 0 for o in duplicates)

    lines: list[str] = []

    def section(title: str) -> None:
        lines.append("")
        lines.append(title)
        lines.append("-" * len(title))

    lines.append("LENDER PACKAGE BUILDER - PROCESSING REPORT")
    lines.append("=" * 70)
    lines.append(f"Application version:   {meta.get('app_version')}")
    lines.append(f"Input path:            {run.input_path}")
    lines.append(f"Output path:           {run.output_path}")
    lines.append(f"Start time:            {run.start_time}")
    lines.append(f"Completion time:       {run.end_time}")
    lines.append(f"Elapsed time:          {run.elapsed_seconds:.2f} seconds")
    lines.append(f"Operating system:      {meta.get('os_info')}")
    lines.append(f"Python version:        {meta.get('python_version')}")

    section("CONFIGURATION")
    lines.append(
        f"Configured maximum pages per part:  {meta.get('max_pages_per_part')}  "
        "(a ceiling -- parts are not padded to reach it)"
    )
    lines.append(
        f"Configured maximum MB per part:     {meta.get('max_size_mb_per_part')}  "
        "(a ceiling -- parts are not padded to reach it)"
    )
    lines.append(f"Allow large input:                  {meta.get('allow_large_input')}")
    lines.append(f"Office backend order:               {', '.join(config.office_backend_order)}")

    section("SOURCE INVENTORY")
    lines.append(f"Source occurrences discovered (total):  {len(occurrences)}")
    lines.append(f"Intentionally ignored system artifacts: {len(ignored)}")
    for occ in ignored:
        lines.append(f"    - {occ.original_relative_path} ({occ.ignored_artifact_reason})")
    lines.append(f"Successfully converted documents:       {len(converted_real)}")
    lines.append(f"Converted via basic fallback renderer:  {len(converted_fallback)}")
    lines.append(f"Placeholder (unconverted) documents:    {len(placeholders)}")
    lines.append(f"Exact duplicate occurrences:             {len(duplicates)}")
    lines.append(f"Unique source hashes:                    {len(unique_hashes)}")

    section("OG / FINAL PACKAGE TOTALS")
    lines.append(f"OG document count:      {sum(len(p.document_ids) for p in run.og_parts)}")
    lines.append(f"Final document count:   {sum(len(p.document_ids) for p in run.final_parts)}")
    lines.append(f"OG page count:          {og_page_total}")
    lines.append(f"Final page count:       {final_page_total}")
    lines.append(f"Pages excluded from Final solely due to exact duplication: {dup_pages}")

    section("OG OUTPUT PARTS")
    for part in run.og_parts:
        lines.append(_format_part_line(part))

    section("FINAL OUTPUT PARTS")
    for part in run.final_parts:
        lines.append(_format_part_line(part))

    section("CONVERSION BACKEND USAGE")
    if run.conversion_backend_usage:
        for backend, count in sorted(run.conversion_backend_usage.items()):
            lines.append(f"    {backend}: {count} file(s)")
    else:
        lines.append("    (none)")

    section("CONVERSION WARNINGS")
    any_warnings = False
    for occ in non_ignored:
        for warning in occ.conversion_warnings:
            any_warnings = True
            lines.append(f"    [{occ.document_id}] {occ.original_relative_path}: {warning}")
    if not any_warnings:
        lines.append("    (none)")

    section("UNCONVERTED / PLACEHOLDER FILES")
    if placeholders:
        for occ in placeholders:
            lines.append(
                f"    [{occ.document_id}] {occ.original_relative_path}: "
                f"{occ.conversion_failure_reason}"
            )
    else:
        lines.append("    (none)")

    section("UNSAFE ARCHIVE PATH INCIDENTS")
    if run.unsafe_archive_incidents:
        for incident in run.unsafe_archive_incidents:
            lines.append(f"    - {incident}")
    else:
        lines.append("    (none)")

    section("INTEGRITY CHECK RESULTS")
    for check in run.integrity_checks:
        status = "PASS" if check.passed else "FAIL"
        lines.append(f"    [{status}] {check.name}")
        lines.append(f"           {check.detail}")

    lines.append("")
    lines.append("=" * 70)
    lines.append(f"OVERALL RESULT: {'SUCCESS' if run.success else 'FAILURE - SEE FAILED CHECKS ABOVE'}")

    path.write_text("\n".join(lines), encoding="utf-8")


def _json_default(obj):
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "value"):  # enum
        return obj.value
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def write_processing_manifest(run: RunResult, meta: dict, path: Path) -> None:
    def occ_dict(occ: SourceOccurrence) -> dict:
        d = dataclasses.asdict(occ)
        return d

    manifest = {
        "meta": meta,
        "input_path": str(run.input_path),
        "output_path": str(run.output_path),
        "start_time": run.start_time,
        "end_time": run.end_time,
        "elapsed_seconds": run.elapsed_seconds,
        "occurrences": [occ_dict(o) for o in run.occurrences],
        "duplicate_groups": [dataclasses.asdict(g) for g in run.duplicate_groups],
        "content_duplicate_groups": [dataclasses.asdict(g) for g in run.content_duplicate_groups],
        "document_families": [dataclasses.asdict(f) for f in run.document_families],
        "overlap_findings": [dataclasses.asdict(f) for f in run.overlap_findings],
        "og_parts": [dataclasses.asdict(p) for p in run.og_parts],
        "final_parts": [dataclasses.asdict(p) for p in run.final_parts],
        "integrity_checks": [dataclasses.asdict(c) for c in run.integrity_checks],
        "conversion_backend_usage": run.conversion_backend_usage,
        "unsafe_archive_incidents": run.unsafe_archive_incidents,
        "content_dedup_notes": run.content_dedup_notes,
        "uncertain_matches": [dataclasses.asdict(m) for m in run.uncertain_matches],
        "key_document_matches": [dataclasses.asdict(m) for m in run.key_document_matches],
        "identity": dataclasses.asdict(run.identity),
        "overall_success": run.success,
    }

    path.write_text(json.dumps(manifest, indent=2, default=_json_default), encoding="utf-8")
