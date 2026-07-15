# CHECKPOINT — RC2 Content-Aware Deduplication Upgrade

**Status as of this checkpoint: IMPLEMENTATION IN PROGRESS, substantial and fully tested.**
The user approved both flagged decision points from §7b (TEST 4 gets updated with a documented reason;
build BOTH the review dialog and the advanced-settings toggle) and said to implement. All 6 new
detection modules, full pipeline wiring, and validation.py generalization are done and committed. GUI
work, reporting expansion, the two new dedicated test files (test_validation.py/test_merging.py), the
Robert-package acceptance test, and Windows CI packaging validation have **not** started yet. This
checkpoint exists because the user needs to step away; work was paused at a safe, fully-tested boundary,
not mid-edit. `git status` shows only clean, coherent, already-verified changes (see §4).

**§5, §6, §7b below are unchanged and still the authoritative research/design reference — read them
before touching anything.** §1–§4 below replace the old (now-stale) planning-phase status entirely.

---

## 1. What is complete (all committed except the very latest local changes — see §4)

All of these are implemented, individually unit-tested, AND verified working together through a real
`build_package()` end-to-end run (not just isolated unit tests):

1. **`models.py`** — every new `SourceOccurrence` field from §7b's data model diff, `included_in_final`
   generalized with the `needs_review` guard, new dataclasses `ContentDuplicateGroup`/`DocumentFamily`/
   `OverlapFinding`, `RunResult` extended with `content_duplicate_groups`/`document_families`/
   `overlap_findings`/`content_dedup_notes`.
2. **`pdf_content.py`** (NEW) — per-page/per-document fingerprinting: normalized text, page geometry,
   AcroForm field extraction (page-scoped, not `PdfReader.get_fields()` — verified empirically),
   annotation extraction, signature-field detection, embedded-image extraction with a hand-rolled
   Pillow-only difference-hash (`_dhash`) AND a mean-RGB `average_color` signal, conservative blank-page
   classification, and `extract_structured_tokens` (dates/dollar-amounts/proper-noun name-hints).
3. **`pdf_render.py`** (NEW) — the only module importing `pypdfium2`; last-tier page rasterization +
   perceptual-hash comparison, LRU-cached, deliberately mockable.
4. **`content_dedup.py`** (NEW) — Levels 2/3/4 engine. One `compare_documents()`/`compare_page()` pair
   underlies all three levels. Hard-veto system (signature state, image-count, form fields, annotations,
   dates, dollar amounts, name-hints) checked BEFORE any fuzzy similarity scoring. Whole-document
   aggregation is WEAKEST-LINK, never average. Staged bucketing + oversized-bucket fallback.
5. **`pdf_portfolio.py`** (NEW) — Portfolio/embedded-file detection wired into
   `InventoryBuilder.build()` as a post-pass. `/Names/EmbeddedFiles` non-empty → extract attachments
   regardless of `/Collection`; `/Collection` present → `is_portfolio_container=True` (only then are the
   container's own pages excluded from Final). Verified against real pypdf-built fixtures, not assumed.
6. **`overlap_detection.py`** (NEW) — merged-document containment, reusing `content_dedup.compare_page`
   directly. Always excludes the standalone side, never the merged PDF. Per-container only, never
   chained across two different containers.
7. **`version_classification.py`** (NEW) — Level 5, purely descriptive, runs last, sets no
   exclusion-relevant field. Family relatedness uses a looser structural key than duplicate-candidate
   bucketing (deliberately excludes signature/form-field presence) plus explicit content-duplicate/
   overlap links, so unsigned+e-signed+wet-signed siblings correctly cluster into one family — verified
   against the task's own worked example.
8. **`config.py`/`config.toml`** — new `[deduplication] enable_content_aware_dedup` toggle (default
   `true`), following the exact existing per-key TOML parsing pattern. New `--disable-content-aware-dedup`
   CLI flag too.
9. **`cli.py`/`progress.py`/`gui/widgets/progress_view.py`** — full pipeline wiring. 4 new
   `ProgressStage` members (`FINGERPRINTING_CONTENT`, `DETECTING_CONTENT_DUPLICATES`,
   `ANALYZING_MERGED_PACKAGES`, `CLASSIFYING_VERSIONS`) inserted between Building OG and Building Final;
   all pipeline stage message prefixes renumbered `[N/10]`. New `_run_content_aware_analysis()` helper
   in `cli.py`, gated by `config.enable_content_aware_dedup` — when disabled, every new stage still
   emits one "skipped" progress event (stable event sequence either way) but does no work and mutates
   nothing, exactly RC1's original behavior.
10. **`validation.py`** — generalized every exact-hash-only formula/check to use `included_in_final`
    generically (works for ANY exclusion reason, not just `is_duplicate`). Added 4 new checks:
    `_check_final_contains_all_included` (replaces the old `_check_no_nonidentical_removed`),
    `_check_no_unexplained_removal` (every Final exclusion must have a non-empty, auditable reason),
    `_check_needs_review_never_excluded`, `_check_content_duplicate_retained_exists`,
    `_check_contained_in_document_retained_exists`. Total integrity checks: **26** (was 21).
11. **Dependencies/packaging** — `pypdfium2` added (Apache-2.0/BSD-3, self-contained wheel,
    `pyinstaller-hooks-contrib` already ships `hook-pypdfium2.py` so no manual binary bundling needed —
    verified by inspecting the installed hooks package directly). Deliberately did NOT add the
    `imagehash` package (would have pulled in numpy+scipy+PyWavelets, ~55MB, purely for a DCT/wavelet
    hash a plain Pillow-only difference-hash doesn't need) — this is a considered deviation from the
    literal "pypdfium2 + imagehash" phrasing the user approved; the approved INTENT (permissive-licensed,
    self-contained, staged/last-tier-only rendering) is fully honored. `pyproject.toml`,
    `requirements.txt`, `requirements-windows-lock.txt`, `LenderPackageBuilder.spec`,
    `packaging/collect_licenses.py`, `THIRD_PARTY_NOTICES.txt` all updated.
12. **TEST 4** (`test_identical_visible_content_different_source_bytes`) — updated per the user's
    approved decision: now asserts exactly one copy is excluded from Final via Level 2
    (`is_content_duplicate=True`, `duplicate_detection_method="normalized_pdf"`), with a comment
    explaining why the expected behavior changed from RC1.
13. **`tests/test_progress.py`** — `expected_order` updated for the 4 new stages; added a new test
    proving the stage sequence is stable even with content-aware dedup disabled via config.

### Four real safety bugs found via direct testing during this work, all fixed and regression-tested

These were NOT theoretical — each was caught by actually running synthetic fixtures through the real
engine, not just by reasoning about the design:

1. **Exact-match shortcut bypassed form-field/annotation differences.** `compare_page`'s fast path
   originally checked only `text_hash` + images; since AcroForm field VALUES and annotation contents
   never appear in extracted page text at all, two pages with identical visible text but different loan
   amounts were silently treated as an exact match, skipping the hard-veto system entirely. Fixed by
   requiring form-fields/annotations/signature-state to also agree before the shortcut fires.
2. **Render-tier escalation used text LENGTH as a proxy for text RELIABILITY.** A short-but-perfectly-
   extracted label ("Content A" vs "Content B") was wrongly escalated to the last-tier render comparison
   under the old 20-character threshold; that tier's coarse 8x8-downsampled perceptual hash literally
   cannot see a single-character difference, silently overwriting a text signal that was already
   correct. Fixed by (a) lowering the reliable-text bar to distinguish "no text" from "short text," and
   (b) the render tier's result can now only ever LOWER confidence via `min()`, never replace it outright
   — and only fires when neither text nor embedded-image extraction found anything usable at all.
3. **Character-level fuzzy text similarity is fundamentally unsafe for realistic document lengths.**
   `difflib.SequenceMatcher` on raw strings trends toward 1.0 as shared text gets longer, so a SINGLE
   meaningfully different word becomes proportionally invisible — "version with some content A" vs
   "...content B" scored 0.963 character-level (crossing the 0.95 auto-remove threshold) but only 0.80
   word-level. Fixed by switching `_text_similarity` to word-level (tokenized) comparison, which counts
   one differing word as one non-matching token regardless of surrounding text length. This is a more
   conservative trade-off (some genuine OCR-noise-only duplicates that would have auto-merged now land
   in `needs_review` instead), which is the explicitly correct direction per the task's own safety
   philosophy.
4. **A plain difference-hash (dHash) is structurally blind to absolute color.** Two solid, uniformly-
   colored images of ANY two different colors produce the identical (all-zero) dHash, since dHash only
   measures local gradients between adjacent pixels and a solid color has none — a solid red test image
   and a solid blue-ish TIFF frame were falsely matched as "exact contained." Fixed by adding a
   mean-RGB `average_color` signal to `EmbeddedImageSignal`, blended via `min()` (weakest-link) with the
   dHash-based similarity in `content_dedup._image_similarity`.

Each bug has a dedicated regression test (see file list in §4) proving it stays fixed.

## 2. What is partially complete / not yet started

Per §7b's module dependency chain and the task's own required deliverable list, still remaining:

- **`reporting.py`** — expand `Duplicate_Removal_Log.txt` with per-method sections (exact-byte/
  normalized-PDF/content-equivalent/blank-page-tolerant); add `write_document_version_report()` →
  `Document_Version_Report.txt`; add `write_merged_overlap_report()` → `Merged_Document_Overlap_Report.txt`.
  `Processing_Manifest.json` needs no code change (confirmed: the existing blind `dataclasses.asdict()`
  walk already picks up every new field automatically) but should get a test proving it.
- **`tests/test_reporting_v2.py`** (new file) — for the above.
- **`tests/test_validation.py`** and **`tests/test_merging.py`** (new files, per §7b's test plan) — a
  dedicated safety test proving OG's document set is invariant to every new exclusion field, and
  dedicated tests for the 5 new validation checks (currently only exercised indirectly through
  end-to-end tests, which IS passing, but a focused test file was planned and not yet written).
- **GUI work** (none started): `gui/widgets/uncertain_review_dialog.py` (new, read-only `QDialog`
  listing `needs_review=True` groups, inspection only, no approval workflow — triggered by a button in
  `ResultView`); `gui/widgets/advanced_settings.py`/`gui/state.py` (new `enable_content_aware_dedup`
  `QCheckBox`, wired into `main_window.py`'s existing `dataclasses.replace(...)` call);
  `gui/widgets/result_view.py` (`_populate_stats` new rows: content-equivalent duplicates removed,
  blank-page-variant duplicates removed, merged-package overlaps resolved, distinct signed/dated
  versions preserved, uncertain comparisons retained for safety). New GUI tests extending
  `tests/gui/test_advanced_settings.py`/`tests/gui/test_results.py`.
- **`tests/test_robert_package_regression.py`** (new file) — existing 14 SHA-256 groups still correct;
  synthetic 619-vs-1099-page recreation of the reported bug (Final = one copy of each unique logical
  document version, explicitly NO fixed-page-total assertion).
- **Full local test suite run** including GUI tests (aware of the pre-existing sandbox Qt segfault —
  see old §3 below, still applies; GUI correctness must ultimately be confirmed on real Windows CI).
- **Windows CI build+package validation** — a real `--onedir` PyInstaller build has NOT been run since
  RC2's changes; `pypdfium2` packaging (native binary bundling via the hooks-contrib hook) is unverified
  on an actual Windows runner. This is required before RC2 can be called done.
- **Final RC2 deliverable report** (root-cause summary, files changed, detection design, test results,
  known limitations, manual Robert-package testing instructions, path to the built artifact) — not
  written yet, waiting on all of the above.

## 3. Tests run and results (current, this session)

```
.venv/bin/python -m pytest -q tests/ --ignore=tests/gui
=> 150 passed, 1 warning in 46.06s
```
Clean. Breakdown: 83 pre-existing engine tests (all still passing, including the RC1 baseline) + 67 new/
updated tests across `test_content_fingerprinting.py` (16), `test_pdf_render.py` (5),
`test_content_dedup.py` (24), `test_pdf_portfolio.py` (8), `test_merged_document_overlap.py` (7),
`test_version_classification.py` (6), plus `test_progress.py` (+1 new test) and
`test_hashing_and_deduplication.py` (TEST 4 rewritten, not a net-new test).

GUI tests (`tests/gui/`) were not re-run this session beyond what already passed in earlier milestones —
the pre-existing sandbox Qt-offscreen segfault (documented in the original §3, preserved below) is
unrelated to RC2 and still applies; GUI correctness for anything RC2 touches (none yet — no GUI code
written) will need confirming once GUI work starts, and ultimately on real Windows CI.

**Original RC1 baseline (kept for reference, still accurate as a pre-RC2 comparison point):**
```
.venv/bin/python -m pytest -q          (full suite, including tests/gui, BEFORE any RC2 change)
=> Segmentation fault after 25 tests passed (dots), inside pytest-qt/offscreen Qt teardown machinery.
   Pre-existing sandbox/environment quirk (Qt offscreen platform + this container), not a regression.
   Last confirmed-clean full suite (124 tests: 83 engine + 41 GUI) was on real Windows CI in run
   29435314643 (commit 4478695) — GUI tests are known-good on real Windows.
```

## 4. Files changed

**Already committed** (5 commits on `claude/lender-package-builder-stage-1-h9sa3n`, all pushed):
- `6d7f6a0` — `models.py`, `pdf_content.py` (NEW), `tests/test_content_fingerprinting.py` (NEW),
  `tests/fixtures/builders.py`, `pyproject.toml`, `requirements.txt`, `requirements-windows-lock.txt`,
  `LenderPackageBuilder.spec`, `packaging/collect_licenses.py`, `THIRD_PARTY_NOTICES.txt`.
- `aa6c9e6` — `pdf_render.py` (NEW), `content_dedup.py` (NEW), `tests/test_pdf_render.py` (NEW),
  `tests/test_content_dedup.py` (NEW), `pdf_content.py` (name-hint fix), `tests/fixtures/builders.py`.
- `e73f81f` — `pdf_portfolio.py` (NEW), `inventory.py` (one-line wire-in), `tests/test_pdf_portfolio.py`
  (NEW).
- `edca9a5` — `overlap_detection.py` (NEW), `tests/test_merged_document_overlap.py` (NEW),
  `content_dedup.py` (escalation-logic bug fix #2 above), `tests/test_content_dedup.py` (regression test).
- `b94d792` — `version_classification.py` (NEW), `tests/test_version_classification.py` (NEW).

**NOT yet committed as of this checkpoint** (staged/working-tree only, but fully tested — 150/150
passing with these changes included):
```
 M config.toml
 M src/lender_package_builder/cli.py
 M src/lender_package_builder/config.py
 M src/lender_package_builder/content_dedup.py       (bug fixes #3, #4 above)
 M src/lender_package_builder/gui/widgets/progress_view.py
 M src/lender_package_builder/models.py               (content_dedup_notes field)
 M src/lender_package_builder/pdf_content.py           (average_color, bug fix #4 above)
 M src/lender_package_builder/progress.py
 M src/lender_package_builder/validation.py            (full generalization)
 M tests/test_content_dedup.py                         (3 new regression tests)
 M tests/test_content_fingerprinting.py                (1 new regression test)
 M tests/test_hashing_and_deduplication.py             (TEST 4 rewrite)
 M tests/test_progress.py                              (stage order + disabled-toggle test)
```
**This checkpoint commits these now** (see §9) — by the time you read this, they should be a 6th commit
on the branch; check `git log` to confirm before assuming anything is still uncommitted.

---

## 5. Architecture research findings (condensed from 3 deep-dive passes — read this before re-exploring)

### 5a. Core data model (`src/lender_package_builder/models.py`)

The atomic unit of the whole engine is `SourceOccurrence` — one input file → one converted PDF →
zero-or-one place in OG → zero-or-one place in Final. **No page-level provenance exists anywhere.**
`merging.py`'s `_build_merged_pdf` does `for doc in docs: for page in PdfReader(doc.converted_pdf_path).pages: writer.add_page(page)`
and immediately discards per-page lineage into an aggregate `OutputPart.page_count` int.

```python
@dataclasses.dataclass
class SourceOccurrence:
    document_id: str; traversal_index: int
    original_filename: str; original_relative_path: str; original_extension: str; original_size_bytes: int
    extracted_path: Path | None; archive_chain_display: str = ""
    original_sha256: str | None; status: ProcessingStatus = ProcessingStatus.DISCOVERED
    is_ignored_artifact: bool = False; ignored_artifact_reason: str | None = None
    converted_pdf_path: Path | None; converted_page_count: int | None; converted_size_bytes: int | None
    conversion_backend: str | None; conversion_warnings: list[str]; conversion_failure_reason: str | None
    used_fallback_renderer: bool = False
    is_duplicate: bool = False; duplicate_of_document_id: str | None = None
    og_part_index: int | None; final_part_index: int | None
    unconverted_copy_path: Path | None
    @property
    def included_in_final(self) -> bool: return not self.is_ignored_artifact and not self.is_duplicate
    @property
    def included_in_og(self) -> bool: return not self.is_ignored_artifact
```

Other models: `OutputPart` (package/index/file_path/document_ids/page_count/file_size_bytes/is_oversized/close_reasons),
`DuplicateGroup` (sha256-keyed: `document_ids`, `retained_document_id = document_ids[0]`,
`duplicate_document_ids = document_ids[1:]` — **canonical selection today is naive "first in traversal
order wins," no quality scoring at all**), `IntegrityCheckResult` (name/passed/detail), `RunResult`
(input_path/output_path/timing/occurrences/duplicate_groups/og_parts/final_parts/integrity_checks/
conversion_backend_usage/unsafe_archive_incidents; `.success = all(c.passed for c in integrity_checks)`).

### 5b. Pipeline (`cli.py::_execute_pipeline`, 6 fixed stages)

1. `[1/6]` **Discover** — `InventoryBuilder.build()` (`inventory.py`) walks folder/ZIP (recursing into
   nested ZIPs at their exact position, depth-limited to 25, natural-sort for folders, ZIP
   central-directory order for archives) → `list[SourceOccurrence]` in stable traversal order,
   `original_sha256` computed on raw extracted bytes at discovery time (`hashing.sha256_of_file`).
   Nothing is ever silently dropped (hard invariant, enforced by `validation.py`).
2. `[2/6]` **Exact-dup detection** — `deduplication.find_duplicates()` (57 lines): buckets by
   `original_sha256`, first-in-traversal-order wins, mutates `is_duplicate`/`duplicate_of_document_id`
   in place. Docstring: *"Two source occurrences are duplicates of each other only when their original
   SHA-256 is identical. Nothing else ... ever participates in this decision."*
3. `[3/6]` **Convert** — non-ignored occurrences: if `is_duplicate`, SKIP conversion, reuse retained
   occurrence's `ConversionResult` via `_copy_conversion_result` (duplicates share the same converted
   PDF file on disk); else `conversion.convert_occurrence()` (module-per-extension dispatch: `pdf.py`
   does a **byte-for-byte `shutil.copyfile` passthrough** for unencrypted PDFs, so original SHA-256 ==
   converted-PDF bytes for pure-PDF sources; `images.py`, `office.py` [LibreOffice/Office-COM/pure-Python
   fallback chain], `email.py` [MIME/.msg → ONE combined PDF; **attachments become synthetic, ephemeral
   `SourceOccurrence`s local to `email.py`'s scope, never added to the real `RunResult.occurrences`
   list** — today's dedup literally cannot see a PDF email-attachment identical to a separately-supplied
   top-level PDF; this gap is explicitly out of scope for RC2 per the task, only PDF Portfolios are
   in scope], `html.py`, `text.py`), falling back to `make_placeholder_pdf` on failure. `validate_pdf()`
   (opens via `PdfReader`, non-zero pages) is the sole per-document success gate — **no content-level
   validation exists anywhere today**.
4. `[4/6]` **Merge OG** — `og_docs = [o for o in occurrences if o.included_in_og]` (everything
   non-ignored, duplicates INCLUDED).
5. `[5/6]` **Merge Final** — `final_docs = [o for o in occurrences if o.included_in_final]` (excludes
   duplicates too). Delegates to `splitting.plan_parts()` (max_pages/max_size are hard ceilings, never
   targets; **a document is NEVER split across parts** — deep, pervasive invariant). Rebuild-loop if
   actual on-disk size exceeds ceiling. Re-reads actual page count from disk after writing.
6. `[6/6]` **Integrity checks** — `validation.py::run_integrity_checks`, 21 independent checks, several
   **re-read actual generated files from disk** (re-hash originals; re-open every converted PDF and
   recount pages; re-open every output part and recount pages). Critically, several checks **hard-code
   exact-SHA-256-duplicate arithmetic**: `_check_final_page_total` asserts
   `final_total == og_total - duplicate_pages`; `_check_duplicate_hash_match` asserts a duplicate's
   SHA-256 literally equals its retained counterpart's; `_check_no_nonidentical_removed` assumes the
   only removal reason is exact-hash-identity. **Any new non-exact removal category breaks these
   checks' arithmetic unless generalized.**

### 5c. Reporting (`reporting.py`)

`write_duplicate_removal_log` (per-removed-file blocks, 100% exact-hash-shaped, one hash = one group),
`write_processing_report` (human-readable sections), `write_processing_manifest` (blind
`dataclasses.asdict()` walk of the whole `RunResult` → JSON — **any new dataclass field on any model
automatically appears here with zero reporting code changes**, as long as JSON-serializable or covered
by the existing `_json_default` Path/enum handling).

### 5d. GUI (`gui/main_window.py`, `gui/widgets/result_view.py`, `gui/widgets/progress_view.py`)

`MainWindow._on_build_finished(run)`: if `not run.success` → `FailureView` (has a reusable collapsible
"▸ Technical details" `QToolButton` + `QPlainTextEdit` pattern — reuse this for "Review uncertain
matches"); else `_has_warnings(run)` (currently: any unconverted placeholder OR any conversion warning)
picks banner status, then `ResultView.set_result(run, is_warning)`. `ResultView._populate_stats` fully
clears+rebuilds a `QGridLayout` of `(label, value)` rows from a hardcoded list every call — this is
where new summary rows get added (cheap/additive). `progress_view.py` has a hardcoded
`STAGE_LABELS: dict[ProgressStage, str]` — any new `ProgressStage` enum member needs a matching entry.
Advanced Settings today = exactly two knobs (`max_pages_per_part`, `max_size_mb_per_part`) via
`gui/widgets/advanced_settings.py`'s `AdvancedSettingsWidget` (collapsible, `get_values()` from
`gui/state.py`, wired into `main_window.py`'s `dataclasses.replace(self.config, ...)` call). **Zero
existing dedup-related config/GUI surface** — a new toggle needs: `AppConfig` field (`config.py`) +
`config.toml` doc comment + `AdvancedSettingsValues` field (`gui/state.py`) + a `QCheckBox` in
`AdvancedSettingsWidget` + one added kwarg in `main_window.py`'s existing `dataclasses.replace(...)` call.

### 5e. Dependencies / packaging

Only `pypdf==5.9.0` for PDF manipulation (no pikepdf, no PyMuPDF/fitz, no pdf2image, no OCR).
`reportlab==4.5.1` for PDF *generation* only. `Pillow==11.3.0` already present but only used for
raster-image-to-PDF conversion, never PDF-page rendering. Files needing updates for any new dependency:
`pyproject.toml`, `requirements.txt`, `requirements-windows-build.txt`, `requirements-windows-lock.txt`
(regenerate via real Windows CI `pip freeze`, per that file's own header comment), and
`LenderPackageBuilder.spec`'s `_metadata_datas` tuple (distribution names for `copy_metadata`, feeds
`diagnostics.py`/self-test version reporting) and `_hiddenimports` list (possibly `binaries=[]` too if
PyInstaller's auto-hook doesn't catch a new C-extension package — check whether
`pyinstaller-hooks-contrib`, already a Windows-lock dependency, ships a hook for the new library).

**No PDF Portfolio / embedded-file / Collection-dictionary support exists anywhere** — confirmed via
full-repo grep, 100% greenfield. Note: pypdf 5.9.0 may have partial built-in support worth checking
first during implementation — `PdfReader.attachments` reads the `/Names/EmbeddedFiles` name tree; the
`/Collection` dictionary (distinguishes a true "Portfolio" UI presentation from a PDF that merely has
file attachments) likely needs lower-level `reader.trailer["/Root"]` access, which pypdf also exposes.
**Verify this empirically before writing `pdf_portfolio.py`** — do not assume the API surface, check it
against a real Portfolio PDF fixture first.

### 5f. Existing regression test that defines a safety boundary — MUST keep passing

`tests/test_hashing_and_deduplication.py::test_signature_packages_both_kept_in_full` — two PDFs share
19 identical boilerplate pages but differ in one final signature page; asserts BOTH kept in Final in
full (`is_duplicate is False` for both). This is fully consistent with the new task's safety rules (a
meaningfully different signature page must never cause removal) — new content-aware logic must still
keep both documents here by correctly recognizing the signature-page difference as meaningful, not by
being scoped to avoid the test.

### 5g. Test infrastructure

`tests/fixtures/builders.py` — synthetic PDF/DOCX/XLSX/image/email/zip generators, deterministic, no
real borrower data. Key existing functions: `make_pdf(path, pages, text_prefix, metadata)`,
`make_signature_package(path, borrower_name, common_pages=19)` (already exactly the "shared boilerplate
+ distinct final page" shape needed for near-duplicate/version fixtures — extend this pattern, don't
replace it), `make_corrupt_pdf`, `make_password_protected_pdf`, `make_image`, `make_multipage_tiff`,
`make_txt`, `make_html`, `make_docx`, `make_xlsx`, `make_eml`, `make_zip`, `read_pdf_page_count`,
`read_pdf_text`. `tests/conftest.py`'s `run_build` fixture wraps `build_package(progress=False, ...)`.
Tests use plain `assert`, numbered `# TEST N` comments per file, `tmp_path` isolation. GUI tests
(`tests/gui/`) use a `window` fixture + autouse synchronous-worker patching (real background thread only
via `@pytest.mark.real_background_thread`). **No `tests/test_merging.py` or `tests/test_validation.py`
exist yet** (validation asserted indirectly via `run.integrity_checks` from other test files) — clean
opportunity for new dedicated test files. Full test file map:

| Area | File | Count |
|---|---|---|
| Conversion | `tests/test_conversion.py` | 10 |
| Merging+Splitting | `tests/test_splitting.py` | 9 |
| Reporting | `tests/test_reporting.py` | 3 |
| Validation | *(none dedicated)* | — |
| Progress | `tests/test_progress.py` | 5 |
| Dedup+hashing | `tests/test_hashing_and_deduplication.py` | 6 |
| Inventory | `tests/test_inventory.py` | 7 |
| Archive safety | `tests/test_archives.py` | 7 |
| Full pipeline | `tests/test_end_to_end.py` | 2 |
| Packaging/CLI/config | `tests/test_stage3_packaging.py` | 34 |
| GUI | `tests/gui/*.py` (10 files) | — |

---

## 6. Decisions already confirmed with the user — do not re-ask

**Rendering/visual-comparison dependency approach**: the task requires "rendered visual appearance"
comparison and says to "reuse the app's existing local PDF rendering components where possible," but
research confirmed **none exist**. The user was asked and explicitly chose:

> **Add pypdfium2 + imagehash.** pypdfium2 (Apache-2.0/BSD-3, self-contained wheel with bundled PDFium
> binary, no external poppler/system dependency) for page rasterization, and imagehash (BSD-2, built on
> already-present Pillow) for perceptual hashing. **Used ONLY as the final, most-expensive tier of a
> staged pipeline** — rendering just the specific still-ambiguous pages, after cheap
> SHA-256/structural/text/embedded-image signals are exhausted, not as a blanket full-document
> rasterization pass.

This was chosen over a "structural-only, no new dependency" alternative (which would have built all
visual signals from pypdf text/form/annotation extraction + Pillow-decoded embedded-image hashing
alone). Both licenses are permissive and fully offline/self-contained — no further license-review
question needed here (unlike the pre-existing, separate, still-open `extract-msg` GPLv3 question, which
is unrelated to this task and not to be conflated with it).

---

## 7. Draft architecture (reasoned design, NOT yet validated or user-approved as a final plan)

### New modules (`src/lender_package_builder/`)

1. **`pdf_content.py`** — low-level per-document/per-page content extraction toolkit: normalized text
   extraction, page geometry (dimensions/rotation), form-field name+value extraction (AcroForm),
   annotation extraction (type/subtype/rect/contents/appearance-stream presence), digital-signature
   detection (AcroForm `/Sig` fields / `/ByteRange`), embedded raster image extraction+hashing (per
   page, via pypdf's image objects → Pillow decode → both exact byte hash and `imagehash.phash`), and
   blank-page classification (text empty + no meaningful annotations/form-fields + embedded images
   either absent or classified blank via Pillow pixel-variance/near-white-ratio analysis on decoded
   image bytes — **not** full-page rasterization; a page's content for blankness purposes is mostly
   recoverable from its embedded objects without rendering). Produces `PageFingerprint` and
   `DocumentFingerprint` dataclasses.
2. **`pdf_render.py`** — thin wrapper around pypdfium2 for the LAST-tier-only rendering of specific
   ambiguous pages to downsampled images + imagehash perceptual comparison. Deliberately isolated as
   the only module importing pypdfium2 — keeps the expensive tier swappable/mockable in tests and easy
   to verify it's genuinely invoked rarely.
3. **`pdf_portfolio.py`** — Portfolio/embedded-file detection (Collection dict + Names/EmbeddedFiles
   tree — verify exact pypdf API empirically first, see §5e) and extraction, called from `inventory.py`
   during discovery (mirroring how nested-ZIP expansion already works) to synthesize new **real**
   `SourceOccurrence`s for each embedded attachment, inserted immediately after their parent in
   traversal order, with a new `portfolio_parent_document_id` provenance field. Determines fallback
   deterministic ordering + records when fallback was used. Excludes the generic Adobe cover page from
   being treated as lender content.
4. **`content_dedup.py`** — Level 2/3/4 engine: staged candidate-bucketing (cheap structural keys
   first: page_count, rounded normalized-text-length, has_signature_field, rounded page dimensions) →
   normalized-fingerprint comparison (Level 2) → multi-signal content-equivalence scoring (Level 3,
   calling into `pdf_render.py` only for genuinely unresolved candidates) → blank-page-tolerant
   page-sequence alignment (Level 4, needs a real sequence-alignment algorithm — e.g. LCS/edit-distance
   style over non-blank page fingerprints, requiring the aligned non-blank subsequence to match with
   high confidence and the only differences being genuinely-classified-blank pages). Produces
   confidence-scored match results feeding new fields on `SourceOccurrence` — **never touches
   `is_duplicate`/`DuplicateGroup`** (those stay exact-hash-only, to protect `validation.py`'s strict
   SHA-256 invariants); uses new fields/dataclasses instead (see below).
5. **`overlap_detection.py`** — merged-document containment: identify merged-package candidates via a
   page-count threshold (candidate/performance heuristic ONLY, never duplicate proof — file size and
   filenames are never used per the task's non-negotiable rules), segment candidates' non-blank
   page-fingerprint sequences, slide standalone/Portfolio-attachment document fingerprint sequences
   against them to classify exact/equivalent/version-differs/partial/uncertain/none. **Decision rule:
   when a standalone document is safely proven fully contained in a merged PDF, always exclude the
   standalone side, never the merged PDF** (the merged PDF usually holds other unique content and rule
   10 forbids deleting isolated pages from its middle — there is no safe way to "remove from" a merged
   PDF, only to remove the redundant standalone copy). Merged-vs-merged overlap (two big binders sharing
   sections) is explicitly out of scope for RC2 — not in the task's examples, adds substantial
   complexity, and the Robert-package scenario is exactly the standalone-in-merged case. **Flag this as
   a documented known limitation in the final report.**
6. **`version_classification.py`** — Level 5, **purely descriptive/read-only**: after modules 4+5 have
   made all keep/remove decisions, cluster compared-candidate documents into "families" (reusing the
   same candidate-bucketing graph from `content_dedup.py`) and label each surviving member's likely
   version kind (unsigned/e-signed/wet-signed/scanned/dated/etc.) purely for
   `Document_Version_Report.txt` readability. **Does not independently remove anything** — this keeps
   all safety-critical removal logic in exactly two places (`content_dedup.py`, `overlap_detection.py`),
   which is much safer to reason about and test than spreading removal decisions across three+ modules.

### Data model additions (`models.py`)

New fields on `SourceOccurrence`: `needs_review: bool`, `review_reason: str | None`,
`is_content_duplicate: bool`, `content_duplicate_of_document_id: str | None`,
`duplicate_detection_method: str | None` (e.g. `"exact_sha256"` / `"normalized_pdf"` /
`"content_equivalent"` / `"blank_page_tolerant"`), `duplicate_confidence: float | None`,
`blank_pages_ignored_count: int`, `is_portfolio_container: bool`,
`portfolio_parent_document_id: str | None`, `is_contained_in_merged_document: bool`,
`contained_in_document_id: str | None`, `contained_page_range: tuple[int, int] | None`,
`document_family_id: str | None`, `version_classification: str | None`.

Extend `included_in_final` to also exclude `is_content_duplicate`, `is_portfolio_container`,
`is_contained_in_merged_document` (all three ONLY when high-confidence/not `needs_review` — a
`needs_review=True` occurrence must NEVER be excluded from Final, per the safety rules).

New dataclasses: `ContentDuplicateGroup`, `DocumentFamily`, `OverlapFinding` — deliberately **not**
overloading the exact-hash `DuplicateGroup`, to avoid touching `validation.py`'s strict SHA-256-only
invariant checks.

### Pipeline re-ordering (`cli.py`)

Portfolio expansion folds into stage 1 (discovery, inside `inventory.py`) so extracted attachments
become normal occurrences flowing through everything downstream unchanged. Exact-hash dedup (stage 2)
and conversion (stage 3) stay exactly as-is and run FIRST — content-aware analysis needs converted PDFs
to exist for non-PDF-original sources, so it must run after conversion. New stages inserted between
conversion and OG-merge: **content fingerprinting → content-aware dedup (Level 2/3/4) →
merged-document overlap detection → version classification (descriptive only)** → then existing OG
merge / Final merge (gate extended) / integrity checks (generalized formulas + new checks) / reports
(2 new files + expanded existing ones). New `ProgressStage` members needed for each new stage (+ matching
entries in `gui/widgets/progress_view.py`'s `STAGE_LABELS` dict).

### Validation generalization (`validation.py`)

Replace the hard-coded `final_total == og_total - duplicate_pages` formula with a generic
`final_total == og_total - sum(pages of every occurrence excluded from Final)`, computed from
`included_in_final` rather than assuming the only exclusion reason is exact-hash duplication. Add new
checks proving: every Final-exclusion has a non-empty, auditable reason recorded; every
`needs_review=True` occurrence is present in BOTH OG and Final (never silently dropped); every Portfolio
attachment was extracted and accounted for.

### Open engineering questions to resolve during implementation (not blocking, but flagged)

- Exact pypdf API surface for Portfolio/Collection/EmbeddedFiles detection — verify against a real
  fixture before finalizing `pdf_portfolio.py`'s design (see §5e).
- Concrete conservative confidence thresholds for "auto-remove" vs. "needs_review" at each staged tier
  — propose starting thresholds, but these should be tunable/documented, not hardcoded magic numbers
  buried in logic.
- Concrete blank-page-tolerant sequence-alignment algorithm needs to be pinned down precisely (LCS-style
  proposed above) with explicit failure-mode handling (what happens when alignment is ambiguous — must
  default to `needs_review`, never to silent removal).

---

## 7b. VALIDATED refinements (architecture-validation pass — COMPLETED, supersedes §7 conflicts)

The validation agent read actual source (`models.py`, `deduplication.py`, `validation.py`, `merging.py`,
`cli.py`, `inventory.py`, `progress.py`, `splitting.py`, `reporting.py`, `conversion/email.py`,
`conversion/pdf.py`, `conversion/base.py`, `config.py`, GUI widgets, test fixtures/files,
`LenderPackageBuilder.spec`, `requirements*.txt`) and found concrete corrections. **Treat this section
as the authoritative design; §7 is superseded wherever they differ.**

### Key reframing
Level 2 is not a separate algorithm from Level 3 — it's an O(1) hash fast-path for the case where
Level 3's real algorithm (page-by-page comparison) would find every page a 1.0-confidence match. Level 4
is the same Level-3 page comparator with blank pages stripped from both sides first. One function,
`compare_documents(a, b, allow_blank_stripping) -> PairComparison`, underlies content_dedup.py directly
and overlap_detection.py's sliding-window form.

### Corrected module list
- **`pdf_content.py`** — per-page fingerprints (normalized text — NOT stripped of numbers/dates, that
  would break the hard-veto system below; page geometry; per-page form fields — verify `get_fields()`
  is document- not page-scoped, may need manual `/Annots` walk; annotations; signature-field presence;
  embedded-image extraction + Pillow blankness + `imagehash.phash`), a conservative `classify_blank_page`,
  `build_document_fingerprint`, and **`extract_structured_tokens(text)`** (regex-based dates/dollar
  amounts/address hints) — this last one is new vs. the §7 draft and is load-bearing (see hard-veto
  below).
- **`pdf_render.py`** — unchanged from §7, only module importing pypdfium2, LRU-cached per-page
  rendering, deliberately mockable so tests can assert it's called rarely.
- **`pdf_portfolio.py`** — `expand_portfolios(occurrences, workspace) -> list[SourceOccurrence]`,
  called as **one new line at the end of `InventoryBuilder.build()`**, not threaded into the
  folder/zip walk (`inventory.py` never opens PDFs today; keep that separation). Portfolio children get
  `document_id = f"{parent.document_id}-PF-{i:03d}"` (mirrors `conversion/email.py`'s existing
  `-ATT-{i:03d}` convention for synthetic attachments) — **`document_id` no longer implies
  `traversal_index` numerically** once spliced; only `traversal_index` gets renumbered 1..N after
  splicing, `document_id` stays stable. **Critical correction**: `/Names/EmbeddedFiles` non-empty
  ≠ `/Collection` present. A PDF can carry a couple of paperclip attachments with real content pages and
  no `/Collection` at all — extract attachments whenever `/Names/EmbeddedFiles` is non-empty regardless
  of `/Collection`, but only set `is_portfolio_container=True` (excluding the container's own pages from
  Final) when `/Collection` is actually present. Getting this wrong would wrongly empty a normal PDF
  that merely has an attachment.
- **`content_dedup.py`** — operates only over
  `[o for o in occurrences if not is_ignored_artifact and not is_duplicate and status == CONVERTED]`
  (the `status == CONVERTED` guard was missing from §7's draft — placeholders must never enter this
  pool). Buckets by `(non_blank_page_count, page_dims_signature, has_signature_field, has_form_fields)`
  plus a first/last-non-blank-page-text-hash index (new vs. §7, needed for O(1)-average
  `overlap_detection.py` lookups too — fold the indexing helper into this module rather than adding a
  7th module). `max_bucket_size_for_full_comparison` guardrail (new) — beyond it, fall back to
  Level-2-hash-only comparison for that bucket and log it in the report.
- **`overlap_detection.py`** — no arbitrary page-count "merged package" threshold; any document is a
  containment candidate for any other whose `non_blank_page_count <= container's raw page count`.
  Containment matching is per-container only, **never chained/unioned across two different merged
  PDFs** — a doc split across two different binders is `partial_overlap` against both, not a match
  against either.
- **`version_classification.py`** — unchanged from §7 (purely descriptive, runs last, sets no
  exclusion field).
- **GUI gap found**: §7's module list was entirely engine-side; the "review uncertain matches" action
  and "conservative advanced setting" need real GUI work — a new small
  `gui/widgets/uncertain_review_dialog.py` (read-only `QDialog`, triggered by a button in
  `ResultView`, listing `needs_review=True` groups — explicitly NOT an approval workflow, inspection
  only) plus one new boolean toggle `enable_content_aware_dedup: bool = True` in
  `AdvancedSettingsValues`/`AppConfig` as an off-switch back to exact-SHA-256-only behavior. **Flagged
  as a product decision to confirm with the user**: spec says "a conservative advanced setting OR
  review screen" — the recommendation is both (dialog primary, toggle as cheap/low-risk addition), but
  confirm before building both.

### Corrected algorithm — blank-page alignment (Level 4)
**Do NOT use general LCS/edit-distance alignment** (this was §7's mistaken suggestion) — general
edit-distance permits arbitrary insertion/deletion of ANY page including non-blank ones, which directly
violates "never delete isolated matching pages from the middle of a document." The only safe operation:
strip conservatively-classified-blank pages from both sides (whitelist removal, from anywhere in the
sequence), THEN require the remaining non-blank pages to match **1:1, in strict positional order, zero
further insertion/deletion tolerance**. If lengths differ after stripping → `NO_MATCH`, full stop.

**Hard-veto system (new, load-bearing)** — `compare_page(pa, pb)`: normalized-text exact hash match →
confidence 1.0 done (this IS Level 2, expressed per-page). Else: **check hard vetoes FIRST** — signature
field presence differs, any form-field value differs, or any extracted date/dollar-amount token differs
(via `extract_structured_tokens`) → `hard_veto=True`, stop scoring immediately, classify
`DIFFERENT_VERSION`, both retained. **Why this matters**: a single-digit date change
(`2026-01-15`→`2026-01-16`) can score dangerously close to 1.0 on plain character-similarity — only an
explicit structured-token comparison reliably catches it; don't rely on a similarity score alone to
protect dated-version tests. Only if no hard veto: blend `difflib.SequenceMatcher(None, a, b).ratio()`
(stdlib, deliberately not bag-of-words/Jaccard — a differing proper noun can score deceptively high
under token-overlap) with image-phash similarity when text is sparse/absent, escalating to
`pdf_render.py` only when the text signal is weak AND the blended score is ambiguous.

**Whole-document aggregation must be weakest-link, never average.** `test_signature_packages_both_kept_in_full`
(19/20 pages identical, 1 differs) will FAIL under any document-level average-similarity score (~95%+
from the 19 shared pages, diluting the 1 real difference) — the per-page comparator's minimum confidence
across all pages is what must gate the match, not a mean. This is the single most important correction
from the validation pass — a document-level aggregate score was §7's implicit design and is unsafe.

Confidence bands (defaults, flagged for empirical tuning against the Robert package — not
first-principles-derived): weakest-link ≥ 0.95 → auto-remove; 0.80 ≤ weakest < 0.95 → `needs_review`,
both retained; hard veto with high extraction confidence → both retained, no review flag needed; hard
veto with low extraction confidence (garbled OCR) → `needs_review`, both retained.

### Data model diff (refined)
Same field list as §7's draft, with one correctness fix: `included_in_final` must guard both new
exclusion reasons with `and not needs_review`:
```python
@property
def included_in_final(self) -> bool:
    return (
        not self.is_ignored_artifact
        and not self.is_duplicate
        and not (self.is_content_duplicate and not self.needs_review)
        and not (self.is_portfolio_container)
        and not (self.is_contained_in_merged_document and not self.needs_review)
    )
```
New dataclasses `ContentDuplicateGroup` (method/document_ids/retained_document_id/confidence/
blank_pages_ignored_count), `DocumentFamily` (family_id/document_ids/versions dict), `OverlapFinding`
(standalone_document_id/container_document_id/classification/contained_page_range/confidence/excluded).
`RunResult` gains `content_duplicate_groups`, `document_families`, `overlap_findings` — all
default-empty-list, purely additive to the existing `dataclasses.asdict()` manifest walk (confirmed, no
reporting.py code change needed for the manifest specifically).

### Corrected pipeline order
Build-OG moves back to its CURRENT position (right after conversion) — `included_in_og` only ever
depends on `is_ignored_artifact`, untouched by this feature, so §7's "delay OG until after new stages"
was an unnecessary diff:
```
[1/9] Discovering files             (incl. Portfolio expansion via one new call at end of build())
[2/9] Detecting exact duplicates    (unchanged)
[3/9] Converting documents          (unchanged)
[4/9] Building OG package           (moved back up — unaffected by new fields)
[5/9] Fingerprinting content        (new)
[6/9] Detecting content duplicates  (new — Level 2/3/4)
[7/9] Analyzing merged packages     (new — overlap_detection.py)
[8/9] Classifying document versions (new — descriptive only)
[9/9] Building Final package        (existing, gate extended)
      Running integrity checks / Writing reports / Complete (existing, non-numbered)
```
**Mechanical but easy to miss**: every `"[N/6]"` string literal in `cli.py::_execute_pipeline`'s
progress messages is now wrong (6 of them) and must become `"[N/9]"`; `tests/test_progress.py`'s
`expected_order` list (asserts an EXACT stage sequence) needs updating; `progress_view.py`'s
`STAGE_LABELS` dict needs new entries.

### Validation.py generalization (concrete)
Replace `_check_final_page_total`'s hardcoded formula with one computed generically from
`included_in_final` (sum pages of every `og_included` occurrence where `not included_in_final`, whatever
the reason). Generalize `_check_no_nonidentical_removed` → `_check_no_unexplained_removal`: every
occurrence with `included_in_og and not included_in_final` must have at least one non-empty explanation
among its exclusion-reason field groups — fail if none set. Add two NEW checks:
`_check_needs_review_never_excluded` (every `needs_review=True` occurrence has `included_in_final=True`
— independently re-verifies the property's guard from actual run data) and
`_check_content_duplicate_retained_exists` (every `content_duplicate_of_document_id`/
`contained_in_document_id` reference resolves to a real, currently-`included_in_final` occurrence).

### Test file plan (concrete file names)
`tests/test_content_fingerprinting.py`, `tests/test_content_dedup.py`, `tests/test_merged_document_overlap.py`,
`tests/test_pdf_portfolio.py`, `tests/test_version_classification.py`, `tests/test_merging.py` (new —
critical safety test: OG's document set is invariant to every new field), `tests/test_validation.py`
(new), `tests/test_reporting_v2.py`, `tests/test_robert_package_regression.py` (new, dedicated — 14
exact-dup groups still correct + synthetic 619-vs-1099 recreation with NO fixed-page-total assertion).
New fixture builders needed in `tests/fixtures/builders.py` (concrete signatures — see full agent output
captured in this session's transcript if exact signatures are needed verbatim; summary):
`make_pdf_with_blank_pages`, `make_pdf_with_faint_content` (not-blank test), `make_form_pdf`,
`make_signed_pdf_variant(signature_kind: "unsigned"|"e_signed"|"wet_signed")`, `make_scanned_like_pdf`
(**image-only pages, no text layer — required to actually exercise `pdf_render.py`**; without this
fixture the render tier is never really tested since text usually resolves ambiguity first),
`make_pdf_portfolio`, `make_merged_pdf`, `make_merged_pdf_with_gap`.

### ⚠️ Two decision points to resolve WITH THE USER before implementing (do not decide unilaterally)

1. **`tests/test_hashing_and_deduplication.py::TEST 4`
   (`test_identical_visible_content_different_source_bytes`) will correctly, unavoidably start failing
   once Level 2 ships.** Its fixtures (`make_pdf` with identical `text_prefix="Shared Text"`, identical
   `pages=2`, differing only in a custom `/CustomTag` metadata value) are the textbook definition of
   Level 2's own target case. Once Level 2 works, this pair SHOULD auto-remove one copy — meaning the
   test's current assertion (`dy.document_id in final_ids`) becomes false by design. This is a direct,
   structural conflict with the "all existing tests still pass" requirement as literally stated,
   confined to this one test. Recommendation: update this test's assertions with a comment explaining
   why, and call it out explicitly in the final deliverable's changelog/known-limitations — do NOT try
   to route around it by artificially excluding this exact case from Level 2 (that would defeat the
   point of Level 2 entirely).
2. **GUI: review dialog vs. advanced-setting toggle vs. both.** Spec says "a conservative advanced
   setting OR review screen." Recommendation is to build both (dialog for inspection, toggle as a cheap
   off-switch), but confirm this scope with the user rather than assuming — it's the one place this
   task's GUI-minimalism instruction ("do not redesign the GUI") intersects with a genuinely new
   surface being added.

### Packaging risk flagged
`imagehash` pulls in `numpy`/`scipy` — check this at implementation time; this is exactly the class of
dependency that works from source and silently breaks frozen under PyInstaller. `pypdfium2`'s native
binary loader may need explicit `_hiddenimports`/`binaries=[]` entries in `LenderPackageBuilder.spec`
beyond what PyInstaller's auto-hooks catch. **A real Windows `--onedir` build+smoke-test pass is
required before RC2, not just source-tree tests** — this project already has a working, green Windows CI
pipeline (commit `4478695`) to build on, don't rebuild it.

---

## 8. Architecture-validation prompt template (COMPLETED — kept for reference only, do not re-run)

A Plan sub-agent was launched with a very long, self-contained prompt containing all of §5, §6, and §7
above plus the full original task spec, asking it to critique 8 specific points: (1) pipeline staging
correctness / ordering traps between Portfolio-expansion and exact-hash-dedup, (2) whether
"always exclude the standalone side, never the merged PDF" is universally safe per the task's rules,
(3) a concrete safe blank-page sequence-alignment algorithm and its failure modes, (4) concrete staged
candidate-bucketing keys and promotion thresholds through the tiers, (5) whether the 26 required tests
all map cleanly onto the 6 proposed modules, (6) exact new test file names + new fixture-builder
function signatures needed in `tests/fixtures/builders.py`, (7) risk in relying on pypdf's
`.attachments`/raw catalog access for Portfolio detection, (8) risk of breaking
`test_signature_packages_both_kept_in_full` or other existing tests. **This agent's result was not
captured before this checkpoint was written.** If resuming, either re-launch an equivalent validation
pass (reconstruct the prompt from §5–§7 of this file) or proceed directly to writing the formal plan
file from §7's draft.

---

## 9. Exact next step to resume this task

Architecture research, validation, AND a substantial, fully-tested chunk of implementation are all done
(§1). The two decision points from the old §7b are resolved (user approved both). Resume by:

1. Re-read this `CHECKPOINT.md` §1–§4 for exactly what's done and what's not; re-read **§7b** for the
   authoritative design of everything still to build (reporting report formats, the GUI plan, the
   canonical-selection/confidence-band reasoning) — it remains accurate for the remaining work.
2. Confirm via `git log --oneline -8` and `git status` that the commit referenced at the end of this
   checkpoint (see the session's final message / commit hash) is present and the working tree is clean;
   if not, something unexpected happened between sessions — investigate before continuing.
3. Continue implementation in this order (everything before this point is done):
   a. `reporting.py` — expand `Duplicate_Removal_Log.txt`, add `write_document_version_report()` and
      `write_merged_overlap_report()`, wire both into `write_all_reports()`. Write
      `tests/test_reporting_v2.py` alongside it, including a test proving the manifest JSON picks up
      the new RC2 fields automatically.
   b. `tests/test_validation.py` + `tests/test_merging.py` (new files) — the dedicated OG-invariance
      safety test and focused tests for the 5 new validation checks, per §7b's test plan. (The checks
      themselves are done and passing via end-to-end tests; this is dedicated, focused coverage that
      was planned but not yet written.)
   c. GUI work: `gui/widgets/uncertain_review_dialog.py` (new), `gui/widgets/advanced_settings.py` +
      `gui/state.py` (new checkbox), `gui/widgets/result_view.py` (new stat rows), `main_window.py`
      (wire the new config field through the existing `dataclasses.replace(...)` call). New/extended
      GUI tests. Remember the GUI-test sandbox segfault (§3) — GUI tests may need running individually
      or their correctness confirmed via careful review + eventual Windows CI, not assumed clean from a
      full local `pytest` run in this environment.
   d. `tests/test_robert_package_regression.py` (new file) — 14-exact-dup-groups-still-correct +
      synthetic 619-vs-1099-page recreation.
   e. Run the FULL local test suite (engine + GUI, working around the sandbox segfault if needed) and
      fix anything that breaks.
   f. Real Windows CI build+package validation — trigger `build-windows-portable.yml` via
      `workflow_dispatch` (see commit `4478695` for how this branch's CI was last made green), watch it
      through to a successful artifact upload. `pypdfium2`'s native binary bundling via
      `pyinstaller-hooks-contrib`'s `hook-pypdfium2.py` is unverified on real Windows — this is the one
      genuinely new packaging risk in this whole RC2 change and needs real confirmation, not just local
      reasoning.
   g. Write the final RC2 deliverable report per the task's own required format (root-cause summary,
      files changed, detection design implemented, tests added, complete test results, known
      limitations, exact manual Robert-package testing instructions, path to the new portable RC2
      artifact).
4. The original full task spec (all 26 required tests verbatim, all 5 detection levels, all reporting/
   GUI/performance requirements) was provided by the user earlier in this task's conversation. §5–§7b
   condense the architecturally-relevant parts in enough detail to implement correctly, but
   **re-confirm exact wording/expectations against the original spec** if anything here seems
   ambiguous — it is not fully re-quoted in this file.

**Suggested exact resume prompt for the user to give**:

> Resume the RC2 content-aware deduplication upgrade from CHECKPOINT.md §1–§4. Continue with reporting.py
> expansion, the two new dedicated test files, GUI work, the Robert-package acceptance test, then run
> the full test suite, validate the Windows CI build, and produce the final RC2 deliverable report.

---

## 10. Explicit reminders carried over from the task's own constraints (do not violate when resuming)

- Do not redesign the GUI.
- Do not add the output-file-naming feature.
- Do not remove or weaken the existing exact-SHA-256 duplicate system.
- Never use filename or file size as duplicate proof (structural bucketing for *performance
  candidate-generation only* is fine; it must never be the actual proof of duplication).
- When confidence is uncertain, keep both documents and report the uncertainty — never silently drop.
- OG must always preserve every original source occurrence untouched.
- Every Final exclusion must be explainable and included in the reports.
- The app must remain fully offline, self-contained, no admin rights, no CLI required for end users.
- A new portable RC2 artifact must be built and validated through real Windows CI before the task is
  considered done (this session's prior work, commit `4478695`, already has a working, green Windows CI
  pipeline for the existing RC1 — reuse it, do not rebuild the CI pipeline from scratch).
