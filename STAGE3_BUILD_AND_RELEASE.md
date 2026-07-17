# Stage 3: Build and Release -- Portable Windows Release Candidate

This document explains how Stage 3 turns the Stage 1 (engine) + Stage 2
(GUI) application into a portable Windows package, how to build and
verify it yourself, and -- critically -- **exactly which claims in
this document are backed by real Windows CI, and which still require
your own manual test on a physical Windows 11 computer.**

---

## 1. What Stage 3 adds

Stage 3 does not rebuild or redesign anything from Stage 1 or Stage 2.
It wraps the existing, already-tested engine and GUI in:

- A single-source version (`src/lender_package_builder/_version.py`):
  `1.0.0rc1` (package), `1.0.0 RC1` (user-facing), `1.0.0.0` (Windows
  file version).
- `runtime_paths.py`: frozen-vs-source path resolution, used for
  locating bundled assets, the external `config.toml`, and the log
  directory correctly whether running from source or as a packaged
  `.exe`.
- Friendly, non-crashing external-config handling (`config.py`'s
  `load_config_safe`) with a guaranteed no-overwrite contract.
- `self_test.py` / `diagnostics.py`: production modules (no `pytest`
  dependency) exposed as `--self-test` / `--diagnostics` on the
  packaged executable.
- `app_entry.py`: the single entry point behind
  `LenderPackageBuilder.exe`, handling `--version`, `--self-test`,
  `--diagnostics`, `--gui-smoke-test`, drag-onto-.exe input
  preselection, and the multiple-items rejection message, before
  falling through to the normal GUI launch.
- `crash_log.py` / `windows_console.py`: startup crash logging to
  `%LOCALAPPDATA%\LenderPackageBuilder\Logs`, and console attachment
  so the CLI modes produce visible output from a windowed-subsystem
  build.
- `LenderPackageBuilder.spec`: the PyInstaller `--onedir` build
  specification (icon, version resource, manifest, hidden imports,
  bundled package metadata -- see inline comments for the reasoning
  behind each choice).
- Windows batch scripts: `BUILD_WINDOWS_PORTABLE.bat`,
  `CLEAN_WINDOWS_BUILD.bat`, `TEST_PORTABLE_APP.bat`,
  `RUN_DIAGNOSTICS.bat`.
- `.github/workflows/build-windows-portable.yml`: builds and verifies
  all of the above on a real `windows-latest` GitHub Actions runner.
- The documentation set this file is part of.

## 2. CI-tested vs. manually-tested -- read this before trusting any claim

**Completion criterion #28 requires this distinction to be explicit.**
Here it is:

### Verified by real Windows CI (`build-windows-portable.yml`, on `windows-latest`)

- The full Stage 1 + Stage 2 + Stage 3 automated test suite passes on
  actual Windows (not just this Linux development environment).
- The PyInstaller `--onedir` build completes successfully on Windows.
- `LenderPackageBuilder.exe --version`, `--self-test`, `--diagnostics`,
  and `--gui-smoke-test` all succeed on Windows.
- Those same four modes succeed on Windows **with `PYTHONHOME`/
  `PYTHONPATH` cleared and `PATH` reduced to only core Windows system
  directories** -- direct evidence the packaged app does not silently
  depend on the Python installation used to build it.
- Those same modes succeed when the built folder is copied to a
  **path containing spaces**.
- The release ZIP is produced and its SHA-256 checksum is computed and
  immediately re-verified in the same CI run.
- The build manifest, third-party license files, and sample test
  package are present in the assembled release folder.

### NOT verified by CI -- requires your own physical Windows 11 machine

CI runners execute without an interactive desktop session and without
a real antivirus/SmartScreen configuration, a real Windows Explorer
drag-and-drop from a human hand, or real DPI/multi-monitor behavior.
None of the following have been confirmed on real hardware yet:

- The GUI actually **looking correct on screen** (layout, DPI scaling,
  fonts, real window chrome) -- `--gui-smoke-test` proves the window
  *constructs and closes without throwing*, not that it *looks right*.
- Real Windows Explorer drag-and-drop, both into the open application
  window and onto the `.exe` icon itself.
- What Windows SmartScreen or a real antivirus product actually shows
  a real user on first launch.
- Real Microsoft Office COM automation (the `pywin32` code path is
  included and defensively written, but has not been exercised against
  a real, licensed Office installation).
- General "does this feel right to a non-technical person" usability
  questions.
- Startup/warm-start timing and memory use on real, typical end-user
  hardware (as opposed to a CI runner's hardware profile).

**`WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md` exists specifically to close
this gap.** Nothing in this repository should be described as "fully
verified on Windows" until that checklist has actually been completed
on a physical machine -- and this document does not claim that it has.

## 3. Building it yourself

```
BUILD_WINDOWS_PORTABLE.bat
```

This, on a Windows machine with Python 3.11-3.13 available:

1. Creates/reuses a `.venv` and installs `requirements-windows-build.txt`.
2. Runs the full test suite -- **the build stops here if anything
   fails.**
3. Regenerates `packaging\app_icon.ico` from `app_icon.svg`.
4. Runs `pyinstaller LenderPackageBuilder.spec --noconfirm --clean`
   after deleting any previous `build\`/`dist\` output.
5. Assembles `release\LP_Builder_<RELEASE_LABEL>_Windows_x64\` (the
   version label comes from the single source in `_version.py`) with
   the built app, `config.toml`, documentation, the sample test
   package, and collected third-party license files.
6. Writes `BUILD_MANIFEST.txt` (Python version, `pip freeze`, git
   commit).
7. Zips the release and writes its SHA-256 checksum.

Then verify the result without needing Python at all:

```
TEST_PORTABLE_APP.bat
```

To start over cleanly:

```
CLEAN_WINDOWS_BUILD.bat
```

## 4. What the GitHub Actions workflow does

`.github/workflows/build-windows-portable.yml` runs the same sequence
above on `windows-latest`, plus the "prove no Python needed" and
"space-containing path" steps described in section 2, then uploads the
zipped release and its checksum as a workflow artifact. It triggers on
`workflow_dispatch` (manual), pushes to `main`, pushes of
`v*-rc*`-style tags, and pull requests that touch packaging-relevant
files. It never creates a git tag or a GitHub Release on its own --
see section 6.

## 5. Explicit non-goals (out of scope for Stage 3)

No installer/MSI, no Windows Registry writes, no Windows service, no
auto-updater, no telemetry, no code signing without a real purchased
certificate, and no attempt to evade SmartScreen, antivirus, or
company security policy. See the master build prompt's section Y for
the complete list; nothing here contradicts it.

## 6. Publishing -- explicitly gated on your approval

Per the explicit instructions this build was done under:

- This is `1.0.0 RC1`, not final `v1.0.0`. It is labeled that way
  everywhere (package version, window title, executable properties,
  release folder/ZIP name, these release notes).
- **No git tag has been created and no GitHub Release has been
  published or drafted by this work.** A release-candidate tag may
  only be created after the Windows CI build and packaged self-tests
  pass (they have, per section 2) -- but tagging and publishing still
  require your explicit go-ahead, and a *final* `v1.0.0` additionally
  requires your own completed `WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md`
  results.
- This document, and this build, stop here and wait for that.

## 7. Licensing note

`extract-msg` (`.msg`/Outlook email conversion) is GPLv3-licensed and
used directly in-process, which is a real, unresolved tension with
this project's own "Proprietary" license declaration for anything
beyond local/internal use. See the top of `THIRD_PARTY_NOTICES.txt`
for the full explanation. This was a deliberate decision (documented,
not silently resolved) made after checking with the project owner.

## 8. Where everything lives

| Concern | File |
|---|---|
| Single version source | `src/lender_package_builder/_version.py` |
| Frozen/source path resolution | `src/lender_package_builder/runtime_paths.py` |
| Packaged self-test | `src/lender_package_builder/self_test.py` |
| Packaged diagnostics | `src/lender_package_builder/diagnostics.py` |
| Unified CLI/GUI entry point | `src/lender_package_builder/app_entry.py` |
| Startup crash logging | `src/lender_package_builder/crash_log.py` |
| PyInstaller build spec | `LenderPackageBuilder.spec` |
| Icon generation | `packaging/generate_icon.py` |
| License collection | `packaging/collect_licenses.py` |
| Windows CI workflow | `.github/workflows/build-windows-portable.yml` |
| Stage 3 automated tests | `tests/test_stage3_packaging.py`, `tests/gui/test_stage3_gui.py` |
| Sample test package generator | `samples/generate_sample_package.py` |
| End-user portable-app guide | `README_PORTABLE.txt` |
| Manual Windows test checklist | `WINDOWS_ACCEPTANCE_TEST_CHECKLIST.md` |
| Build/packaging troubleshooting | `PACKAGING_TROUBLESHOOTING.md` |
| Third-party license notices | `THIRD_PARTY_NOTICES.txt` |
| This release's notes | `RELEASE_NOTES_1.0.0_RC1.md` |
