"""Windows-safe atomic file replace, with a short bounded retry.

`Path.replace()` (`os.replace()` / `MoveFileExW` on Windows) fails with
`PermissionError` ("WinError 32: The process cannot access the file
because it is being used by another process") if something else has the
source or destination file transiently open at the exact moment of the
rename -- most commonly antivirus real-time scanning, cloud-sync clients
(OneDrive/Dropbox), Windows Search indexing, or Explorer generating a
thumbnail, all of which routinely open a freshly-written file within
milliseconds of its creation. This is a real, reported crash: a merged
PDF part written to a user's Downloads folder hit exactly this race
during the immediately-following rename to its final filename.

These locks are normally released within a second or two, so a short
retry resolves the overwhelming majority of cases with no user-visible
delay. POSIX `rename()` has no equivalent failure mode, so this is a
harmless no-op fast path (first attempt always succeeds) on Linux/macOS.
If the file is still locked after every attempt, the original
`PermissionError` is re-raised unchanged -- this never silently drops a
file, it only gives a transient lock time to clear.
"""

from __future__ import annotations

import time
from pathlib import Path

_DEFAULT_MAX_ATTEMPTS = 15
_DEFAULT_DELAY_SECONDS = 0.3


def replace_with_retry(
    src: Path,
    dest: Path,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    delay_seconds: float = _DEFAULT_DELAY_SECONDS,
) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            src.replace(dest)
            return
        except PermissionError:
            if attempt == max_attempts:
                raise
            time.sleep(delay_seconds)
