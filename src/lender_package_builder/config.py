"""Configuration loading for Lender Package Builder.

Defaults live here and are overridden, in order, by `config.toml` (if
present) and then by explicit CLI flags. Uses the standard-library
`tomllib` parser (available on Python 3.11+), so no extra dependency is
required just to read configuration.
"""

from __future__ import annotations

import dataclasses
import tomllib
from pathlib import Path


@dataclasses.dataclass
class AppConfig:
    page_limit: int = 200
    size_limit_mb: float = 75.0

    large_input_warning_mb: float = 2000.0
    max_expanded_size_mb: float = 8000.0
    max_archive_entries: int = 200_000
    required_free_space_multiplier: float = 3.0

    office_backend_order: tuple[str, ...] = ("libreoffice", "office_com", "fallback")

    log_level: str = "INFO"

    @property
    def size_limit_bytes(self) -> int:
        return int(self.size_limit_mb * 1024 * 1024)

    @property
    def large_input_warning_bytes(self) -> int:
        return int(self.large_input_warning_mb * 1024 * 1024)

    @property
    def max_expanded_size_bytes(self) -> int:
        return int(self.max_expanded_size_mb * 1024 * 1024)


def load_config(config_path: Path | None) -> AppConfig:
    """Load configuration from a TOML file, falling back to defaults.

    A missing file is not an error -- built-in defaults are used. A
    present-but-invalid file raises so the user finds out immediately
    rather than silently running with unexpected values.
    """

    cfg = AppConfig()
    if config_path is None or not config_path.exists():
        return cfg

    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    splitting = raw.get("splitting", {})
    safety = raw.get("safety", {})
    conversion = raw.get("conversion", {})
    logging_cfg = raw.get("logging", {})

    if "page_limit" in splitting:
        cfg.page_limit = int(splitting["page_limit"])
    if "size_limit_mb" in splitting:
        cfg.size_limit_mb = float(splitting["size_limit_mb"])

    if "large_input_warning_mb" in safety:
        cfg.large_input_warning_mb = float(safety["large_input_warning_mb"])
    if "max_expanded_size_mb" in safety:
        cfg.max_expanded_size_mb = float(safety["max_expanded_size_mb"])
    if "max_archive_entries" in safety:
        cfg.max_archive_entries = int(safety["max_archive_entries"])
    if "required_free_space_multiplier" in safety:
        cfg.required_free_space_multiplier = float(safety["required_free_space_multiplier"])

    if "office_backend_order" in conversion:
        cfg.office_backend_order = tuple(conversion["office_backend_order"])

    if "level" in logging_cfg:
        cfg.log_level = str(logging_cfg["level"])

    return cfg
