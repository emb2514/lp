# Claude Design Handoff -- Document Merger

This document is for whoever (or whichever Claude) does the final visual
pass on this app. Every screen listed below is **functionally complete,
accessible, responsive, and covered by automated tests** -- what remains
is colors/branding artwork/animations/decorative illustrations/major
typography/pixel-perfect restyling, per the boundary the implementation
work was explicitly asked to respect. Read this whole document before
changing anything; it documents exactly what must not break.

**Golden rule:** every behavior described here (state transitions,
button enablement, confirmation dialogs, filenames shown to the user,
what happens on cancel) is backed by an automated test. If a visual
change would require changing one of those behaviors, stop and treat it
as a functional question, not a styling one.

---

## 1. Branding constants -- do not hardcode strings that already exist

- **Product name**: `PRODUCT_NAME = "Document Merger"` in
  `src/lender_package_builder/_version.py`. This is the ONLY place the
  user-visible product name is defined. It appears in the GUI header
  (`main_window.py`, `title = QLabel(PRODUCT_NAME)`, `objectName=
  "AppTitle"`), the window title (`f"{PRODUCT_NAME} - v{USER_VERSION}"`),
  `--version`/`--about` CLI output, and generated report headers.
- **Version**: `USER_VERSION = "RC2"`, `__version__ = "1.0.0rc2"`. Shown
  as `f"v{USER_VERSION}"` in the window title and the header subtitle
  (`"Build complete and deduplicated lender PDF packages  ·  v{USER_VERSION}"`).
  Never hardcode "RC1" anywhere new -- it is stale everywhere it still
  appears (only in historical filenames like
  `RELEASE_NOTES_1.0.0_RC1.md`, which is an intentionally-preserved
  historical document, not something to update).
- The **internal Python package name** (`lender_package_builder`), CLI
  command names, config folder names (`config.toml`,
  `%LOCALAPPDATA%\LenderPackageBuilder`), and report field names/schemas
  were deliberately left unrenamed -- this was a user-visible branding
  change only. Do not rename these while restyling.

## 2. Existing style tokens (`gui/theme.py`)

A full palette, font stack, and QSS stylesheet already exist and are
applied globally via `theme.apply_theme(app)`. This is exactly the kind
of thing Claude Design is expected to refine -- but refine it by editing
`theme.py`'s constants and `build_stylesheet()`, not by hand-styling
individual widgets, so the whole app stays consistent from one place.

```python
BACKGROUND = "#F4F6F8"       CARD_BACKGROUND = "#FFFFFF"   CARD_BORDER = "#E2E6EA"
ACCENT = "#0E6E8C"           ACCENT_HOVER = "#0B5A73"      ACCENT_PRESSED = "#094859"
ACCENT_DISABLED = "#A9C4CD"
TEXT_PRIMARY = "#1F2733"     TEXT_SECONDARY = "#5B6673"    TEXT_ON_ACCENT = "#FFFFFF"
SUCCESS = "#1E8E3E" / "#E6F4EA" bg    WARNING = "#B7791F" / "#FEF3E2" bg    ERROR = "#C5221F" / "#FCE8E6" bg
FONT_FAMILIES = ["Segoe UI", "Segoe UI Variable", "-apple-system", "Helvetica Neue", "Arial", "sans-serif"]
RADIUS = 10
```

Widgets reference these via Qt `objectName` selectors in the stylesheet
(`AppTitle`, `Card`, `SectionHeading`, `MutedLabel`, `PrimaryButton`,
`StatusBanner`, `StatusBannerTitle`, ...) -- reuse existing object names
on new widgets wherever the role matches, rather than inventing
one-off styling.

## 3. Output folder structure and exact filename examples (Milestone 1)

**This section is load-bearing for design work** -- several screens
display these exact names/patterns to the user, so any mockup or copy
change must stay consistent with them.

Main output folder (created next to the input, or wherever the user
picks), commas between every value, never underscores:

```
Last Name, First Name, Loan Number                       (normal file)
Last Name, First Name, Adverse, Loan Number               (adverse/withdrawn/denied/cancelled file)
Last Name, First Name, Loan Number, v2                    (auto-versioned if that name already exists)
```

Inside it, exactly three folders (never more):

```
Final/               Lender Package + Original Lender Package + extracted key documents, no subfolders
Reports/              All logs/reports/manifests
Unconverted Files/     Only created when at least one file genuinely couldn't be converted
```

There is deliberately no `OG` folder and no `Logs` folder anymore.

Filenames inside `Final`, borrower "Michael True", loan `6192278785`:

```
True, Michael, Lender Package.pdf                                       single-part Final
True, Michael, Lender Package, Part 001.pdf                             multi-part Final (3-digit, omitted if 1 part)
True, Michael, Original Lender Package.pdf                              single-part Original
True, Michael, Original Lender Package, Part 001.pdf                    multi-part Original
True, Michael, Closing Disclosure, Signed, 6192278785.pdf                extracted key document
True, Michael, Driver's License Front, E-Sign, 6192278785.pdf
True, Michael, Driver's License Front, Copy 2, 6192278785.pdf            genuine duplicate, not a version bump
```

Key-document filename pattern: `Last Name, First Name, Document Name,
Signature Status (when applicable), Loan Number.pdf`. Signature status
is one of `Signed` (only with real wet-signature evidence -- never
guessed from a flat scan), `E-Sign`, `Unsigned`, or omitted /
`Signature Unknown` when genuinely indeterminate.

## 4. Named screens and states -- Build workflow

`MainWindow` is a persistent left **sidebar** (`objectName="Sidebar"`,
fixed width) plus a content column. The sidebar holds three checkable
nav buttons (`objectName="NavButton"`, mutually exclusive via
`_set_active_nav()`): **Package** (`self.nav_package_button`),
**Compare** (`self.compare_packages_button` -- kept that attribute name
for continuity with the pre-sidebar header button it replaced),
and **History** (`self.nav_history_button`), plus the "Local processing
only" privacy badge at the bottom. Clicking one switches
`self.top_level_stack` (a `QStackedWidget` holding the Package page,
the Compare Packages workspace (§5), and the History screen) and
updates which nav button is checked. Compare Packages' own "Back to
Build" button routes through the same `_show_build_workspace()` method,
so it also correctly restores Package as the active nav item. Switching
pages never touches another page's state -- a build in progress stays
in progress if you switch away and back (switching away is not
currently blocked while a build is running, but closing the whole app
is -- see `closeEvent()`).

**The Package page is itself two columns**, not a single stacked page:
a center column (`self.stack`, a `QStackedWidget` wrapped in a
`QScrollArea` so a tall expanded Advanced Settings panel scrolls
instead of squeezing rows toward zero height -- see the
`_CurrentPageStackedWidget` note below) holding Input/Result/Failure,
and a **persistent right-side Progress panel** (`self.progress_view`,
fixed width, NOT one of `self.stack`'s pages) that is visible at all
times on this page -- before a build starts (idle "Ready to build"
state), while one runs, and immediately after (it reverts to idle the
moment `stop()` is called, since the center column's Result/Failure
view is what communicates a finished run's outcome).

1. **Input page** (`self.input_page`, one of `self.stack`'s pages) --
   drop zone + Browse File/Browse Folder, selected-input summary card,
   Advanced Settings (collapsed by default), and the **Build Lender
   Packages** button.
   - Dropping/selecting more than one item shows
     `dialogs.show_multiple_items_message()` instead of silently
     picking one.
   - Exceeding the hard safety limit shows `LargeInputConfirmDialog`
     ("Process This Known Large Package" vs. "Go Back") before
     `allow_large_input=True` is ever set.
   - **Package Details** now live inline, as the first section inside
     Advanced Settings (`advanced_settings.py`) -- last name (required),
     first name, loan number, an adverse/non-proceeding checkbox, and a
     **live preview of the exact output folder name**
     (`identity_preview_label`) using the naming rules in §3. There is
     no modal dialog anymore (`PackageIdentityDialog` was removed) --
     filling these in ahead of time, before an input is even selected,
     is the whole point (a returning user re-processing for the same
     borrower doesn't have to retype anything since the fields persist
     across builds in one session). Clicking Build with no last name
     entered auto-expands Advanced Settings and shows the same
     `validation_label` error styling the page/size ceiling checks
     already use -- last name is checked first, before those. Identity
     is never invented or silently defaulted by anything other than a
     human filling in this section.
2. **Progress panel** (`self.progress_view`, `ProgressView`, persistent
   side panel, not a stacked page) -- a circular percentage indicator
   (`CircularProgressIndicator`, purely visual -- the real progress data
   other code/tests read stays the plain `QProgressBar`, kept in the
   tree but hidden), stage label, "N of M documents processed",
   Current step / Current doc, Elapsed time / Est. time remaining (the
   latter is intentionally always "--" -- there is no reliable estimate
   to show, and showing a fabricated one would violate this app's
   conservative-honesty pattern), a scrolling activity log, and a
   **Cancel Processing** button that is hidden except while a build is
   actually running.
   - Clicking Cancel Processing shows `dialogs.confirm_cancel_processing()`
     ("Stop processing this package?" / Continue Processing / Stop
     Processing) -- **never cancels on the first click**.
   - After confirming, the button/label should read as "Cancelling..."
     (`set_cancelling()`) until the worker actually stops -- cancellation
     is cooperative, not instant, so there is a real gap here to show
     honestly, not to paper over with a spinner that implies it already
     finished.
3. **Result page, success/warning** (`self.result_view`, `ResultView`,
   one of `self.stack`'s pages) -- a status banner
   (`StatusBanner`/`StatusBannerTitle`, colored via `SUCCESS`/`WARNING`
   tokens), stats grid (documents processed, duplicates removed, parts
   produced, **key-document stat rows**, and **wet-signature stat
   rows** -- see §4a), Open Output Folder / Open Final Package
   (`os_actions.open_file`) / Open Final Folder buttons, and Process
   Another Package. This view's button row is wide (six buttons) --
   this is exactly why `self.stack` needed the
   `_CurrentPageStackedWidget` size-hint override below; don't widen it
   further without re-checking the Package page at the app's minimum
   window size.
4. **Result page, failure** (`self.failure_view`, `FailureView`, one of
   `self.stack`'s pages) -- red banner, technical-details section, Try
   Again. Has a **distinct cancelled state** (`set_cancelled(error)`)
   that must render visually differently from a real failure
   (warning-colored banner, not error-red -- `banner.property("status")
   == "warning"` is asserted by a test) with reason text that explicitly
   says nothing was changed on disk. **A cancelled run must never look
   like a red error and must never look like a green success** -- it is
   its own third thing.
5. **Review Uncertain Matches** (`uncertain_review_dialog.py`, a modal,
   not a stack page) -- appears only when at least one comparison needs
   a human decision. Every match defaults to "Keep Both" (no
   confirmation needed); choosing to exclude a document requires a
   second, explicit confirmation naming the file before anything
   changes. This predates the six milestones in this handoff but shares
   the same workspace and should feel visually consistent with it.
6. **History** (`self.history_view`, `HistoryView`, a `top_level_stack`
   page, not part of the Package page) -- a table of past builds this
   installation has run (newest first), each row showing name, loan
   number, date, status, and an Open Folder action (disabled if that
   folder no longer exists on disk). Read from a local JSON log
   (`history.py`, `runtime_paths.history_file_path()`) that a
   history-write failure never surfaces to the user -- it is a
   convenience log, not part of the processing/safety contract. Refresh
   happens automatically each time the History nav button is clicked
   (`refresh()`). Empty state: "No packages built yet -- packages you
   build will be listed here."

**Why `_CurrentPageStackedWidget` exists**: a plain `QStackedWidget`
reports a size hint equal to the max across ALL of its pages, even ones
not currently shown -- once `self.stack` sits inside a `QScrollArea`
(needed for the Advanced Settings scrolling fix above), that becomes an
enforced floor, and Result's six-button row was wide enough to force a
horizontal scrollbar onto the Input page too. `main_window.py`'s
`_CurrentPageStackedWidget` subclass overrides `sizeHint()`/
`minimumSizeHint()` to reflect only `currentWidget()`, and forces
`updateGeometry()` on every page change so the surrounding scroll area
re-measures. If you add a wide element to any Result/Failure/History
page, re-check the Input page doesn't inherit a horizontal scrollbar
from it.

### 4a. Key-document and wet-signature status display (Milestone 4)

On the success/warning result screen:

- A **"Wet-Signed Documents Found: [count]"** section. When count > 0,
  list each one (document type, filename, page range). When count is 0,
  show exactly: *"No wet-signed documents were found in the Final
  lender package."*
- Separately, always show **"Wet-Signed Closing Disclosure:"** with its
  own status (e.g. "Not found") whenever the CD specifically isn't
  wet-signed -- **even if other documents in the package are
  wet-signed.** These two lines must never be conflated into one; a
  reader must be able to tell "nothing at all is wet-signed" apart from
  "other things are wet-signed but the CD specifically isn't."
- Key-document matches use four confidence bands, shown as a label, not
  silently hidden: **Confirmed**, **Strong Match**, **Possible Match**,
  **Not Found**. Only Confirmed/Strong Match are ever auto-extracted as
  standalone files -- a Possible Match stays flagged for human review
  and must be visually distinguishable (do not style it identically to
  Confirmed).
- Because reliably opening a PDF at a specific page isn't possible
  across Windows PDF viewers, the UI opens the correct package **part**
  file and prominently displays the page number as text next to it --
  it does not claim to jump to a page directly. Don't design around a
  "jump to page" interaction that the app can't actually deliver.

## 5. Named screens and states -- Compare Packages workspace (Milestone 5B/6)

`CompareWorkspace` (`gui/widgets/compare_workspace.py`) owns its own
three-page `QStackedWidget` (`self.stack`), entirely independent of the
build workflow's state:

1. **Input page** (`self.input_page`) -- two `CompareSideSelector`
   instances, labeled **"Old / Reference Package"** and **"New /
   Generated Package"**. Each has Select PDF / Select Multiple Parts /
   Select Folder / Clear Selection.
   - Select Multiple Parts sorts whatever the OS file dialog returns
     into natural part order (`Part 001`, `Part 002`, ...) regardless of
     click order -- the summary must reflect the sorted order, not
     selection order.
   - Select Folder routes through `compare_packages.describe_folder_contents()`.
     If the folder contains **both** a Final and an Original Lender
     Package, `dialogs.choose_final_or_original_package()` asks
     explicitly which to use -- this choice must never be silently
     inferred. An empty/no-PDF folder shows
     `dialogs.show_no_pdfs_found()` instead of enabling an empty
     comparison.
   - The **Compare Packages** button stays disabled until both
     selectors report a valid selection.
2. **Progress page** (`self.progress_view`, `CompareProgressView`) --
   status message (short strings like *"Aligning N old page(s) against
   M new page(s)..."*, *"Resolving K unmatched page(s)..."*,
   *"Comparison complete."*), an indeterminate progress bar, elapsed
   time, and a **Cancel Comparison** button gated by
   `dialogs.confirm_cancel_comparison()`. Comparison never modifies
   either package, cancelled or not -- the confirmation exists purely so
   an accidental click can't discard a comparison that may have taken a
   while, not because anything is at risk on disk.
3. **Results page** (`self.results_view`, `CompareResultsView`) --
   - Summary grid: old/new page counts, matched, equivalent, likely
     duplicates removed, contained documents, meaningful differences,
     only-in-old, only-in-new, possible missing, needs review.
   - A category filter and a text search over findings.
   - A findings table plus a side-by-side detail panel per finding:
     file, part, page range, detected type, signature/version status,
     confidence, protected differences, plain-English explanation.
   - Previous Finding / Next Finding, Open Old Package / Open New
     Package, Export Report, and **New Comparison** (clears both
     selectors and returns to the input page).
   - The full category list a finding can be labeled with: **Exact
     Match, Equivalent Content, Contained in Larger Document, Same
     Document Different Version, Meaningful Difference, Likely
     Duplicate Removed, Moved or Reordered, Only in Old, Only in New,
     Possible Missing Document, Extra Blank/Cover/Index/Report Page,
     Unrecognized Section, Needs Review.** Each deserves a visually
     distinct treatment (at minimum, "Needs Review"/"Possible Missing
     Document" should never look as neutral as "Exact Match") -- but do
     not invent a 13th category or rename these; they are exact strings
     the report/manifest files also use.

**Known scope gap, not a bug**: there is currently no GUI action to
reopen a previously exported `Package Comparison Manifest.json` without
rerunning the comparison. If a "reopen saved comparison" entry point
gets added to the input page, it belongs next to Select PDF/Select
Multiple Parts/Select Folder as a peer action, not a separate screen.

## 6. Cross-cutting behaviors that must survive any restyling

- **Non-freezing progress everywhere.** Both the build worker and the
  compare worker run on a background `QThread`
  (`gui/worker.py::CallableWorker`/`start_worker()`); the window must
  never appear to hang. If you add animation, it must not imply
  progress percentage the app doesn't actually know (both progress
  views are intentionally indeterminate-style, not a percentage bar).
- **Every cancel action requires a second, explicit confirmation
  click** ("Stop Processing"/"Stop Comparing") -- never remove this
  step, even to "streamline" a flow.
- **A cancelled run is a distinct visual state**, never styled as
  either success or failure.
- **Disabled-until-valid buttons stay disabled-until-valid**: Build
  Lender Packages needs a valid single input; Compare Packages needs
  both sides valid; Continue in the identity dialog needs a last name.
  Don't replace a disabled state with an enabled button that shows an
  error after the click -- the tests assert the disabled state directly.
- **Folder-name live preview** in `PackageIdentityDialog` must keep
  updating as the user types, using the exact `naming.py` rules in §3
  -- it is not decorative text, it is the literal folder name about to
  be created.
- **Accessibility**: existing GUI tests assert on widget `objectName`s
  and on real button/label text (not pixel positions) -- keep visible,
  real text labels on interactive elements (no icon-only buttons
  without an accessible name), and keep `objectName`s stable when
  restyling so tests and any screen-reader mapping built on them keep
  working.
- **Responsive resizing**: all layouts use Qt layout managers
  (`QVBoxLayout`/`QHBoxLayout`/`QGridLayout`/`QStackedWidget`), no fixed
  pixel-perfect absolute positioning -- keep it that way so the window
  stays usable resized or at different DPI scales.

## 7. Module boundary (why this split exists)

Comparison logic, naming logic, and cancellation logic all live in
plain Python engine modules (`compare_packages.py`, `naming.py`,
`cancellation.py`) with **zero Qt imports** -- GUI widgets only call
into them and render the results. This was a deliberate safety
requirement ("comparison logic must never live inside GUI widgets") so
that restyling a widget can never accidentally change what counts as a
duplicate, a match, or a valid filename. When changing a widget, if you
find yourself wanting to add a business-logic decision (e.g., "is this
really a duplicate," "what should this file be named"), that decision
belongs in the corresponding engine module, not in the widget.
