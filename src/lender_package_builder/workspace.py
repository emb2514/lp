"""Temporary workspace management.

All extraction and intermediate conversion happens inside a private
temporary directory tree, never in-place inside the user's input. The
workspace is deleted on success unless `--keep-temp` is passed; on
failure it is left behind (with logs) to aid diagnosis.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


class Workspace:
    """Owns a temporary directory tree used for one build run."""

    def __init__(self, base_dir: Path | None = None):
        self._root = Path(
            tempfile.mkdtemp(prefix="lpb_", dir=str(base_dir) if base_dir else None)
        )
        self.extract_dir = self._root / "extract"
        self.convert_dir = self._root / "convert"
        self.extract_dir.mkdir(parents=True, exist_ok=True)
        self.convert_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("Created workspace at %s", self._root)

    @property
    def root(self) -> Path:
        return self._root

    def new_extract_path(self, suggested_name: str) -> Path:
        """Return a unique path under extract_dir that will not collide.

        Duplicate filenames (including duplicate paths inside a ZIP) must
        never overwrite each other, so every extracted occurrence gets a
        unique directory keyed by a UUID.
        """

        unique_dir = self.extract_dir / uuid.uuid4().hex
        unique_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(suggested_name).name or "file"
        return unique_dir / safe_name

    def new_convert_path(self, document_id: str) -> Path:
        target_dir = self.convert_dir / document_id
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir / "converted.pdf"

    def cleanup(self) -> None:
        try:
            shutil.rmtree(self._root, ignore_errors=True)
            logger.debug("Removed workspace at %s", self._root)
        except OSError as exc:  # pragma: no cover - best effort cleanup
            logger.warning("Failed to remove workspace %s: %s", self._root, exc)
