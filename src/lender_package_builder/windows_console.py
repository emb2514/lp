"""Windows console attachment for a windowed-subsystem .exe.

A PyInstaller windowed build (`console=False`) sets `sys.stdout`,
`sys.stderr`, and `sys.stdin` to `None` on Windows -- there is no
console to write to. That makes any bare `print()` in the CLI modes
(`--version`, `--self-test`, `--diagnostics`) raise an unhandled
`AttributeError` and crash with no visible output at all (there is
nowhere to even print the traceback), rather than just being silently
invisible.

`attach_parent_console()` guarantees `sys.stdout`/`sys.stderr`/
`sys.stdin` are real, writable objects by the time it returns --
`print()` must never crash the process regardless of what console (if
any) is available:

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

`release_console_streams()` undoes that reassignment before interpreter
shutdown (see its own docstring). It is a no-op unless
`attach_parent_console()` actually reassigned something -- critically,
this means it never touches `sys.stdout`/`sys.stderr` when they were
already valid to begin with (e.g. running under `pytest`'s own output
capture, or from source via `python.exe`). An earlier version did not
have this guard and corrupted `pytest`'s capture fixtures for the rest
of the test session when the *test suite itself* ran on real Windows,
where `sys.platform == "win32"` is true throughout.

Both functions are a no-op on non-Windows platforms.
"""

from __future__ import annotations

import os
import sys

_ATTACH_PARENT_PROCESS = -1

_streams_attached = False


def attach_parent_console() -> None:
    global _streams_attached

    if sys.platform != "win32":
        return
    if sys.stdout is not None and sys.stderr is not None:
        # Already have working streams (e.g. running from source via
        # python.exe, under pytest's own capture, or already attached)
        # -- nothing to fix, and nothing for release_console_streams()
        # to undo later.
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

    _streams_attached = True


def release_console_streams() -> None:
    """Call this once a CLI mode is completely done printing, before
    returning from `main()` and letting the interpreter shut down.

    CPython has flushed `sys.stdout`/`sys.stderr` during interpreter
    finalization and reported a non-zero process exit status if that
    flush fails since Python 3.6 -- even after `sys.exit(0)` was
    already called with a successful result. A real Win32 console
    handle reopened via `attach_parent_console()` is an unusual object
    for the interpreter to flush/close a second time during shutdown;
    detaching from it explicitly here, and replacing it with a plain
    `os.devnull`-backed file (which can never fail to flush/close),
    means whatever the interpreter does next can't corrupt the exit
    code this CLI mode already decided.

    A no-op on non-Windows platforms, and -- just as importantly -- a
    no-op if `attach_parent_console()` never actually reassigned
    anything (streams were already valid). Without that guard, this
    would blindly close and replace whatever `sys.stdout`/`sys.stderr`
    currently are, which is actively harmful when they belong to
    something else entirely, such as pytest's own capture fixtures
    when the test suite itself runs on real Windows.
    """

    global _streams_attached

    if not _streams_attached:
        return
    _streams_attached = False

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        try:
            stream.flush()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass
        try:
            setattr(sys, stream_name, open(os.devnull, "w", encoding="utf-8"))
        except OSError:
            setattr(sys, stream_name, None)

    stdin = getattr(sys, "stdin", None)
    if stdin is not None:
        try:
            stdin.close()
        except Exception:
            pass
        try:
            sys.stdin = open(os.devnull, "r", encoding="utf-8")
        except OSError:
            sys.stdin = None
