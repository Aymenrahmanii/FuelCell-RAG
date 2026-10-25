from pathlib import Path

import pytest

from fcrag.truth import SystemTruth, load_all

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def systems() -> dict[str, SystemTruth]:
    return load_all(REPO_ROOT / "data_gen" / "systems")
