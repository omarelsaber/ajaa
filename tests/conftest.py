"""
Root conftest.py — shared fixtures and markers.
"""
from __future__ import annotations

import pytest


# ── Marker registration ───────────────────────────────────────────────────────
# All markers are also declared in pyproject.toml [tool.pytest.ini_options]


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers to suppress PytestUnknownMarkWarning."""
    config.addinivalue_line("markers", "slow: marks tests as slow")
    config.addinivalue_line(
        "markers", "integration: marks tests that require external services (mocked)"
    )
    config.addinivalue_line("markers", "e2e: marks end-to-end tests")
    config.addinivalue_line("markers", "adversarial: marks adversarial corpus tests")
    config.addinivalue_line(
        "markers", "genericity: marks the 4-candidate genericity suite"
    )
    config.addinivalue_line("markers", "canary: marks weekly connector canary tests")
