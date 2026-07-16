"""Command-line interface and top-level pipeline orchestration.

`build_package()` is the pure, testable engine entry point: it takes an
input path and options and returns a `RunResult`, without touching
`sys.argv`, `sys.exit`, or stdout formatting. `main()` is the thin CLI
wrapper used by `python -m lender_package_builder build ...`.
"""

from __future__ import annotations

import argparse
import logging
import platform
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from . import (
    __version__,
    archives,
    content_dedup,
    deduplication,
    merging,
    overlap_detection,
    reporting,
    runtime_paths,
    validation,
    version_classification,
)
from .config import AppConfig, load_config
from .conversion import convert_occurrence
from .conversion.base import make_placeholder_pdf
from .exceptions import (
    ArchiveTooLargeError,
    InsufficientDiskSpaceError,
    InvalidConfigError,
    InvalidInputError,
    LenderPackageBuilderError,
    OutputAlreadyExistsError,
)
from .inventory import InventoryBuilder
from .models import ConversionOutcome, ProcessingStatus, RunResult
from .progress import ProgressCallback, ProgressEvent, ProgressSeverity, ProgressStage
from .workspace import Workspace

logger = logging.getLogger("lender_package_builder")


# ---------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lender_package_builder")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build", help="Build OG and Final lender packages from an input ZIP, folder, or file."
    )
    build.add_argument("input_path", help="Path to a ZIP file, folder, or single supported document.")
    build.add_argument("--output", type=Path, default=None, help="Explicit output directory.")
    build.add_argument(
        "--max-pages-per-part",
        type=int,
        default=None,
        help="Override the maximum pages allowed in one output part (a ceiling, not a target).",
    )
    build.add_argument(
        "--max-size-mb-per-part",
        type=float,
        default=None,
        help="Override the maximum MB allowed in one output part (a ceiling, not a target).",
    )
    build.add_argument(
        "--allow-large-input",
        action="store_true",
        help="Bypass ZIP-bomb-style safety thresholds for a known, intentional large package.",
    )
    build.add_argument(
        "--disable-content-aware-dedup",
        action="store_true",
        help="Fall back to exact-SHA-256-only duplicate detection (RC1 behavior); "
        "skips content-aware/Portfolio/merged-package analysis entirely.",
    )
    build.add_argument(
        "--keep-temp", action="store_true", help="Do not delete the temporary workspace after the run."
    )
    build.add_argument("--verbose", action="store_true", help="Enable debug-level logging.")
    build.add_argument("--config", type=Path, default=None, help="Path to a config.toml file.")
    build.add_argument(
        "--quiet", action="store_true", help="Suppress live progress output (still prints the summary)."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "build":
        return _run_build_command(args)

    parser.print_help()
    return 2


def _run_build_command(args: argparse.Namespace) -> int:
    input_path = Path(args.input_path).expanduser().resolve()
    config_path = args.config or _default_config_path()

    try:
        config = load_config(config_path)
    except InvalidConfigError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1

    if args.max_pages_per_part is not None:
        config.max_pages_per_part = args.max_pages_per_part
    if args.max_size_mb_per_part is not None:
        config.max_size_mb_per_part = args.max_size_mb_per_part
    if args.disable_content_aware_dedup:
        config.enable_content_aware_dedup = False

    try:
        run = build_package(
            input_path=input_path,
            output_dir=args.output,
            config=config,
            allow_large_input=args.allow_large_input,
            keep_temp=args.keep_temp,
            verbose=args.verbose,
            progress=not args.quiet,
        )
    except LenderPackageBuilderError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # top-level safety net; never a bare crash with no message
        print(f"\nUNEXPECTED ERROR: {exc}", file=sys.stderr)
        logger.exception("Unexpected error during build")
        return 1

    _print_summary(run)
    return 0 if run.success else 1


def _default_config_path() -> Path:
    """Where to look for `config.toml` when none is given explicitly.

    Prefers the current working directory (developer convenience: `cd`
    into the project and run `config.toml` edits without a full path),
    then falls back to the portable application root -- the project
    root when running from source, or the folder containing the .exe
    when frozen (see `runtime_paths.py`). A missing file at either
    location is not an error; `load_config` falls back to defaults.
    """

    cwd_candidate = Path.cwd() / "config.toml"
    if cwd_candidate.exists():
        return cwd_candidate
    return runtime_paths.external_config_path()


def _print_summary(run: RunResult) -> None:
    print()
    print("=" * 70)
    print(f"Output folder: {run.output_path}")
    print(f"OG documents:  {sum(len(p.document_ids) for p in run.og_parts)}  "
          f"({len(run.og_parts)} part(s))")
    print(f"Final documents: {sum(len(p.document_ids) for p in run.final_parts)}  "
          f"({len(run.final_parts)} part(s))")
    for check in run.integrity_checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"  [{status}] {check.name}")
    print("-" * 70)
    print("OVERALL RESULT:", "SUCCESS" if run.success else "FAILURE")
    print("=" * 70)


# ---------------------------------------------------------------------
# Core engine (no argparse/sys.exit -- directly testable)
# ---------------------------------------------------------------------


class _ProgressReporter:
    """Bridges pipeline progress to console printing, the log file, and
    an optional structured `progress_callback` -- without changing what
    the CLI has always printed/logged for callers that pass no callback.
    """

    _LOG_FUNCS = {
        ProgressSeverity.INFO: logger.info,
        ProgressSeverity.WARNING: logger.warning,
        ProgressSeverity.ERROR: logger.error,
    }

    def __init__(self, callback: ProgressCallback | None, print_enabled: bool):
        self._callback = callback
        self._print_enabled = print_enabled

    def emit(
        self,
        stage: ProgressStage,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        current_item: str | None = None,
        severity: ProgressSeverity = ProgressSeverity.INFO,
        detail: str | None = None,
        print_message: bool = True,
    ) -> None:
        if self._print_enabled and print_message:
            print(message)
        self._LOG_FUNCS[severity](message)
        if self._callback is not None:
            event = ProgressEvent(
                stage=stage,
                message=message,
                current=current,
                total=total,
                current_item=current_item,
                severity=severity,
                detail=detail,
            )
            # A misbehaving callback (e.g. a GUI bug) must never take down
            # the processing job itself.
            try:
                self._callback(event)
            except Exception:
                logger.exception("progress_callback raised; continuing processing")


def build_package(
    input_path: Path,
    output_dir: Path | None,
    config: AppConfig,
    allow_large_input: bool = False,
    keep_temp: bool = False,
    verbose: bool = False,
    progress: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> RunResult:
    if not input_path.exists():
        raise InvalidInputError(f"Input path does not exist: {input_path}")

    resolved_output_dir = _compute_output_dir(input_path, output_dir)
    if resolved_output_dir.exists():
        raise OutputAlreadyExistsError(f"Output folder already exists: {resolved_output_dir}")

    og_dir = resolved_output_dir / "OG"
    final_dir = resolved_output_dir / "Final"
    reports_dir = resolved_output_dir / "Reports"
    unconverted_dir = resolved_output_dir / "Unconverted_Files"
    logs_dir = resolved_output_dir / "Logs"
    for d in (resolved_output_dir, og_dir, final_dir, reports_dir, unconverted_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    file_handler = _setup_logging(logs_dir, verbose)
    start_dt = datetime.now()
    start_perf = time.perf_counter()
    reporter = _ProgressReporter(progress_callback, print_enabled=progress)

    try:
        _preflight_checks(input_path, resolved_output_dir, config, allow_large_input, reporter)

        workspace = Workspace()
        run_succeeded = False
        try:
            run = _execute_pipeline(
                input_path=input_path,
                output_dir=resolved_output_dir,
                og_dir=og_dir,
                final_dir=final_dir,
                reports_dir=reports_dir,
                unconverted_dir=unconverted_dir,
                config=config,
                allow_large_input=allow_large_input,
                workspace=workspace,
                progress=progress,
                reporter=reporter,
            )
            run_succeeded = True
        finally:
            if run_succeeded and not keep_temp:
                workspace.cleanup()
            elif keep_temp or not run_succeeded:
                logger.info("Temporary workspace preserved at: %s", workspace.root)

        end_dt = datetime.now()
        run.start_time = start_dt.isoformat(timespec="seconds")
        run.end_time = end_dt.isoformat(timespec="seconds")
        run.elapsed_seconds = time.perf_counter() - start_perf

        meta = {
            "app_version": __version__,
            "os_info": platform.platform(),
            "python_version": platform.python_version(),
            "max_pages_per_part": config.max_pages_per_part,
            "max_size_mb_per_part": config.max_size_mb_per_part,
            "allow_large_input": allow_large_input,
        }
        reporter.emit(ProgressStage.WRITING_REPORTS, "Writing reports...")
        reporting.write_all_reports(run, config, meta, reports_dir)

        reporter.emit(
            ProgressStage.COMPLETE,
            "Processing complete." if run.success else "Processing finished with failed integrity checks.",
            severity=ProgressSeverity.INFO if run.success else ProgressSeverity.WARNING,
            print_message=False,
        )
        return run
    finally:
        logger.removeHandler(file_handler)
        file_handler.close()


def _compute_output_dir(input_path: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = input_path.stem if input_path.is_file() else input_path.name
    return input_path.parent / f"{name}_Lender_Package_Output_{timestamp}"


def _setup_logging(logs_dir: Path, verbose: bool) -> logging.Handler:
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

    file_handler = logging.FileHandler(logs_dir / "run.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if not any(isinstance(h, logging.StreamHandler) and h.stream is sys.stderr for h in logger.handlers):
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return file_handler


def _preflight_checks(
    input_path: Path,
    output_dir: Path,
    config: AppConfig,
    allow_large_input: bool,
    reporter: _ProgressReporter,
) -> None:
    estimate = archives.estimate_expansion(input_path)
    reporter.emit(
        ProgressStage.PREFLIGHT,
        f"Preflight estimate: {estimate.total_entries} entries, "
        f"{estimate.total_uncompressed_bytes / (1024 * 1024):.1f} MB expanded.",
        detail=f"entries={estimate.total_entries} "
        f"expanded_mb={estimate.total_uncompressed_bytes / (1024 * 1024):.1f}",
        print_message=False,
    )

    if not allow_large_input:
        if estimate.total_uncompressed_bytes > config.max_expanded_size_bytes:
            raise ArchiveTooLargeError(
                f"Estimated expanded input size ({estimate.total_uncompressed_bytes / (1024*1024):.0f} MB) "
                f"exceeds the safety limit of {config.max_expanded_size_mb:.0f} MB. If this is a known, "
                "intentional large lender package, re-run with --allow-large-input."
            )
        if estimate.total_entries > config.max_archive_entries:
            raise ArchiveTooLargeError(
                f"Estimated entry count ({estimate.total_entries}) exceeds the safety limit of "
                f"{config.max_archive_entries}. If this is a known, intentional large lender package, "
                "re-run with --allow-large-input."
            )
    elif estimate.total_uncompressed_bytes > config.large_input_warning_bytes:
        reporter.emit(
            ProgressStage.PREFLIGHT,
            f"Input expands to approximately {estimate.total_uncompressed_bytes / (1024 * 1024):.0f} MB, "
            f"above the warning threshold of {config.large_input_warning_mb:.0f} MB.",
            severity=ProgressSeverity.WARNING,
            print_message=False,
        )

    check_root = output_dir.parent if output_dir.parent.exists() else Path(output_dir.anchor or "/")
    try:
        usage = shutil.disk_usage(check_root)
    except OSError:
        return
    required = estimate.total_uncompressed_bytes * config.required_free_space_multiplier
    if usage.free < required:
        raise InsufficientDiskSpaceError(
            f"Insufficient free disk space. Estimated requirement: {required / (1024*1024):.0f} MB "
            f"(expanded input x{config.required_free_space_multiplier:g} safety margin); "
            f"available: {usage.free / (1024*1024):.0f} MB at {check_root}."
        )


def _execute_pipeline(
    input_path: Path,
    output_dir: Path,
    og_dir: Path,
    final_dir: Path,
    reports_dir: Path,
    unconverted_dir: Path,
    config: AppConfig,
    allow_large_input: bool,
    workspace: Workspace,
    progress: bool,
    reporter: _ProgressReporter,
) -> RunResult:
    reporter.emit(ProgressStage.DISCOVERING_FILES, f"[1/10] Discovering source files in: {input_path}")
    inventory_builder = InventoryBuilder(config, workspace, allow_large_input)
    occurrences = inventory_builder.build(input_path)
    reporter.emit(
        ProgressStage.DISCOVERING_FILES, f"      Found {len(occurrences)} source occurrence(s)."
    )

    reporter.emit(ProgressStage.DETECTING_DUPLICATES, "[2/10] Detecting exact duplicates (whole-file SHA-256)...")
    duplicate_groups = deduplication.find_duplicates(occurrences)
    dup_count = sum(len(g.duplicate_document_ids) for g in duplicate_groups)
    reporter.emit(
        ProgressStage.DETECTING_DUPLICATES,
        f"      {dup_count} duplicate occurrence(s) in {len(duplicate_groups)} group(s).",
    )

    occ_by_id = {o.document_id: o for o in occurrences}
    backend_usage: dict[str, int] = {}

    non_ignored = [o for o in occurrences if not o.is_ignored_artifact]
    reporter.emit(
        ProgressStage.CONVERTING_DOCUMENTS,
        f"[3/10] Converting {len(non_ignored)} document(s) to PDF...",
        total=len(non_ignored),
    )

    for i, occ in enumerate(non_ignored, start=1):
        if occ.is_duplicate:
            retained = occ_by_id[occ.duplicate_of_document_id]
            _copy_conversion_result(retained, occ)
            if occ.status == ProcessingStatus.UNCONVERTED_PLACEHOLDER:
                _preserve_unconverted_original(occ, unconverted_dir)
            reporter.emit(
                ProgressStage.CONVERTING_DOCUMENTS,
                f"      [{i}/{len(non_ignored)}] {occ.original_relative_path}: duplicate of "
                f"{retained.document_id} (reused conversion)",
                current=i,
                total=len(non_ignored),
                current_item=occ.original_relative_path,
            )
            backend_usage[occ.conversion_backend or "unknown"] = (
                backend_usage.get(occ.conversion_backend or "unknown", 0) + 1
            )
            continue

        if occ.conversion_failure_reason and occ.status == ProcessingStatus.DISCOVERED:
            result_outcome_failed = True
            failure_reason = occ.conversion_failure_reason
            warnings: list[str] = []
            extra_preserved: list[tuple[str, Path]] = []
        else:
            dest = workspace.new_convert_path(occ.document_id)
            result = convert_occurrence(occ, dest, config, workspace)
            result_outcome_failed = result.outcome == ConversionOutcome.FAILED
            failure_reason = result.failure_reason
            warnings = result.warnings
            extra_preserved = result.extra_preserved_files

            if not result_outcome_failed:
                occ.status = ProcessingStatus.CONVERTED
                occ.converted_pdf_path = result.pdf_path
                occ.converted_page_count = result.page_count
                occ.converted_size_bytes = result.pdf_path.stat().st_size
                occ.conversion_backend = result.backend
                occ.used_fallback_renderer = result.outcome == ConversionOutcome.FALLBACK_SUCCESS
                occ.conversion_warnings.extend(warnings)
                for name, path in extra_preserved:
                    _copy_extra_preserved_file(name, path, unconverted_dir)

        if result_outcome_failed:
            occ.status = ProcessingStatus.UNCONVERTED_PLACEHOLDER
            occ.conversion_failure_reason = failure_reason
            occ.conversion_warnings.extend(warnings)
            placeholder_path = workspace.new_convert_path(occ.document_id)
            page_count = make_placeholder_pdf(
                occ, placeholder_path, failure_reason or "Unknown conversion failure.",
                original_preserved=occ.extracted_path is not None,
            )
            occ.converted_pdf_path = placeholder_path
            occ.converted_page_count = page_count
            occ.converted_size_bytes = placeholder_path.stat().st_size
            occ.conversion_backend = "placeholder"
            _preserve_unconverted_original(occ, unconverted_dir)

        status_word = "OK" if occ.status == ProcessingStatus.CONVERTED else "PLACEHOLDER"
        reporter.emit(
            ProgressStage.CONVERTING_DOCUMENTS,
            f"      [{i}/{len(non_ignored)}] {occ.original_relative_path}: {status_word} "
            f"({occ.conversion_backend}, {occ.converted_page_count} page(s))",
            current=i,
            total=len(non_ignored),
            current_item=occ.original_relative_path,
            severity=ProgressSeverity.WARNING if status_word == "PLACEHOLDER" else ProgressSeverity.INFO,
        )
        backend_usage[occ.conversion_backend or "unknown"] = (
            backend_usage.get(occ.conversion_backend or "unknown", 0) + 1
        )

    reporter.emit(ProgressStage.BUILDING_OG, "[4/10] Merging OG package...")
    og_docs = [o for o in occurrences if o.included_in_og]
    og_parts = merging.write_package(
        og_docs,
        og_dir,
        "Full_Lender_Package_OG_Files_Part",
        "OG",
        config.max_pages_per_part,
        config.max_size_bytes_per_part,
    )
    for part in og_parts:
        for doc_id in part.document_ids:
            occ_by_id[doc_id].og_part_index = part.index
    reporter.emit(ProgressStage.BUILDING_OG, f"      OG: {len(og_parts)} part(s) written.")

    content_duplicate_groups, document_families, overlap_findings, oversized_bucket_notes, uncertain_matches = (
        _run_content_aware_analysis(occurrences, config, reporter)
    )

    reporter.emit(ProgressStage.BUILDING_FINAL, "[9/10] Merging Final package...")
    final_docs = [o for o in occurrences if o.included_in_final]
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
    reporter.emit(ProgressStage.BUILDING_FINAL, f"      Final: {len(final_parts)} part(s) written.")

    run = RunResult(
        input_path=input_path,
        output_path=output_dir,
        start_time="",
        occurrences=occurrences,
        duplicate_groups=duplicate_groups,
        content_duplicate_groups=content_duplicate_groups,
        document_families=document_families,
        overlap_findings=overlap_findings,
        og_parts=og_parts,
        final_parts=final_parts,
        conversion_backend_usage=backend_usage,
        unsafe_archive_incidents=inventory_builder.unsafe_incidents,
        content_dedup_notes=oversized_bucket_notes,
        uncertain_matches=uncertain_matches,
    )

    reporter.emit(ProgressStage.RUNNING_INTEGRITY_CHECKS, "[10/10] Running integrity checks...")
    run.integrity_checks = validation.run_integrity_checks(
        run, config.max_pages_per_part, config.max_size_bytes_per_part
    )
    passed = sum(1 for c in run.integrity_checks if c.passed)
    reporter.emit(
        ProgressStage.RUNNING_INTEGRITY_CHECKS,
        f"      {passed}/{len(run.integrity_checks)} integrity checks passed.",
        severity=ProgressSeverity.INFO if passed == len(run.integrity_checks) else ProgressSeverity.WARNING,
    )

    return run


def _run_content_aware_analysis(occurrences, config: AppConfig, reporter: _ProgressReporter):
    """Levels 2-4 content-aware duplicate detection, merged-document
    overlap detection, and Level 5 version classification -- all run
    over already-converted documents, between Building OG and Building
    Final. Guarded by `config.enable_content_aware_dedup`: when
    disabled, every stage still emits a progress event (for a stable,
    predictable event sequence) but does no work and mutates nothing,
    which is exactly RC1's original exact-hash-only behavior.

    Returns (content_duplicate_groups, document_families,
    overlap_findings, oversized_bucket_notes, uncertain_matches).
    """

    if not config.enable_content_aware_dedup:
        for stage, label in (
            (ProgressStage.FINGERPRINTING_CONTENT, "[5/10] Content-aware analysis disabled; skipping."),
            (ProgressStage.DETECTING_CONTENT_DUPLICATES, "[6/10] Content-aware analysis disabled; skipping."),
            (ProgressStage.ANALYZING_MERGED_PACKAGES, "[7/10] Content-aware analysis disabled; skipping."),
            (ProgressStage.CLASSIFYING_VERSIONS, "[8/10] Content-aware analysis disabled; skipping."),
        ):
            reporter.emit(stage, label)
        return [], [], [], [], []

    reporter.emit(ProgressStage.FINGERPRINTING_CONTENT, "[5/10] Analyzing document content...")
    fingerprints = content_dedup.build_fingerprints(occurrences)
    reporter.emit(
        ProgressStage.FINGERPRINTING_CONTENT,
        f"      Fingerprinted {len(fingerprints)} document(s) for content-aware comparison.",
    )

    reporter.emit(ProgressStage.DETECTING_CONTENT_DUPLICATES, "[6/10] Detecting content-aware duplicates...")
    content_duplicate_groups, oversized_bucket_notes, uncertain_content_pairs = content_dedup.detect_content_duplicates(
        occurrences, fingerprints
    )
    content_dup_count = sum(len(g.document_ids) - 1 for g in content_duplicate_groups)
    reporter.emit(
        ProgressStage.DETECTING_CONTENT_DUPLICATES,
        f"      {content_dup_count} content-aware duplicate occurrence(s) in "
        f"{len(content_duplicate_groups)} group(s).",
    )
    for note in oversized_bucket_notes:
        reporter.emit(ProgressStage.DETECTING_CONTENT_DUPLICATES, f"      {note}", severity=ProgressSeverity.WARNING)

    reporter.emit(ProgressStage.ANALYZING_MERGED_PACKAGES, "[7/10] Analyzing merged-package overlaps...")
    overlap_findings = overlap_detection.detect_overlaps(occurrences, fingerprints)
    contained_count = sum(1 for f in overlap_findings if f.excluded)
    reporter.emit(
        ProgressStage.ANALYZING_MERGED_PACKAGES,
        f"      {len(overlap_findings)} overlap finding(s); {contained_count} document(s) "
        "safely proven contained in a merged package.",
    )

    reporter.emit(ProgressStage.CLASSIFYING_VERSIONS, "[8/10] Classifying document versions...")
    document_families = version_classification.build_document_families(
        occurrences, fingerprints, content_duplicate_groups, overlap_findings
    )
    reporter.emit(
        ProgressStage.CLASSIFYING_VERSIONS, f"      {len(document_families)} document family/families identified."
    )

    uncertain_matches = _build_uncertain_matches(uncertain_content_pairs, overlap_findings)

    return content_duplicate_groups, document_families, overlap_findings, oversized_bucket_notes, uncertain_matches


def _build_uncertain_matches(
    uncertain_content_pairs: list[tuple[str, str, float]],
    overlap_findings: list,
) -> list:
    """Turns the two structural sources of "the engine could not decide
    automatically" -- content_dedup.py's uncertain content-duplicate
    pairs, and overlap_detection.py's uncertain_overlap findings -- into
    one unified, GUI-facing list of `UncertainMatch` records. Creating
    these records never changes anything by itself; see
    `review_decisions.apply_review_decision()` for the only mechanism
    that can ever record an exclusion.
    """

    from .models import UncertainMatch

    matches: list[UncertainMatch] = []
    seq = 1

    for id_a, id_b, confidence in uncertain_content_pairs:
        matches.append(
            UncertainMatch(
                match_id=f"UM-{seq:04d}",
                kind="content_duplicate",
                document_id_a=id_a,
                document_id_b=id_b,
                confidence=confidence,
                detail=(
                    f"Uncertain content match (confidence {confidence:.2f}, below the "
                    f"{content_dedup.AUTO_REMOVE_THRESHOLD:.2f} safe auto-removal threshold). Either "
                    "document may reasonably be treated as the canonical copy."
                ),
                excludable_ids=(id_a, id_b),
            )
        )
        seq += 1

    for finding in overlap_findings:
        if finding.classification != "uncertain_overlap":
            continue
        matches.append(
            UncertainMatch(
                match_id=f"UM-{seq:04d}",
                kind="merged_containment",
                document_id_a=finding.standalone_document_id,
                document_id_b=finding.container_document_id,
                confidence=finding.confidence,
                detail=(
                    f"Uncertain merged-package containment match (confidence {finding.confidence:.2f}, "
                    f"below the {content_dedup.AUTO_REMOVE_THRESHOLD:.2f} safe auto-exclusion threshold). "
                    "Only the standalone copy may be excluded -- the merged package is never a valid "
                    "exclusion target."
                ),
                excludable_ids=(finding.standalone_document_id,),
            )
        )
        seq += 1

    return matches


def _copy_conversion_result(retained, duplicate) -> None:
    duplicate.status = retained.status
    duplicate.converted_pdf_path = retained.converted_pdf_path
    duplicate.converted_page_count = retained.converted_page_count
    duplicate.converted_size_bytes = retained.converted_size_bytes
    duplicate.conversion_backend = retained.conversion_backend
    duplicate.used_fallback_renderer = retained.used_fallback_renderer
    duplicate.conversion_warnings = list(retained.conversion_warnings)
    duplicate.conversion_failure_reason = retained.conversion_failure_reason


def _preserve_unconverted_original(occ, unconverted_dir: Path) -> None:
    if occ.extracted_path is None or not occ.extracted_path.exists():
        return
    dest = _unique_destination(unconverted_dir, occ.original_relative_path, occ.document_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(occ.extracted_path, dest)
    occ.unconverted_copy_path = dest


def _copy_extra_preserved_file(relative_name: str, source_path: Path, unconverted_dir: Path) -> None:
    dest = unconverted_dir / relative_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest = dest.with_name(f"{dest.stem}_{source_path.stat().st_size}{dest.suffix}")
    shutil.copyfile(source_path, dest)


def _unique_destination(base_dir: Path, relative_path: str, document_id: str) -> Path:
    parts = [p for p in relative_path.replace("\\", "/").split("/") if p]
    candidate = base_dir.joinpath(*parts) if parts else base_dir / "unnamed"
    if not candidate.exists():
        return candidate
    return candidate.with_name(f"{candidate.stem}_{document_id}{candidate.suffix}")


if __name__ == "__main__":
    sys.exit(main())
