from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from lender_package_builder.cli import build_package
from lender_package_builder.config import AppConfig


@pytest.fixture
def config() -> AppConfig:
    return AppConfig()


@pytest.fixture
def run_build():
    def _run(input_path, output_dir=None, config=None, **kwargs):
        cfg = config or AppConfig()
        return build_package(
            input_path=input_path,
            output_dir=output_dir,
            config=cfg,
            progress=False,
            **kwargs,
        )

    return _run
