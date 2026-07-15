"""Lender Package Builder - local, offline lender package assembly engine.

No network access is ever performed on borrower content; every
operation runs on the local machine.
"""

from ._version import RELEASE_LABEL, USER_VERSION, WINDOWS_FILE_VERSION, __version__

__all__ = ["__version__", "USER_VERSION", "WINDOWS_FILE_VERSION", "RELEASE_LABEL"]
