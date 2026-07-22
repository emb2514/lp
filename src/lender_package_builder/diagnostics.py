"""Packaged diagnostics: a read-only snapshot of the environment the
app is actually running in, for troubleshooting on a machine the
developer cannot see directly (e.g. a lender's locked-down Windows
laptop).

Nothing here modifies the system. Office/LibreOffice detection is a
lightweight presence probe only -- it never launches Word, Excel, or
LibreOffice.
"""

from __future__ import annotations

import dataclasses
import importlib
import platform
import shutil
import sys
from importlib import metadata as importlib_metadata
from pathlib import Path

from . import __version__, runtime_paths
from ._version import PRODUCT_NAME, RELEASE_LABEL, USER_VERSION, WINDOWS_FILE_VERSION
from .config import load_config_safe

# (distribution name for `importlib.metadata`, importable module name).
# A frozen PyInstaller bundle does not ship `.dist-info` metadata, so
# the metadata lookup is tried first (fast, exact version) and falls
# back to actually importing the module -- which is what proves the
# library is really usable inside a frozen build, metadata or not.
_LIBRARY_MODULES = (
    ("pypdf", "pypdf"),
    ("reportlab", "reportlab"),
    ("Pillow", "PIL"),
    ("python-docx", "docx"),
    ("openpyxl", "openpyxl"),
    ("beautifulsoup4", "bs4"),
    ("extract-msg", "extract_msg"),
    ("PySide6", "PySide6"),
)

_WINDOWS_LIBREOFFICE_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


@dataclasses.dataclass
class DiagnosticsReport:
    lines: list[str]

    def render(self) -> str:
        return "\n".join(self.lines)


def collect_diagnostics() -> DiagnosticsReport:
    lines: list[str] = []
    lines.append(f"{PRODUCT_NAME} -- Diagnostics")
    lines.append("=" * 60)
    lines.extend(_version_section())
    lines.append("")
    lines.extend(_runtime_section())
    lines.append("")
    lines.extend(_config_section())
    lines.append("")
    lines.extend(_system_section())
    lines.append("")
    lines.extend(_library_section())
    lines.append("")
    lines.extend(_document_backend_section())
    return DiagnosticsReport(lines=lines)


def _version_section() -> list[str]:
    return [
        "[Version]",
        f"  Package version:  {__version__}",
        f"  Displayed as:     {USER_VERSION}",
        f"  Windows file ver: {WINDOWS_FILE_VERSION}",
        f"  Release label:    {RELEASE_LABEL}",
    ]


def _runtime_section() -> list[str]:
    lines = [
        "[Runtime]",
        f"  Frozen (packaged .exe): {runtime_paths.is_frozen()}",
        f"  App root:               {runtime_paths.app_root()}",
        f"  Bundled assets root:    {runtime_paths.bundled_assets_root()}",
        f"  Log directory:          {runtime_paths.default_log_root()}",
        f"  Executable:             {sys.executable}",
    ]
    lines.append(f"  Python version:         {platform.python_version()}")
    return lines


def _config_section() -> list[str]:
    config_path = runtime_paths.external_config_path()
    result = load_config_safe(config_path)
    lines = [
        "[Configuration]",
        f"  config.toml path: {config_path}",
        f"  Exists:           {config_path.exists()}",
    ]
    if result.used_defaults_due_to_error:
        lines.append(f"  Status:           INVALID -- using built-in defaults ({result.warning})")
    else:
        lines.append("  Status:           OK (or not present -- using built-in defaults)")
    lines.append(f"  max_pages_per_part:    {result.config.max_pages_per_part}")
    lines.append(f"  max_size_mb_per_part:  {result.config.max_size_mb_per_part}")
    return lines


def _system_section() -> list[str]:
    lines = [
        "[System]",
        f"  Platform:  {platform.platform()}",
        f"  Machine:   {platform.machine()}",
        f"  Processor: {platform.processor() or 'unknown'}",
    ]
    try:
        app_root = runtime_paths.app_root()
        usage = shutil.disk_usage(app_root)
        lines.append(
            f"  Disk free at app root: {usage.free / (1024 * 1024):.0f} MB "
            f"of {usage.total / (1024 * 1024):.0f} MB"
        )
    except OSError as exc:
        lines.append(f"  Disk free at app root: could not determine ({exc})")
    return lines


def _library_section() -> list[str]:
    lines = ["[Bundled libraries]"]
    for display_name, module_name in _LIBRARY_MODULES:
        try:
            version = importlib_metadata.version(display_name)
            lines.append(f"  {display_name}: {version}")
            continue
        except importlib_metadata.PackageNotFoundError:
            pass

        try:
            module = importlib.import_module(module_name)
        except ImportError:
            lines.append(f"  {display_name}: NOT FOUND")
            continue

        version = getattr(module, "__version__", None)
        if version:
            lines.append(f"  {display_name}: {version}")
        else:
            lines.append(f"  {display_name}: installed (version unknown)")

    try:
        from PySide6.QtCore import qVersion

        lines.append(f"  Qt (runtime): {qVersion()}")
    except Exception as exc:  # diagnostics must never crash on a broken Qt install
        lines.append(f"  Qt runtime probe failed: {exc}")
    return lines


def _document_backend_section() -> list[str]:
    lines = ["[Document conversion backends]"]

    soffice = _find_libreoffice()
    lines.append(f"  LibreOffice (soffice): {'found at ' + soffice if soffice else 'not found'}")

    if sys.platform == "win32":
        lines.append(f"  Microsoft Word (COM):  {_describe_office_com('Word.Application')}")
        lines.append(f"  Microsoft Excel (COM): {_describe_office_com('Excel.Application')}")
    else:
        lines.append("  Microsoft Office (COM): not applicable (not running on Windows)")

    lines.append(
        "  Pure-Python fallback (.docx/.xlsx only, text/values, no formatting): always available"
    )
    return lines


def _find_libreoffice() -> str | None:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    if platform.system() == "Windows":
        for candidate in _WINDOWS_LIBREOFFICE_CANDIDATES:
            if Path(candidate).exists():
                return candidate
    return None


def _describe_office_com(prog_id: str) -> str:
    """Windows-only, registry-only presence check.

    Reads whether `prog_id` (e.g. "Word.Application") is registered
    under HKEY_CLASSES_ROOT. This never launches Office -- it only
    inspects the registry, exactly like Windows Explorer does to
    decide which icon to show a file type.
    """

    try:
        import winreg
    except ImportError:
        return "unknown (winreg unavailable)"

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, prog_id):
            return "registered"
    except FileNotFoundError:
        return "not registered (Office not installed, or not registered for automation)"
    except OSError as exc:
        return f"unknown ({exc})"
