"""Windows console attachment for a windowed-subsystem .exe.

A PyInstaller windowed build (`console=False`) sets `sys.stdout`,
`sys.stderr`, and `sys.stdin` to `None` on Windows -- there is no
console to write to. That makes any bare `print()` in the CLI modes
(`--version`, `--self-test`, `--diagnostics`) raise an unhandled
`AttributeError` and crash with no visible output at all (there is
nowhere to even print the traceback), rather than just being silently
invisible.

This function guarantees `sys.stdout`/`sys.stderr`/`sys.stdin` are
real, writable streams by the time it returns, using the same
technique tools like `git.exe` use to support both double-click GUI
use and command-line flags from one executable:

1. Attach to an already-open console the process was launched from
   (a real terminal window), if one exists in the process's ancestry.
2. Otherwise, allocate a brand-new console. This covers automation
   contexts (e.g. a CI runner) that have no console anywhere in the
   process tree at all -- relying on AttachConsole alone silently
   no-ops there, leaving stdout/stderr as None and crashing the very
   next print().

A no-op (and always safe) on non-Windows platforms, and effectively a
no-op when stdout/stderr are already valid streams (running from
source via `python.exe`, or already attached).
"""

from __future__ import annotations

import sys

_ATTACH_PARENT_PROCESS = -1


def attach_parent_console() -> None:
    if sys.platform != "win32":
        return
    if sys.stdout is not None and sys.stderr is not None:
        # Already have working streams (e.g. running from source via
        # python.exe, or already attached) -- nothing to fix.
        return

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        attached = bool(kernel32.AttachConsole(_ATTACH_PARENT_PROCESS))
        if not attached:
            # No existing console anywhere in the process's ancestry
            # (e.g. double-clicked with no terminal, or a
            # non-interactive automation context) -- create one so
            # stdout/stderr are never left as None.
            attached = bool(kernel32.AllocConsole())
        if not attached:
            return

        for stream_name, device, mode in (
            ("stdout", "CONOUT$", "w"),
            ("stderr", "CONOUT$", "w"),
            ("stdin", "CONIN$", "r"),
        ):
            try:
                setattr(sys, stream_name, open(device, mode, encoding="utf-8", errors="replace"))
            except OSError:
                # One stream failing to (re)open must not prevent the
                # others from working.
                continue
    except Exception:
        # Console attachment is a convenience only -- a failure here
        # must never prevent the requested CLI mode from running.
        pass
