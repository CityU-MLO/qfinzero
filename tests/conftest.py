"""Shared test fixtures for tools unit tests."""

import os
import pytest

# Mock base URLs — no real servers needed
MOCK_UPQ_URL = "http://mock-upq:19350"
MOCK_ESP_URL = "http://mock-esp:19330"
MOCK_PMB_URL = "http://mock-pmb:19380"


@pytest.fixture
def mock_env(monkeypatch):
    """Patch env vars so MCP tools use mock URLs."""
    monkeypatch.setenv("QFINZERO_UPQ_URL", MOCK_UPQ_URL)
    monkeypatch.setenv("QFINZERO_ESP_URL", MOCK_ESP_URL)
    monkeypatch.setenv("QFINZERO_PMB_URL", MOCK_PMB_URL)


@pytest.fixture(scope="session")
def sample_root(tmp_path_factory):
    """The synthetic sample, built once per test run (about 25 s)."""
    from qfinzero.sample.build import build
    root = tmp_path_factory.mktemp("qfz_sample")
    build(root)
    return root
