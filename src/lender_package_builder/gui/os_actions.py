"""Operating-system actions: opening folders in the system file manager.

Isolated here so widgets never call Qt's OS-integration APIs directly
-- keeps that concern testable/mockable in one place (see TEST 15).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def open_folder(path: Path) -> bool:
    """Open `path` in the system file manager (Explorer on Windows).

    Returns True if Qt reports the request was handled, False
    otherwise (e.g. the path does not exist). Never raises.
    """

    if not path.exists():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def open_file(path: Path) -> bool:
    """Open `path` with the OS default handler for its file type (e.g.
    the system PDF viewer on Windows). Opening a specific PAGE within a
    PDF is not reliably supported across Windows PDF viewers, so this
    only ever opens the whole file -- callers needing a specific page
    must show that page number in the UI instead of pretending direct-
    page opening worked.

    Returns True if Qt reports the request was handled, False
    otherwise (e.g. the path does not exist). Never raises.
    """

    if not path.exists():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
