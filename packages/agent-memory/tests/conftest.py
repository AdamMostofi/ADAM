from __future__ import annotations

import pytest

from agent_memory import Store


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Keys and stores live in the test's temporary folder, never in the user's real ones."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("AMEM_HOME", raising=False)
    monkeypatch.delenv("AMEM_PASSPHRASE", raising=False)


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "store", project_id="test-project", min_free_bytes=0)
