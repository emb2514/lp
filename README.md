# Lender Package Builder (Stage 1)

A local, offline tool that turns a lender ZIP, nested ZIP, folder, or
loose document collection into two organized PDF packages:

- **OG** -- every source document, in original order, nothing removed.
- **Final** -- the same, minus later occurrences of exact byte-for-byte
  duplicate source files.

**The core safety rule: one source file equals one indivisible
document.** Nothing in this application ever deletes, merges, or
compares content at the page level. See `NON_NEGOTIABLE_SAFETY_RULE`
below.

Everything runs on your own computer. No file, filename, hash, or
report is ever uploaded anywhere. There is no telemetry.

This is **Stage 1**: a command-line engine only. There is no graphical
window yet (that is Stage 2) and no standalone `.exe` installer yet
(Stage 3). See "Roadmap" below.

---

## Quick start (Windows, non-technical)

See **FIRST_TEST_INSTRUCTIONS.md** for a full plain-English walkthrough.
The short version:

1. Double-click `SETUP_AND_TEST.bat` and wait for it to finish.
2. Drag a ZIP file onto `RUN_STAGE1.bat`.
3. Open the new output folder created next to your ZIP.

---

## The non-negotiable safety rule

A source file may be one page or a thousand pages. Regardless of its
content, the entire source file always stays together as one document.

This application never:

- deletes an individual page because it resembles another page,
- performs page-level deduplication,
- splits one source document across two output files,
- guesses internal document boundaries inside a PDF,
- separates forms bundled inside one source PDF, or
- treats two files as duplicates because their titles or visible text
  look similar.

Two files are only ever treated as duplicates when their **original
SHA-256** (computed on the untouched source bytes, before any
conversion) is identical. Filename, extracted text, OCR, page hashes,
visual similarity, converted-PDF hashes, and metadata are never used to
decide a duplicate.

---

## Requirements

- Windows 11 (primary target), or any OS with Python for development.
- Python 3.11, 3.12, or 3.13 (64-bit). Python 3.13 is fully supported
  and preferred when available -- it is not hardcoded to 3.11.
- No administrator rights required. Nothing is installed outside this
  project folder's `.venv`.
- Optional, for higher-fidelity DOCX/XLS(X)/DOC conversion: a local
  install of **LibreOffice** (free) or **Microsoft Office**. Without
  either, DOCX/XLSX still convert via a built-in fallback renderer
  (plain text/tables only, clearly labeled as such in the report);
  legacy `.doc`/`.xls` without LibreOffice or Office become placeholders
  (see "Known Stage 1 Limitations").

## Installation

### Windows (recommended path)

Double-click `SETUP_AND_TEST.bat`. It finds a supported Python,
creates `.venv` in this folder, installs dependencies into it, and runs
the automated test suite.

### Manual / developer setup (any OS)

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
pytest tests -v
```

## Command-line usage

```
python -m lender_package_builder build "<input_path>" [options]
```

Options:

| Flag | Meaning |
|---|---|
| `--output PATH` | Explicit output folder (default: a new timestamped folder next to the input). |
| `--max-pages-per-part N` | Maximum pages allowed in one output PDF part (default from `config.toml`; see "Choosing the output-part size defaults" below). This is a ceiling, not a target -- see "Output splitting is a maximum, not a target" below. |
| `--max-size-mb-per-part N` | Maximum megabytes allowed in one output PDF part (default from `config.toml`). Also a ceiling, not a target. |
| `--allow-large-input` | Bypass ZIP-bomb-style safety thresholds for a known, intentional large package. |
| `--keep-temp` | Do not delete the temporary working folder after a successful run (useful for diagnostics). |
| `--verbose` | Print debug-level logging to the console as well as the log file. |
| `--config PATH` | Use a specific `config.toml` instead of the default. |
| `--quiet` | Suppress the live per-document progress lines (still prints the final summary). |

The exit code is `0` only when the build completed **and** every
required integrity check passed.

## Configuration

Defaults live in `config.toml` at the project root:

```toml
[splitting]
max_pages_per_part = 750
max_size_mb_per_part = 100

[safety]
large_input_warning_mb = 2000
max_expanded_size_mb = 8000
max_archive_entries = 200000
required_free_space_multiplier = 3.0

[conversion]
office_backend_order = ["libreoffice", "office_com", "fallback"]
```

Command-line flags (`--max-pages-per-part`, `--max-size-mb-per-part`, etc.)
override these per run without editing the file. Editing `config.toml`
changes the default for every future run, with no source code changes
required.

### Output splitting is a maximum, not a target

`max_pages_per_part` and `max_size_mb_per_part` are **ceilings**, not
sizes the tool tries to reach. Complete source documents are added to
the current output part, in original order, until adding the *next
complete* document would exceed either maximum. At that point the
current part is closed -- however far below the maximum it happens to
be -- and a new part is started with that document. Parts are never
padded, and documents are never reordered to fill unused space.

Example, with a 400-page maximum:

| Document | Pages |
|---|---|
| A | 125 |
| B | 98 |
| C | 162 |
| D | 41 |

Required result: **Part 1** = A + B + C (385 pages, left below the
400-page maximum on purpose). **Part 2** = D (41 pages). It is
forbidden to take 15 pages out of D to pad Part 1 to exactly 400 -- no
source document is ever split, for any reason.

A single source document that, on its own, exceeds a maximum is kept
completely intact in its own oversized output part. This is reported,
never treated as a failure, and never split.

A package's *total* page count is never treated as an output-part
limit -- a package with 3,000+ pages across many documents simply
produces as many parts as it needs.

### Choosing the output-part size defaults

The shipped defaults (750 pages / 100 MB per part) come from
`benchmarks/benchmark_pdf_defaults.py`, a script that generates two
families of synthetic PDFs -- dense **digital-text** pages (the common
case for disclosures, applications, statements) and **scanned/
image-heavy** pages (the common case for signed forms, IDs, and
mailed-in documents) -- at page counts from 50 up to 3,000, and
measures, on this development machine:

- on-disk file size and KB/page,
- time to open the file and read its page count (`pypdf`),
- time to extract all text (a proxy for local search/indexing cost),
- an estimated cost to page through the whole document, derived from
  rendering two small sample chunks with poppler's `pdftoppm` (the same
  rasterizer used by many Linux/desktop PDF viewers) and solving for a
  fixed per-open cost plus a marginal per-page cost -- this keeps the
  benchmark itself fast even at thousands of pages while still
  reflecting real per-page rendering cost.

Full results are in `benchmarks/results.md`, regenerated by re-running
the script. Key observations from this machine's results:

- Digital-text pages in this benchmark are very cheap (well under 1
  KB/page for dense paragraph text), so `max_size_mb_per_part` is
  rarely the binding constraint for pure-text packages -- page count
  dominates, and 750 pages keeps a part's *rendering* cost in the tens
  of seconds rather than minutes, while still avoiding an unmanageable
  number of parts for a large disclosure package.
- Scanned/image-heavy pages in this benchmark run roughly 300+ KB/page
  at a realistic 150 DPI business-scan resolution, so file size becomes
  the binding constraint well before 750 pages -- a 100 MB ceiling
  typically closes a scanned-heavy part in the low hundreds of pages,
  which keeps individual part files comfortably below common email/
  portal attachment limits (many lender and title-company portals cap
  attachments around 25-100 MB) and away from sizes that make
  Windows Explorer, antivirus scanning, or cloud-sync (OneDrive/Teams)
  noticeably sluggish on typical hardware.
- 100 MB was chosen over a much larger ceiling because very large
  single PDFs (many hundreds of MB) visibly slow down opening, page
  navigation, and full-text search in common viewers, and are more
  likely to be rejected outright by upload portals and email systems.

**Important caveats, stated plainly and not as a guarantee:**

- This benchmark ran inside a shared, sandboxed development container,
  not a physical Windows 11 business laptop -- the *absolute* millisecond
  numbers in `benchmarks/results.md` are almost certainly slower than a
  real desktop's dedicated CPU/GPU rendering path. They are used here
  for *relative* comparison (digital-text vs. scanned, cost scaling with
  page count) and rough magnitude, not as a precise prediction of your
  computer's performance.
- "Smooth" depends on your hardware, your PDF viewer, and what else is
  running -- these numbers are a reasoned starting point, not a
  universal promise.
- Both maximums are trivially changeable per run (`--max-pages-per-part`,
  `--max-size-mb-per-part`) or permanently (`config.toml`) with no code
  changes, specifically so you can tune them for your own machine and
  document mix.

## Output layout

```
<Input_Name>_Lender_Package_Output_<timestamp>/
├── OG/            Full_Lender_Package_OG_Files_Part_001.pdf, ...
├── Final/         Full_Lender_Package_Final_Part_001.pdf, ...
├── Reports/       Processing_Report.txt, Duplicate_Removal_Log.txt, Processing_Manifest.json
├── Unconverted_Files/   Original copies of anything that could not be converted
└── Logs/          run.log
```

`Processing_Report.txt` is the main human-readable summary, including
every one of the 22 integrity checks (18 required by the original spec, strengthened with 4 additional independent page-count re-verification checks) with an explicit
PASS/FAIL. The CLI never reports overall success if any check fails.

## Project structure

```
src/lender_package_builder/
├── cli.py            Argument parsing + top-level pipeline orchestration
├── config.py          config.toml loading
├── models.py           Core data classes (SourceOccurrence, OutputPart, ...)
├── inventory.py         Discovery, traversal order, natural sort
├── archives.py           ZIP safety: path sanitization, ignored-artifact detection, size estimation
├── hashing.py             Whole-file SHA-256
├── deduplication.py        Exact whole-file duplicate detection
├── conversion/               One converter module per format (pdf, images, text, html, office, email)
├── merging.py               Whole-document PDF merging into output parts
├── splitting.py               Whole-document output-splitting plan
├── validation.py                22 integrity checks (18 required + 4 strengthened re-verification checks)
├── reporting.py                  Plain-text + JSON report generation
├── workspace.py                   Temporary workspace management
└── exceptions.py                   Error types
```

## Testing

```
.venv\Scripts\python.exe -m pytest tests -v      (Windows)
.venv/bin/python -m pytest tests -v              (macOS/Linux)
```

38 automated tests cover all 22 scenarios required for Stage 1 (see
`tests/`), plus extra coverage for ignored system artifacts, non-
overwriting duplicate ZIP filenames, report reconciliation, the
pure-Python DOCX/XLSX fallback renderer, and (on machines with
LibreOffice installed) the real high-fidelity DOCX/XLSX/DOC/XLS
conversion path.

## Roadmap

- **Stage 1 (this delivery):** local processing engine, CLI, automated
  tests, setup scripts, conversion, deduplication, PDF merging/splitting,
  reports. Complete.
- **Stage 2 (not started):** a simple Windows drag-and-drop window.
- **Stage 3 (not started):** a portable Windows package needing no
  Python install, no admin rights, and no installer.

## Known Stage 1 limitations

See the "Known Stage 1 Limitations" section provided at the end of the
build for the full list (Windows/Office-automation testing status, MSG
fixture coverage, very large nested archives, etc). Nothing in that
list weakens the non-negotiable safety rule -- it only describes
conversion-fidelity and environment edge cases.
