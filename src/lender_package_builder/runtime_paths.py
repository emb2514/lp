"""Runtime path resolution for both source and PyInstaller-frozen execution.

PyInstaller's bootloader sets `sys.frozen = True` and `sys._MEIPASS` to
the directory holding bundled data. For a `--onedir` build (what Stage 3
uses), `sys._MEIPASS` is the same directory the executable itself lives
in, but reading it via the documented `sys._MEIPASS` attribute (rather
than assuming `sys.executable`'s parent always equals the bundle root)
keeps this working correctly even if that ever changes.

Nothing in this module imports Qt or the engine, so it can be imported
very early (before any other subsystem) and used to locate the external
config file before logging or the GUI even exist.
"""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running inside a PyInstaller-built executable."""

    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """The portable application folder.

    Frozen: the folder containing the .exe (where `config.toml`,
    `README_PORTABLE.txt`, etc. live alongside it).
    Source: the project root (three levels above this file:
    src/lender_package_builder/runtime_paths.py -> project root).
    """

    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def bundled_assets_root() -> Path:
    """Where bundled read-only resources (icons, etc.) are found.

    Frozen: PyInstaller's extraction/bundle directory (`sys._MEIPASS`).
    Source: this package's own directory, so `gui/assets/...` resolves
    the same way it always has.
    """

    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", app_root()))
    return Path(__file__).resolve().parent


def external_config_path() -> Path:
    """Where the user-editable `config.toml` is looked for.

    Always a sibling of the application root -- next to the .exe when
    frozen, at the project root when running from source. A missing
    file here is not an error; callers fall back to built-in defaults.
    """

    return app_root() / "config.toml"


def default_log_root() -> Path:
    """A guaranteed-writable location for startup/crash logs, used only
    before a normal per-job output/Logs folder exists (e.g. an error
    during config loading, before any input has even been chosen).

    Windows: %LOCALAPPDATA%\\LenderPackageBuilder\\Logs
    Other platforms (source-mode development): ~/.local/share/LenderPackageBuilder/Logs
    """

    import os

    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        base_path = Path(base) if base else Path.home() / "AppData" / "Local"
    else:
        base_path = Path.home() / ".local" / "share"
    return base_path / "LenderPackageBuilder" / "Logs"
