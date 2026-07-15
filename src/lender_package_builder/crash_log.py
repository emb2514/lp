"""Startup/crash logging for the GUI entry point.

A windowed-subsystem .exe with no console has nowhere to show an
unhandled exception -- the process just disappears. This writes a
timestamped log file under `runtime_paths.default_log_root()` before
the GUI starts, and installs a `sys.excepthook` that appends any
unhandled exception to that same file, so a crash during startup still
leaves evidence the user can send back.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import runtime_paths
from ._version import USER_VERSION, __version__


def setup_crash_logging() -> Path:
    """Create (or reuse) the log directory and return today's startup
    log file path. Never raises -- if the log directory cannot be
    created, a best-effort path is still returned so callers have
    something to report to the user.
    """

    log_dir = runtime_paths.default_log_root()
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"startup_{timestamp}.log"
    try:
        with log_path.open("w", encoding="utf-8") as fh:
            fh.write(f"Lender Package Builder {USER_VERSION} ({__version__}) starting.\n")
            fh.write(f"Frozen: {runtime_paths.is_frozen()}\n")
            fh.write(f"App root: {runtime_paths.app_root()}\n")
    except OSError:
        pass
    return log_path


def install_excepthook(log_path: Path) -> None:
    previous_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb) -> None:
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write("\n--- UNHANDLED EXCEPTION ---\n")
                fh.write(f"{datetime.now().isoformat(timespec='seconds')}\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=fh)
        except OSError:
            pass
        previous_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
