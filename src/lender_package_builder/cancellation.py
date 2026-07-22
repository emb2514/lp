"""Cooperative cancellation support for a running build.

`CancellationToken` wraps a `threading.Event`. GUI code calls
`request()` from the main thread once the user confirms "Stop
Processing" in the Cancel Processing dialog; pipeline code calls
`check_cancelled(token)` between safe units of work -- never mid-write
of a single file -- to raise `ProcessingCancelled` as soon as it is
safe to stop. No pipeline code ever force-kills the worker thread or
process; every stop is cooperative.
"""

from __future__ import annotations

import threading


class ProcessingCancelled(Exception):
    """Internal signal raised by `check_cancelled()`. Caught only by
    `cli.build_package()`, which owns cleanup and reporting -- every
    other module simply lets this propagate uncaught.
    """


class CancellationToken:
    """Thread-safe request/check flag, one per build run."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def request(self) -> None:
        self._event.set()

    def is_requested(self) -> bool:
        return self._event.is_set()


def check_cancelled(token: CancellationToken | None) -> None:
    """Raises `ProcessingCancelled` if `token` is set. A no-op when
    `token` is None, so every check point below stays a single call
    regardless of whether the caller opted into cancellation support.
    """

    if token is not None and token.is_requested():
        raise ProcessingCancelled()
