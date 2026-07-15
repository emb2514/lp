"""Windows console attachment for a windowed-subsystem .exe.

A PyInstaller windowed build (`console=False`) sets `sys.stdout`,
`sys.stderr`, and `sys.stdin` to `None` on Windows -- there is no
console to write to. That makes any bare `print()` in the CLI modes
(`--version`, `--self-test`, `--diagnostics`) raise an unhandled
`AttributeError` and crash with no visible output at all (there is
nowhere to even print the traceback), rather than just being silently
invisible.

This function guarantees `sys.stdout`/`sys.stderr`/`sys.stdin` are
real, writable objects by the time it returns -- `print()` must never
crash the process regardless of what console (if any) is available:

1. Attach to an already-open console the process was launched from
   (a real terminal window), if one exists in the process's ancestry
   -- the same technique tools like `git.exe` use to support both
   double-click GUI use and command-line flags from one executable.
2. Otherwise, fall back to a null writer/reader (like redirecting to
   `os.devnull`). This deliberately does NOT call `AllocConsole()` to
   create a brand-new console window: that additionally proved to
   cause an unrelated failure when exercised on a real Windows
   GitHub Actions runner (a non-interactive automation context with
   no window station) -- creating a whole new console there is both
   unnecessary (nothing is present to read it) and, empirically,
   risky. A null fallback fixes the actual bug (a crash from writing
   to `None`) with no such risk; the only cost is that CLI mode output
   is invisible in that one narrow case (no console anywhere in the
   process's ancestry), which does not affect exit codes.

A no-op (and always safe) on non-Windows platforms, and effectively a
no-op when stdout/stderr are already valid streams (running from
source via `python.exe`, or already attached).
"""

from __future__ import annotations

import os
import sys

_ATTACH_PARENT_PROCESS = -1


def attach_parent_console() -> None:
    if sys.platform != "win32":
        return
    if sys.stdout is not None and sys.stderr is not None:
        # Already have working streams (e.g. running from source via
        # python.exe, or already attached) -- nothing to fix.
        return

    attached = False
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        attached = bool(kernel32.AttachConsole(_ATTACH_PARENT_PROCESS))
    except Exception:
        attached = False

    if attached:
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

    # Whatever attaching did or didn't accomplish above, guarantee
    # stdout/stderr/stdin are never left as None -- a bare print() or
    # input() must never crash the process.
    for stream_name in ("stdout", "stderr"):
        if getattr(sys, stream_name, None) is None:
            try:
                setattr(sys, stream_name, open(os.devnull, "w", encoding="utf-8"))
            except OSError:
                pass
    if getattr(sys, "stdin", None) is None:
        try:
            sys.stdin = open(os.devnull, "r", encoding="utf-8")
        except OSError:
            pass
