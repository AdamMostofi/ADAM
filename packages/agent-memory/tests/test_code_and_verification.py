"""Stage 2.4 (#53): file history, code dependency graph, verification records and status."""
from __future__ import annotations

import os

import pytest

from agent_memory import EventInput
from agent_memory.verification import capture_environment

FILES = {
    "api/__init__.py": "",
    "api/jwt.py": "def decode(token):\n    return token.split('.')\n",
    "api/auth.py": "from . import jwt\nfrom api.jwt import decode\n\ndef login(t):\n    return decode(t)\n",
    "api/users.py": "USERS = ['ann']\n",
    "tests/test_auth.py": "import api.auth\n\ndef test_login():\n    assert api.auth.login('a.b')\n",
    "web/util.ts": "export const twice = (n: number) => n * 2;\n",
    "web/app.ts": "import React from 'react';\nimport { twice } from './util';\nconsole.log(twice(2));\n",
}
ENV = {"interpreters": {"python": "3.12.8"}, "os": "Linux 6.6", "lockfiles": {"uv.lock": "aaa"},
       "dependencies_hash": "x", "env_vars_checked": [], "env_vars_present": []}


def write(store, path, content, session="s1", **summary):
    return store.append(EventInput(kind="file_change", session_id=session, writer_id="w", payload=content,
                                   summary_fields={"path": path, **summary}))


@pytest.fixture
def project(store):
    events = {path: write(store, path, content, change="added") for path, content in FILES.items()}
    return events


def env(**changes):
    out = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in ENV.items()}
    for key, value in changes.items():
        out[key] = value
    return out


# ------------------------------------------------------------ file history

def test_every_version_is_recorded_and_linked(store, project):
    path = store.create("path", "s1", "w", topic="jwt", description="faster decode")
    v2 = write(store, "api/jwt.py", "def decode(t):\n    return t.split('.', 2)\n", change="modified",
               git_blob="b2", git_commit="c2", path_id=path, path_role="experiment")
    view = store.file_view("api/jwt.py")
    assert [v["change"] for v in view["versions"]] == ["added", "modified"]
    latest = view["versions"][-1]
    assert latest["event"] == v2.event_id and latest["git_blob"] == "b2" and latest["git_commit"] == "c2"
    assert latest["path_id"] == path and latest["path_role"] == "experiment"
    assert store.payload(latest["event"]) == b"def decode(t):\n    return t.split('.', 2)\n"
    assert store.current_files()["api/jwt.py"] == (v2.payload_object, v2.event_id)


def test_a_rename_moves_the_file(store, project):
    write(store, "api/accounts.py", FILES["api/users.py"], change="renamed", old_path="api/users.py")
    current = store.current_files()
    assert "api/accounts.py" in current and "api/users.py" not in current
    assert store.file_view("api/accounts.py")["versions"][-1]["renamed_from"] == "api/users.py"
    assert any(e["type"] == "follows" and e["attrs"]["link"] == "rename"
               for e in store.edges("file:api/accounts.py", "out"))


def test_a_deleted_file_is_not_current(store, project):
    store.append(EventInput(kind="file_change", session_id="s1", writer_id="w",
                            summary_fields={"path": "api/users.py", "change": "deleted"}))
    assert "api/users.py" not in store.current_files()


def test_returning_to_an_earlier_version_is_recorded_as_a_revert(store, project):
    write(store, "api/jwt.py", "broken = True\n", change="modified")
    back = write(store, "api/jwt.py", FILES["api/jwt.py"], change="modified")
    assert any(e["type"] == "reverts" and e["to"] == project["api/jwt.py"].event_id
               for e in store.edges(back.event_id, "out"))
    proposals = [p for p in store.project_view()["paths"] if store.node(p)["attrs"].get("signal") == "revert"]
    assert proposals and store.path_view(proposals[0])["status"] == "proposed"


# ------------------------------------------------------------ code dependency graph

def test_imports_are_resolved_to_project_files(store, project):
    store.update_code_graph()
    g = store.codegraph
    # Importing api.auth also runs api/__init__.py, so the package init is a real dependency.
    assert g.imports_of("tests/test_auth.py") == ["api/__init__.py", "api/auth.py"]
    assert g.imports_of("api/auth.py") == ["api/__init__.py", "api/jwt.py"]
    assert g.closure(["tests/test_auth.py"]) == {"tests/test_auth.py", "api/__init__.py", "api/auth.py", "api/jwt.py"}
    assert g.importers_of("api/jwt.py") == ["api/auth.py"]
    assert g.closure(["api/jwt.py"], "dependents") == {"api/jwt.py", "api/auth.py", "tests/test_auth.py"}


def test_typescript_imports_resolve_and_packages_stay_external(store, project):
    store.update_code_graph()
    assert store.codegraph.imports_of("web/app.ts") == ["web/util.ts"]
    assert store.codegraph.external_imports("web/app.ts") == ["react"]


def test_an_edit_reparses_only_changed_files(store, project):
    first = store.update_code_graph()
    assert first["parsed"] == 7 and first["unsupported"] == 0      # five Python files, two TypeScript
    assert store.update_code_graph()["parsed"] == 0
    write(store, "api/jwt.py", "def decode(t):\n    return []\n", change="modified")
    again = store.update_code_graph()
    assert again["parsed"] == 1 and again["reused"] == 6


def test_identical_content_is_parsed_once(store, project):
    store.update_code_graph()
    write(store, "api/copy_of_jwt.py", FILES["api/jwt.py"], change="added")
    assert store.update_code_graph()["parsed"] == 0                  # same content id as api/jwt.py


def test_the_graph_rebuilds_to_the_same_result(store, project):
    store.update_code_graph()
    before = {p: store.codegraph.imports_of(p) for p in FILES}
    assert store.codegraph.rebuild(store.archive)["parsed"] == 7
    assert {p: store.codegraph.imports_of(p) for p in FILES} == before


# ------------------------------------------------------------ verification and status

def check(store, **kwargs):
    defaults = dict(command="pytest tests/test_auth.py", result="passed", exit_code=0, output="1 passed\n",
                    targets=["tests/test_auth.py"], environment=env(), commit="c1", branch="main",
                    worktree="/work/proj", dirty=False)
    defaults.update(kwargs)
    return store.record_verification("s1", "w", **defaults)


def test_a_verification_records_its_full_context(store, project):
    v = check(store)
    s = v.summary_fields
    assert s["relevance_method"] == "import_closure"
    assert set(s["relevant_files"]) == {"tests/test_auth.py", "api/__init__.py", "api/auth.py", "api/jwt.py"}
    assert (s["commit"], s["branch"], s["worktree"], s["dirty"]) == ("c1", "main", "/work/proj", False)
    assert s["environment"]["interpreters"] == {"python": "3.12.8"} and len(s["tree_hash"]) == 64
    assert store.payload(v) == b"1 passed\n"
    assert v.event_id in store.file_view("api/jwt.py")["verifications"]
    assert store.verification_status(v.event_id, env())["status"] == "verified"


def test_changing_an_imported_file_makes_it_stale_naming_the_file(store, project):
    v = check(store)
    change = write(store, "api/jwt.py", "def decode(t):\n    raise ValueError\n", change="modified")
    result = store.verification_status(v.event_id, env())
    assert result["status"] == "stale"
    assert result["reasons"] == [f"api/jwt.py changed in event {change.event_id}"]


def test_changing_an_unrelated_file_keeps_it_verified(store, project):
    v = check(store)
    write(store, "api/users.py", "USERS = []\n", change="modified")
    write(store, "web/util.ts", "export const twice = (n: number) => n + n;\n", change="modified")
    assert store.verification_status(v.event_id, env())["status"] == "verified"


def test_reverting_to_the_exact_earlier_state_restores_verified(store, project):
    v = check(store)
    write(store, "api/jwt.py", "broken = True\n", change="modified")
    assert store.verification_status(v.event_id, env())["status"] == "stale"
    write(store, "api/jwt.py", FILES["api/jwt.py"], change="modified")
    assert store.verification_status(v.event_id, env())["status"] == "verified"


@pytest.mark.parametrize("changed, reason", [
    ({"interpreters": {"python": "3.13.1"}}, "Python 3.12.8 -> 3.13.1"),
    ({"lockfiles": {"uv.lock": "bbb"}}, "lockfile uv.lock changed"),
    ({"lockfiles": {}}, "lockfile uv.lock removed"),
    ({"lockfiles": {"uv.lock": "aaa", "package-lock.json": "p"}}, "lockfile package-lock.json added"),
    ({"os": "Linux 6.8"}, "OS Linux 6.6 -> Linux 6.8"),
])
def test_an_environment_change_makes_it_stale_naming_the_reason(store, project, changed, reason):
    v = check(store)
    result = store.verification_status(v.event_id, env(**changed))
    assert result["status"] == "stale" and result["reasons"] == [reason]


def test_whole_tree_relevance_is_the_marked_fallback(store, project):
    v = check(store, targets=["docs/guide.md"])          # not a parsed language: the graph can't decide
    assert v.summary_fields["relevance_method"] == "whole_tree"
    write(store, "api/users.py", "USERS = []\n", change="modified")   # any change counts now
    result = store.verification_status(v.event_id, env())
    assert result["status"] == "stale" and result["method"] == "whole_tree"
    v2 = check(store, targets=[])
    write(store, "api/new.py", "X = 1\n", change="added")
    assert "api/new.py was added (whole-tree relevance)" in store.verification_status(v2.event_id, env())["reasons"]


def test_coverage_data_sets_the_relevant_files(store, project):
    v = check(store, coverage_files=["api/auth.py", "api/users.py"])
    assert v.summary_fields["relevance_method"] == "coverage"
    write(store, "api/jwt.py", "changed = 1\n", change="modified")        # not covered
    assert store.verification_status(v.event_id, env())["status"] == "verified"
    write(store, "api/users.py", "changed = 1\n", change="modified")      # covered
    assert store.verification_status(v.event_id, env())["status"] == "stale"


def test_status_is_unknown_when_it_cant_be_checked(store, project):
    v = check(store)
    assert store.verification_status(v.event_id)["status"] == "unknown"               # no environment supplied
    assert store.verification_status(v.event_id, env(), reconciled=False)["status"] == "unknown"


def test_a_deleted_relevant_file_makes_it_stale(store, project):
    v = check(store)
    store.append(EventInput(kind="file_change", session_id="s1", writer_id="w",
                            summary_fields={"path": "api/jwt.py", "change": "deleted"}))
    assert store.verification_status(v.event_id, env())["reasons"] == ["api/jwt.py was deleted"]


def test_capture_environment_records_names_never_values(tmp_path, monkeypatch):
    (tmp_path / "uv.lock").write_text("lock")
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "package-lock.json").write_text("{}")
    monkeypatch.setenv("API_TOKEN", "a-very-secret-value")
    captured = capture_environment(tmp_path, env_names=["API_TOKEN", "UNSET_VAR"])
    assert set(captured["lockfiles"]) == {"uv.lock", "web/package-lock.json"}
    assert captured["env_vars_present"] == ["API_TOKEN"] and captured["env_vars_checked"] == ["API_TOKEN", "UNSET_VAR"]
    assert "a-very-secret-value" not in repr(captured)
    assert "python" in captured["interpreters"]


def test_structure_still_rebuilds_exactly(store, project):
    check(store)
    write(store, "api/jwt.py", "x = 1\n", change="modified")
    write(store, "api/jwt.py", FILES["api/jwt.py"], change="modified")
    assert store.verify()["ok"]


def test_changing_a_package_init_makes_it_stale(store, project):
    v = check(store)
    change = write(store, "api/__init__.py", "import os\n", change="modified")
    assert store.verification_status(v.event_id, env())["reasons"] == [f"api/__init__.py changed in event {change.event_id}"]


def test_a_src_layout_import_resolves(store):
    write(store, "src/pkg/__init__.py", "")
    write(store, "src/pkg/core.py", "X = 1\n")
    write(store, "tests/test_core.py", "from pkg.core import X\n")
    store.update_code_graph()
    assert store.codegraph.imports_of("tests/test_core.py") == ["src/pkg/__init__.py", "src/pkg/core.py"]
