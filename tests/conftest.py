"""Shared fixtures and configuration for pytest."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "infra: tests that require a running Docker Compose stack (skipped by default)",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip infra tests by default; run them only with -m infra."""
    if config.getoption("-m") != "infra":
        skip_infra = pytest.mark.skip(reason="infra test — run with pytest -m infra")
        for item in items:
            if "infra" in item.keywords:
                item.add_marker(skip_infra)
