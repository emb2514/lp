"""Single authoritative version source for Lender Package Builder.

Every other place a version string appears (package metadata,
`__version__`, the GUI window title, Windows executable metadata, the
release folder/ZIP name, the build manifest) is derived from the three
constants below -- there is no second place to update.
"""

from __future__ import annotations

#: PEP 440 package version. Used in pyproject.toml (via [tool.setuptools.dynamic]),
#: pip metadata, and Processing_Report.txt / Processing_Manifest.json.
__version__ = "1.0.0rc1"

#: Friendly, user-facing version shown in the GUI and printed by --version.
USER_VERSION = "1.0.0 RC1"

#: Windows executable file-version property (must be N.N.N.N).
WINDOWS_FILE_VERSION = "1.0.0.0"

#: Short label used to name the release folder/ZIP (no spaces).
RELEASE_LABEL = "1.0.0_RC1"
