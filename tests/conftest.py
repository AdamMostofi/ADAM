"""Test isolation for ADAM.

Every test:
- runs in its own temporary working directory, so default relative store
  paths (adam_memory.db, adam_vectors.lance, adam_save, skills) land there;
- gets ADAM_DB and ADAM_LANCE pointing at that directory;
- uses a deterministic fake embedder and a fake Ear, so neither the MiniLM
  model nor Needle is loaded or downloaded (tests marked `real_model` are the
  exception);
- cannot open network connections other than to this machine.

The whole run is guarded: production stores are fingerprinted before and
after, and the run fails if anything changed.

Opt-in real-model tests: ADAM_REAL_MODEL=1 python -m pytest tests -m real_model
"""
from __future__ import annotations

import hashlib
import ipaddress
import math
import os
import socket
from pathlib import Path

import sys

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import store_guard  # noqa: E402
REAL_MODEL = os.environ.get("ADAM_REAL_MODEL") == "1"
EMBED_DIM = 384


def pytest_configure(config):
    config.addinivalue_line("markers", "real_model: needs a real model (embedding or Needle); set ADAM_REAL_MODEL=1 to run")
    config.addinivalue_line("markers", "slow: takes more than a few seconds; deselect with -m 'not slow'")
    problems = store_guard.env_problems(REPO, dict(os.environ))
    if problems:
        # UsageError gives a non-zero exit status (4); pytest.exit here does not.
        raise pytest.UsageError("Refusing to run: " + "; ".join(problems))


def pytest_collection_modifyitems(config, items):
    stress_dir = Path(__file__).resolve().parent / "stress"
    for item in items:
        if stress_dir in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.slow)
    if REAL_MODEL:
        return
    skip = pytest.mark.skip(reason="needs a real model; set ADAM_REAL_MODEL=1")
    for item in items:
        if "real_model" in item.keywords:
            item.add_marker(skip)


def pytest_sessionstart(session):
    session.config._adam_store_fingerprint = store_guard.fingerprint(REPO)


def pytest_sessionfinish(session, exitstatus):
    before = getattr(session.config, "_adam_store_fingerprint", None)
    if before is None:
        return
    changes = store_guard.differences(before, store_guard.fingerprint(REPO))
    if changes:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        message = store_guard.failure_message(changes)
        if reporter:
            reporter.write_line("")
            reporter.write_line(message, red=True, bold=True)
        else:
            print(message)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def fake_embed(self, text: str) -> list[float]:
    """Deterministic bag-of-words vector: shared words give similar vectors."""
    vector = [0.0] * EMBED_DIM
    for word in text.lower().split():
        index = int.from_bytes(hashlib.sha256(word.encode()).digest()[:4], "big") % EMBED_DIM
        vector[index] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class FakeEar:
    """Stands in for the Needle-backed Ear, using the Ear's own keyword fallback."""

    def __init__(self):
        from interface.ear import UserIntent
        self._intent = UserIntent

    def listen(self, text: str):
        lowered = text.lower()
        if any(w in lowered for w in ("great", "good", "awesome", "amazing", "love", "fantastic")):
            sentiment = "positive"
        elif any(w in lowered for w in ("terrible", "awful", "bad", "hate", "horrible", "frustrating")):
            sentiment = "negative"
        else:
            sentiment = "neutral"
        return self._intent(action="unknown", topic=text[:50], sentiment=sentiment)

    def close(self):
        pass


def _is_local(address) -> bool:
    if not isinstance(address, tuple):
        return True  # Unix sockets
    host = address[0]
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch, request):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ADAM_DB", str(tmp_path / "adam_memory.db"))
    monkeypatch.setenv("ADAM_VECTORS", str(tmp_path / "adam_vectors.db"))
    monkeypatch.setenv("ADAM_LANCE", str(tmp_path / "adam_vectors.db"))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    if "real_model" not in request.keywords:
        from memory.semantic_index import SemanticIndex
        monkeypatch.setattr(SemanticIndex, "_embed", fake_embed)
        monkeypatch.setattr(SemanticIndex, "_load_model", lambda self: None)

        import interface.core
        monkeypatch.setattr(interface.core, "Ear", FakeEar)

        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex

        def guarded(method):
            def wrapper(sock, address):
                if not _is_local(address):
                    raise OSError(f"network access blocked in tests: {address!r}")
                return method(sock, address)
            return wrapper

        monkeypatch.setattr(socket.socket, "connect", guarded(original_connect))
        monkeypatch.setattr(socket.socket, "connect_ex", guarded(original_connect_ex))
    yield
