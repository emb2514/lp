"""Whole-file SHA-256 hashing.

Hashing is always performed on the exact original extracted bytes,
before any conversion happens. This module contains no conversion or
comparison logic on purpose: it is the single source of truth for "what
does this original file's content hash to."
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK_SIZE = 1024 * 1024


def sha256_of_file(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of a file's exact bytes."""

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
