"""Shared pytest fixtures + sys.path setup so tests can `import hs_search_tool`."""
import sys
from pathlib import Path

import pytest

# Make the package importable from anywhere
PACKAGE_PARENT = Path(__file__).resolve().parent.parent.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="session")
def engine(data_dir: Path):
    from hs_search_tool import SearchEngine
    return SearchEngine(data_dir=data_dir)
