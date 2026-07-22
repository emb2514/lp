"""Unified entry point for the single packaged executable.

The portable build ships one .exe. Run with no arguments, it opens
the normal desktop GUI. Run with `--version`, `--self-test`,
`--diagnostics`, or `--gui-smoke-test`, it behaves as a command-line
tool and exits -- no separate console build, no external Python or
pytest required.

Windows Explorer's "drag file(s) onto an .exe" passes each dropped
path as its own argv entry, so this is also where that is handled:
exactly one existing path preselects it in the GUI (never auto-
processed); anything else reuses the same "one input at a time"
rejection message the in-app drop zone already shows.

Kept import-light at module scope: PySide6, the engine, and even
`runtime_paths`-dependent I/O are only imported inside the branch that
needs them, so `--version` (the most likely first thing anyone runs to
sanity-check a build) works even if something else is broken.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

_FLAGS = {"--version", "--self-test", "--gui-smoke-test", "--diagnostics", "--help", "-h"}


@dataclasses.dataclass
class ParsedArgs:
    mode: str  # "help" | "version" | "self_test" | "diagnostics" | "gui_smoke_test" | "gui"
    preselect_path: Path | None = None
    multiple_items_message: str | None = None


def parse_args(argv: list[str]) -> ParsedArgs:
    """Pure argv parsing -- no filesystem or Qt access besides `Path.exists()`,
    so this is directly unit-testable without a display.
    """

    flags = [a for a in argv if a in _FLAGS]
    paths = [a for a in argv if a not in _FLAGS]

    if "--help" in flags or "-h" in flags:
        return ParsedArgs(mode="help")
    if "--version" in flags:
        return ParsedArgs(mode="version")
    if "--self-test" in flags:
        return ParsedArgs(mode="self_test")
    if "--diagnostics" in flags:
        return ParsedArgs(mode="diagnostics")
    if "--gui-smoke-test" in flags:
        return ParsedArgs(mode="gui_smoke_test")

    if len(paths) == 0:
        return ParsedArgs(mode="gui")
    if len(paths) == 1:
        candidate = Path(paths[0])
        if candidate.exists():
            return ParsedArgs(mode="gui", preselect_path=candidate)
        return ParsedArgs(
            mode="gui", multiple_items_message=f"That path could not be found: {candidate}"
        )

    from .gui.widgets.drop_zone import MULTIPLE_ITEMS_MESSAGE

    return ParsedArgs(mode="gui", multiple_items_message=MULTIPLE_ITEMS_MESSAGE)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parsed = parse_args(args)

    if parsed.mode == "gui":
        return _run_gui(parsed)

    from . import windows_console

    windows_console.attach_parent_console()
    try:
        if parsed.mode == "help":
            print(_help_text())
            return 0
        if parsed.mode == "version":
            return _run_version()
        if parsed.mode == "self_test":
            return _run_self_test()
        if parsed.mode == "diagnostics":
            return _run_diagnostics()
        return _run_gui_smoke_test()
    finally:
        # Detach from any console-backed stream before the interpreter
        # starts shutting down -- see release_console_streams()'s own
        # docstring for why this specifically matters here.
        windows_console.release_console_streams()


def _help_text() -> str:
    from ._version import PRODUCT_NAME, USER_VERSION

    return (
        f"{PRODUCT_NAME} {USER_VERSION}\n\n"
        "Usage:\n"
        "  LenderPackageBuilder.exe                    Launch the desktop app.\n"
        "  LenderPackageBuilder.exe <path>              Launch and preselect one ZIP, folder, or file.\n"
        "  LenderPackageBuilder.exe --version           Print the version and exit.\n"
        "  LenderPackageBuilder.exe --self-test         Run a self-contained functional check and exit.\n"
        "  LenderPackageBuilder.exe --diagnostics       Print environment diagnostics and exit.\n"
        "  LenderPackageBuilder.exe --gui-smoke-test    Verify the GUI can start and exit (used by CI).\n"
    )


def _run_version() -> int:
    from ._version import PRODUCT_NAME, USER_VERSION, __version__

    print(f"{PRODUCT_NAME} {USER_VERSION} ({__version__})")
    return 0


def _run_self_test() -> int:
    from .self_test import run_self_test

    result = run_self_test()
    print(result.render_report())
    return 0 if result.success else 1


def _run_diagnostics() -> int:
    from datetime import datetime

    from . import runtime_paths
    from .diagnostics import collect_diagnostics

    report = collect_diagnostics()
    print(report.render())
    try:
        log_dir = runtime_paths.default_log_root()
        log_dir.mkdir(parents=True, exist_ok=True)
        out_path = log_dir / f"diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        out_path.write_text(report.render(), encoding="utf-8")
        print(f"\n(Diagnostics also written to: {out_path})")
    except OSError:
        pass
    return 0


def _run_gui_smoke_test() -> int:
    """Constructs the real GUI, shows it, pumps the event loop, and
    closes it again -- proves PySide6/Qt actually works inside this
    process (packaged or source) without requiring a human to look at
    a window. Intended for CI with `QT_QPA_PLATFORM=offscreen`, but
    works unmodified against a real display too.
    """

    try:
        from .gui.app import create_app
        from .gui.main_window import MainWindow

        app = create_app()
        window = MainWindow()
        window.show()
        app.processEvents()
        window.close()
        app.processEvents()
        print("GUI SMOKE TEST: PASS")
        return 0
    except Exception as exc:
        print(f"GUI SMOKE TEST: FAIL ({exc})")
        return 1


def _run_gui(parsed: ParsedArgs) -> int:
    from .crash_log import install_excepthook, setup_crash_logging
    from .gui.app import create_app
    from .gui.main_window import MainWindow

    log_path = setup_crash_logging()
    install_excepthook(log_path)

    app = create_app()
    window = MainWindow(
        preselect_path=parsed.preselect_path,
        startup_multiple_items_message=parsed.multiple_items_message,
    )
    window.show()
    return app.exec()
