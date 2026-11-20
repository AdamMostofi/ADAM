"""ADAM runs against the released memory engine (Stage 3.6, #61), not an in-repo copy."""
from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_installed_engine_is_the_pinned_release():
    tag = re.search(r'"yewtree @ git\+https://github.com/[^@"]+@v([\d.]+)"',
                    (ROOT / "pyproject.toml").read_text()).group(1)
    assert metadata.version("yewtree") == tag


def test_the_engine_stores_and_verifies_a_record(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))   # its keys stay in the test's folder
    import agent_memory
    from agent_memory import EventInput, Store
    # Installed into the environment, not imported from a copy in this repository.
    assert "site-packages" in Path(agent_memory.__file__).resolve().parts
    store = Store(tmp_path / ".agent-memory", min_free_bytes=0)
    store.append(EventInput(kind="note", session_id="adam", writer_id="adam", summary_fields={"text": "hello"},
                            payload=b"the payload"))
    assert store.verify()["ok"]
