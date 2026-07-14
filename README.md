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
| `--page-limit N` | Max pages per output PDF part (default from `config.toml`, 200). |
| `--size-limit-mb N` | Max megabytes per output PDF part (default from `config.toml`, 75). |
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
page_limit = 200
size_limit_mb = 75

[safety]
large_input_warning_mb = 2000
max_expanded_size_mb = 8000
max_archive_entries = 200000
required_free_space_multiplier = 3.0

[conversion]
office_backend_order = ["libreoffice", "office_com", "fallback"]
```

Command-line flags override these per run without editing the file.

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
every one of the 18 required integrity checks with an explicit
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
├── validation.py                18 required integrity checks
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
