"""pytest fixtures and path setup for the smoke tests."""

import sys
from pathlib import Path

# Make project root importable when pytest runs from anywhere
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
