# CHECKPOINT — RC2 Content-Aware Deduplication Upgrade

## NEW WORK IN PROGRESS: "Document Merger" naming/workflow overhaul (Milestones 1-6)

A large new task spec (post-RC2, all of it on top of the validated RC2 baseline at commit
`04ee3b1` / Windows CI run 29608871958 documented below) requests six milestones: (1) output
folder/filename naming overhaul, (2) safe Cancel Processing, (3) rename the visible product to
"Document Merger", (4) a key-document page locator/extraction feature, (5) a Compare Packages
engine, (6) a Compare Packages GUI workspace. Working through these autonomously, one milestone
at a time, each committed and pushed separately so progress is never lost mid-flight.

**MILESTONE 1 COMPLETE -- Output folder structure and naming.** New `naming.py` module is now the
single source of every user-facing output name, driven by a new `PackageIdentity` (last name,
first name, loan number, adverse flag) dataclass in `models.py`:

- **Main output folder**: `Last Name, First Name, Loan Number` (e.g. `True, Michael,
  6192278785`), or `Last Name, First Name, Adverse, Loan Number` for a non-proceeding file. No
  underscores, no awkward double commas when a field is blank. Collisions are never overwritten --
  `naming.resolve_versioned_output_dir()` appends `, v2`, `, v3`, ... automatically.
- **Folder consolidation**: the old five-folder layout (`OG`, `Final`, `Reports`,
  `Unconverted_Files`, `Logs`) is now just `Final` and `Reports`, plus `Unconverted Files`
  (space, not underscore) created lazily only when a file actually could not be converted -- an
  empty folder is never shipped. The Original Lender Package now lives directly inside `Final`
  alongside the deduplicated Final package; `run.log` now lives inside `Reports`. No separate `OG`
  or `Logs` folder is ever created.
- **Package filenames**: `Last Name, First Name, Lender Package.pdf` (single part) or `..., Part
  001.pdf` (three-digit, only added when there is more than one part) for Final; `..., Original
  Lender Package.pdf` / `..., Original Lender Package, Part 001.pdf` for OG. `merging.write_package()`
  now writes to temporary filenames first (since the final name depends on the settled total part
  count) and renames once part planning settles, rather than rebuilding the PDF twice.
- **Key-document filename convention** (`naming.key_document_filename()`) is implemented and
  tested now, ready for Milestone 4's extraction engine to call: `Last Name, First Name, Document
  Name, Signature Status, Loan Number.pdf`, with `person_name_override` for a second borrower's own
  document (e.g. a co-borrower's Driver's License) and `copy_suffix` for `, Copy 2` etc.
- **`review_decisions._rebuild_final_and_reports()`** was fixed to delete only the exact Final
  part files it is about to replace (via `run.final_parts`), never a `*.pdf` glob over the shared
  Final folder -- a glob would now also delete the Original Lender Package and any future extracted
  key documents sitting alongside Final in the same folder.
- **GUI**: a new `PackageIdentityDialog` ("Confirm package details") appears after Advanced
  Settings validation and any large-input confirmation, before a build starts -- collects last
  name (required), first name, loan number, and an adverse/non-proceeding checkbox, with a live
  preview of the exact output folder name. Continue is disabled until a last name is entered.
- **CLI**: `--last-name`, `--first-name`, `--loan-number`, `--adverse` flags feed the same
  `PackageIdentity` path for headless/scripted use.
- **Backward-compatible fallback**: a caller that supplies no identity at all (a headless/library
  `build_package()` call with no borrower info) keeps the original input-filename-derived,
  timestamped folder name rather than erroring -- the GUI always supplies an identity, so this only
  affects programmatic callers that opt out of it.
- 24 new naming-unit tests (`tests/test_naming.py`), 8 new pipeline-level folder-structure tests
  (`tests/test_output_structure.py`), 5 new dialog tests (`tests/gui/test_package_identity_dialog.py`).
  Updated `tests/test_review_decisions.py`, `tests/gui/test_uncertain_review_dialog.py`, and the
  GUI large-input/advanced-settings tests for the new `write_package()`/`_start_build()` signatures,
  plus an autouse GUI-test fixture (`tests/gui/conftest.py`) that auto-confirms the new pre-build
  dialog so existing tests don't block on a real modal. Local suite: 244 engine + 62 GUI = 306
  total, all passing (up from 212/57 at the RC2 baseline).

**MILESTONE 2 COMPLETE -- Safe abort (Cancel Processing).** New `cancellation.py` module:
`CancellationToken` (a thin `threading.Event` wrapper) plus `check_cancelled()`, a single-call
check point that raises `ProcessingCancelled` when requested. Cooperative only -- nothing ever
force-kills the worker thread.

- **Check points threaded through the real pipeline**, not just top-level stage boundaries: the
  per-document conversion loop, `merging.write_package()`'s per-part loop (both the size-check
  rebuild loop and the temp-to-real-filename promotion loop), `inventory.py`'s per-file folder
  and per-entry ZIP traversal loops (covers "during inventory"/"during archive extraction"),
  `content_dedup.build_fingerprints()`'s per-document loop and `detect_content_duplicates()`'s
  per-bucket loop, and `overlap_detection.detect_overlaps()`'s per-candidate loop -- so a long
  fingerprinting/comparison stage on a large real package stops within about one document's worth
  of work, not only between whole stages.
- **`build_package()`** accepts an optional `cancellation_token`; catching `ProcessingCancelled`
  routes to a new `_finish_cancellation()` that: deletes the workspace's temp files regardless of
  `keep_temp` (a deliberate cancel always cleans up); deletes any partial Final/Original Lender
  Package parts and any partial `Unconverted Files` copies (never leaves a partial PDF under a
  real package filename); deletes the normal reports and writes a distinct
  `Reports/Cancellation_Report.txt` instead (never the normal success-only reports); and, only if
  that cleanup itself fails (e.g. a locked file), renames the whole output folder to a versioned
  `Incomplete Cancelled Output` folder rather than leaving a broken folder under the identity's
  normal name. Raises `ProcessingCancelledError` (new in `exceptions.py`) carrying the stage
  cancelled at, the final output path, and whether cleanup succeeded -- never returns a
  `RunResult`, so a cancelled run can never be mistaken for success or a normal failure.
- **GUI**: `ProgressView` gets a "Cancel Processing" button; clicking it shows a new
  "Stop processing this package?" confirmation (Continue Processing / Stop Processing, per the
  spec) via `dialogs.confirm_cancel_processing()` -- only an explicit Stop Processing calls
  `CancellationToken.request()`. `CallableWorker` gets a distinct `cancelled` signal (separate
  from `failed`) carrying the `ProcessingCancelledError`, so `FailureView.set_cancelled()` shows a
  clearly distinct amber "Processing was cancelled" banner (never the red failure banner or the
  green success banner) with the stage, cleanup status, and a reminder that source files were
  never touched. Processing can be restarted immediately afterward with no app restart -- the
  identity-based output-folder versioning from Milestone 1 means a retry with the same identity
  just becomes ", v2" automatically.
- A real threading hazard was found and fixed while writing the end-to-end GUI test: connecting a
  plain Python function directly to a cross-thread Qt signal executes it on the EMITTING (worker)
  thread rather than queuing it onto the main thread, which is unsafe for touching widgets --
  the fix (in the test only) was hooking the already-connected bound QObject method
  (`MainWindow._on_progress_event`) instead, which Qt correctly queues across threads.
- 12 new engine-level tests (`tests/test_cancellation.py`: token semantics, cancellation at
  multiple real stages, no partial package/no success-only reports left behind, source files
  never modified, immediate retry after cancellation succeeds) and 6 new GUI tests
  (`tests/gui/test_cancellation_gui.py`, including one real-background-thread end-to-end
  cancellation through the actual worker). Local suite: 256 engine + 68 GUI = 324 total, all
  passing (up from 244/62 after Milestone 1).

Milestone 3 (rename the visible product to "Document Merger") is next.

---

**POST-RELEASE FIX #8 (release naming correction, direct user feedback)**: fix #7's
`LP_Builder_RC2_<shortsha>_...` naming still wasn't right -- the user explicitly rejected the
7-character git-commit-hash suffix (e.g. `ad00fd8`) as meaningless clutter in a user-facing filename.
Replaced it with `$env:GITHUB_RUN_NUMBER` (a plain, ever-increasing integer -- this workflow's own
build count), giving a clean `LP_Builder_v<N>_Windows_x64_Portable.zip` pattern -- exactly the
"v1, v2, v3..." style the user had already been doing by hand before asking for this to be automated.
Still guaranteed unique per build; `RELEASE_LABEL` ("RC2") is retained internally (BUILD_MANIFEST.txt,
`--version` output) but no longer appears in the filename itself. Committed as `55dbe55`, pushed, and
**re-validated on real Windows CI** (run
[29608871958](https://github.com/emb2514/lp/actions/runs/29608871958), build #18, SUCCESS, 266
passed/3 expected skips/0 failed -- matches local exactly). Artifact is literally named
`LP_Builder_v18_Windows_x64-Portable` (ID `8417997302`), release ZIP SHA-256
`71827A8191F64F57BC80A6E3BCD31C4EC28430AFFD3745EDFF85B9CFA47E972A` -- confirms the new naming works
exactly as intended. See `RC2_DELIVERABLE_REPORT.md` §8/§10 for the current download link.

**POST-RELEASE FIX #7 (Explorer "Path too long" extracting the ZIP, real user report) + release
naming/version overhaul (explicit user request)**: the user's Windows Explorer failed to extract the
fix-#6 ZIP with "Error 0x80010135: Path too long" on `iso_schematron_skeleton_for_xslt1` (an XSL
Stylesheet). Root cause, confirmed by direct inspection: `lxml` is a real, needed transitive dependency
(`python-docx` uses `lxml.etree` for .docx parsing), but `pyinstaller-hooks-contrib`'s `hook-lxml.py`
unconditionally `collect_submodules('lxml')`s -- including `lxml.isoschematron`, an unrelated ISO
Schematron XML-validation submodule confirmed (via grep across this app and python-docx) to never be
imported anywhere in this app's dependency graph. That submodule's own hook then bundles its entire
`resources/` tree unconditionally, whose deepest file
(`isoschematron/resources/xsl/iso-schematron-xslt1/iso_schematron_skeleton_for_xslt1.xsl`) is ~90
characters of nested path on its own -- enough, combined with a normal Downloads-folder path, to push
the full extracted path over Windows Explorer's classic 260-character extraction limit (a different
mechanism than this app's own MAX_PATH handling for output folders it creates itself -- Explorer's
built-in Zip extraction is not long-path-aware). Fixed by adding `"lxml.isoschematron"` to
`LenderPackageBuilder.spec`'s `Analysis(excludes=[...])` -- removes ~30 unused files with no effect on
real functionality (confirmed PySide6's own per-module hooks mean the app's unused QtQuick/QML tree,
whose deepest paths are even longer, was never bundled either, since this is a QtWidgets-only app).
1 new regression test (`tests/test_stage3_packaging.py`) parses the spec file's AST to assert the
exclude is present, guarding against an accidental future revert.

**Separately, per explicit user request** ("that needs to be LP Builder v(whatever version the next
one is)"): the release naming was overhauled. `_version.py` (the single authoritative version source)
bumped from `1.0.0 RC1` / `RELEASE_LABEL="1.0.0_RC1"` to `USER_VERSION="RC2"` /
`RELEASE_LABEL="RC2"` / `__version__="1.0.0rc2"` / `WINDOWS_FILE_VERSION="1.0.0.2"` -- reflecting the
milestone this entire session's work has consistently been called throughout (this CHECKPOINT's own
title). The hardcoded `Lender_Package_Builder` release-folder/ZIP prefix (in both
`build-windows-portable.yml` and `BUILD_WINDOWS_PORTABLE.bat`) was shortened to `LP_Builder`, so a
build's release ZIP is now named `LP_Builder_RC2_<shortsha>_Windows_x64_Portable.zip` -- short, human-
readable, and still unique per build (the short-commit-SHA fix from fix #5 is retained). Updated the two
hardcoded version-string assertions in `tests/test_stage3_packaging.py` to match, and updated
forward-looking (non-historical) filename references in `README_PORTABLE.txt`,
`STAGE3_BUILD_AND_RELEASE.md`, and `WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md` to describe the new pattern
generically rather than hardcoding the old exact name. Local suite: 212 engine + 57 GUI = 269 total,
all passing. Committed as `ad00fd8`, pushed, and **re-validated on real Windows CI** (run
[29607844766](https://github.com/emb2514/lp/actions/runs/29607844766), SUCCESS, 266 passed/3 expected
skips/0 failed -- matches the local 269-collected count exactly; job log directly confirms
`test_spec_excludes_lxml_isoschematron` PASSED, and no isoschematron-related PyInstaller warning
appears anywhere in the build log). New artifact `LP_Builder_RC2_ad00fd8_Windows_x64-Portable`
(ID `8417625480`), release ZIP SHA-256
`6E92B4BF6DC3658198F858DD8782D489E3072CCFA656B1E003D5B46B9521F46C` -- see
`RC2_DELIVERABLE_REPORT.md` §8/§10 for the current download link.

**POST-RELEASE FIX #6 (real-package validation: SUCCESS, plus one report-accuracy bug found via
manual manifest cross-check)**: the user ran their real ~212-document package on the fix-#5 build and
shared all five generated reports. Result: **OVERALL RESULT: SUCCESS, all 27 integrity checks
passed**, run time ~10.6 minutes (down from ~35 minutes pre-fix-#3) -- direct, real-world confirmation
that fixes #1-#5 all work correctly together on the actual reported package. Specifically verified: the
DOC-000159 -> DOC-000153 -> DOC-000152 chain that broke in fix #4/#5's scenario now resolves correctly
(DOC-000153 is fully contained in DOC-000152 but stays in Final because DOC-000159 depends on it,
exactly as fix #4 intended). While cross-checking the human-readable reports against the authoritative
`Processing_Manifest.json` (212 - 174 = 38 excluded: 25 exact + 9 content-duplicate + 4 contained, all
independently verified against `included_in_final`), found a real discrepancy: `Duplicate_Removal_Log.txt`
claimed 11 normalized/content-equivalent duplicates removed, but only 9 were actually excluded -- 2
occurrences (DOC-000011, DOC-000012) are non-canonical members of a confirmed "same" group AND
separately carry an unrelated uncertain pairwise result (`needs_review=True`), which correctly keeps
them in Final (per `included_in_final`) but the log listed them as removed anyway. Root cause:
`reporting.write_duplicate_removal_log()` counted/listed every `ContentDuplicateGroup` member
unconditionally, never checking `needs_review`. This is a report-accuracy bug only -- Final's actual
contents were always correct, confirmed independently via the manifest -- but a misleading audit trail
undermines the app's core trust guarantee. Fixed by skipping (and not counting) any group member whose
`needs_review` is True in both the per-method sections and the total. 1 new regression test in
`tests/test_reporting_v2.py`, confirmed failing before the fix (old code reported "2" instead of "1"
for a group with one protected member) and passing after. Local suite: 211 engine + 57 GUI = 268 total,
all passing. Committed as `72cf1b8`, pushed, and **re-validated on real Windows CI** (run
[29606148402](https://github.com/emb2514/lp/actions/runs/29606148402), SUCCESS, 265 passed/3 expected
skips/0 failed -- matches the local 268-collected count exactly). New artifact ID `8416986057`, release
ZIP SHA-256 `97DAE9C4429E38A9729C43704365E40632F94311FB86AB00DB84C937D0C1126D` -- see
`RC2_DELIVERABLE_REPORT.md` §8/§10 for the current download link.

**POST-RELEASE FIX #5 (same bug class as fix #4, reached through the interactive review pathway) +
release-artifact filename fix**: after fix #4 shipped, the SAME validation failure recurred on the
SAME document ID ('DOC-000159') on the rebuilt artifact -- confirmed by the user this was NOT a stale
download. Root cause, confirmed by direct reproduction: `review_decisions.apply_review_decision()`
(the ONLY code path that applies a human's "exclude" choice from the "Review Uncertain Matches" GUI
dialog) sets `manually_excluded=True` on the chosen document with NO check for whether some OTHER,
completely unrelated occurrence was already relying on that same document as ITS retained
content-duplicate target or merged-document container -- content_dedup.py and overlap_detection.py
have their own mutual protection against this (fix #4), but a human reviewing one uncertain match has
no visibility into an already-CONFIRMED, unrelated content-duplicate relationship elsewhere in a
212-document package. Excluding that document orphaned the reference exactly like fix #4's scenario,
just reached through a third, previously-unguarded path. Fixed by adding
`_rescue_orphaned_dependents()`: whenever a document is manually excluded, any other occurrence that
was automatically excluded BECAUSE of it (`content_duplicate_of_document_id` or
`contained_in_document_id` pointing to the now-excluded document) is restored to Final -- the only safe
direction, since it is no longer provably redundant with anything actually present in Final. 2 new
regression tests in `tests/test_review_decisions.py` (a direct reproduction plus a full end-to-end
pipeline test using real content matching, not mocks, for the confirmed pair), both confirmed failing
before the fix and passing after. Also fixed, per direct user feedback: every CI rebuild produced the
byte-for-byte identical release ZIP filename, forcing manual renaming to avoid collisions across
multiple downloads -- `build-windows-portable.yml` now appends the short git commit SHA to
`RELEASE_NAME`, so every build's filename (and GitHub Actions artifact name) is automatically unique;
the app's own version string (`RELEASE_LABEL`) is untouched. Local suite: 210 engine + 57 GUI = 267
total, all passing. Committed as `cc02467`, pushed, and **re-validated on real Windows CI** (run
[29600140245](https://github.com/emb2514/lp/actions/runs/29600140245), SUCCESS, 264 passed/3 expected
skips/0 failed -- matches the local 267-collected count exactly). New artifact ID `8414739955` -- note
the artifact/release-ZIP name now correctly includes the commit SHA
(`Lender_Package_Builder_1.0.0_RC1_cc02467_Windows_x64_Portable.zip`), confirming the filename fix
itself works. Release ZIP SHA-256 `2030A3264E7666774ECCAF2E7E32E706A800643ADFF8EA363C52BA96CD60265D`
-- see `RC2_DELIVERABLE_REPORT.md` §8/§10 for the current download link (all earlier artifacts are
missing at least this fix and should not be used).

**POST-RELEASE FIX #4 (integrity check correctly caught a real cross-module bug: orphaned
content-duplicate reference)**: after fix #3 let a real ~900-page package finish "Analyzing document
content" (in ~35 min on the OLD, pre-fix-#3 build the user was still running -- not a new stall), the
run correctly reported failed integrity checks rather than shipping something unreliable: "1
content-duplicate(s) reference a retained document missing from Final: ['DOC-000159']". Root cause,
confirmed by direct reproduction: `content_dedup.py` designates one document per group as the
"retained" canonical that every other content-equivalent copy's `content_duplicate_of_document_id`
points to, but `overlap_detection.py` runs AFTERWARD and had no awareness of this -- if it later found
that same canonical document fully, confidently contained inside a separate larger merged package, it
excluded it from Final (`is_contained_in_merged_document=True`) with no knowledge that another
occurrence was relying on it staying present. This orphaned the content-duplicate reference: the
duplicate was correctly excluded, but its "retained" copy vanished too, leaving that content with zero
copies in Final. validation.py's own `_check_content_duplicate_retained_exists` integrity check did
exactly its job -- it caught this and safely blocked the run rather than producing a broken package
("Processing finished, but one or more required integrity checks did not pass. This output should not
be treated as reliable.") -- but the underlying cross-module interaction needed fixing at the source.
Fixed two ways: (1) `overlap_detection.detect_overlaps()` now never excludes a candidate that is
currently serving as another occurrence's retained content-duplicate target, even on a fully-proven
containment match -- the finding is still recorded for the report, the candidate (and everything
depending on it) simply stays in Final, exactly like the existing "different_version"/"partial_overlap"
cases already do. (2) `content_dedup._select_canonical()` now also proactively never chooses a PDF
Portfolio container as canonical (its own pages are unconditionally excluded from Final regardless of
anything else -- the identical bug class, but knowable in advance since `is_portfolio_container` is
decided during inventory building, long before content_dedup runs). 3 new regression tests (2 direct
module-level reproductions in `tests/test_merged_document_overlap.py` and `tests/test_content_dedup.py`,
plus a full end-to-end `run_build` test reproducing the exact "26/27 integrity checks passed" symptom)
-- all three confirmed failing before the fix and passing after. Local suite: 208 engine + 57 GUI = 265
total, all passing. Committed as `e6f32ff`, pushed, and **re-validated on real Windows CI** (run
[29598340493](https://github.com/emb2514/lp/actions/runs/29598340493), SUCCESS, 262 passed/3 expected
skips/0 failed -- matches the local 265-collected count exactly). New artifact ID `8414035077`, release
ZIP SHA-256 `349A0B50865EFDD9B9DA93A58312E2869730383561736B512F856454F6E101C7` -- see
`RC2_DELIVERABLE_REPORT.md` §8/§10 for the current download link (all earlier artifacts are missing at
least this fix and should not be used).

**POST-RELEASE FIX #3 (severe performance bug on real scanned documents)**: a real user reported the
app appeared stuck for 10+ minutes on stage "[5/10] Analyzing document content..." while processing a
real 212-document, ~900-page lender package containing several large (86-155 page) scanned PDFs.
Root cause, confirmed by direct timing reproduction: `pdf_content.py`'s `_average_color()` and
`_classify_image_blank()` (run once per embedded image, for every page of every document, during
fingerprinting) materialized every pixel of the decoded image into a Python list and summed it in a
pure-Python loop. For a realistic full-resolution scan (~1700x2200px, a typical 200 DPI letter-size
page), this took **~3 seconds per image** (0.29s blank-check + 2.68s average-color, measured directly)
-- for the four largest documents in the reported package alone (155+126+95+86 = 462 pages), that is
roughly **23 minutes**, fully explaining the reported stall. Fixed by using Pillow's own C-implemented
`ImageStat` (mean/variance) and `Image.histogram()` (dark-pixel count) instead of Python-level
per-pixel loops -- mathematically identical results (verified directly, matching to 4+ decimal places),
~13-100x faster per image. A 155-page synthetic scanned PDF that would have taken minutes to
fingerprint under the old code now fingerprints in ~11 seconds end to end. 1 new performance-regression
test in `tests/test_content_fingerprinting.py` (asserts realistic-resolution processing stays under a
generous 2-second ceiling, not a specific value -- correctness is already covered by the existing
blank-classification and `average_color` tests, all of which still pass unchanged). Local suite: 205
engine + 57 GUI = 262 total, all passing. Committed as `2b1da0e`, pushed, and **re-validated on real
Windows CI** (run [29596759299](https://github.com/emb2514/lp/actions/runs/29596759299), SUCCESS, 259
passed/3 expected skips/0 failed -- matches the local 262-collected count exactly). New artifact ID
`8413426018`, release ZIP SHA-256 `DAEECC94FA7AE2F7976E944AC1681EE13544491C4A4FC711F70EFBE5E955B15B`
-- see `RC2_DELIVERABLE_REPORT.md` §8/§10 for the current download link (all three earlier artifacts
are missing at least this fix and should not be used).

**POST-RELEASE FIX #2 (Final folder silently empty)**: a real user reported that a rebuilt package
("packaged successfully") produced a completely empty `Final` folder. Root cause, confirmed by direct
reproduction: `pdf_portfolio.py`'s `_expand_one()` set `occurrence.is_portfolio_container = True`
(which unconditionally excludes a document's own pages from Final) whenever a PDF's `/Root` dictionary
carried a `/Collection` entry — **regardless of whether any actual embedded attachments were found to
replace it with**. A PDF can carry `/Collection` (a leftover/cosmetic Portfolio flag from whatever tool
assembled it, e.g. some loan-origination/document-binder software) with zero attachments pypdf's
`.attachments` can enumerate. When that happened, the document was excluded from Final with **zero**
replacement children spliced in — and because `is_portfolio_container` is treated as an "explained"
removal reason, every integrity check still passed and the run reported success. If such a PDF was the
only (or dominant) file in the package, Final came out completely empty. Fixed by reordering
`_expand_one()` so `is_portfolio_container` is only ever set once real replacement attachments have
actually been found and spliced in as children — a `/Collection`-flagged PDF with no enumerable
attachments now stays an ordinary standalone document instead of vanishing. 2 new regression tests in
`tests/test_pdf_portfolio.py` (a direct reproduction plus a full end-to-end pipeline run), both
confirmed failing before the fix and passing after. Local suite: 204 engine + 57 GUI = 261 total, all
passing. Committed as `11d6229`, pushed, and **re-validated on real Windows CI** (run
[29528680767](https://github.com/emb2514/lp/actions/runs/29528680767), SUCCESS, 258 passed/3 expected
skips/0 failed — matches the local 261-collected count exactly). New artifact ID `8387805926`, release
ZIP SHA-256 `BD5D862C50E34BC21A88316321C9CB724CAA18726C1D1FF4D8BFFA37825F50FB` — see
`RC2_DELIVERABLE_REPORT.md` §8/§10 for the current download link (the artifact from run `29525368003`
does NOT have this fix and should not be used).

**POST-RELEASE FIX #1, RE-VALIDATED ON WINDOWS CI**: a real user hit `FileNotFoundError: [WinError 3]`
on `Path.mkdir()` when building a package from a file with a very long, browser-downloaded/
URL-derived filename -- the derived output folder name exceeded Windows' 260-char MAX_PATH limit
despite `app.manifest` declaring `longPathAware="true"` (proven insufficient by this real crash).
Fixed in `cli.py`: `_compute_output_dir`, `_unique_destination`, and `_copy_extra_preserved_file`
now all proactively shorten any filesystem name derived from arbitrary input via a new shared
`_shorten_for_filesystem()` helper (extension-preserving, headroom-aware, leaves normal filenames
untouched). 12 new regression tests in `tests/test_output_path_safety.py`, including a full pipeline
run using the exact shape of the filename that crashed. Committed as `122d7ce`, pushed, and
**re-validated on real Windows CI** (run
[29525368003](https://github.com/emb2514/lp/actions/runs/29525368003), SUCCESS, 256 passed/3 expected
skips/0 failed). New artifact ID `8386505901` -- see `RC2_DELIVERABLE_REPORT.md` §8/§10 for the
current download link (the artifact from the earlier run does NOT have this fix and should not be
used).

**STATUS: RC2 COMPLETE.** All planned engine modules, GUI work, the interactive uncertain-match
review workflow, the (documented-blocked, synthetically-substituted) Robert-package acceptance test,
the GitHub Actions Node-deprecation fix, and real Windows CI validation are all done, all green, and
the portable Windows artifact has been built and verified. **See `RC2_DELIVERABLE_REPORT.md` at the
repo root for the complete, final deliverable** (features, safety behavior, detection logic, Portfolio
behavior, GUI review behavior, Robert-package results, test counts, Windows CI/build results, known
limitations, exact artifact location, and install/run instructions for a nontechnical Windows 11
user). This CHECKPOINT.md file remains as the detailed development history/resume record; the
deliverable report is the user-facing summary.

**Final numbers**: 190 engine tests + 57 GUI tests = **247 total, all passing** locally; **244 passed,
3 expected skips, 0 failed** on real Windows CI (run
[29517398524](https://github.com/emb2514/lp/actions/runs/29517398524), commit `e52374b`+one docs
commit -- see §4 for the exact final commit). Portable Windows artifact built, uploaded, and verified
runnable with no external Python/pip/Git/Visual Studio/internet dependency.

**A real, non-trivial bug was found and fixed while building this feature**: the review dialog only
ever appears after a build has already finished, by which point the pipeline's temporary conversion
workspace has already been deleted (`workspace.Workspace.cleanup()`) — so rebuilding Final after a
manual exclusion decision could not simply re-read each document's original `converted_pdf_path`. Fixed
in `review_decisions.py` by transparently re-extracting any missing document's exact page range from
its own **permanent** OG output part instead (OG's page-order/page-count invariants are already
independently proven by validation.py's own integrity checks). Caught by a full-pipeline test
(`test_review_decisions.py::test_full_pipeline_produces_and_can_decide_a_real_uncertain_match`), then
pinned down with a dedicated deterministic regression test. This would otherwise have crashed on every
real-world use of the exclude-a-document feature.

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
   regardless of `/Collection`; `/Collection` present AND at least one attachment was actually found and
   spliced in as a replacement child → `is_portfolio_container=True` (only then are the container's own
   pages excluded from Final — see POST-RELEASE FIX #2 above: a `/Collection` flag with zero enumerable
   attachments no longer excludes anything). Verified against real pypdf-built fixtures, not assumed.
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
14. **`reporting.py`** — expanded. `write_duplicate_removal_log()` now has 4 sections: "EXACT BYTE
    DUPLICATES" (unchanged content, reformatted) plus one section per content-aware method
    (`normalized_pdf` → "NORMALIZED PDF DUPLICATES", `content_equivalent` → "CONTENT-EQUIVALENT
    DUPLICATES", `blank_page_tolerant` → "BLANK-PAGE-TOLERANT DUPLICATES"), each with a description,
    count, and per-item detail block (removed/retained filename+path+ID, detection method, confidence,
    page count, blank-pages-ignored count when applicable). New `write_document_version_report()` →
    `Document_Version_Report.txt` (per-family version breakdown, RETAINED/EXCLUDED status per member via
    `included_in_final`, `_final_exclusion_reason()` helper covering all 4 exclusion categories). New
    `write_merged_overlap_report()` → `Merged_Document_Overlap_Report.txt` (PDF Portfolios detected +
    their attachments; containment findings grouped by classification, with the structural-safety-rule
    explanation for `exact_contained`/`equivalent_contained`). `write_processing_manifest()` explicitly
    now includes `content_duplicate_groups`, `document_families`, `overlap_findings`,
    `content_dedup_notes` (the manifest dict is hand-built per-field, NOT a blind `asdict(run)` — this
    was a real gap, now fixed and covered by a dedicated test). `write_all_reports()` calls all 5 report
    functions.
15. **`tests/test_reporting_v2.py`** (NEW, 7 tests) — end-to-end (via `run_build`, not hand-built
    `RunResult` objects) coverage of the reporting.py expansion above: all 4 duplicate-log method
    sections present with correct detail; Document_Version_Report.txt lists families/versions/
    retention status correctly (including the "no families" empty case); Merged_Document_Overlap_Report.txt
    lists both detected Portfolios+attachments and containment findings with the correct outcome text;
    Processing_Manifest.json carries all 4 new RC2 fields; all 5 report files still generate cleanly
    (with empty-but-present RC2 sections) when `enable_content_aware_dedup=False`.
16. **`tests/test_validation.py`** (NEW, 17 tests) — dedicated unit tests calling the 5 new
    `validation.py` check functions directly (`_check_final_contains_all_included`,
    `_check_no_unexplained_removal`, `_check_needs_review_never_excluded`,
    `_check_content_duplicate_retained_exists`, `_check_contained_in_document_retained_exists`),
    exercising both their PASS and FAIL branches with hand-built `SourceOccurrence` objects — proving
    each check actually catches the specific safety violation it exists to catch (e.g. an exclusion flag
    set with no explanation, a `needs_review` occurrence also excluded, a duplicate/containment reference
    pointing at a broken or missing target), not just that it passes on the happy path. Plus one
    end-to-end sanity test confirming all 5 appear in `run.integrity_checks` (26 total) and all pass on a
    real run.
17. **`tests/test_merging.py`** (NEW, 2 tests) — the dedicated OG-invariance safety test: one real
    `run_build` package triggers all 4 current RC2 Final-exclusion reasons at once (exact-hash duplicate,
    content-aware/normalized_pdf duplicate, PDF Portfolio container, standalone-contained-in-merged-
    package) and asserts every single non-ignored occurrence is present in OG regardless, OG's total page
    count equals the sum of every non-ignored document's own page count, and every Final exclusion has an
    auditable reason.
18. **GUI: `gui/widgets/uncertain_review_dialog.py`** (NEW) — read-only `QDialog` (never an approval
    workflow) listing every `needs_review=True` occurrence in a 3-column read-only `QTableWidget`
    (File / Document ID / Why it needs review, populated from `occ.review_reason`), with a heading that
    explains both copies were already safely kept and no action is required, and a clean "no uncertain
    matches" empty state when nothing is flagged. Opened from a new "Review Uncertain Matches" button on
    `ResultView` (`_open_uncertain_review_dialog`, follows the exact same self-contained-button pattern
    as the existing Open Output/Final/Reports Folder buttons — no round-trip through `MainWindow`).
19. **GUI: advanced-settings toggle** — new `AdvancedSettingsValues.enable_content_aware_dedup: bool`
    (`gui/state.py`); `AdvancedSettingsWidget` gained a `default_enable_content_aware_dedup` constructor
    param, a `QCheckBox` ("Enable content-aware duplicate detection", tooltip explains the fallback
    behavior when off), included in `get_values()`/`reset_to_defaults()`. `main_window.py` passes
    `self.config.enable_content_aware_dedup` into the widget at construction and threads
    `values.enable_content_aware_dedup` through the existing `dataclasses.replace(self.config, ...)` call
    in `_on_build_clicked()` — this is the only production code change in `main_window.py`, no other
    orchestration logic touched.
20. **GUI: `result_view.py` new stat rows** — `_populate_stats` gained 5 new rows derived directly from
    real `SourceOccurrence`/`RunResult` RC2 fields (not the checkpoint's earlier placeholder wording,
    which was written before the exact field names existed): "Content-aware duplicates excluded from
    Final" (`is_content_duplicate` count), "Merged-package duplicates excluded from Final"
    (`is_contained_in_merged_document` count), "PDF Portfolio containers detected"
    (`is_portfolio_container` count), "Document families identified" (`len(run.document_families)`),
    "Uncertain matches retained for review" (`needs_review` count).
21. **GUI tests** (10 new, all passing individually) — `tests/gui/test_uncertain_review_dialog.py` (NEW,
    4 tests: lists flagged occurrences with reasons, clean empty state, table is genuinely read-only/no
    edit triggers, `ResultView`'s button opens the dialog with the correct `run` via a monkeypatched fake
    dialog class); `tests/gui/test_advanced_settings.py` (+4: checkbox defaults from config,
    `get_values()` round-trip, `reset_to_defaults()` restores it, unchecking it actually flows through
    into the `run_config` passed to `_start_build`); `tests/gui/test_results.py` (+2: all 5 new stat rows
    show correct counts against a hand-built RC2-field-populated `RunResult`, and the dialog opened from
    `ResultView._run` reflects the real `needs_review` count). GUI suite now 51 tests total (was 41).

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

### Interactive uncertain-match review workflow (this session's chunk, items 18-25)

18. **`models.py`** — new `UncertainMatch` dataclass (match_id/kind/document_id_a/document_id_b/
    confidence/detail/excludable_ids/decision/decided_document_id/decided_at/decided_reason);
    `RunResult.uncertain_matches: list[UncertainMatch]`; new `SourceOccurrence.manually_excluded: bool`
    + `manually_excluded_match_id: str | None`; `included_in_final` extended with a top-level
    `and not self.manually_excluded` clause (independent of the existing `needs_review` guards, so an
    explicit human decision can override the "keep when uncertain" default that automated code can
    never override).
19. **`content_dedup.py`** — `_pairwise_grouping()` and `detect_content_duplicates()` now also return the
    structured `uncertain_pairs: list[(document_id_a, document_id_b, confidence)]` list (previously only
    encoded into free-text `review_reason` strings on each occurrence) so the GUI can build
    `UncertainMatch` records without parsing text. **Breaking return-signature change** (2-tuple →
    3-tuple) — all call sites updated (`cli.py`, `tests/test_content_dedup.py`,
    `tests/test_version_classification.py`; `tests/test_merged_document_overlap.py` doesn't unpack, so
    unaffected).
20. **`cli.py`** — new `_build_uncertain_matches()` helper turns `content_dedup.py`'s uncertain
    content-duplicate pairs AND `overlap_detection.py`'s `uncertain_overlap` findings into one unified
    `list[UncertainMatch]`, threaded onto `RunResult.uncertain_matches`. `_run_content_aware_analysis()`
    return signature extended (4-tuple → 5-tuple) accordingly.
21. **`validation.py`** — `_check_no_unexplained_removal` now also accepts `manually_excluded` +
    `manually_excluded_match_id` as an explained-removal reason. `_check_needs_review_never_excluded`
    redefined: a `needs_review=True` occurrence excluded from Final is now only a violation if it is
    **not** `manually_excluded` (renamed to "...without an explicit human decision" to reflect this).
    New `_check_manual_exclusions_have_valid_decision_record` independently re-derives, from
    `run.uncertain_matches` directly (never trusting the occurrence's own flags alone), that every
    `manually_excluded` occurrence traces back to a real, `decision == "excluded"` match record naming
    exactly that document. Total integrity checks: **27** (was 26).
22. **`review_decisions.py`** (NEW module) — `apply_review_decision(run, config, match_id, decision, ...)`
    is the ONLY code path anywhere in the app that can exclude a `needs_review=True` occurrence from
    Final. `"keep_both"` only records the decision (no file changes). `"excluded"` validates
    `excluded_document_id` is in the match's `excludable_ids`, marks that occurrence
    `manually_excluded`, then rebuilds ONLY Final (`_rebuild_final_and_reports`): clears stale
    `Final/*.pdf`, rebuilds from the current `included_in_final` set, reruns
    `validation.run_integrity_checks`, rewrites every report. Re-deciding an already-decided match,
    excluding a document outside `excludable_ids`, or naming an unknown match/decision all raise
    `ReviewDecisionError` rather than silently no-op'ing. **Handles the stale-converted-PDF bug** (see
    top-of-file summary) via `_ensure_converted_pdfs_available()`, which re-extracts any non-ignored
    occurrence's exact page range from its own permanent OG output part whenever its original
    `converted_pdf_path` no longer exists on disk.
23. **`gui/widgets/uncertain_review_dialog.py`** (rewritten from the earlier read-only version) —
    interactive per-match cards inside a scroll area: undecided matches show radio buttons ("Keep Both
    (recommended -- default, always safe)" pre-selected, plus one "Mark as duplicate to exclude: X" radio
    per `excludable_ids` entry), decided matches show a static, read-only decision summary. One "Apply
    Decisions" button applies every currently-selected choice across all undecided matches at once; any
    pending exclusion triggers a single blocking `QMessageBox.question` confirmation naming every
    document about to be excluded before anything is applied -- answering No (or closing/cancelling the
    dialog without clicking Apply) changes nothing. Emits `decisions_applied` so `ResultView` can refresh
    its stats after a successful apply.
24. **`gui/widgets/result_view.py` / `main_window.py`** — `ResultView.set_result()` now also accepts
    `config`/`allow_large_input` (needed to rebuild Final); `MainWindow` stores
    `self._last_run_config`/`self._last_allow_large_input` in `_start_build()` and threads them through
    `_on_build_finished()`. New `_on_review_decisions_applied()` refreshes `_populate_stats` after the
    dialog reports a successful apply.
25. **`reporting.py`** — new `write_uncertain_match_review_log()` → `Uncertain_Match_Review_Log.txt`
    (6th report file): full audit trail of every `UncertainMatch` (both documents, confidence, detail,
    which side(s) are excludable, and its decision/timestamp/reason if decided, or "AWAITING REVIEW" if
    not). `_final_exclusion_reason()` now checks `manually_excluded` FIRST (before the automated
    exclusion reasons), since it is the true causal reason whenever present -- `is_content_duplicate`/
    `is_contained_in_merged_document` alone would NOT have excluded the occurrence (both stay guarded by
    `needs_review`), so reporting either of those instead would misattribute the real cause.
    `write_processing_manifest()` now includes `uncertain_matches`. `write_all_reports()` calls all 6
    report functions.

**22 new focused tests added for this chunk**: `tests/test_review_decisions.py` (NEW, 12 tests --
keep-both no-op, explicit exclusion, OG/original-file invariance, integrity-check consistency, audit
report content, re-decision rejection, invalid-exclusion-target rejection, unknown-match/decision
rejection, stale-Final-file cleanup, the workspace-cleanup regression fix (both a deterministic direct
test and a full-`run_build`-pipeline test)); `tests/gui/test_uncertain_review_dialog.py` (rewritten, 10
tests -- default selection, applying default changes nothing, explicit exclude removes exactly the
chosen document, containment matches only offer the standalone side, cancelling the confirmation popup
applies nothing, closing the dialog without applying changes nothing, decisions persist across a dialog
reopen within the session, the audit report reflects a decision, the empty state, `ResultView`'s button
wiring); `tests/gui/test_results.py` (net 0 -- replaced the now-obsolete dialog-internals test with one
proving `ResultView` stores the config the dialog needs).

26. **`tests/test_robert_package_regression.py`** (NEW, 2 tests) — **the real Robert package (the actual
    customer-reported package referenced in the original task spec) is NOT present anywhere in this
    repository or environment** (confirmed via full repo + filesystem search for "robert" -- see the
    file's own docstring for the complete documented blocker). Per the explicit fallback instruction
    covering this exact situation, built a synthetic acceptance test recreating the SAME CLASS of bug
    instead: a large merged package containing several component documents, some of those same
    documents ALSO redundantly re-submitted standalone (content-identical, byte-different -- exactly
    what defeated RC1's exact-hash-only detection), two genuinely different signed/unsigned versions of
    one document (must both survive), and a conventional exact-duplicate pair (Level 1 unaffected).
    Assertions are entirely about which specific documents survive and why, never a fixed page-count
    target. Both tests pass; see §3 and the final deliverable report for the full result.
27. **GitHub Actions workflow (`build-windows-portable.yml`)** — the Node.js 20 deprecation warning
    fixed by bumping `actions/checkout` v4→v5, `actions/setup-python` v5→v6, `actions/upload-artifact`
    v4→v6. Every version verified empirically (not guessed) by fetching each candidate tag's real
    `action.yml`/`package.json` from `raw.githubusercontent.com` and confirming `runs.using: node24` plus
    self-consistent version metadata before choosing it (`checkout@v6`'s tag had inconsistent
    `package.json` metadata still reporting `5.0.0`, so `v5` was chosen instead as the clean,
    self-consistent Node24 major). Confirmed each release's own changelog states the ONLY breaking
    change is the Node20→24 runtime bump itself (no input/behavior changes) -- the app's own Python
    version and every workflow step's behavior are untouched. GitHub-hosted `windows-latest` runners
    already satisfy the new minimum Actions Runner version requirement (v2.327.1+) automatically.

## 2. What is partially complete / not yet started

**Nothing.** Everything in §7b's module dependency chain and the task's own required deliverable list
is complete:

- Windows CI build+package validation: run
  [29517398524](https://github.com/emb2514/lp/actions/runs/29517398524), **SUCCESS**, all 16 steps
  individually verified (not inferred from the green checkmark), 244 passed/3 expected skips/0 failed
  on the real-Windows test run, `pypdfium2` native binary bundling specifically confirmed via direct
  inspection of the two cooperating `pyinstaller-hooks-contrib` hooks. Full detail in
  `RC2_DELIVERABLE_REPORT.md` §8.
- Final RC2 deliverable report: written as `RC2_DELIVERABLE_REPORT.md` at the repo root — see that
  file for the complete, final, user-facing summary (this CHECKPOINT.md remains the development
  history/resume record).

If resuming after this point, there is no RC2 work left to pick up — check with the user for a new
task, or see `RC2_DELIVERABLE_REPORT.md` §9 "Known limitations" for what a genuinely NEW follow-up
task might address (e.g. obtaining the real Robert package, merged-vs-merged overlap, email-attachment
content-aware matching).

## 3. Tests run and results (current, this session)

```
.venv/bin/python -m pytest -q tests/ --ignore=tests/gui
=> 190 passed, 1 warning in 32.1s
```
Clean. Breakdown: 188 from the interactive-review chunk (176 + 12 new in
`tests/test_review_decisions.py`), plus 2 more in `tests/test_robert_package_regression.py` (NEW file --
the documented real-package blocker + the synthetic acceptance test, see §1 item 26).

**GUI tests, this chunk**: the interactive review dialog is done (§1 items 18-25) and its tests pass.
```
for f in tests/gui/test_*.py; do QT_QPA_PLATFORM=offscreen python -m pytest "$f" -q; done
=> every file passes, including test_progress_worker.py this run (the whole-suite-in-one-process
   segfault is nondeterministic/environment-load-dependent -- reproduced again when running
   `pytest tests/gui/` as a single process this session, confirmed still unrelated to any change here
   since it occurs deep in Qt/pytest-qt's own teardown machinery, not in any RC2 code path).
```
57 GUI tests collected total (was 51; net +6: `test_uncertain_review_dialog.py` rewritten in place from
4 read-only tests to 10 interactive tests, `test_results.py` net 0).

**Real Windows CI, final confirmation** (run
[29517398524](https://github.com/emb2514/lp/actions/runs/29517398524), commit `e52374b`, conclusion
SUCCESS): the exact same 247-test suite (engine + GUI together, no per-file workaround needed on real
Windows -- the sandbox segfault is specific to this Linux container's Qt offscreen platform) ran as one
process and produced **244 passed, 3 skipped (all expected -- 2x because LibreOffice is not installed
on the runner, 1x `test_windows_console_attach_is_noop_on_non_windows`, which is designed to run only
on non-Windows platforms and correctly self-skips when actually running on Windows), 0 failed, 1
warning (the same expected zipfile UserWarning seen locally)** -- matching the local collection count
of 247 exactly. Full step-by-step detail in `RC2_DELIVERABLE_REPORT.md` §8.

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

- `5f00288` — the six items listed just above (`config.toml`, `cli.py`, `config.py`, `content_dedup.py`
  bug fixes #3/#4, `gui/widgets/progress_view.py`, `models.py` `content_dedup_notes` field,
  `pdf_content.py` `average_color`/bug fix #4, `progress.py`, `validation.py` full generalization, plus
  test updates in `test_content_dedup.py`/`test_content_fingerprinting.py`/
  `test_hashing_and_deduplication.py`/`test_progress.py`) — this was the previous checkpoint's commit.

- `fac0ae1` (+ follow-up `3e85c00`) — reporting.py expansion + 3 new test files (§1 items 14-17).

- `69d3fee` — GUI: review dialog (read-only version) + advanced-settings toggle + result-view stat rows
  + 10 GUI tests (§1 items 18-21 as originally built, before this session's interactive-decision
  upgrade) — this was the previous checkpoint's commit.

- `318ff50` (+ follow-up `a04a2e6`) — interactive uncertain-match review/decision workflow (§1 items
  18-25) — this was the previous checkpoint's commit.

- `e52374b` — Robert-package acceptance test + GitHub Actions Node fix (§1 items 26-27). This was the
  commit the successful Windows CI run (29517398524) built and tested.

**This session's final chunk** (RC2_DELIVERABLE_REPORT.md, WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md RC2
update, this CHECKPOINT.md closeout) — to be committed at the very end (see §9 for the exact final
commit hash once pushed):
```
A  RC2_DELIVERABLE_REPORT.md
 M WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md
 M CHECKPOINT.md
```

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

## 9. RC2 is complete — nothing to resume

Every item in the original task spec and every item from the autonomous-completion instruction is
done: architecture research, all engine modules, GUI work, the interactive uncertain-match review
workflow, validation.py's 27 integrity checks, the (documented-blocked, synthetically-substituted)
Robert-package acceptance test, the GitHub Actions Node-deprecation fix, and real Windows CI
build+package validation (run 29517398524, SUCCESS, verified step-by-step, artifact uploaded).

**If you are resuming this task from a fresh context**: there is nothing left to do for RC2 itself.
Read `RC2_DELIVERABLE_REPORT.md` at the repo root first — it is the complete, final, user-facing
summary (features, safety behavior, detection logic, Portfolio behavior, GUI review behavior,
Robert-package results, test counts, Windows CI/build results, known limitations, exact artifact
location, install/run instructions). This CHECKPOINT.md remains only as the detailed development
history. Confirm via `git log --oneline -5` and `git status` that the final commit referenced in §4 is
present and the working tree is clean; if the user has a NEW request, treat it as its own task rather
than continuing RC2 — see `RC2_DELIVERABLE_REPORT.md` §9 "Known limitations" for plausible next steps
(e.g. obtaining and running against the real Robert package, merged-vs-merged overlap detection,
email-attachment content-aware matching, or a version-string bump if the project owner wants one).

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
