"""Stage 3.4 (#59): the Pi adapter and extension, and Pi's session tree mapped onto engine branches.

The payload shapes are Pi 1.4's, recorded from the real runtime driven by a scripted model
(`fixtures/pi_scripted_model.js`, built on Pi's own faux provider).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_memory import Store
from agent_memory.adapters import claude_code as cc
from agent_memory.adapters import pi
from agent_memory.location import store_path
from agent_memory.mcp import resolve_session
from agent_memory.structure import session_node
from agent_memory.tools import call

ROOT = Path(__file__).resolve().parents[3]
EXTENSION = ROOT / "plugins" / "pi"
FIXTURES = Path(__file__).parent / "fixtures"
S = "01a1f88d-f202-70f8-83fa-d391c91bf22f"
FILE = f"/home/u/.pi/agent/sessions/--proj--/2026-11-20T10-43-34-531Z_{S}.jsonl"


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@example.invalid"],
                ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=p, check=True)
    (p / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=p, check=True)
    return p


def ev(project, event, payload):
    out, code = pi.handle(event, json.dumps({"cwd": str(project), **payload}).encode(),
                          dict(os.environ, AMEM_PROJECT=str(project)))
    assert code == 0
    return out


def open_store(project):
    return Store(store_path(project), min_free_bytes=0)


def starts(store):
    return [(e.session_id, e.summary_fields.get("source"), e.summary_fields.get("forked_from"))
            for e in store.events() if e.kind == "session_start"]


def edit(project, call_id, rel, text, session=S, tool="edit"):
    args = {"path": rel, "edits": [{"oldText": "x", "newText": "y"}]} if tool == "edit" else {"path": rel,
                                                                                               "content": text}
    ev(project, "tool_before", {"session_id": session, "call_id": call_id, "tool": tool, "args": args})
    (project / rel).write_text(text)
    ev(project, "tool_after", {"session_id": session, "call_id": call_id, "tool": tool, "args": args,
                               "content": [{"type": "text", "text": f"Successfully replaced 1 block(s) in {rel}."}],
                               "is_error": False})


# ------------------------------------------------------------ the adapter
def test_a_pi_session_is_captured_and_gets_memory(project):
    ev(project, "session", {"session_id": S, "reason": "startup", "session_file": FILE, "leaf_id": "794534a3"})
    brief = ev(project, "brief", {"session_id": S})
    assert brief and not brief.startswith("{")
    ev(project, "prompt", {"session_id": S, "text": "add sub to calc.py", "leaf_id": "556608d2"})
    edit(project, "call_1", "calc.py", "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    ev(project, "tool_before", {"session_id": S, "call_id": "call_2", "tool": "bash",
                                "args": {"command": "python3 -m pytest -q"}})
    ev(project, "tool_after", {"session_id": S, "call_id": "call_2", "tool": "bash",
                               "args": {"command": "python3 -m pytest -q"},
                               "content": [{"type": "text", "text": "1 failed"}], "is_error": True,
                               "structured": {"output": "1 failed", "truncated": False, "exit_code": 1}})
    ev(project, "text", {"session_id": S, "text": "Added sub.", "timestamp": 1795171222324, "model": "scripted"})
    ev(project, "idle", {"session_id": S})
    ev(project, "shutdown", {"session_id": S, "reason": "quit"})

    store = open_store(project)
    kinds = [e.kind for e in store.events(session_id=S) if e.kind in
             ("session_start", "user_message", "tool_call", "tool_result", "assistant_message", "session_end")]
    assert kinds == ["session_start", "user_message", "tool_call", "tool_result", "tool_call", "tool_result",
                     "assistant_message", "session_end"]
    change = [e.summary_fields for e in store.events() if e.kind == "file_change"
              and e.summary_fields["attribution"] != "baseline"]
    assert change[-1]["path"] == "calc.py" and change[-1]["by"] == f"pi:{S}"
    bash = [e.summary_fields for e in store.events(session_id=S) if e.kind == "tool_result"
            and e.summary_fields["tool"] == "bash"][0]
    assert bash["failed"] and bash["exit_code"] == 1
    assert [e.summary_fields["result"] for e in store.events() if e.kind == "verification"] == ["failed"]
    assert store.verify()["ok"]


def test_a_session_resumed_in_a_new_process_starts_again_as_a_resume(project):
    ev(project, "session", {"session_id": S, "reason": "startup", "session_file": FILE})
    ev(project, "shutdown", {"session_id": S, "reason": "quit"})
    ev(project, "session", {"session_id": S, "reason": "startup", "session_file": FILE})   # `pi --session FILE`
    assert [s for _, s, _ in starts(open_store(project))] == ["startup", "resume"]


def test_a_forked_session_becomes_an_engine_branch(project):
    """`/fork`, `/clone` or `pi --fork`: a new Pi session whose header names its parent."""
    ev(project, "session", {"session_id": S, "reason": "startup", "session_file": FILE})
    ev(project, "shutdown", {"session_id": S, "reason": "fork"})
    child = "01a1f88e-0998-77b8-9b50-7b3e7dc36c09"
    # `pi --fork FILE` reports "startup"; the header's parentSession is what makes it a fork.
    ev(project, "session", {"session_id": child, "reason": "startup", "parent_session_file": FILE,
                            "session_file": FILE.replace(S, child)})
    store = open_store(project)
    assert (child, "startup", S) in starts(store)
    conn = store._connect()
    try:
        linked = conn.execute("SELECT COUNT(*) FROM edges WHERE from_id = ? AND to_id = ? AND type = 'based_on'",
                              (session_node(child), session_node(S))).fetchone()[0]
        paths = conn.execute("SELECT COUNT(*) FROM nodes WHERE node_type = 'approach' AND "
                             "json_extract(attrs, '$.signal') = 'session_fork'").fetchone()[0]
    finally:
        conn.close()
    assert linked == 1 and paths == 1                    # the core's own fork structure: a branch, no core change


def test_a_tree_branch_inside_a_session_becomes_an_engine_branch(project):
    """`/tree`: the same Pi session continues on another line; records on it stay on that branch."""
    ev(project, "session", {"session_id": S, "reason": "startup", "session_file": FILE})
    ev(project, "prompt", {"session_id": S, "text": "add sub"})
    edit(project, "call_1", "calc.py", "main line\n")
    ev(project, "tree", {"session_id": S, "new_leaf": "ea6f0796", "old_leaf": "1d705ba9",
                         "summary": "Branch explored adding sub in calc.py."})
    ev(project, "prompt", {"session_id": S, "text": "try mul in its own file instead"})
    edit(project, "call_1", "mul.py", "def mul(a, b):\n    return a * b\n", tool="write")
    ev(project, "idle", {"session_id": S})
    store = open_store(project)
    branch = f"{S}~ea6f0796"
    assert (branch, "tree", S) in starts(store)
    assert resolve_session(store, "auto") == branch     # the memory tools follow the branch
    on_branch = [e.summary_fields.get("text") for e in store.events(session_id=branch) if e.kind == "user_message"]
    on_main = [e.summary_fields.get("text") for e in store.events(session_id=S) if e.kind == "user_message"]
    assert on_branch == ["try mul in its own file instead"] and on_main == ["add sub"]
    by = {e.summary_fields["path"]: e.summary_fields.get("by") for e in store.events() if e.kind == "file_change"
          and e.summary_fields["attribution"] != "baseline"}
    assert by == {"calc.py": f"pi:{S}", "mul.py": f"pi:{branch}"}
    notes = [e for e in store.events(session_id=branch) if e.kind == "note"]
    assert notes and store.archive.get(notes[0].payload_object).decode().startswith("Branch explored")
    # The same call id on two branches is two different calls, and both are kept.
    assert len([e for e in store.events() if e.kind == "tool_result"]) == 2


def test_compaction_restores_memory_on_the_next_run(project):
    ev(project, "session", {"session_id": S, "reason": "startup"})
    first = ev(project, "brief", {"session_id": S})
    decision = call(open_store(project), S, "mem_declare", {"op": "create", "kind": "decision",
                                                            "title": "calc.py stays dependency-free"})
    call(open_store(project), S, "mem_get", {"id": decision.split()[0]})
    ev(project, "compacting", {"session_id": S, "reason": "manual"})
    ev(project, "compacted", {"session_id": S, "reason": "manual", "summary": "We added sub."})
    after = ev(project, "brief", {"session_id": S})
    assert after and after != first
    store = open_store(project)
    phases = [e for e in store.events(session_id=S) if e.kind == "compaction"]
    assert [e.summary_fields["phase"] for e in phases] == ["before", "after"]
    assert store.archive.get(phases[1].payload_object) == b"We added sub."


def test_a_broken_store_never_blocks_pi(project):
    store_dir = store_path(project)
    store_dir.mkdir(parents=True)
    (store_dir / "memory.db").write_text("not a database")
    assert "isn't being remembered" in ev(project, "brief", {"session_id": S})
    assert ev(project, "prompt", {"session_id": S, "text": "hi"}) == ""


def test_session_files_name_their_session():
    assert pi.session_id_of_file(FILE) == S
    assert pi.session_id_of_file(None) is None


def test_a_second_identical_event_is_kept_and_a_retried_delivery_is_not(project):
    """Pi sends the same shutdown or compaction payload each time; the extension's delivery id tells them apart."""
    ev(project, "session", {"session_id": S, "reason": "startup", "delivery": "d1"})
    for delivery in ("d2", "d2", "d3"):          # d2 retried after a failed hand-off, then a real second compaction
        ev(project, "compacting", {"session_id": S, "reason": "threshold", "delivery": delivery})
    phases = [e for e in open_store(project).events(session_id=S) if e.kind == "compaction"]
    assert len(phases) == 2


# ------------------------------------------------------------ the extension in the real Pi runtime
PI = shutil.which("pi")
AMEM = shutil.which("amem") or str(Path(sys.executable).parent / "amem")


@pytest.mark.skipif(PI is None, reason="Pi isn't installed")
def test_pi_install_turns_on_capture_in_the_real_runtime(project, tmp_path):
    """`pi install` the package, then drive real Pi with a scripted model: no network, no model."""
    agent_dir = tmp_path / "pi-agent"
    env = dict(os.environ, PI_CODING_AGENT_DIR=str(agent_dir), AMEM_BIN=AMEM, PI_OFFLINE="1")
    installed = subprocess.run([PI, "install", str(EXTENSION)], env=env, capture_output=True, text=True, timeout=120)
    assert installed.returncode == 0, installed.stderr

    def run(steps, *args):
        script = tmp_path / "script.json"
        script.write_text(json.dumps(steps))
        dump = tmp_path / f"dump{len(list(tmp_path.glob('dump*')))}"
        r = subprocess.run([PI, "-p", "-e", str(FIXTURES / "pi_scripted_model.js"),
                            "-e", str(FIXTURES / "pi_test_commands.js"), "--session-dir", str(tmp_path / "sessions"),
                            "--model", "scripted/scripted", *args], cwd=project, capture_output=True, text=True,
                           timeout=180, env=dict(env, PI_SCRIPT=str(script), PI_DUMP=str(dump)))
        assert r.returncode == 0, r.stderr
        return dump

    dump = run([{"tool": "edit", "args": {"path": "calc.py", "edits": [
                    {"oldText": "return a + b", "newText": "return a + b\n\ndef sub(a, b):\n    return a - b"}]}},
                {"tool": "mcp__agent_memory__mem_declare",
                 "args": {"op": "create", "kind": "decision", "title": "calc.py stays dependency-free"}},
                {"text": "Done."}], "add sub to calc.py")
    session_file = next((tmp_path / "sessions").glob("*.jsonl"))
    run([{"text": "forked"}], "--fork", str(session_file), "continue in a fork")

    first_request = json.loads((dump / "request-1.json").read_text())
    system = first_request[0]
    assert "agent_memory" in (system.get("sections") or {})     # the memory reached the model's system prompt
    store = open_store(project)
    pi_session = pi.session_id_of_file(str(session_file))
    kinds = {e.kind for e in store.events(session_id=pi_session)}
    assert {"session_start", "user_message", "tool_call", "tool_result", "assistant_message", "session_end"} <= kinds
    decisions = [e for e in store.events() if e.kind in ("decision", "entry") and e.writer_id == f"pi:{pi_session}"]
    assert decisions, "the memory tool reached the engine through Pi's MCP support"
    assert any(source == "startup" and parent == pi_session for _, source, parent in starts(store))
    assert store.verify()["ok"]
