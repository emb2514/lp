# Lender Package Builder -- RC2 Deliverable Report

**Content-aware deduplication upgrade.** This report summarizes what RC2 adds on top of RC1
(1.0.0 RC1, the portable-Windows-packaging milestone), how it stays safe, how it was tested, and
what a nontechnical Windows 11 user needs to know to run it.

**Bottom line: yes, the RC2 Windows application is ready to use.** Real Windows CI (not a
source-only or Linux-only check) built the portable executable, ran the entire 261-test suite
against it, proved it needs no external Python, and produced a downloadable release ZIP -- all
green, with real evidence (not just a checkmark) verified below.

**Post-release fix #2**: a real user reported that a package built with the fix-#1 rebuild said
"packaged successfully" but the `Final` folder was completely empty. Root cause, confirmed by direct
reproduction: `pdf_portfolio.py` excluded a PDF's own pages from Final (`is_portfolio_container=True`)
whenever the PDF's internal `/Collection` flag was present, **even when zero actual embedded
attachments could be found to replace it with** -- some PDF-assembly/loan-binder tools leave that flag
set without a true multi-file Portfolio structure underneath it. When that happened, the document
vanished from Final with nothing to replace it, while every safety/integrity check still passed
because the removal looked "explained." Fixed by only ever setting `is_portfolio_container` once real
replacement attachments have actually been found and spliced in as their own documents -- a
`/Collection`-flagged PDF with no enumerable attachments now stays an ordinary standalone document
instead of being dropped. 2 new regression tests (`tests/test_pdf_portfolio.py`), both confirmed
failing before the fix and passing after. See `CHECKPOINT.md` for the commit hash and Windows CI
re-validation status.

**Post-release fix #1**: a real user hit `FileNotFoundError: [WinError 3]` building a package from a
file downloaded via a browser with a very long, URL-derived filename (a common, realistic case --
e.g. saving a document from an API endpoint whose long query string the browser turns into a
filename). The output folder name, derived from that filename, exceeded Windows' 260-character
MAX_PATH limit -- and this app's own `app.manifest` already declares `longPathAware="true"`, which
this real crash proved is not sufficient on its own to prevent it. Fixed by proactively shortening
every filesystem name this app derives from an arbitrary input filename (output folder name, and the
two places a preserved-original-copy's filename is used), always leaving generous headroom below the
260-character limit, while preserving file extensions and leaving normal, reasonably-named inputs
completely untouched. 12 new regression tests (`tests/test_output_path_safety.py`) pin this down,
including a full end-to-end pipeline run using the exact shape of the filename that crashed. See
`CHECKPOINT.md` for the commit hash.

---

## 1. What RC2 adds

RC1's duplicate detection was exact-SHA-256 only: two files with even one differing byte -- a
re-saved PDF, a different scan of the same page, a metadata change -- were always treated as
different documents, however visually identical their content. RC2 adds four layered, safety-first
detection capabilities on top of (never instead of) that exact-hash system:

1. **Content-aware duplicate detection (Levels 2-4)** -- catches duplicates exact-hash detection
   cannot: the same document re-saved with different PDF metadata/compression/object ordering
   (Level 2, "normalized PDF duplicate"), the same document confirmed equivalent via multi-signal
   comparison of text/forms/annotations/signature-state/rendered appearance (Level 3,
   "content-equivalent"), and the same document once verified-blank pages are ignored on either
   side (Level 4, "blank-page-tolerant").
2. **Merged-document overlap detection** -- recognizes when a standalone document is a complete,
   safely-proven copy of content already present inside a separate, larger merged PDF package
   (e.g. a big binder that already includes a disclosure also supplied separately), and excludes
   only the redundant standalone copy -- the merged package itself is never split, reordered, or
   discarded.
3. **PDF Portfolio support** -- detects true Adobe PDF Portfolios (`/Collection` present) and
   ordinary PDFs that merely carry file attachments (`/Names/EmbeddedFiles` present without
   `/Collection`), extracts every embedded attachment as its own real, independently-processed
   document, and excludes only the generic "open this in Acrobat" cover page from Final.
4. **Document version classification** -- purely descriptive grouping of related documents into
   families (e.g. "unsigned / e-signed / wet-signed copies of the same disclosure") for
   `Document_Version_Report.txt`. Never makes a keep/remove decision by itself.
5. **Interactive, auditable human review** -- any comparison the engine cannot confirm
   automatically with high confidence is never silently resolved either way. Both documents stay in
   Final by default ("when uncertain, keep both"), and a new "Review Uncertain Matches" screen lets
   a person explicitly confirm Keep Both or choose one specific document to exclude, with a required
   confirmation step and a full, permanent audit trail.
6. **An advanced-settings toggle** (`Enable content-aware duplicate detection`, on `config.toml`'s
   `[deduplication] enable_content_aware_dedup`) to fall back to RC1's exact-hash-only behavior if
   ever needed.

## 2. Non-negotiable safety rules (unchanged, and actively enforced by 27 automated integrity checks
   plus dedicated regression tests)

- **Filename and file size are never used as duplicate proof.** They may only ever narrow which
  documents get compared to each other (a performance optimization), never decide that two
  documents are the same.
- **Exact-byte SHA-256 detection is untouched and still the mandatory first pass.** RC2 only adds
  detection tiers on top of it; nothing about Level 1 changed.
- **When confidence is uncertain, both documents are always kept**, and the uncertainty is recorded
  and surfaced for human review -- this is enforced structurally (`SourceOccurrence.included_in_final`
  guards every content-aware/containment exclusion with `and not needs_review`), not just by
  convention, and independently re-verified by a dedicated integrity check on every run.
- **A meaningfully different document is never removed.** Differing signatures, e-signature audit
  info, wet-signature marks, initials, dates, checkboxes, form field values, loan amounts,
  addresses, borrower names, wording, annotations, stamps, page order, or attachments all cause a
  hard veto that stops any similarity scoring immediately and keeps both documents -- confirmed by
  `test_signature_packages_both_kept_in_full` (19 identical boilerplate pages, 1 differing signature
  page: both kept in full) and by the form-field/date/dollar-amount/name-hint hard-veto test suite.
- **Extra blank pages alone never block duplicate detection, but blank-page classification is
  conservative** -- a page with a faint scanned mark, a stamp, or any raster content is never
  classified blank, confirmed by dedicated tests.
- **No isolated page is ever deleted from the middle of a document.** Blank-page tolerance strips
  only conservatively-classified-blank pages, then requires the remaining pages to match 1:1 in
  strict order with zero further insertion/deletion tolerance.
- **Duplicate/containment decisions operate only on complete logical documents**, never partial
  page ranges.
- **OG always preserves every original source occurrence, completely untouched**, regardless of any
  Final-side decision -- automated or human. This is proven independently on every run by
  `_check_no_silent_omission` and, for the new interactive-review feature specifically, by
  `test_og_and_original_files_untouched_by_exclusion` and the OG-invariance test in
  `tests/test_merging.py`.
- **Every Final exclusion, whatever the reason, is explained and auditable** -- in
  `Duplicate_Removal_Log.txt`, `Document_Version_Report.txt`, `Merged_Document_Overlap_Report.txt`,
  `Uncertain_Match_Review_Log.txt`, and `Processing_Manifest.json` -- and independently proven by
  `_check_no_unexplained_removal` and `_check_manual_exclusions_have_valid_decision_record`.
- **A human review decision is the only way an uncertain match can ever be excluded.** No automated
  code path can do this; `review_decisions.apply_review_decision()` is the sole entry point, and it
  requires an explicit document choice plus a confirmed, non-reversible action from the GUI before
  anything changes.

## 3. Duplicate / overlap / version detection logic

**Staged comparison pipeline** (never unbounded O(n^2)): cheap structural bucketing first
(non-blank page count, page dimensions, signature-field presence, form-field presence) groups only
plausible candidates together; an oversized bucket (beyond a configurable limit) falls back to the
cheaper exact-normalized-hash-only comparison for that bucket and is noted in the report, rather than
attempting full pairwise comparison at unsafe cost.

**Per-page comparator** (`content_dedup.compare_page`), used identically by both whole-document
duplicate detection and merged-package containment detection so the two never disagree about what
"the same page" means:

1. A fast exact-match shortcut fires only when normalized text hash, embedded-image bytes, form
   field values, annotation content, AND signature state all agree simultaneously.
2. Otherwise, **hard vetoes are checked first, before any similarity scoring**: signature-field
   presence/signed-state, embedded-image count, form-field values, annotation content, and
   structured dates/dollar-amounts/proper-noun name-hints. Any disagreement immediately classifies
   the pair `different_version` and both documents are kept -- no similarity score can override this.
3. Only if no hard veto fires: word-level (tokenized, not character-level) text similarity blended
   with embedded-image perceptual-hash + mean-color similarity, escalating to last-tier rendered-page
   comparison (the only module using `pypdfium2`) only when neither text nor image extraction found
   anything usable at all.

**Whole-document aggregation is always weakest-link (the minimum confidence across all compared
pages), never an average** -- a document-level average would let many agreeing pages dilute one real
difference into a falsely high score; the single weakest page must be able to veto the whole match by
itself. This was the single most important correctness finding of the whole design process.

**Confidence bands**: weakest-link >= 0.95 -> auto-remove (same version, one copy retained,
canonical copy chosen by signature/annotation preservation, fewer accidental blank pages, more
searchable text, then earliest traversal order); 0.80 <= weakest < 0.95 -> `needs_review` (both
retained, surfaced for human review); below 0.80, or any hard veto -> `different_version` (both
retained, no review flag needed unless independently uncertain).

**Merged-package containment** reuses the identical per-page comparator in a sliding-window form: a
candidate's complete non-blank page sequence is matched against contiguous runs of a larger
document's non-blank pages. A safe full match excludes only the standalone side; the merged package
is never touched. Containment matching is strictly per-container -- a document split across two
different merged PDFs is `partial_overlap` against both, never chained into a combined match against
either.

## 4. PDF Portfolio behavior

Two distinct signals are checked, deliberately not conflated:

- `/Names/EmbeddedFiles` non-empty -> every embedded attachment is extracted as a real, independent
  `SourceOccurrence` (document ID suffix `-PF-NNN`) that flows through hashing, conversion,
  deduplication, and merging exactly like any other discovered file -- **regardless of** whether
  `/Collection` is present, so an ordinary PDF that merely carries a paperclip attachment never has
  its own content wrongly excluded.
- `/Collection` present -> `is_portfolio_container=True` on the parent occurrence **only once at
  least one real embedded attachment has actually been found and spliced in as a replacement
  document** -- so ONLY THEN is the container's own page content (the generic "open this in Acrobat"
  cover/UI page) excluded from Final. It always remains in OG, untouched, like every other original
  file. (See "Post-release fix #2" above: a `/Collection` flag with zero enumerable attachments no
  longer excludes anything, since there would be nothing to replace it with.)

## 5. GUI review behavior ("Review Uncertain Matches")

The dialog lists every uncertain comparison the engine could not confirm automatically. Each
undecided match shows both documents (filename, path, document ID, page count, version
classification if known), the comparison kind and confidence, and a plain-language explanation of
why it's uncertain. Two choices are offered:

- **Keep Both** -- pre-selected by default on every match, and the only choice that requires no
  further confirmation. Nothing about any output file changes.
- **Mark as duplicate to exclude: <filename>** -- for a content-duplicate match, either document may
  be chosen; for a merged-package containment match, only the standalone side is offered (the
  merged container is never a valid choice, matching the same structural safety rule automated
  detection follows).

Clicking **Apply Decisions** gathers every currently-selected choice. If any pending choice would
exclude a document, a single blocking confirmation dialog names every document about to be excluded
and requires an explicit Yes before anything happens; answering No, or closing the dialog without
clicking Apply, changes nothing at all. Once applied, a decision is permanent (a match cannot be
re-decided) and is recorded with a timestamp and reason on the `UncertainMatch` record, which drives
a full audit trail in `Uncertain_Match_Review_Log.txt` and `Processing_Manifest.json`. Applying an
exclusion rebuilds only the Final package (OG and every original source file are provably untouched)
and reruns every integrity check before the reports are rewritten.

**A real bug found and fixed while building this**: the review dialog only ever appears after a
build has finished, by which point the engine's temporary conversion workspace has already been
cleaned up -- so rebuilding Final could not simply re-open a document's original converted PDF file.
Fixed by transparently re-extracting the exact page range for any missing document from its own
*permanent* OG output part instead (OG's page-order and per-document page-count invariants are
already independently proven by the integrity checks), verified by both a targeted regression test
and a full pipeline test.

## 6. Robert-package acceptance test

**Documented blocker**: the real "Robert package" -- the actual customer-reported lender package
referenced in the original RC2 task specification (approximately 1099 source pages expected to
reduce to approximately 619 pages in Final, with roughly 14 pre-existing exact-SHA-256 duplicate
groups) -- is not present anywhere in this repository or in this session's environment. A full
repository and filesystem search for "robert" turned up nothing but this project's own planning
notes referencing it. This session cannot run the acceptance test against the real data, and no
number in this report reproduces the real package's exact figures.

**Fallback executed, per explicit instruction covering this exact situation**: a synthetic
acceptance test (`tests/test_robert_package_regression.py`) recreates the same class of bug the real
package exposed --

- a large merged "package" PDF concatenating four distinct component documents;
- two of those exact same component documents ALSO redundantly resubmitted as standalone top-level
  files (content-identical to their copy inside the merged PDF, but byte-different due to differing
  container structure -- exactly the case exact-hash detection cannot catch, and exactly what
  inflated the real package's page count);
- two genuinely different signed/unsigned versions of one document, which must both survive; and
- a conventional exact-byte duplicate pair, proving Level 1 detection is completely unaffected.

**Result: PASS.** The merged package is retained in full; both redundant standalone resubmissions
are excluded from Final, each with a recorded, auditable containment reason; both signature-state
versions survive; the exact-duplicate pair reduces to one copy exactly as RC1 always did; every
document remains present, untouched, in OG; and every one of the 27 integrity checks passes.
Assertions in this test are entirely about which specific documents survive Final and why -- never a
fixed target page count, per the plan's explicit instruction not to force one.

## 7. Complete test counts and results

**Engine test suite** (`pytest tests/ --ignore=tests/gui`): **204 passed, 0 failed.**

Breakdown by area (approximate, by file):
conversion, splitting/merging, reporting, progress, hashing/deduplication, inventory, archive safety,
full-pipeline end-to-end, packaging/CLI/config, content fingerprinting, content-aware deduplication,
PDF rendering, PDF Portfolio (including the Final-folder-empty regression, "Post-release fix #2"
above), merged-document overlap, document version classification, validation (dedicated), the
OG-invariance safety test, expanded reporting coverage, the interactive review-decision engine, the
Robert-package synthetic acceptance test, and output-path-length safety (the MAX_PATH fix, "Post-release
fix #1" above).

**GUI test suite** (`tests/gui/`, run per-file due to a known, pre-existing, environment-specific Qt
offscreen-platform teardown instability in this sandboxed container -- confirmed nondeterministic
(reproduces on some full-process runs, not others) and unrelated to any RC2 code, since it occurs
deep inside pytest-qt/Qt's own teardown machinery in files this session never touched): **57
collected, all pass when run file-by-file.** GUI correctness is further confirmed on the real Windows
CI runner below, which does not share this container's offscreen-platform quirk.

**Total: 261 automated tests, all passing** (204 engine + 57 GUI).

## 8. Windows CI / build results

**Latest run** (includes the Final-folder-empty fix -- "Post-release fix #2" above):
[`Build Windows Portable Release` #29528680767](https://github.com/emb2514/lp/actions/runs/29528680767)
-- triggered via `workflow_dispatch` on branch `claude/lender-package-builder-stage-1-h9sa3n` at
commit `11d6229`. **Conclusion: SUCCESS**, runner `windows-latest`, total job time ~3.8 minutes
(19:36:34-19:40:21 UTC).

Every one of the 16 steps passed -- verified individually, not inferred from the overall green
checkmark:

| Step | Result |
|---|---|
| Check out repository / Set up Python 3.13 | PASS |
| Install build dependencies | PASS |
| **Run the full automated test suite on Windows** | PASS -- **258 passed, 3 skipped, 0 failed, 1 warning**, in 37.34s (261 collected total, matching the local count exactly -- includes the 2 new Portfolio/Collection regression tests) |
| Generate the multi-resolution application icon | PASS |
| Build the portable executable with PyInstaller | PASS |
| Verify the build produced `LenderPackageBuilder.exe` | PASS |
| Prove no external Python is required (`--version`/`--self-test`/`--diagnostics`/`--gui-smoke-test`, with `PYTHONHOME`/`PYTHONPATH` cleared and `PATH` reduced to only Windows system directories) | PASS |
| Prove the app runs from a space-containing path | PASS |
| Assemble the release folder / collect licenses / write build manifest | PASS |
| Zip the release and compute + immediately re-verify its SHA-256 | PASS |
| Upload the portable release artifact | PASS |

The 3 skips are the same expected, accounted-for skips as every prior run (not silent gaps): two
conversion tests skip because LibreOffice is not installed on the GitHub-hosted Windows runner (the
app's documented LibreOffice -> Office COM -> pure-Python fallback chain handles this at runtime the
same way), and one packaging test (`test_windows_console_attach_is_noop_on_non_windows`) is
specifically designed to run on non-Windows and correctly skips itself when actually running on
Windows. The single warning is Python's own `zipfile` module surfacing an intentional test fixture (a
ZIP built with a duplicate entry name), not an application defect.

**Downloadable artifact (current, includes both post-release fixes)**:
- Name: `Lender_Package_Builder_1.0.0_RC1_Windows_x64-Portable` (internal release label; contains
  RC2's full feature set -- see the note in this section's last paragraph)
- Contains: `Lender_Package_Builder_1.0.0_RC1_Windows_x64_Portable.zip` (the actual portable release,
  SHA-256 `BD5D862C50E34BC21A88316321C9CB724CAA18726C1D1FF4D8BFFA37825F50FB`) and its matching
  `..._Portable_SHA256.txt` checksum file
- Artifact size: 80,108,080 bytes (~76.4 MB)
- Artifact ID: `8387805926`, digest `sha256:452ee966c21ee6e2e089f442bbf466c2e7a3cd6ce95d26bf8bdf251e213300b9`
  (the wrapper artifact's own hash -- distinct from the release ZIP's hash above)
- Download URL: <https://github.com/emb2514/lp/actions/runs/29528680767/artifacts/8387805926>
  (expires 2026-08-15, 30-day GitHub Actions retention -- download and store it somewhere durable
  well before then if it needs to be kept)
- Inside the release folder: `LenderPackageBuilder.exe` + `_internal/` (all bundled dependencies,
  including the Windows PDFium binary for `pypdfium2`), `config.toml`, `RUN_DIAGNOSTICS.bat`,
  `README_PORTABLE.txt`, `RELEASE_NOTES_1.0.0_RC1.md`, `THIRD_PARTY_NOTICES.txt`,
  `WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md` (now updated for RC2 -- see §6/§10),
  `PACKAGING_TROUBLESHOOTING.md`, the synthetic `Sample_Test_Package.zip` +
  `Sample_Test_Package_Expected_Results.txt`, and `BUILD_MANIFEST.txt` (records the exact commit,
  CI run, and `pip freeze` lock for this specific build).

**Previous runs (kept for history only -- do not use these artifacts):**
- [#29525368003](https://github.com/emb2514/lp/actions/runs/29525368003) at commit `122d7ce`
  (MAX_PATH fix only, does NOT have the Final-folder-empty fix), 256 passed/3 skipped/0 failed,
  artifact ID `8386505901`.
- [#29517398524](https://github.com/emb2514/lp/actions/runs/29517398524) at commit `e52374b`
  (neither post-release fix), 244 passed/3 skipped/0 failed, artifact ID `8383329424`.

Both are superseded by the run above.

**`pypdfium2` native binary bundling -- specifically verified, not assumed**: inspected the
installed `pyinstaller-hooks-contrib` package directly (both locally and as installed fresh by this
CI run) and confirmed two cooperating hooks handle it correctly: `hook-pypdfium2.py` collects the
package's `version.json`, and `hook-pypdfium2_raw.py` calls `collect_dynamic_libs('pypdfium2_raw')`
to bundle the actual native PDFium shared library (`pdfium.dll` on Windows) -- the real risk case
here, since it is loaded via a relative-path `ctypes` lookup rather than a directly-importable
compiled extension module, which is exactly the pattern PyInstaller's plain static-import analysis
can miss without an explicit hook. No manual `binaries=[]` entry was needed in
`LenderPackageBuilder.spec`, and this CI run's successful `--self-test`/`--gui-smoke-test` steps
(which exercise the content-aware detection pipeline, including `pdf_render.py`, the only module
that imports `pypdfium2`) are the real-Windows proof this bundling actually works end to end.

**Note on the release label**: this build's internal `RELEASE_LABEL`/`RELEASE_NAME` still reads
`1.0.0_RC1`, because `_version.py`'s single-source version string was not bumped as part of this
RC2 work (out of scope -- the task asked for RC2's functionality and validation, not a version/naming
change, and bumping it unilaterally would be exactly the kind of unrelated naming work the task
explicitly said not to start). The artifact's actual contents are the complete RC2 feature set
described in this report; only the version string itself has not yet been advanced.

## 9. Known limitations

- **Merged-vs-merged overlap** (two large binders sharing overlapping sections) is explicitly out of
  scope -- only standalone-document-inside-a-merged-package containment is detected. This was an
  intentional scope decision (not in the task's own examples, substantial added complexity, and the
  reported real-world scenario is exactly the standalone-in-merged case).
- **Email attachments** (`.msg`/MIME) become synthetic, ephemeral occurrences local to the email
  converter and never enter the real occurrence list RC2's content-aware detection scans -- a PDF
  email attachment identical to a separately-supplied top-level PDF cannot currently be matched. This
  predates RC2 and was explicitly out of scope for this task (only PDF Portfolios were in scope for
  the "embedded attachment" case).
- **PDF Portfolio attachment ordering** relies on pypdf's verified `/Names` name-tree walk order as
  the primary signal; true Adobe Acrobat Portfolio UI ordering can additionally be influenced by
  per-item `/CI` metadata with no documented high-level pypdf API, which was judged riskier to
  hand-parse speculatively. This is a known limitation to verify against a real Adobe-generated
  Portfolio during manual acceptance testing -- synthetic test fixtures cannot by themselves prove
  Acrobat's own ordering conventions are handled.
- **Confidence-band thresholds** (0.95 auto-remove, 0.80 needs-review) are principled defaults, not
  empirically tuned against the real Robert package (unavailable, see §6) -- they should be revisited
  once real-world usage data is available.
- **The real Robert package acceptance test could not be run** -- see §6's documented blocker. The
  synthetic recreation exercises the same bug class but cannot substitute for validation against the
  actual reported data.
- **The whole-process GUI test suite** intermittently segfaults in this specific sandboxed Linux
  container (pre-existing since before RC2, unrelated to any RC2 change, confirmed nondeterministic
  and confirmed absent from the per-file GUI runs and from real Windows CI).

## 10. Installing and running (for a nontechnical Windows 11 user)

1. Download the release from the Windows CI build artifact:
   <https://github.com/emb2514/lp/actions/runs/29528680767/artifacts/8387805926> (requires being
   signed in to GitHub with access to this repository; the artifact expires 2026-08-15). Inside is
   `Lender_Package_Builder_1.0.0_RC1_Windows_x64_Portable.zip` -- no account, license key, or
   installer is required beyond that GitHub download step.
2. Right-click the downloaded ZIP and choose **Extract All...**, then pick any folder (Desktop,
   Documents, or a USB drive all work).
3. Open the extracted folder and double-click **LenderPackageBuilder.exe**.
   - No Python, pip, Git, Visual Studio, or internet connection is required to run it -- everything
     needed is already inside the extracted folder.
   - Windows SmartScreen may show a blue "Windows protected your PC" warning the first time, because
     the .exe is not signed with a paid code-signing certificate. Click **More info**, then
     **Run anyway**. This is expected for an independent, unsigned tool and is not a sign of a
     problem with the download.
4. Drag a ZIP file, folder, or single document onto the window (or click to browse), review the
   Advanced Settings if needed (the defaults are recommended for almost everyone), and click
   **Build Lender Packages**.
5. When it finishes, the app shows exactly what happened, with buttons to open the Output folder,
   the Final package folder, and the Reports folder directly. If any comparison needed a human
   decision, a **Review Uncertain Matches** button appears -- reviewing it is optional; both
   documents are always safely kept until and unless you explicitly decide otherwise there.
6. To move the app, copy the whole extracted folder -- everything it needs travels together. Nothing
   is written outside that folder except its own settings/log files under
   `%LOCALAPPDATA%\LenderPackageBuilder`.

For a full manual acceptance-test checklist (recommended before trusting this build with real
borrower data), see `WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md` in the same release folder.
