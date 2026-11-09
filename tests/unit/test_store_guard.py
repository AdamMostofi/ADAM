"""Tests for the production store guard used by tests/conftest.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import store_guard


def make_repo(root):
    (root / "adam_memory.db").write_bytes(b"sqlite")
    lance = root / "adam_vectors.lance" / "facts.lance" / "_versions"
    lance.mkdir(parents=True)
    (lance / "1.manifest").write_bytes(b"v1")
    (root / "adam_save").mkdir()
    (root / "adam_save" / "graph.json").write_text("{}")
    return root


def test_unchanged_repo_has_no_differences(tmp_path):
    repo = make_repo(tmp_path)
    assert store_guard.differences(store_guard.fingerprint(repo), store_guard.fingerprint(repo)) == []


def test_simulated_production_write_fails_with_clear_message(tmp_path):
    repo = make_repo(tmp_path)
    before = store_guard.fingerprint(repo)
    (repo / "adam_memory.db").write_bytes(b"sqlite plus a test write")
    (repo / "adam_vectors.lance" / "facts.lance" / "_versions" / "2.manifest").write_bytes(b"v2")
    changes = store_guard.differences(before, store_guard.fingerprint(repo))
    assert "modified: adam_memory.db" in changes
    assert any(c.startswith("created: adam_vectors.lance") for c in changes)
    message = store_guard.failure_message(changes)
    assert "PRODUCTION STORE GUARD" in message and "adam_memory.db" in message


def test_new_store_created_during_run_is_detected(tmp_path):
    repo = make_repo(tmp_path)
    before = store_guard.fingerprint(repo)
    (repo / "skills").mkdir()
    (repo / "skills" / "s.json").write_text("{}")
    assert "created: skills/s.json" in store_guard.differences(before, store_guard.fingerprint(repo))


def test_env_paths_inside_repo_are_rejected(tmp_path):
    inside = {"ADAM_DB": str(tmp_path / "adam_memory.db"), "ADAM_LANCE": str(tmp_path.parent / "elsewhere.lance")}
    problems = store_guard.env_problems(tmp_path, inside)
    assert len(problems) == 1 and problems[0].startswith("ADAM_DB=")
