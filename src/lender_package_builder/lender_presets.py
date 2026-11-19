"""Remembered per-lender output-part size limits.

Real user question, then request: "idk if 750 pages and 100 mb is the
best for every single package you get me? or am i wrong?" -- the right
ceiling for a package almost always comes from an EXTERNAL constraint
(what a given lender's own upload portal, email system, or investor/
custodian accepts), not from how big any particular batch of input
files happens to be. A package's own content doesn't change what limit
makes sense; the lender does. So instead of guessing a suggestion from
the uploaded files, this remembers whatever limits were actually used
the last time a build ran for a given lender name, and the GUI offers
to re-apply them the next time that same lender is typed in --
"this would be good... its gotta remember? cause idk what the presets
would be [up front]."

Pure Python, no Qt -- same GUI/engine separation as `history.py`, which
this deliberately mirrors: a corrupt or missing presets file only means
no suggestion is offered, never a reason to block a build or crash the
GUI, so every function here fails soft.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from . import runtime_paths
from .atomic_replace import replace_with_retry

_MAX_PRESETS = 200


@dataclasses.dataclass(frozen=True)
class LenderPreset:
    """The limits last used for one lender. `lender_label` keeps the
    original casing/spacing the user typed (lookups themselves are
    case-insensitive), purely so a suggestion can be displayed back
    exactly as that lender's name is normally written.
    """

    lender_label: str
    max_pages_per_part: int
    max_size_mb_per_part: float


def _normalize(lender: str) -> str:
    return lender.strip().casefold()


def _load_raw(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def lookup_preset(lender: str, path: Path | None = None) -> LenderPreset | None:
    """The remembered limits for `lender`, or None if it's blank or has
    never been seen before.
    """

    key = _normalize(lender)
    if not key:
        return None
    target = path if path is not None else runtime_paths.lender_presets_file_path()
    entry = _load_raw(target).get(key)
    if not isinstance(entry, dict):
        return None
    try:
        return LenderPreset(
            lender_label=str(entry.get("lender_label", lender.strip())),
            max_pages_per_part=int(entry["max_pages_per_part"]),
            max_size_mb_per_part=float(entry["max_size_mb_per_part"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def remember_preset(
    lender: str, max_pages_per_part: int, max_size_mb_per_part: float, path: Path | None = None
) -> None:
    """Best-effort -- called once a build actually starts with a given
    lender and limits, so the next time that lender is typed in, those
    limits are suggested. A write failure never affects the build
    itself. Does nothing when `lender` is blank -- there is nothing
    meaningful to remember it by.
    """

    key = _normalize(lender)
    if not key:
        return
    target = path if path is not None else runtime_paths.lender_presets_file_path()
    presets = _load_raw(target)

    presets[key] = {
        "lender_label": lender.strip(),
        "max_pages_per_part": max_pages_per_part,
        "max_size_mb_per_part": max_size_mb_per_part,
    }
    # Keep the store bounded -- a plain cap, not true least-recently-used
    # eviction (re-saving an existing lender doesn't move it to the back).
    while len(presets) > _MAX_PRESETS:
        presets.pop(next(iter(presets)))

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(presets, indent=2), encoding="utf-8")
    replace_with_retry(tmp, target)
