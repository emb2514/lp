# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the Lender Package Builder portable
Windows release candidate.

Builds a `--onedir` windowed application: no console flashes on a
normal double-click launch, and `--version` / `--self-test` /
`--diagnostics` / `--gui-smoke-test` attach to an already-open console
instead of needing a second console build (see `app_entry.py` and
`windows_console.py`).

Explicitly NOT done here, per the project's packaging rules:
  - No UPX compression (`upx=False` everywhere below).
  - No executable packers or obfuscators.
  - No `--onefile` build (onedir only -- faster startup, easier to
    inspect/scan, and avoids onefile's silent self-extraction step).
  - No third-party company name or trademark claimed in the version
    resource below.

Run via BUILD_WINDOWS_PORTABLE.bat, or directly from the repo root:
    pyinstaller LenderPackageBuilder.spec --noconfirm --clean
"""

import datetime
import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

REPO_ROOT = Path(SPECPATH).resolve()
SRC_DIR = REPO_ROOT / "src"
PACKAGING_DIR = REPO_ROOT / "packaging"

sys.path.insert(0, str(SRC_DIR))
from lender_package_builder._version import USER_VERSION, WINDOWS_FILE_VERSION  # noqa: E402

# ---------------------------------------------------------------------
# Icon: regenerate from the SVG source whenever it's missing or the
# source artwork changed, so the .ico can never silently go stale.
# ---------------------------------------------------------------------
ICON_PATH = PACKAGING_DIR / "app_icon.ico"
SVG_SOURCE = SRC_DIR / "lender_package_builder" / "gui" / "assets" / "app_icon.svg"
if not ICON_PATH.exists() or ICON_PATH.stat().st_mtime < SVG_SOURCE.stat().st_mtime:
    sys.path.insert(0, str(PACKAGING_DIR))
    from generate_icon import generate_icon

    generate_icon()

# ---------------------------------------------------------------------
# Windows version-info resource: generated fresh on every build from
# the single version source in `_version.py` (see `USER_VERSION`,
# `WINDOWS_FILE_VERSION` in that module) -- this file is never hand-
# edited and never a second place version numbers could drift.
# CompanyName is the product's own name, not a real registered company
# -- this is an independent local tool, not published by, affiliated
# with, or endorsed by any lender, Microsoft, Qt, or other third party.
# ---------------------------------------------------------------------
_file_version_tuple = tuple(int(p) for p in WINDOWS_FILE_VERSION.split("."))
_copyright_year = datetime.datetime.now().year
VERSION_INFO_PATH = PACKAGING_DIR / "version_info.txt"
VERSION_INFO_PATH.write_text(
    "# UTF-8\n"
    "VSVersionInfo(\n"
    "  ffi=FixedFileInfo(\n"
    f"    filevers={_file_version_tuple!r},\n"
    f"    prodvers={_file_version_tuple!r},\n"
    "    mask=0x3f,\n"
    "    flags=0x0,\n"
    "    OS=0x40004,\n"
    "    fileType=0x1,\n"
    "    subtype=0x0,\n"
    "    date=(0, 0),\n"
    "  ),\n"
    "  kids=[\n"
    "    StringFileInfo(\n"
    "      [\n"
    "        StringTable(\n"
    "          u'040904B0',\n"
    "          [\n"
    "            StringStruct(u'CompanyName', u'Lender Package Builder'),\n"
    "            StringStruct(u'FileDescription', u'Lender Package Builder "
    "- local, offline lender PDF package tool'),\n"
    f"            StringStruct(u'FileVersion', u'{WINDOWS_FILE_VERSION}'),\n"
    "            StringStruct(u'InternalName', u'LenderPackageBuilder'),\n"
    f"            StringStruct(u'LegalCopyright', u'Copyright (c) {_copyright_year} "
    "Lender Package Builder. All rights reserved.'),\n"
    "            StringStruct(u'OriginalFilename', u'LenderPackageBuilder.exe'),\n"
    "            StringStruct(u'ProductName', u'Lender Package Builder'),\n"
    f"            StringStruct(u'ProductVersion', u'{USER_VERSION}'),\n"
    "          ],\n"
    "        )\n"
    "      ]\n"
    "    ),\n"
    "    VarFileInfo([VarStruct(u'Translation', [1033, 1200])]),\n"
    "  ],\n"
    ")\n",
    encoding="utf-8",
)

# ---------------------------------------------------------------------
# Package metadata: bundled so `importlib.metadata.version(...)` works
# the same way frozen as it does from source (used by `diagnostics.py`
# and by anything else that inspects installed-package versions at
# runtime). A frozen PyInstaller build does not ship .dist-info
# directories by default.
# ---------------------------------------------------------------------
_metadata_datas = []
for _dist_name in (
    "pypdf",
    "reportlab",
    "Pillow",
    "python-docx",
    "openpyxl",
    "beautifulsoup4",
    "extract-msg",
    "PySide6",
    "pypdfium2",
):
    _metadata_datas += copy_metadata(_dist_name)

block_cipher = None

# extract-msg's own runtime dependencies (see its METADATA "Requires").
# PyInstaller's static import graph normally finds these on its own,
# but they are listed explicitly per the project's packaging
# requirements so .msg (Outlook email) conversion cannot silently lose
# a dependency in a future PyInstaller version.
_extract_msg_deps = [
    "compressed_rtf",
    "ebcdic",
    "olefile",
    # The "red-black-tree-mod" distribution's importable modules are
    # red_black_dict_mod / red_black_set_mod, not a module matching
    # the distribution's own name.
    "red_black_dict_mod",
    "red_black_set_mod",
    "RTFDE",
    "tzlocal",
]

_hiddenimports = [
    "pypdf",
    "reportlab",
    "reportlab.graphics.barcode",
    "PIL",
    "PIL.Image",
    "docx",
    "openpyxl",
    "bs4",
    "extract_msg",
    # RC2 content-aware duplicate detection's last-tier page rasterizer
    # (pdf_render.py). pyinstaller-hooks-contrib ships hook-pypdfium2.py,
    # which bundles the native PDFium binary automatically -- this entry
    # is belt-and-suspenders for the pure-Python import itself.
    "pypdfium2",
    *_extract_msg_deps,
]

# Microsoft Office COM automation (conversion/office.py) is Windows-
# only and already defensively guarded there with `try/except
# ImportError` -- these hidden imports only matter, and are only
# resolvable, when actually building on Windows.
if sys.platform == "win32":
    _hiddenimports += [
        "win32com",
        "win32com.client",
        "win32api",
        "win32con",
        "pythoncom",
        "pywintypes",
    ]

# Only the one data directory the frozen app actually reads at runtime
# via `runtime_paths.bundled_assets_root()` -- deliberately NOT tests/,
# .git/, .venv/, dev caches, or config.toml (config.toml ships as an
# external, user-editable sibling of the .exe instead; see
# BUILD_WINDOWS_PORTABLE.bat).
a = Analysis(
    [str(PACKAGING_DIR / "pyinstaller_entry.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=[
        (str(SRC_DIR / "lender_package_builder" / "gui" / "assets"), "gui/assets"),
        *_metadata_datas,
    ],
    hiddenimports=_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        # lxml is a real, needed transitive dependency (python-docx uses
        # lxml.etree for .docx XML parsing), but pyinstaller-hooks-
        # contrib's hook-lxml.py unconditionally collect_submodules()'s
        # ALL of lxml -- including lxml.isoschematron, an unrelated ISO
        # Schematron XML-validation submodule this app never imports
        # (confirmed: nothing in this app or python-docx references
        # isoschematron). That submodule's own hook then bundles its
        # entire resources/ tree, whose deepest file
        # (isoschematron/resources/xsl/iso-schematron-xslt1/
        # iso_schematron_skeleton_for_xslt1.xsl) is ~90 characters of
        # nested path on its own -- confirmed, via a real user's crash,
        # to push the full extracted path over Windows Explorer's
        # classic 260-char extraction limit (distinct from this app's
        # own MAX_PATH handling for output folders it creates itself;
        # this is Explorer's built-in Zip extraction, which is not
        # long-path-aware). Excluding it removes ~30 files of a
        # submodule nothing in this app's dependency graph ever calls.
        "lxml.isoschematron",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LenderPackageBuilder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_PATH),
    version=str(VERSION_INFO_PATH),
    manifest=str(PACKAGING_DIR / "app.manifest"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LenderPackageBuilder",
)
