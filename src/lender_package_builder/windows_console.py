"""Windows console attachment for a windowed-subsystem .exe.

A PyInstaller windowed build (no console window) has no stdout/stderr
wired up, so `print()` output from `--version`, `--self-test`, and
`--diagnostics` would be invisible when the .exe is run from an
existing terminal. This attaches to that terminal's console, the same
technique used by tools like `git.exe` that support both double-click
GUI use and command-line flags from one executable.

A no-op (and always safe) on non-Windows platforms, and effectively a
no-op when running from source, where a console already exists.
"""

from __future__ import annotations

import sys

_ATTACH_PARENT_PROCESS = -1


def attach_parent_console() -> None:
    if sys.platform != "win32":
        return

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        if not kernel32.AttachConsole(_ATTACH_PARENT_PROCESS):
            return

        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
    except Exception:
        # Console attachment is a convenience only -- a failure here
        # must never prevent the requested CLI mode from running; the
        # output will simply not be visible in that unlikely case.
        pass
