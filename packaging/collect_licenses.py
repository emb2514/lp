"""Collects each bundled third-party package's own license file into
`licenses\\<package>.txt` inside a release folder, so
THIRD_PARTY_NOTICES.txt's claim that "full license text is included"
is actually true rather than aspirational.

Run with: python packaging/collect_licenses.py <release_dir>
"""

from __future__ import annotations

import sys
from importlib import metadata as importlib_metadata
from pathlib import Path

# Every bundled distribution THIRD_PARTY_NOTICES.txt describes. Keep
# this list in sync with that file and with LenderPackageBuilder.spec's
# `copy_metadata` list.
_DISTRIBUTIONS = [
    "pyinstaller",
    "PySide6",
    "shiboken6",
    "pypdf",
    "pypdfium2",
    "reportlab",
    "Pillow",
    "python-docx",
    "openpyxl",
    "beautifulsoup4",
    "extract-msg",
    "compressed-rtf",
    "ebcdic",
    "olefile",
    "red-black-tree-mod",
    "RTFDE",
    "tzlocal",
    "pywin32",
]

_LICENSE_FILENAME_HINTS = ("LICENSE", "LICENCE", "COPYING", "NOTICE")


def _find_license_text(dist_name: str) -> str | None:
    try:
        dist = importlib_metadata.distribution(dist_name)
    except importlib_metadata.PackageNotFoundError:
        return None

    files = dist.files or []
    for f in files:
        name = Path(str(f)).name
        if any(hint in name.upper() for hint in _LICENSE_FILENAME_HINTS):
            try:
                # `Distribution.read_text()` resolves its argument
                # relative to the dist-info directory itself, but `f`
                # here is relative to the site-packages root (as
                # recorded in RECORD) -- `locate_file` resolves that
                # correctly regardless of which root it's relative to.
                path = Path(dist.locate_file(f))
                if path.exists():
                    return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

    # Some packages only declare the license as metadata text, with no
    # separate LICENSE file shipped in the wheel.
    license_expr = dist.metadata.get("License-Expression") or dist.metadata.get("License")
    if license_expr:
        return f"(No separate license file was shipped with this package.)\nDeclared license: {license_expr}\n"
    return None


def collect_licenses(release_dir: Path) -> list[str]:
    licenses_dir = release_dir / "licenses"
    licenses_dir.mkdir(parents=True, exist_ok=True)

    missing = []
    for dist_name in _DISTRIBUTIONS:
        text = _find_license_text(dist_name)
        if text is None:
            missing.append(dist_name)
            continue
        safe_name = dist_name.replace("/", "_")
        (licenses_dir / f"{safe_name}.txt").write_text(text, encoding="utf-8", errors="replace")
    return missing


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python packaging/collect_licenses.py <release_dir>", file=sys.stderr)
        return 2

    release_dir = Path(sys.argv[1])
    if not release_dir.exists():
        print(f"ERROR: release directory does not exist: {release_dir}", file=sys.stderr)
        return 1

    missing = collect_licenses(release_dir)
    if missing:
        # pywin32 is expected to be "missing" on a non-Windows build
        # environment and is not fatal -- everything else should be
        # found, since these are all real installed dependencies.
        unexpected = [m for m in missing if m.lower() != "pywin32"]
        print(f"Collected licenses; not found: {', '.join(missing)}")
        if unexpected:
            print(f"ERROR: unexpected missing license(s): {', '.join(unexpected)}", file=sys.stderr)
            return 1
        return 0

    print("Collected all third-party license files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
