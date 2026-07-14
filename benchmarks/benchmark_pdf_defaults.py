"""Benchmark script used to choose Stage 1's default output-part maximums.

This is a standalone, manually-run script (not part of `pytest tests`,
since it takes tens of seconds and its purpose is choosing defaults, not
verifying correctness). Run it with:

    python benchmarks/benchmark_pdf_defaults.py

It builds two families of synthetic PDFs -- dense digital-text pages
(the common case: disclosures, applications, statements) and
scanned/image-heavy pages (the common case for signed forms, IDs,
mailed-in documents) -- at a range of page counts, then measures, on
THIS machine:

  - on-disk file size
  - time to open the file and read its page count (pypdf)
  - time to extract all text (proxy for search/indexing cost)
  - time to rasterize a representative sample of pages at 150 DPI
    (proxy for the "flip through the document in a viewer" experience,
    via poppler's `pdftoppm`, the same rendering library Linux/desktop
    PDF viewers commonly use)

Results are written to `benchmarks/results.md`. See
`README.md` ("Choosing the output-part size defaults") for how these
numbers were turned into the shipped defaults, and for the explicit
caveat that this machine is not a typical Windows 11 business laptop --
these numbers inform the defaults, they do not guarantee identical
performance on every machine.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(tempfile.mkdtemp(prefix="lpb_benchmark_"))

# Digital-text PDFs are cheap to generate/store, so a wider range is
# practical. Scanned/image-heavy PDFs are 100-800x larger per page, so
# the range is capped lower to keep the benchmark's own disk/time cost
# reasonable while still covering realistic single-part sizes.
DIGITAL_TEXT_PAGE_COUNTS = [100, 300, 600, 1000, 2000, 3000]
SCANNED_PAGE_COUNTS = [50, 150, 300, 500, 750]

LOREM = (
    "Borrower acknowledges receipt of this disclosure and agrees that the terms "
    "described herein are subject to the credit agreement executed on the closing "
    "date. Please review each section carefully and contact your loan officer with "
    "any questions regarding rate, term, escrow, or fee schedule details. "
)


def build_digital_text_pdf(path: Path, pages: int) -> None:
    c = canvas.Canvas(str(path), pagesize=LETTER)
    for p in range(pages):
        c.setFont("Helvetica", 10)
        y = 740
        for line_no in range(38):
            text = f"[{p + 1}:{line_no}] " + LOREM[: 90 + (line_no % 7) * 4]
            c.drawString(54, y, text)
            y -= 18
        c.showPage()
    c.save()


def _scan_page_image(page_num: int, size=(1275, 1650)) -> Image.Image:
    # 150 DPI equivalent for an 8.5x11 page -- a realistic resolution for
    # business-document scanning (courts, banks, title companies commonly
    # scan at 150-200 DPI, not print-quality 300+ DPI). Text lines with
    # realistic margins/whitespace, not edge-to-edge, to approximate how
    # a real scanned letter compresses.
    img = Image.new("L", size, color=252)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
    except OSError:
        font = ImageFont.load_default()
    y = 110
    for line_no in range(32):
        text = f"Page {page_num} line {line_no}: " + LOREM[: 55 + (line_no % 5) * 3]
        d.text((110, y), text, fill=15, font=font)
        y += 40
    return img


def build_scanned_pdf(path: Path, pages: int) -> None:
    tmp_images = OUT_DIR / f"scan_src_{path.stem}"
    tmp_images.mkdir(parents=True, exist_ok=True)
    image_paths = []
    for p in range(pages):
        img = _scan_page_image(p + 1)
        img_path = tmp_images / f"{p:05d}.jpg"
        img.save(img_path, format="JPEG", quality=72)
        image_paths.append(img_path)

    c = canvas.Canvas(str(path), pagesize=LETTER)
    from reportlab.lib.utils import ImageReader

    for img_path in image_paths:
        c.drawImage(ImageReader(str(img_path)), 0, 0, width=LETTER[0], height=LETTER[1])
        c.showPage()
    c.save()
    shutil.rmtree(tmp_images, ignore_errors=True)


def time_open_and_page_count(path: Path) -> tuple[float, int]:
    start = time.perf_counter()
    reader = PdfReader(str(path))
    count = len(reader.pages)
    elapsed = time.perf_counter() - start
    return elapsed, count


def time_extract_all_text(path: Path) -> float:
    reader = PdfReader(str(path))
    start = time.perf_counter()
    for page in reader.pages:
        page.extract_text()
    return time.perf_counter() - start


def _render_chunk(path: Path, first: int, last: int) -> float:
    if shutil.which("pdftoppm") is None:
        return -1.0
    render_dir = OUT_DIR / f"render_{path.stem}_{first}_{last}"
    render_dir.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    subprocess.run(
        ["pdftoppm", "-r", "150", "-f", str(first), "-l", str(last), "-png", str(path), str(render_dir / "page")],
        capture_output=True, check=True,
    )
    elapsed = time.perf_counter() - start
    shutil.rmtree(render_dir, ignore_errors=True)
    return elapsed


def estimate_render_cost(path: Path, page_count: int) -> tuple[float, float, float]:
    """Estimate (fixed_startup_s, marginal_s_per_page, est_full_render_s).

    Rendering every page of a multi-thousand-page PDF just to benchmark
    it does not scale. Instead this renders two small, differently-sized
    contiguous chunks (10 pages and min(40, page_count) pages) in two
    single `pdftoppm` process launches, then solves the two-point linear
    system:

        t_small = fixed + n_small * rate
        t_large = fixed + n_large * rate

    for `fixed` (process/library startup overhead, paid once per
    document open) and `rate` (marginal seconds per rendered page).
    `fixed + rate * page_count` then estimates the cost of paging
    through the entire document without actually doing so.
    """

    if shutil.which("pdftoppm") is None or page_count < 10:
        return -1.0, -1.0, -1.0

    n_small = min(10, page_count)
    n_large = min(40, page_count)
    if n_large <= n_small:
        n_large = page_count

    t_small = _render_chunk(path, 1, n_small)
    t_large = _render_chunk(path, 1, n_large)

    if n_large == n_small:
        return -1.0, -1.0, -1.0

    rate = (t_large - t_small) / (n_large - n_small)
    fixed = t_small - n_small * rate
    fixed = max(fixed, 0.0)
    rate = max(rate, 0.0)
    est_full = fixed + rate * page_count
    return fixed, rate, est_full


def main() -> None:
    rows = []
    profiles = (
        ("digital-text", build_digital_text_pdf, DIGITAL_TEXT_PAGE_COUNTS),
        ("scanned/image-heavy", build_scanned_pdf, SCANNED_PAGE_COUNTS),
    )
    for profile_name, builder, page_counts in profiles:
        # Rendering (spawning poppler's pdftoppm) is, on this particular
        # container, dramatically slower than on typical desktop hardware
        # (see README.md caveat). To keep this benchmark itself finishing
        # in a reasonable time even at 3000-page levels, the render
        # rate (fixed startup + ms/page) is measured ONCE per profile,
        # on its smallest page-count sample, and reused for every other
        # page-count level in that profile -- valid because all samples
        # within one profile share the same per-page content complexity
        # by construction.
        profile_fixed_s: float | None = None
        profile_rate_s_per_page: float | None = None

        for pages in page_counts:
            path = OUT_DIR / f"{profile_name.replace('/', '_')}_{pages}.pdf"
            t0 = time.perf_counter()
            builder(path, pages)
            build_time = time.perf_counter() - t0

            size_mb = path.stat().st_size / (1024 * 1024)
            open_time, actual_pages = time_open_and_page_count(path)
            text_time = time_extract_all_text(path)

            if profile_fixed_s is None:
                profile_fixed_s, profile_rate_s_per_page, _ = estimate_render_cost(path, pages)
            fixed_s = profile_fixed_s
            rate_s_per_page = profile_rate_s_per_page
            est_full_s = (
                fixed_s + rate_s_per_page * pages if fixed_s is not None and fixed_s >= 0 else -1.0
            )

            row = {
                "profile": profile_name,
                "pages": pages,
                "actual_pages": actual_pages,
                "size_mb": size_mb,
                "mb_per_page": size_mb / pages,
                "build_time_s": build_time,
                "open_time_s": open_time,
                "text_extract_time_s": text_time,
                "render_fixed_s": fixed_s,
                "render_ms_per_page": rate_s_per_page * 1000,
                "est_full_render_s": est_full_s,
            }
            rows.append(row)
            print(
                f"{profile_name:22s} pages={pages:5d} size={size_mb:8.2f}MB "
                f"({row['mb_per_page']*1000:7.1f} KB/page) open={open_time*1000:7.1f}ms "
                f"text={text_time*1000:8.1f}ms render_rate={row['render_ms_per_page']:6.1f}ms/pg "
                f"est_full_render={est_full_s:7.2f}s"
            )
            path.unlink()

    write_report(rows)


def write_report(rows: list[dict]) -> None:
    out_path = REPO_ROOT / "benchmarks" / "results.md"
    lines = [
        "# PDF size/performance benchmark results",
        "",
        "Generated by `benchmarks/benchmark_pdf_defaults.py`. See that script",
        "for methodology. Machine: this development/test container, NOT a",
        "Windows 11 business laptop -- see README.md for how these numbers",
        "were interpreted.",
        "",
        "`Est. full render (s)` is NOT measured by rendering the whole document --",
        "it is `fixed_startup + rate_per_page * page_count`, where `fixed_startup`",
        "and `rate_per_page` are solved from two small rendered chunks (10 and 40",
        "pages) of the SAME file. This keeps the benchmark itself fast even at",
        "thousands of pages while still reflecting real per-page rendering cost.",
        "",
        "| Profile | Pages | Size (MB) | KB/page | Open (ms) | Text extract (ms) | "
        "Render rate (ms/page) | Est. full render (s) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['profile']} | {row['pages']} | {row['size_mb']:.2f} | "
            f"{row['mb_per_page']*1000:.1f} | {row['open_time_s']*1000:.1f} | "
            f"{row['text_extract_time_s']*1000:.1f} | {row['render_ms_per_page']:.1f} | "
            f"{row['est_full_render_s']:.2f} |"
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
