"""Single authoritative version/branding source for Lender Package Builder.

Every other place a version string appears (package metadata,
`__version__`, the GUI window title, Windows executable metadata, the
release folder/ZIP name, the build manifest) is derived from the three
constants below -- there is no second place to update.

`PRODUCT_NAME` is the single user-visible branding string (GUI window
title/header, `--version` output, generated report headers). This is a
branding change only -- the internal Python package name
(`lender_package_builder`), CLI command names, config folder names,
and report schemas/field names are deliberately left untouched.
"""

from __future__ import annotations

#: The user-visible product name shown in the GUI and printed by
#: --version/--about, and in generated report headers. Distinct from
#: the internal Python package name, which is never renamed.
PRODUCT_NAME = "Document Merger"

#: PEP 440 package version. Used in pyproject.toml (via [tool.setuptools.dynamic]),
#: pip metadata, and Processing_Report.txt / Processing_Manifest.json.
__version__ = "1.0.0rc2"

#: Friendly, user-facing version shown in the GUI and printed by --version.
USER_VERSION = "RC2"

#: Windows executable file-version property (must be N.N.N.N).
WINDOWS_FILE_VERSION = "1.0.0.2"

#: Short label used to name the release folder/ZIP (no spaces).
RELEASE_LABEL = "RC2"
