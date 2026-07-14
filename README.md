# Lender Package Builder (Stage 1 + Stage 2)

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

**Stage 1** is the command-line processing engine. **Stage 2** adds a
polished PySide6 desktop window around that same engine -- no command
line required. There is no standalone, Python-free `.exe` package yet
(that is Stage 3). See "Roadmap" below.

---

## Quick start (Windows, non-technical)

**Desktop application (recommended):** see
**STAGE2_WINDOWS_TEST_INSTRUCTIONS.md** for a full plain-English
walkthrough. The short version:

1. Double-click `SETUP_AND_TEST.bat` and wait for it to finish.
2. Double-click `RUN_GUI.bat`.
3. Drag a ZIP, folder, or document onto the window and click
   **Build Lender Packages**.

**Command line:** see **FIRST_TEST_INSTRUCTIONS.md**. The short
version:

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

## Desktop application (Stage 2)

A native PySide6/Qt desktop window around the exact same engine --
`gui/main_window.py` calls `cli.build_package()` directly, on a
background `QThread`, and never re-implements any processing logic.

Launch it with:

```
python -m lender_package_builder.gui         (any OS with a display)
```

or, on Windows, double-click **`RUN_GUI.bat`**.

| State | Screenshot |
|---|---|
| Idle / drop | ![Idle / drop state](docs/screenshots/01_idle_drop_state.png) |
| Processing | ![Processing state](docs/screenshots/02_processing_state.png) |
| Completion | ![Completion state](docs/screenshots/03_completion_state.png) |

Screenshots were captured from this repository's own automated test
harness using synthetic data (see "Manual GUI verification performed"
below) -- not a real lender package.

Highlights:

- **Drag-and-drop or Browse File/Browse Folder** -- accepts exactly one
  ZIP, folder, or document at a time; dropping more than one shows a
  friendly message instead of silently picking one.
- **Advanced Settings** (collapsed by default) exposes the same
  `max_pages_per_part` / `max_size_mb_per_part` ceilings as the CLI,
  with the same "these are maximums, not targets, and no document is
  ever split" explanation baked into the UI text.
- **Structured progress**, via `lender_package_builder.progress`
  (`ProgressStage` / `ProgressEvent`) -- a new, additive, optional
  `progress_callback` parameter on `build_package()`. Existing callers
  that don't pass one see no behavior change at all.
- **Background worker** (`gui/worker.py`) -- the engine always runs on
  a `QThread`, never the UI thread; the window stays responsive and
  disables input controls while a job is running, and warns (rather
  than silently allowing) closing the window mid-job.
- **Success / warning / failure states** driven entirely by the real
  `RunResult` -- a run is only ever shown as successful when every
  integrity check actually passed, even if PDFs were produced.
- **Large-input confirmation** -- exceeding the configured hard safety
  limit requires an explicit "Process This Known Large Package" click
  before `allow_large_input=True` is ever passed to the engine.

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
├── progress.py           ProgressStage / ProgressEvent structured progress API
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
├── exceptions.py                   Error types
└── gui/                              Stage 2: PySide6 desktop application
    ├── app.py                          QApplication bootstrap
    ├── main_window.py                  Top-level window, state, wiring
    ├── worker.py                       Background QThread worker layer
    ├── theme.py                        Colors, fonts, stylesheet
    ├── state.py                        GUI-side data models (no Qt)
    ├── dialogs.py                      Large-input confirm, close-warning dialogs
    ├── os_actions.py                   Open-folder (QDesktopServices) actions
    ├── formatting.py                   Byte-size / elapsed-time display helpers
    ├── assets/app_icon.svg               Local application icon
    └── widgets/                          drop_zone, advanced_settings, progress_view, result_view
```

## Testing

```
.venv\Scripts\python.exe -m pytest tests -v      (Windows)
.venv/bin/python -m pytest tests -v              (macOS/Linux)
```

83 automated tests: 49 engine tests (`tests/*.py`) covering all 22
Stage 1 scenarios plus extra coverage (ignored system artifacts,
non-overwriting duplicate ZIP filenames, report reconciliation, the
pure-Python DOCX/XLSX fallback renderer, LibreOffice conversion when
available, the structured progress API, and the maximum-constraint
splitting behavior), and 34 GUI tests (`tests/gui/*.py`, using
`pytest-qt` with the Qt `offscreen` platform) covering all 20 Stage 2
scenarios: initial state, drag-and-drop and Browse fallbacks, the
multiple-items rejection message, Advanced Settings defaults/
validation, structured progress rendering, the real background
worker's threading and cleanup, success/warning/failure result views,
large-input confirmation, folder-opening actions, "Process Another
Package", close-while-processing, and a full synthetic package run
through the real GUI worker end to end.

**Environment note:** on the headless Linux container this project was
built and tested in, `QT_QPA_PLATFORM=offscreen` is required (no real
display); on real Windows the native Qt platform plugin is used
automatically instead. In that headless container, running the full
83-test suite in one process occasionally (roughly 1 run in 4-6)
segfaults strictly at Python/Qt interpreter *shutdown*, after every
test has already passed -- a known category of PySide6/Shiboken
fragility specific to the `offscreen` platform under heavy repeated
widget construction/destruction in one long-lived process, not a defect
in any individual test or in the application. Every individual test
passes reliably and repeatedly; no crash has ever occurred with
application code on the stack. This has not been observed running the
GUI normally (one window, one process lifetime) and is not expected on
real Windows with the native window system.

## Roadmap

- **Stage 1:** local processing engine, CLI, automated tests, setup
  scripts, conversion, deduplication, PDF merging/splitting, reports.
  Complete.
- **Stage 2 (this delivery):** PySide6 desktop window around the same
  engine, structured progress API, background worker, drag-and-drop,
  advanced settings, success/warning/failure states, GUI automated
  tests. Complete.
- **Stage 3 (not started):** a portable Windows package needing no
  Python install, no admin rights, and no installer.

## Known limitations

**Stage 1** -- see the "Known Stage 1 Limitations" summary from the
original build for the full list (Windows/Office-automation testing
status, MSG fixture coverage, very large nested archives, etc). Nothing
in that list weakens the non-negotiable safety rule -- it only
describes conversion-fidelity and environment edge cases.

**Stage 2 additions:**

- The GUI has been run and tested extensively on this Linux development
  machine (real widget behavior, drag-and-drop logic, the real
  background worker, a full synthetic end-to-end run) using Qt's
  `offscreen` platform and `Xvfb`-free screenshot capture -- it has
  **not** been run on a real Windows 11 desktop. Windows-specific
  concerns (native drag-and-drop from Explorer, DPI scaling on a real
  multi-monitor setup, SmartScreen prompts, `pythonw.exe` launch
  behavior) still need real-machine verification; see
  `STAGE2_WINDOWS_TEST_INSTRUCTIONS.md`.
- See "Testing" above for the headless-offscreen-platform shutdown-crash
  caveat in this development container.
- The large-input confirmation dialog only appears when the
  background size estimate has already completed by the time you click
  **Build Lender Packages**; if you click before it finishes (rare, on
  a very large input, with an unusually slow disk), the engine's own
  safety check still applies and safely stops with a clear error --
  nothing is silently bypassed, but the friendlier confirmation dialog
  is skipped in that edge case.
- No cancellation button exists, by design (see Stage 2 spec) -- closing
  the window is blocked with a warning while a job is running instead.
