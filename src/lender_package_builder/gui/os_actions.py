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
