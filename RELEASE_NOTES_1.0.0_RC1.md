# Lender Package Builder -- Release Notes: 1.0.0 RC1

**This is a release candidate, not a final production release.**
Final `v1.0.0` will only be tagged and published after this build
passes manual acceptance testing on a real Windows 11 computer (see
`WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md`) and after explicit approval
from the project owner.

## What's new in this release

Stage 3 converts the existing Stage 1 (processing engine) + Stage 2
(desktop GUI) application into a portable Windows package:

- **No Python installation required.** The application is built with
  PyInstaller into a self-contained folder (`--onedir`); a bundled
  Python runtime and all dependencies ship alongside the executable.
- **No installer, no admin rights, no registry changes, no Windows
  service.** Extract the ZIP and double-click `LenderPackageBuilder.exe`.
- **Single authoritative version.** `1.0.0rc1` (package/Python),
  `1.0.0 RC1` (user-facing), `1.0.0.0` (Windows file version) --
  consistent everywhere: package metadata, window title, executable
  properties, release folder name, and this document.
- **New command-line modes on the same executable:**
  `--version`, `--self-test`, `--diagnostics`, `--gui-smoke-test`.
  None of them require a separate Python install, pytest, or the
  source repository -- they run entirely from the packaged .exe.
- **Drag-onto-.exe support.** Dropping one ZIP, folder, or document
  directly onto `LenderPackageBuilder.exe` opens the app with that
  input preselected -- it never starts processing automatically; you
  still click "Build Lender Packages" yourself. Dropping more than one
  item shows the same friendly "one input at a time" message the
  in-app drop zone already uses.
- **External, editable `config.toml`** ships beside the executable. A
  missing config file is not an error (built-in defaults apply); an
  invalid config file shows a friendly warning and falls back to
  defaults rather than crashing or silently guessing -- and it is
  never overwritten automatically.
- **Startup crash logging.** An unhandled exception during startup is
  logged to `%LOCALAPPDATA%\LenderPackageBuilder\Logs` instead of the
  application just disappearing with no explanation.
- **Multi-resolution application icon and Windows executable version
  metadata** (product name, file/product version, description) --
  with no claimed affiliation with any lender, Microsoft, Qt, or other
  third party.
- **A harmless, reproducible synthetic sample test package**
  (`Sample_Test_Package.zip`) with documented expected results, for
  safely verifying a build without any real borrower data.
- **A GitHub Actions Windows workflow** that builds this exact
  package on a real Windows runner, runs the full test suite there,
  and proves the packaged .exe needs no external Python (by clearing
  `PYTHONHOME`/`PYTHONPATH` and minimizing `PATH` before running its
  self-test) before uploading the release as a build artifact.

## What did NOT change

Every Stage 1 and Stage 2 safety rule and behavior is unchanged and
covered by regression tests:

- One source file equals one indivisible document; no page-level
  operations of any kind.
- Exact duplicates are determined only by whole-file SHA-256.
- The OG package includes every source occurrence; Final excludes only
  later byte-identical duplicates.
- Output-part maximums (750 pages / 100 MB, still configurable) remain
  ceilings, never targets; a part never crosses those maximums, and no
  source document is ever split across parts.
- All 22 Stage 1 integrity checks and the full GUI behavior from
  Stage 2 remain in place and are re-verified by the Stage 3 test
  suite.

## Known limitations of this release candidate

- **Not yet manually tested on a real, physical Windows 11 computer.**
  Everything described above has been verified by this project's own
  test suite (source and packaged), and separately by an actual
  Windows GitHub Actions build runner -- but CI passing is not the
  same as a human clicking through the real interface on real
  hardware. See `WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md`, which must be
  completed before this is called a finished v1.0.0.
- **Unsigned executable.** No commercial code-signing certificate has
  been applied yet, so Windows SmartScreen or antivirus products may
  show a first-run warning. See `README_PORTABLE.txt` and
  `PACKAGING_TROUBLESHOOTING.md`.
- **A licensing question requires legal review before wide
  distribution:** `extract-msg` (used for `.msg`/Outlook email
  conversion) is GPLv3-licensed and is imported directly in-process,
  which is a different situation from this project's other,
  permissively-licensed dependencies. See the "FLAGGED FOR LEGAL
  REVIEW" section at the top of `THIRD_PARTY_NOTICES.txt` for the
  full explanation. This does not affect local/internal use, only
  wider redistribution.
- **Microsoft Office COM automation** (used opportunistically when
  Office is installed, via `pywin32`) is implemented and included in
  the Windows build, but -- like in Stage 1 -- has not been exercised
  against a real, licensed Office installation as part of this build;
  it is written defensively so any failure there simply falls through
  to the next available conversion method.
- **PySide6/Qt version.** Built and tested against PySide6 6.11.1 on
  Python 3.13 (Windows CI) and Python 3.11 (this development
  environment). If a real Windows machine requires a different pinned
  version for compatibility, that change -- and a full retest -- would
  need to happen before final release.

## Where to go next

- To test this build: `WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md`
- To understand what's in the release folder: `README_PORTABLE.txt`
- For build/packaging problems: `PACKAGING_TROUBLESHOOTING.md`
- For how this was built and verified: `STAGE3_BUILD_AND_RELEASE.md`
- For license details: `THIRD_PARTY_NOTICES.txt`
