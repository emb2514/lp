"""Plain-text and JSON report generation.

Three files are produced per run: `Processing_Report.txt` (the main
human-readable summary), `Duplicate_Removal_Log.txt` (full detail on
every exact duplicate excluded from Final), and
`Processing_Manifest.json` (a complete machine-readable record).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .models import ProcessingStatus, RunResult, SourceOccurrence


def write_all_reports(run: RunResult, config, meta: dict, reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    write_duplicate_removal_log(run, reports_dir / "Duplicate_Removal_Log.txt")
    write_processing_report(run, config, meta, reports_dir / "Processing_Report.txt")
    write_processing_manifest(run, meta, reports_dir / "Processing_Manifest.json")


def write_duplicate_removal_log(run: RunResult, path: Path) -> None:
    occ_by_id = {o.document_id: o for o in run.occurrences}
    duplicates = [o for o in run.occurrences if o.is_duplicate]

    lines: list[str] = []
    lines.append("DUPLICATE REMOVAL LOG")
    lines.append("=" * 70)
    lines.append(
        "Lists every source occurrence excluded from the Final package because it is a "
        "byte-for-byte exact duplicate (identical SHA-256) of an earlier occurrence."
    )
    lines.append(f"Total duplicate occurrences removed from Final: {len(duplicates)}")
    lines.append("")

    if not duplicates:
        lines.append("No exact duplicates were found in this run.")
    else:
        for i, occ in enumerate(duplicates, start=1):
            retained = occ_by_id.get(occ.duplicate_of_document_id or "")
            lines.append(f"[{i}] Duplicate occurrence")
            lines.append(f"    Duplicate traversal index:      {occ.traversal_index}")
            lines.append(f"    Duplicate internal document ID: {occ.document_id}")
            lines.append(f"    Duplicate original filename:    {occ.original_filename}")
            lines.append(f"    Duplicate original relative path: {occ.original_relative_path}")
            if retained:
                lines.append(f"    Retained traversal index:       {retained.traversal_index}")
                lines.append(f"    Retained internal document ID:  {retained.document_id}")
                lines.append(f"    Retained original filename:     {retained.original_filename}")
                lines.append(
                    f"    Retained original relative path: {retained.original_relative_path}"
                )
            lines.append(f"    Shared SHA-256:                 {occ.original_sha256}")
            lines.append(f"    Converted page count:           {occ.converted_page_count}")
            lines.append(f"    OG output part (duplicate):     {occ.og_part_index}")
            lines.append(
                f"    Final output part (retained):   {retained.final_part_index if retained else 'N/A'}"
            )
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


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
    lines.append(f"Page limit per part:        {meta.get('page_limit')}")
    lines.append(f"Size limit per part (MB):   {meta.get('size_limit_mb')}")
    lines.append(f"Allow large input:          {meta.get('allow_large_input')}")
    lines.append(f"Office backend order:       {', '.join(config.office_backend_order)}")

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
        oversized = " [OVERSIZED]" if part.is_oversized else ""
        lines.append(
            f"    {part.file_path.name}: {len(part.document_ids)} document(s), "
            f"{part.page_count} page(s), {part.file_size_bytes:,} bytes{oversized}"
        )

    section("FINAL OUTPUT PARTS")
    for part in run.final_parts:
        oversized = " [OVERSIZED]" if part.is_oversized else ""
        lines.append(
            f"    {part.file_path.name}: {len(part.document_ids)} document(s), "
            f"{part.page_count} page(s), {part.file_size_bytes:,} bytes{oversized}"
        )

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
        "og_parts": [dataclasses.asdict(p) for p in run.og_parts],
        "final_parts": [dataclasses.asdict(p) for p in run.final_parts],
        "integrity_checks": [dataclasses.asdict(c) for c in run.integrity_checks],
        "conversion_backend_usage": run.conversion_backend_usage,
        "unsafe_archive_incidents": run.unsafe_archive_incidents,
        "overall_success": run.success,
    }

    path.write_text(json.dumps(manifest, indent=2, default=_json_default), encoding="utf-8")
