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

from .exceptions import InvalidConfigError


@dataclasses.dataclass
class AppConfig:
    # Maximum output-part constraints (NOT targets -- see splitting.py).
    # A part is closed as soon as adding the next whole document would
    # exceed either maximum; parts are never padded or rearranged to
    # approach these values. See "Choosing the output-part size
    # defaults" in README.md for the benchmark-based reasoning behind
    # the shipped defaults.
    max_pages_per_part: int = 750
    max_size_mb_per_part: float = 100.0

    large_input_warning_mb: float = 2000.0
    max_expanded_size_mb: float = 8000.0
    max_archive_entries: int = 200_000
    required_free_space_multiplier: float = 3.0

    office_backend_order: tuple[str, ...] = ("libreoffice", "office_com", "fallback")

    log_level: str = "INFO"

    @property
    def max_size_bytes_per_part(self) -> int:
        return int(self.max_size_mb_per_part * 1024 * 1024)

    @property
    def large_input_warning_bytes(self) -> int:
        return int(self.large_input_warning_mb * 1024 * 1024)

    @property
    def max_expanded_size_bytes(self) -> int:
        return int(self.max_expanded_size_mb * 1024 * 1024)


def load_config(config_path: Path | None) -> AppConfig:
    """Load configuration from a TOML file, falling back to defaults.

    A missing file is not an error -- built-in defaults are used. A
    present-but-invalid file raises `InvalidConfigError` (a friendly,
    user-facing message) rather than a raw parser traceback, and never
    silently falls back to unexpected values without telling the
    caller. This function never writes to `config_path` -- a
    user-edited config is only ever read, never overwritten.
    """

    cfg = AppConfig()
    if config_path is None or not config_path.exists():
        return cfg

    try:
        with config_path.open("rb") as fh:
            raw = tomllib.load(fh)

        splitting = raw.get("splitting", {}) or {}
        safety = raw.get("safety", {}) or {}
        conversion = raw.get("conversion", {}) or {}
        logging_cfg = raw.get("logging", {}) or {}

        if "max_pages_per_part" in splitting:
            cfg.max_pages_per_part = int(splitting["max_pages_per_part"])
        if "max_size_mb_per_part" in splitting:
            cfg.max_size_mb_per_part = float(splitting["max_size_mb_per_part"])

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
    except tomllib.TOMLDecodeError as exc:
        raise InvalidConfigError(
            f"The configuration file at {config_path} could not be parsed as valid TOML: {exc}. "
            "Built-in defaults were used instead for this run. Fix or remove the file and try again."
        ) from exc
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidConfigError(
            f"The configuration file at {config_path} contains an invalid value: {exc}. "
            "Built-in defaults were used instead for this run. Fix or remove the file and try again."
        ) from exc

    return cfg


@dataclasses.dataclass
class ConfigLoadResult:
    """Result of a non-raising config load, for callers (the GUI) that
    must never crash outright on a bad config file."""

    config: AppConfig
    source_path: Path | None
    used_defaults_due_to_error: bool
    warning: str | None = None


def load_config_safe(config_path: Path | None) -> ConfigLoadResult:
    """Like `load_config`, but never raises: an invalid file falls back
    to built-in defaults and the problem is returned as a warning
    string for the caller to display, instead of crashing startup.
    """

    try:
        cfg = load_config(config_path)
    except InvalidConfigError as exc:
        return ConfigLoadResult(
            config=AppConfig(),
            source_path=config_path,
            used_defaults_due_to_error=True,
            warning=str(exc),
        )
    return ConfigLoadResult(config=cfg, source_path=config_path, used_defaults_due_to_error=False)
