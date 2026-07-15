"""PyInstaller's Analysis needs a script path, not an installed console
entry point, so this tiny bootstrap is what actually gets frozen. It
does nothing beyond calling the same `app_entry.main()` used by the
`lender-package-builder-gui` console-script when running from source,
so packaged and source behavior stay identical.
"""

from __future__ import annotations

import sys

from lender_package_builder.app_entry import main

if __name__ == "__main__":
    sys.exit(main())
