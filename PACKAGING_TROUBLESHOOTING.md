# Packaging Troubleshooting

Problems you might hit building or running the portable Windows
release, and what to do about each.

---

## Building the portable .exe

### `BUILD_WINDOWS_PORTABLE.bat` says "No supported Python installation was found"

Install Python 3.11, 3.12, or 3.13 (64-bit) from
https://www.python.org/downloads/, checking "Add python.exe to PATH"
during installation, then run the script again.

### The test suite fails and the build stops

This is intentional -- `BUILD_WINDOWS_PORTABLE.bat` refuses to produce
a release on top of a failing test suite. Read the pytest output, fix
the underlying issue (do not skip or delete the failing test to make
the build proceed), and run the script again.

### PyInstaller build fails with a missing-module error

1. Check `build\LenderPackageBuilder\warn-LenderPackageBuilder.txt`
   (created during the build) for the exact module PyInstaller could
   not find.
2. If it's one of this project's own dependencies, add it to
   `hiddenimports` in `LenderPackageBuilder.spec`.
3. Re-run `CLEAN_WINDOWS_BUILD.bat` then `BUILD_WINDOWS_PORTABLE.bat`
   (a stale `build\` cache can otherwise mask the fix).

### The built .exe launches but the window never appears / closes immediately

1. Run `LenderPackageBuilder.exe --diagnostics` from a Command Prompt
   (not by double-clicking) to see console output and any early error.
2. Check `%LOCALAPPDATA%\LenderPackageBuilder\Logs` for a
   `startup_*.log` file -- an unhandled exception during startup is
   logged there even when no window ever appears.
3. Confirm the `_internal` folder is present next to the .exe and was
   not partially copied (a corrupted or incomplete PyInstaller output
   is the most common cause of this).

### The icon or version info didn't change after editing `_version.py`

`packaging/app_icon.ico` and `packaging/version_info.txt` are both
generated automatically at build time (see `LenderPackageBuilder.spec`)
-- run `CLEAN_WINDOWS_BUILD.bat` to remove any stale generated files,
then rebuild. `app_icon.ico` is only regenerated when it's missing or
older than `app_icon.svg`; delete it directly to force a fresh
regeneration from source.

---

## Running the portable .exe on someone else's Windows computer

### Windows SmartScreen shows "Windows protected your PC"

Expected for a new, unsigned executable -- see the "SmartScreen,
antivirus, and company policy" section of `README_PORTABLE.txt`. This
does not by itself indicate malware. Do not disable SmartScreen or
your antivirus to work around this; on a company-managed computer,
get IT approval first.

### Antivirus quarantines or deletes `LenderPackageBuilder.exe`

Also expected for a newly built, unsigned executable, especially
before a legitimate code-signing certificate has been applied (see
"Prepared for future code signing" below). Verify the ZIP's SHA-256
checksum against `..._SHA256.txt` to confirm you have the genuine
file, then submit it to your antivirus vendor for review/whitelisting
if your organization's policy allows that, or ask your IT department.

### "This app can't run on your PC"

The release is built for 64-bit Windows (x64). This message means
either a 32-bit Windows install (not supported) or a corrupted/partial
download -- re-download and re-verify the checksum.

### The app runs but document conversion for `.docx`/`.xlsx` looks
### low-fidelity (plain text/values only, no formatting)

This means neither LibreOffice nor Microsoft Office was found on that
computer, so the built-in pure-Python fallback renderer was used --
this is documented, expected behavior (see "How optional
Office/LibreOffice conversion works" in `README_PORTABLE.txt`), not a
bug. Run `RUN_DIAGNOSTICS.bat` to confirm what was/wasn't detected.
Installing LibreOffice (free) or Microsoft Office on that computer
enables higher-fidelity conversion for future runs.

### Legacy `.doc`/`.xls` files become placeholders

There is no safe pure-Python fallback for the legacy binary Office
formats -- only LibreOffice or Microsoft Office can convert them. If
neither is installed, the original file is preserved and a labeled
placeholder is used in its place. This is expected, not a bug.

---

## Reproducibility

Two builds from identical source code will not be byte-for-byte
identical (timestamps inside the PDF/ZIP, PyInstaller's own embedded
build metadata), but every dependency version and every included file
is fully documented in that build's own `BUILD_MANIFEST.txt`
(dependency versions via `pip freeze`, the exact git commit, build
date/time, and which GitHub Actions run produced it, when applicable).
Compare two manifests to see exactly what differs between builds.

---

## Prepared for future code signing

This project intentionally does not self-sign the release and present
it as trusted -- that would be misleading. When a legitimate
Authenticode code-signing certificate becomes available, it can be
applied to `dist\LenderPackageBuilder\LenderPackageBuilder.exe` (for
example with Microsoft's `signtool.exe`) as an additional step after
`BUILD_WINDOWS_PORTABLE.bat` finishes, without any change to
application logic, the PyInstaller spec, or this build process.

---

## Where to look for more detail

- `BUILD_MANIFEST.txt` (inside a built release folder) -- exact build
  environment for that specific build.
- `%LOCALAPPDATA%\LenderPackageBuilder\Logs` -- startup/crash logs.
- A processing run's own `Reports\` and `Logs\` folders -- per-job
  logs and reports (unrelated to packaging).
- `STAGE3_BUILD_AND_RELEASE.md` -- how the whole Stage 3 build and CI
  pipeline works end to end.
