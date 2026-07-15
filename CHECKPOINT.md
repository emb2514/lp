# CHECKPOINT — RC2 Content-Aware Deduplication Upgrade

**Status as of this checkpoint: PLANNING/RESEARCH ONLY. Zero implementation code has been written.**
`git status` is clean — no source files were touched this session for this task. This checkpoint exists
because the user's usage limit was approaching mid-planning; work was paused at a safe boundary rather
than left mid-edit.

---

## 1. What is complete

- Full architecture research of the existing codebase (three parallel deep-dive passes covering:
  (a) dedup/hashing/data model, (b) conversion/merging/splitting/reporting/validation, (c) GUI results
  display/tests/packaging config). Findings condensed in §5 below — this is the expensive part to
  redo, so it is preserved in full here.
- One architecture decision explicitly confirmed with the user (§6 — do not re-ask).
- A draft architecture designed from that research (§7) — six new modules, data model diff, pipeline
  re-ordering, staged comparison design.
- An architecture-validation pass was launched (a Plan sub-agent, prompted with the full draft
  architecture in §7 and asked to critique 8 specific risk areas — see §8). **This agent COMPLETED and
  its findings ARE captured below in §7b.** It read the actual source files (not just summaries) and
  found several substantive corrections to the draft in §7 — §7b supersedes §7 wherever they conflict.
  Read §7b before implementing anything.
- Baseline test run to confirm the starting point is clean (§3).

## 2. What is partially complete

- **The formal plan file was never written to `/root/.claude/plans/`** — planning was interrupted
  before Phase 4 (write final plan) / Phase 5 (call `ExitPlanMode` for user approval). No plan has been
  presented to or approved by the user yet. **Resuming this task means re-entering plan mode (or
  proceeding directly to implementation with explicit new user approval), not assuming §7 below is
  pre-approved.**
- No code, tests, config, dependency, or packaging-spec changes exist yet in any form — nothing is
  "half-done" at the file level, but the entire feature is undesigned-in-code / unimplemented.

## 3. Tests run and results (baseline, before any change)

```
.venv/bin/python -m pytest -q tests/ --ignore=tests/gui
=> 83 passed, 1 warning in 65.29s
```
Clean. This is the pre-existing engine-test baseline any new work must not regress.

```
.venv/bin/python -m pytest -q          (full suite, including tests/gui)
=> Segmentation fault after 25 tests passed (dots), inside pytest-qt/offscreen Qt teardown machinery
   (PySide6.QtCore/QtGui/QtWidgets/QtTest extension modules listed in the crash's loaded-extensions
   dump). This happened with ZERO source changes present — it is a pre-existing sandbox/environment
   quirk (Qt offscreen platform + this container), not a regression caused by this session. Worth
   knowing about when re-running the full suite here, but not something to chase/fix as part of this
   task. The last confirmed-clean run of the full suite (124 tests: 83 engine + 41 GUI) was on real
   Windows CI in run 29435314643 (see git log around commit 4478695) — GUI tests are known-good on
   real Windows; the segfault is specific to this Linux sandbox's offscreen Qt setup.
```

## 4. Files changed

**None.** This entire session (for the RC2 dedup task) was research and planning. `git log` head is
still `4478695` (the prior task's Windows-CI `$LASTEXITCODE` fix, already committed/pushed before this
task began). Current branch: `claude/lender-package-builder-stage-1-h9sa3n`.

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

This task was interrupted **during plan mode**, before a plan was ever presented to the user for
approval — but the architecture research AND its independent validation pass are both now complete
(§5, §7b). The next session should:

1. Re-read this `CHECKPOINT.md` in full, especially **§7b (the validated, authoritative design)** — it
   substitutes for both the expensive research phase and the architecture-validation phase. Do not
   re-run the 3 Explore agents or the Plan-validation agent from scratch unless something here seems
   stale or wrong.
2. Resolve the two flagged decision points in §7b before writing code: (a) how to handle
   `TEST 4`'s unavoidable conflict with "all existing tests pass" once Level 2 ships, (b) whether to
   build both the uncertain-review dialog and the advanced-settings toggle, or just one.
3. Re-enter plan mode, write the formal plan file to `/root/.claude/plans/` using §7b as the
   authoritative content (light editing/restructuring only — the substance is already validated), and
   call `ExitPlanMode` for the user's approval before writing any code. Do not skip the approval step
   even though research is done — no plan has been shown to the user yet.
4. Once approved, implement in this order (per §7b's module dependency chain):
   `models.py` data-model additions → `pdf_content.py` (foundational toolkit) → `pdf_portfolio.py` →
   `content_dedup.py` → `overlap_detection.py` → `version_classification.py` → `pdf_render.py` →
   `cli.py`/`progress.py` pipeline wiring → `validation.py` generalization → `reporting.py` new
   report writers → GUI wiring → dependency/packaging updates → tests (written alongside each module,
   not deferred to the end) → full local test run → Windows CI build+package → final deliverable report.
5. The original full task spec (all 26 required tests verbatim, all 5 detection levels, all
   reporting/GUI/performance requirements) was provided by the user in the message that started this
   task. §5–§7b condense the architecturally-relevant parts and preserve the safety rules, 5 detection
   levels, merged/Portfolio handling rules, and reporting/GUI/performance requirements in enough detail
   to implement correctly — but **re-confirm the exact wording of the 26 required tests against the
   original spec** before finalizing test names/assertions, since it is not fully re-quoted here.

**Suggested exact resume prompt for the user to give**:

> Resume the RC2 content-aware deduplication upgrade from CHECKPOINT.md. The architecture is researched
> and validated (§7b) — resolve the two flagged decision points, re-enter plan mode, write the formal
> plan file from §7b, and get my approval before writing any code.

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
