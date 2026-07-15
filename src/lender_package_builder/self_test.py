"""Packaged self-test: proves the core engine works end-to-end inside
the running process (source checkout or frozen .exe) without any
external test runner.

This is production code, not a test-suite helper -- `pytest` is never
imported here and this module has no dependency on anything under
`tests/`. It is exposed as `--self-test` on the CLI and GUI entry
points so a portable build can prove itself functional on a machine
that has no Python installed at all.

The synthetic package uses only pure-Python converters (reportlab for
the PDF, Pillow for the image, the built-in text backend) -- no
LibreOffice or Microsoft Office dependency, so the result is
meaningful on any machine, including one with neither installed.
"""

from __future__ import annotations

import dataclasses
import tempfile
import time
from pathlib import Path

from . import __version__, runtime_paths
from .cli import build_package
from .config import AppConfig, load_config_safe
from .exceptions import LenderPackageBuilderError
from .models import ProcessingStatus


@dataclasses.dataclass
class SelfTestCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclasses.dataclass
class SelfTestResult:
    checks: list[SelfTestCheck]
    elapsed_seconds: float

    @property
    def success(self) -> bool:
        return all(c.passed for c in self.checks)

    def render_report(self) -> str:
        lines = [
            "Lender Package Builder -- Self-Test",
            f"Version: {__version__}",
            "=" * 60,
        ]
        for check in self.checks:
            status = "PASS" if check.passed else "FAIL"
            lines.append(f"[{status}] {check.name}")
            if check.detail:
                lines.append(f"       {check.detail}")
        lines.append("-" * 60)
        passed = sum(1 for c in self.checks if c.passed)
        lines.append(f"{passed}/{len(self.checks)} checks passed in {self.elapsed_seconds:.2f}s")
        lines.append("OVERALL RESULT: " + ("PASS" if self.success else "FAIL"))
        return "\n".join(lines)


def run_self_test() -> SelfTestResult:
    start = time.perf_counter()
    checks: list[SelfTestCheck] = []

    checks.append(_check_runtime_paths())
    checks.append(_check_config_defaults())
    checks.append(_check_log_directory_writable())
    checks.extend(_check_engine_pipeline())

    return SelfTestResult(checks=checks, elapsed_seconds=time.perf_counter() - start)


def _check_runtime_paths() -> SelfTestCheck:
    try:
        root = runtime_paths.app_root()
        assets = runtime_paths.bundled_assets_root()
        if not root.exists():
            return SelfTestCheck("Runtime paths resolve", False, f"App root does not exist: {root}")
        if not assets.exists():
            return SelfTestCheck("Runtime paths resolve", False, f"Assets root does not exist: {assets}")
        return SelfTestCheck(
            "Runtime paths resolve",
            True,
            f"app_root={root} frozen={runtime_paths.is_frozen()}",
        )
    except Exception as exc:  # a self-test check must never itself crash the run
        return SelfTestCheck("Runtime paths resolve", False, f"Unexpected error: {exc}")


def _check_config_defaults() -> SelfTestCheck:
    try:
        result = load_config_safe(runtime_paths.external_config_path())
        if result.used_defaults_due_to_error:
            return SelfTestCheck(
                "Configuration loads",
                False,
                f"config.toml present but invalid: {result.warning}",
            )
        return SelfTestCheck(
            "Configuration loads",
            True,
            f"max_pages_per_part={result.config.max_pages_per_part} "
            f"max_size_mb_per_part={result.config.max_size_mb_per_part}",
        )
    except Exception as exc:
        return SelfTestCheck("Configuration loads", False, f"Unexpected error: {exc}")


def _check_log_directory_writable() -> SelfTestCheck:
    try:
        log_dir = runtime_paths.default_log_root()
        log_dir.mkdir(parents=True, exist_ok=True)
        probe = log_dir / ".self_test_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return SelfTestCheck("Log directory is writable", True, str(log_dir))
    except Exception as exc:
        return SelfTestCheck("Log directory is writable", False, f"{log_dir}: {exc}")


def _make_self_test_pdf() -> bytes:
    import io

    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    for page_num in (1, 2):
        c.setFont("Helvetica", 12)
        c.drawString(72, 700, f"Self-test synthetic document, page {page_num} of 2.")
        c.showPage()
    c.save()
    return buf.getvalue()


def _build_self_test_input(in_dir: Path) -> None:
    """A small synthetic package covering every category the packaged
    self-test must exercise: a PDF, a text file, an image, an exact
    duplicate, a nonidentical-but-similar pair, and an unsupported file
    that must become a placeholder rather than crash the run.
    """

    from PIL import Image

    pdf_bytes = _make_self_test_pdf()
    (in_dir / "Loan_Disclosure.pdf").write_bytes(pdf_bytes)
    # An exact byte-for-byte duplicate under a different filename.
    (in_dir / "Loan_Disclosure_Copy.pdf").write_bytes(pdf_bytes)

    (in_dir / "Borrower_Statement.txt").write_text(
        "Lender Package Builder self-test document.\nLine two.\n", encoding="utf-8"
    )

    # Similar but NOT identical -- both must remain in Final; neither
    # is a duplicate of the other or of anything else.
    (in_dir / "Property_Notes_Draft.txt").write_text(
        "Property condition notes -- draft.\nRoof: good condition.\n", encoding="utf-8"
    )
    (in_dir / "Property_Notes_Revised.txt").write_text(
        "Property condition notes -- revised.\nRoof: good condition, minor repair noted.\n",
        encoding="utf-8",
    )

    Image.new("RGB", (40, 30), color=(18, 131, 158)).save(in_dir / "Property_Photo.png")

    # An unsupported file type -- must become a placeholder, not crash
    # the run or silently disappear.
    (in_dir / "Legacy_Notes.xyz").write_bytes(b"Unsupported file type content for the self-test.")


def _check_engine_pipeline() -> list[SelfTestCheck]:
    """Run a real, small build through the exact same `build_package()`
    used by the CLI and GUI, in an isolated temp directory that is
    always cleaned up on success. Proves extraction, whole-file
    SHA-256 exact-duplicate detection, PDF/image/text conversion,
    placeholder handling, merging, and integrity validation all work
    together in this process.
    """

    with tempfile.TemporaryDirectory(prefix="lpb_selftest_in_") as in_dir_str:
        in_dir = Path(in_dir_str) / "Self_Test_Input"
        in_dir.mkdir()
        _build_self_test_input(in_dir)

        with tempfile.TemporaryDirectory(prefix="lpb_selftest_out_") as out_root_str:
            output_dir = Path(out_root_str) / "Self_Test_Output"
            try:
                run = build_package(
                    input_path=in_dir,
                    output_dir=output_dir,
                    config=AppConfig(),
                    allow_large_input=False,
                    keep_temp=False,
                    verbose=False,
                    progress=False,
                )
            except LenderPackageBuilderError as exc:
                return [SelfTestCheck("Core engine pipeline runs", False, str(exc))]
            except Exception as exc:
                return [SelfTestCheck("Core engine pipeline runs", False, f"Unexpected error: {exc}")]

            return _evaluate_self_test_run(run, output_dir)


def _evaluate_self_test_run(run, output_dir: Path) -> list[SelfTestCheck]:
    checks: list[SelfTestCheck] = []

    checks.append(
        SelfTestCheck(
            "Core engine pipeline runs",
            run.success,
            f"{len(run.occurrences)} document(s), {len(run.og_parts)} OG part(s), "
            f"{len(run.final_parts)} Final part(s)",
        )
    )

    dup_count = sum(len(g.duplicate_document_ids) for g in run.duplicate_groups)
    checks.append(
        SelfTestCheck(
            "Exact-duplicate detection works",
            dup_count == 1,
            f"expected 1 duplicate occurrence, found {dup_count}",
        )
    )

    non_ignored = [o for o in run.occurrences if not o.is_ignored_artifact]

    placeholders = [o for o in non_ignored if o.status == ProcessingStatus.UNCONVERTED_PLACEHOLDER]
    checks.append(
        SelfTestCheck(
            "Unsupported file becomes a placeholder",
            len(placeholders) == 1,
            f"expected 1 placeholder, found {len(placeholders)}",
        )
    )

    similar_pair_names = {"Property_Notes_Draft.txt", "Property_Notes_Revised.txt"}
    similar_pair_in_final = sum(
        1 for o in non_ignored if o.original_relative_path in similar_pair_names and o.included_in_final
    )
    checks.append(
        SelfTestCheck(
            "Nonidentical similar documents both remain",
            similar_pair_in_final == 2,
            f"expected both similar-but-different documents in Final, found {similar_pair_in_final}",
        )
    )

    pdfs_ok, pdfs_detail = _output_pdfs_open(run)
    checks.append(SelfTestCheck("Output PDFs exist and open", pdfs_ok, pdfs_detail))

    reports_ok, reports_detail = _reports_exist(output_dir)
    checks.append(SelfTestCheck("Reports were written", reports_ok, reports_detail))

    failed_integrity = [c.name for c in run.integrity_checks if not c.passed]
    checks.append(
        SelfTestCheck(
            "Integrity checks pass",
            not failed_integrity,
            "all passed" if not failed_integrity else f"failed: {', '.join(failed_integrity)}",
        )
    )

    return checks


def _output_pdfs_open(run) -> tuple[bool, str]:
    from pypdf import PdfReader

    all_parts = list(run.og_parts) + list(run.final_parts)
    if not all_parts:
        return False, "no output parts were produced"

    for part in all_parts:
        if not part.file_path.exists():
            return False, f"missing output file: {part.file_path}"
        try:
            reader = PdfReader(str(part.file_path))
            if len(reader.pages) < 1:
                return False, f"output PDF has no pages: {part.file_path}"
        except Exception as exc:
            return False, f"could not open {part.file_path}: {exc}"

    return True, f"{len(all_parts)} output PDF part(s) opened successfully"


def _reports_exist(output_dir: Path) -> tuple[bool, str]:
    reports_dir = output_dir / "Reports"
    expected = ["Duplicate_Removal_Log.txt", "Processing_Report.txt", "Processing_Manifest.json"]
    missing = [name for name in expected if not (reports_dir / name).exists()]
    if missing:
        return False, f"missing report file(s): {', '.join(missing)}"
    return True, f"all {len(expected)} report files present in {reports_dir}"
