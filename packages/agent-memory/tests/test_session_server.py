"""Decision D14 (#90): the session server. Hooks hand their payload to a process that has the store open."""
from __future__ import annotations

import json
import os
import re
import socket
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_memory import Store, server
from agent_memory.location import store_path
from agent_memory.server import SessionServer, forward, ping, read_server_file, server_file

ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "plugins" / "claude-code" / "scripts" / "amem-run"
AMEM = Path(sys.executable).parent / "amem"
S = "sess-srv"


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@example.invalid"],
                ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=p, check=True)
    (p / "jwt.py").write_text("def refresh():\n    return 1\n")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=p, check=True)
    return p


def env_for(project, **extra):
    return dict(os.environ, AMEM_BIN=str(AMEM), CLAUDE_PROJECT_DIR=str(project), **extra)


@pytest.fixture
def running(project):
    srv = SessionServer(store_path(project), env_for(project, AMEM_PROJECT=str(project))).start()
    yield srv
    srv.stop()


def launch(project, event, payload, **extra):
    out = subprocess.run(["bash", str(LAUNCHER), "hook", event], input=json.dumps(payload).encode(),
                         capture_output=True, env=env_for(project, **extra), timeout=120)
    assert out.returncode == 0, out.stderr
    return out.stdout.decode()


def session(project):
    return [
        ("SessionStart", {"session_id": S, "source": "startup", "cwd": str(project)}),
        ("UserPromptSubmit", {"session_id": S, "prompt": "refresh in jwt.py returns the wrong value — ünïcödé ✓"}),
        ("PreToolUse", {"session_id": S, "tool_name": "Bash", "tool_use_id": "b1",
                        "tool_input": {"command": "pytest -q"}}),
        ("PostToolUse", {"session_id": S, "tool_name": "Bash", "tool_use_id": "b1", "tool_input": {"command": "pytest -q"},
                         "tool_response": {"stdout": "1 passed", "stderr": "", "exit_code": 0}}),
        ("SessionEnd", {"session_id": S, "reason": "exit"}),
    ]


def captured(project):
    store = Store(store_path(project), min_free_bytes=0)
    return store, [e.kind for e in store.events(session_id=S) if not e.kind.startswith("context_")]


def test_hooks_go_through_the_server_and_store_what_the_direct_path_stores(project, tmp_path, running):
    outputs = [launch(project, event, payload) for event, payload in session(project)]
    assert running.hooks_served == len(session(project))   # every hook took the fast path
    start = json.loads(outputs[0])["hookSpecificOutput"]
    assert start["hookEventName"] == "SessionStart" and start["additionalContext"]
    store, fast = captured(project)

    other = tmp_path / "other"
    subprocess.run(["cp", "-r", str(project), str(other)], check=True)
    for d in (other / ".agent-memory",):
        subprocess.run(["rm", "-rf", str(d)], check=True)
    for event, payload in session(other):
        launch(other, event, payload, AMEM_SERVER="0")
    _, direct = captured(other)
    assert fast == direct
    assert "verification" in fast or any(e.kind == "verification" for e in store.events())
    assert store.verify(full=True)["ok"]


def test_replaying_through_the_direct_path_stores_nothing_twice(project, running):
    for event, payload in session(project):
        launch(project, event, payload)
    _, before = captured(project)
    for event, payload in session(project):
        if event != "SessionStart":   # a fresh session start legitimately reconciles and checkpoints again
            launch(project, event, payload, AMEM_SERVER="0")
    _, after = captured(project)
    assert after == before


def test_a_wrong_token_falls_back_to_the_direct_path(project, running):
    path = server_file(store_path(project))
    port, sid, _token, pid = path.read_text().split()
    path.write_text(f"{port} {sid} {'0' * 32} {pid}\n")
    launch(project, "UserPromptSubmit", {"session_id": S, "prompt": "hello"})
    assert running.hooks_served == 0
    _, kinds = captured(project)
    assert "user_message" in kinds


def test_a_stale_file_never_sends_the_payload_to_another_program(project):
    received = []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()

    def accept():
        conn, _ = listener.accept()
        conn.sendall(b"SSH-2.0-not-amem\r\n")
        conn.settimeout(3)
        try:
            received.append(conn.recv(65536))
        except OSError:
            received.append(b"")
        conn.close()

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    path = server_file(store_path(project))
    path.parent.mkdir(parents=True)
    path.write_text(f"{listener.getsockname()[1]} abcdef {'1' * 32} 1\n")
    launch(project, "UserPromptSubmit", {"session_id": S, "prompt": "a private prompt"})
    t.join(5)
    listener.close()
    assert received == [b""]   # nothing was sent: the greeting didn't match
    _, kinds = captured(project)
    assert "user_message" in kinds   # and the hook still ran, directly


def test_a_dead_server_costs_little_and_falls_back(project):
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()   # nothing listens there now
    path = server_file(store_path(project))
    path.parent.mkdir(parents=True)
    path.write_text(f"{port} abcdef {'1' * 32} 1\n")
    launch(project, "UserPromptSubmit", {"session_id": S, "prompt": "hello"})
    _, kinds = captured(project)
    assert "user_message" in kinds


def test_parallel_hooks_are_all_stored_and_the_chain_stays_valid(project, running):
    store_dir = store_path(project)
    payloads = [{"session_id": S, "prompt": f"prompt number {i}"} for i in range(12)]
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda p: forward(store_dir, "claude-code", "UserPromptSubmit",
                                                  json.dumps(p).encode()), payloads))
    assert all(r is not None for r in results)
    store, kinds = captured(project)
    assert kinds.count("user_message") == 12
    assert store.verify(full=True)["ok"]


def test_a_second_server_takes_over_when_the_first_goes_away(project, monkeypatch):
    monkeypatch.setattr(server, "TAKEOVER_EVERY", 0.1)
    environ = env_for(project, AMEM_PROJECT=str(project))
    first = SessionServer(store_path(project), environ).start()
    second = SessionServer(store_path(project), environ).start()
    try:
        assert first.owns_file() and not second.owns_file()
        first.stop()
        deadline = time.time() + 5
        while not second.owns_file() and time.time() < deadline:
            time.sleep(0.05)
        assert second.owns_file() and ping(store_path(project))
    finally:
        second.stop()
    assert not server_file(store_path(project)).exists()   # the last one out removes the file


def test_the_server_file_is_private(project, running):
    mode = server_file(store_path(project)).stat().st_mode & 0o777
    assert mode == 0o600


def test_amem_mcp_runs_the_server_beside_the_tools_and_cleans_up(project):
    proc = subprocess.Popen([str(AMEM), "--project", str(project), "--session", "auto", "mcp"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=env_for(project))
    try:
        deadline = time.time() + 20
        while not ping(store_path(project)) and time.time() < deadline:
            time.sleep(0.1)
        assert ping(store_path(project))
        out = launch(project, "SessionStart", {"session_id": S, "source": "startup", "cwd": str(project)})
        assert json.loads(out)["hookSpecificOutput"]["additionalContext"]
        proc.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"mem_state",'
                         b'"arguments":{"op":"overview"}}}\n')
        proc.stdin.flush()
        reply = json.loads(proc.stdout.readline())
        assert reply["result"]["isError"] is False
    finally:
        proc.stdin.close()
        proc.wait(20)
    assert not server_file(store_path(project)).exists()


def test_amem_serve_runs_until_its_parent_closes_stdin(project):
    proc = subprocess.Popen([str(AMEM), "--project", str(project), "serve"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, env=env_for(project))
    try:
        assert proc.stdout.readline().startswith(b"AMEM1 serving ")
        assert read_server_file(store_path(project)) is not None and ping(store_path(project))
        assert forward(store_path(project), "claude-code", "UserPromptSubmit",
                       json.dumps({"session_id": S, "prompt": "from an in-process plugin"}).encode()) is not None
    finally:
        proc.stdin.close()
        assert proc.wait(20) == 0
    assert not server_file(store_path(project)).exists()


def test_the_fast_path_is_faster_than_starting_amem(project, running):
    launch(project, "SessionStart", {"session_id": S, "source": "startup", "cwd": str(project)})

    def timed(**extra):
        took = []
        for i in range(8):
            t = time.perf_counter()
            launch(project, "PreToolUse", {"session_id": S, "tool_name": "Read", "tool_use_id": f"r{i}{extra}",
                                           "tool_input": {"file_path": str(project / "jwt.py")}}, **extra)
            took.append(time.perf_counter() - t)
        return statistics.median(took)

    fast, direct = timed(), timed(AMEM_SERVER="0")
    assert fast < direct


# ---------------------------------------------------------------- speedups found by profiling the server
def test_one_git_status_gives_what_rev_parse_reflog_and_status_give(project):
    from agent_memory.reconcile import Reconciler
    store = Store(store_path(project), min_free_bytes=0)
    (project / "with space.py").write_text("x = 1\n")
    (project / "jwt.py").write_text("def refresh():\n    return 2\n")
    subprocess.run(["git", "checkout", "-qb", "feature"], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qam", "change"], cwd=project, check=True)
    (project / "jwt.py").write_text("def refresh():\n    return 3\n")
    r = Reconciler(store, project, S)
    r._status = None
    git = lambda *a: subprocess.run(["git", "-C", str(project), *a], capture_output=True, text=True).stdout
    assert r._head() == git("rev-parse", "HEAD").strip()
    assert r._reflog() == git("reflog", "--format=%gs").splitlines()
    assert r._dirty() == {"jwt.py", "with space.py"}


def test_a_fresh_repository_has_no_head_yet(tmp_path):
    from agent_memory.reconcile import Reconciler
    p = tmp_path / "empty"
    p.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=p, check=True)
    (p / "a.py").write_text("a = 1\n")
    store = Store(store_path(p), min_free_bytes=0)
    r = Reconciler(store, p, S)
    assert (r._head(), r._reflog(), r._dirty()) == (None, [], {"a.py"})


def test_the_artifact_index_skips_work_only_when_nothing_changed(project):
    store = Store(store_path(project), min_free_bytes=0)
    store.reconciler(project, S).run()
    store.update_artifacts()
    assert store.codegraph.find_part("refresh")
    again = store.update_artifacts()
    assert again["parsed"] == 0 and again["described"] == 0
    (project / "jwt.py").write_text("def rotate():\n    return 1\n")
    store.reconciler(project, S).run()
    store.update_artifacts()
    assert store.codegraph.find_part("rotate") and not store.codegraph.find_part("refresh")
    store.rebuild_derived()   # clears the fingerprint with the index: the rebuild really rebuilds
    assert store.codegraph.find_part("rotate")
    assert store.codegraph.find_parts(["rotate", "nothing"]) == {
        "rotate": store.codegraph.find_part("rotate"), "nothing": []}


def test_the_wsl_bridge_keeps_git_bash_from_rewriting_linux_paths():
    # Found on Windows: Git Bash turned /home/x into C:/Program Files/Git/home/x before wsl.exe saw it.
    text = LAUNCHER.read_text()
    bridge = text[text.index("command -v wsl.exe"):]
    assert bridge.index("MSYS_NO_PATHCONV=1") < bridge.index("exec wsl.exe")
    assert "$HOME/.local/bin/amem" in bridge   # where `uv tool install` puts it, even off the login PATH


def test_the_fast_path_starts_no_process():
    # Each process costs about 50 ms in Git Bash on Windows; the hand-off uses builtins only.
    text = LAUNCHER.read_text()
    fast = text[text.index("# Fast path"):text.index("# Direct path")]
    code = "\n".join(line for line in fast.splitlines() if not line.lstrip().startswith("#"))
    assert "$(" not in code and "`" not in code and "cat " not in code
    assert not re.search(r"(?<!\|)\|(?!\|)", code)   # no pipe; "||" is fine
