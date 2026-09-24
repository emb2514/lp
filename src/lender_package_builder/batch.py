"""Batch mode: build multiple independent loan packages in one run,
given a parent folder containing one subfolder per loan.

Real user request: "point the app at a folder-of-folders (one per
loan) and build them all in one run instead of one at a time." Each
subfolder is processed as a fully independent build via the existing
`build_package()` -- this module adds nothing to how a single loan is
processed, only the orchestration of running many of them in one
sitting and reporting the combined result. Loans are never merged or
mixed together; each still gets its own separate OG+Final package,
exactly like running the app once per loan by hand.

A single loan's failure is isolated and never aborts the batch (the
same "one bad thing never takes down everything else" principle
already used throughout this app, e.g. one unconvertible document
never crashes a whole build) -- see `BatchResult.failed`. A real
cancellation request, in contrast, DOES abort the whole batch
immediately, exactly like cancelling a single build.

Per-loan identity (borrower name, loan number) is parsed from each
loan subfolder's own name -- see `identity_from_folder_name` -- rather
than requiring manual entry for every loan, since that manual step is
exactly what batch mode exists to eliminate. Parsing is conservative:
only the app's own "Last, First[, LoanNumber]" convention is split into
separate fields; anything else becomes the last name alone. This only
ever affects output folder/file NAMING, never which documents are
processed or how, and is always correctable afterward.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from typing import Callable

from .cancellation import CancellationToken, check_cancelled
from .config import AppConfig
from .exceptions import ProcessingCancelledError
from .models import PackageIdentity, RunResult

_FOLDER_NAME_PATTERN = re.compile(
    r"^(?P<last>[^,]+?)\s*,\s*(?P<first>[^,]+?)(?:\s*,\s*(?P<loan_number>[^,]+?))?\s*$"
)


def identity_from_folder_name(folder_name: str) -> PackageIdentity:
    """Best-effort borrower identity from a loan subfolder's own name.

    Only this app's own "Last, First" or "Last, First, LoanNumber"
    convention (the same shape `naming.main_folder_name` itself
    produces) is split into separate fields -- never guessed from any
    other shape. A folder name with no comma at all (or any other
    unrecognized shape) becomes the last name alone, first name and
    loan number left blank for the user to fill in/correct afterward.
    Always safe and reversible: an imperfectly-parsed name only affects
    the OUTPUT folder/file names, never which documents get processed.
    """

    match = _FOLDER_NAME_PATTERN.match(folder_name.strip())
    if not match:
        return PackageIdentity(last_name=folder_name.strip())
    return PackageIdentity(
        last_name=match.group("last").strip(),
        first_name=match.group("first").strip(),
        loan_number=(match.group("loan_number") or "").strip(),
    )


def discover_loan_folders(parent_folder: Path) -> list[Path]:
    """Every immediate subdirectory of `parent_folder`, in a stable,
    deterministic (case-insensitive alphabetical) order. Never recurses
    further, and never treats a file directly inside `parent_folder`
    itself as a loan -- only a subfolder counts as one loan.
    """

    return sorted(
        (p for p in parent_folder.iterdir() if p.is_dir()),
        key=lambda p: p.name.casefold(),
    )


@dataclasses.dataclass
class BatchLoanResult:
    loan_folder: Path
    identity: PackageIdentity
    success: bool
    run: RunResult | None
    error_message: str | None


@dataclasses.dataclass
class BatchResult:
    parent_folder: Path
    loan_results: list[BatchLoanResult]

    @property
    def succeeded(self) -> list[BatchLoanResult]:
        return [r for r in self.loan_results if r.success]

    @property
    def failed(self) -> list[BatchLoanResult]:
        return [r for r in self.loan_results if not r.success]


def build_batch(
    parent_folder: Path,
    output_dir: Path | None,
    config: AppConfig,
    allow_large_input: bool = False,
    progress_callback: Callable[[Path, int, int], None] | None = None,
    cancellation_token: CancellationToken | None = None,
) -> BatchResult:
    """Builds one independent OG+Final package per immediate subfolder
    of `parent_folder`. See this module's docstring for the identity-
    parsing and failure-isolation rules.

    `progress_callback`, when given, is called as
    `progress_callback(loan_folder, current, total)` once per loan as
    it starts (not per-document progress within that loan).

    `output_dir`, when given, is the PARENT of each loan's own output
    folder (named after that loan's own subfolder, via the same
    `build_package`/`naming.main_folder_name` convention as a single
    build) -- when omitted, each loan's output lands next to its own
    input folder, exactly like a single `build_package` call with no
    explicit `output_dir` would.
    """

    from .cli import build_package  # local import: avoids a cli.py <-> batch.py cycle

    loan_folders = discover_loan_folders(parent_folder)
    results: list[BatchLoanResult] = []

    for index, loan_folder in enumerate(loan_folders, start=1):
        check_cancelled(cancellation_token)
        if progress_callback is not None:
            try:
                progress_callback(loan_folder, index, len(loan_folders))
            except Exception:
                pass  # a misbehaving callback must never take down the batch

        identity = identity_from_folder_name(loan_folder.name)
        loan_output_dir = (output_dir / loan_folder.name) if output_dir is not None else None

        try:
            run = build_package(
                input_path=loan_folder,
                output_dir=loan_output_dir,
                config=config,
                allow_large_input=allow_large_input,
                progress=False,
                identity=identity,
                cancellation_token=cancellation_token,
            )
        except ProcessingCancelledError:
            # A real cancellation request aborts the WHOLE batch, not
            # just the loan in flight -- never caught/isolated below.
            raise
        except Exception as exc:
            # Any other failure -- a known LenderPackageBuilderError
            # subtype (bad input, output already exists, insufficient
            # disk space, ...) or any genuinely unexpected bug -- is
            # isolated to this one loan, exactly like a single
            # document's failure never crashes a whole build.
            results.append(
                BatchLoanResult(
                    loan_folder=loan_folder, identity=identity, success=False, run=None, error_message=str(exc)
                )
            )
            continue

        results.append(
            BatchLoanResult(
                loan_folder=loan_folder, identity=identity, success=run.success, run=run, error_message=None
            )
        )

    return BatchResult(parent_folder=parent_folder, loan_results=results)


def write_batch_summary(result: BatchResult, path: Path) -> None:
    """`Batch Summary.txt` -- a human-readable record of every loan
    processed in this batch: which succeeded, which failed and why,
    and where each one's output landed.
    """

    lines: list[str] = []
    lines.append("BATCH PROCESSING SUMMARY")
    lines.append("=" * 70)
    lines.append(f"Parent folder: {result.parent_folder}")
    lines.append(f"Loans found: {len(result.loan_results)}")
    lines.append(f"Succeeded: {len(result.succeeded)}")
    lines.append(f"Failed: {len(result.failed)}")
    lines.append("")

    for loan_result in result.loan_results:
        status = "SUCCESS" if loan_result.success else "FAILED"
        lines.append("-" * 70)
        lines.append(f"[{status}] {loan_result.loan_folder.name}")
        identity = loan_result.identity
        lines.append(
            f"    Parsed identity: last={identity.last_name!r} first={identity.first_name!r} "
            f"loan_number={identity.loan_number!r}"
        )
        if loan_result.run is not None:
            lines.append(f"    Output: {loan_result.run.output_path}")
        if loan_result.error_message:
            lines.append(f"    Error: {loan_result.error_message}")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
