"""Stage 2.5 (#54): reconciliation, checkpoints, recovery, concurrency (design section 8)."""
from __future__ import annotations

import json
import os
import random
import signal
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from agent_memory import Store, structure
from agent_memory.cli import main as amem
from agent_memory.reconcile import GROUP_THRESHOLD, reconcile_ok
from agent_memory.schema import EventInput

sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "reconcile"))
import scenarios  # noqa: E402

SESSION = "agent-a"


def ev(kind="note", session="s1", writer="w1", **kw):
    return EventInput(kind=kind, session_id=session, writer_id=writer, **kw)


def feed(store: Store, observations: list[dict]) -> None:
    """Record what an agent adapter would have recorded for these observations."""
    for o in observations:
        writer = o.get("writer", SESSION)
        if o["type"] == "tool_edit":
            before = scenarios.CONTENT[o["before"]] if o["before"] else None
            store.record_tool_edit(writer, writer, o["path"], scenarios.CONTENT[o["after"]], before)
        elif o["type"] == "bash_start":
            store.append(ev("tool_call", writer, writer, summary_fields={"tool": "Bash", "command": o["command"]}))
        elif o["type"] == "bash_end":
            store.append(ev("tool_result", writer, writer, summary_fields={"tool": "Bash", "exit_code": 0}))
        # session_start: nothing to record; the reconcile itself is what the adapter does then


def assert_memory_matches_files(store: Store, rec, repo: Path) -> None:
    """After a reconcile, the store's current files are exactly the project's (by content id)."""
    current = store.current_files()
    listed = rec._listed()
    assert sorted(current) == listed
    for p in listed:
        assert current[p][0] == rec.content_id((repo / p).read_bytes(), p), p


# ---------------------------------------------------------------- reconciliation (8.1)
def test_every_seeded_scenario_is_detected_and_never_misattributed(tmp_path):
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    holder = {}

    def baseline(repo):
        rec = holder["rec"] = store.reconciler(repo, SESSION)
        first = rec.run()
        assert first.changes and {c.attribution for c in first.changes} == {"baseline"}

    report = []
    conflicts_expected = conflicts_found = groups = 0
    for step, repo in scenarios.run_scenario(tmp_path / "work", big_checkout_files=GROUP_THRESHOLD + 50,
                                             on_init=baseline):
        rec = holder["rec"]
        feed(store, step.observations)
        result = rec.run(full=step.full_scan)
        got = {(c.path, c.kind): c for c in result.changes}
        for e in step.expected:
            c = got.pop((e.path, e.kind), None)
            if c is None:
                report.append(f"{step.name}: missed {e.path} {e.kind}")
            elif not (c.attribution == e.attribution or c.attribution in e.acceptable):
                report.append(f"{step.name}: {e.path} attributed {c.attribution}, truth {e.attribution}")
            elif e.old_path and c.old_path != e.old_path:
                report.append(f"{step.name}: {e.path} renamed from {c.old_path}, truth {e.old_path}")
        report += [f"{step.name}: spurious {p} {k} {c.attribution}" for (p, k), c in got.items()]
        conflicts_expected += step.conflicts
        conflicts_found += len(result.conflicts)
        groups += result.group_event is not None
        assert_memory_matches_files(store, rec, repo)
    assert report == []
    assert conflicts_found == conflicts_expected == 1
    assert groups == 2   # the large checkout and the checkout back
    assert store.verify()["ok"]


def test_a_large_git_operation_is_one_group_that_lists_every_file(tmp_path):
    repo, _ = scenarios.init_repo(tmp_path)
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    rec = store.reconciler(repo, SESSION)
    rec.run()
    scenarios.git(repo, "checkout", "-q", "-b", "bulk")
    for i in range(GROUP_THRESHOLD + 20):
        (repo / f"gen_{i}.py").write_text(f"X = {i}\n")
    scenarios.git(repo, "add", "-A")
    scenarios.git(repo, "commit", "-q", "-m", "bulk")
    scenarios.git(repo, "checkout", "-q", "main")
    rec.run()
    scenarios.git(repo, "checkout", "-q", "bulk")
    result = rec.run()
    group = store.event(result.group_event)
    assert group.kind == "change_group" and group.summary_fields["count"] == GROUP_THRESHOLD + 20
    assert sorted(p for p, _ in group.summary_fields["files"]) == sorted(f"gen_{i}.py" for i in range(GROUP_THRESHOLD + 20))
    members = [e for e in store.edges(result.group_event, direction="in") if e["type"] == "part_of"]
    assert len(members) == GROUP_THRESHOLD + 20


def test_a_large_git_operation_makes_affected_verifications_stale(tmp_path):
    repo, _ = scenarios.init_repo(tmp_path)
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    rec = store.reconciler(repo, SESSION)
    rec.run()
    env = {"python": "3.12"}
    check = store.record_verification(SESSION, SESSION, "pytest", "passed", 0,
                                      coverage_files=["pkg/mod_001.py"], environment=env)
    assert store.verification_status(check.event_id, env)["status"] == "verified"
    scenarios.git(repo, "checkout", "-q", "-b", "other")
    (repo / "pkg" / "mod_001.py").write_text("changed = True\n")
    scenarios.git(repo, "commit", "-qam", "change")
    scenarios.git(repo, "checkout", "-q", "main")
    rec.run()
    scenarios.git(repo, "checkout", "-q", "other")
    rec.run()
    status = store.verification_status(check.event_id, env)
    assert status["status"] == "stale" and "pkg/mod_001.py changed" in status["reasons"][0]


def test_an_edit_the_agent_never_reported_is_resolved_from_the_file(tmp_path):
    """8.4: the agent announced an edit and crashed before reporting back."""
    repo, _ = scenarios.init_repo(tmp_path)
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    rec = store.reconciler(repo, SESSION)
    rec.run()
    target = repo / "pkg" / "mod_002.py"
    new = b"import os\nvalue = 'written before the crash'\n"
    intent = store.record_tool_edit(SESSION, SESSION, "pkg/mod_002.py", new, target.read_bytes(), intent=True)
    target.write_bytes(new)   # the edit happened; no tool_result ever arrives
    (change,) = rec.run().changes
    assert (change.attribution, change.resolves_intent) == ("agent_tool", intent.event_id)


def test_a_change_made_while_the_agent_crashed_is_found(tmp_path):
    """8.4: an edit that was never reported at all is still found, and not falsely attributed."""
    repo, _ = scenarios.init_repo(tmp_path)
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    rec = store.reconciler(repo, SESSION)
    rec.run()
    store.append(ev("session_start", "crashed", "crashed"))   # a session that never ended
    (repo / "pkg" / "mod_003.py").write_text("lost = True\n")
    (change,) = store.reconciler(repo, "next-session").run().changes
    assert (change.path, change.attribution) == ("pkg/mod_003.py", "unattributed")


def test_reconciling_never_writes_inside_the_project(tmp_path):
    repo, _ = scenarios.init_repo(tmp_path)
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    index = repo / ".git" / "index"
    before = (index.stat().st_mtime_ns, index.read_bytes())
    (repo / "pkg" / "mod_004.py").write_text("x = 1\n")
    rec = store.reconciler(repo, SESSION)
    rec.run()
    rec.run(full=True)
    assert (index.stat().st_mtime_ns, index.read_bytes()) == before


def test_an_in_project_store_is_not_reconciled_as_project_files(tmp_path):
    """D3: the store lives in the project; it must never show up as a project change."""
    repo, _ = scenarios.init_repo(tmp_path)
    from agent_memory.location import store_path
    store = Store(store_path(repo), min_free_bytes=0)
    rec = store.reconciler(repo, SESSION)
    rec.run()
    store.append(ev(payload=b"more history"))
    assert rec.run().changes == []
    assert not any(p.startswith(".agent-memory") for p in store.current_files())
    assert scenarios.git(repo, "status", "--porcelain") == ""


def test_a_folder_without_git_is_reconciled_by_walking_it(tmp_path):
    root = tmp_path / "notes"
    root.mkdir()
    (root / "a.md").write_text("# a\n")
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    rec = store.reconciler(root, SESSION)
    assert [c.path for c in rec.run().changes] == ["a.md"]
    (root / "a.md").write_text("# a, edited\n")
    (root / "b.md").write_text("# b\n")
    got = {(c.path, c.kind, c.attribution) for c in rec.run().changes}
    assert got == {("a.md", "modified", "external"), ("b.md", "added", "external")}


# ---------------------------------------------------------------- concurrency (8.5)
def test_two_writers_changing_one_file_produce_a_conflict_record(tmp_path):
    repo, _ = scenarios.init_repo(tmp_path)
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    rec = store.reconciler(repo, SESSION)
    rec.run()
    path = repo / "pkg" / "mod_005.py"
    base = path.read_bytes()
    store.record_tool_edit("agent-a", "agent-a", "pkg/mod_005.py", b"a = 1\n", base)
    store.record_tool_edit("agent-b", "agent-b", "pkg/mod_005.py", b"b = 2\n", base)   # didn't see a's edit
    path.write_bytes(b"b = 2\n")
    result = rec.run()
    (conflict,) = result.conflicts
    assert conflict["writer"] == "agent-b"
    (record,) = [e for e in store.events() if e.kind == "conflict"]
    node_id = f"conflict:{record.event_id}"
    node = store.node(node_id)
    assert node["status"] == "open" and node["status_history"][-1]["basis"] == "recorded"
    # Nothing was overwritten: both edits are still in the log.
    edits = [e for e in store.events() if e.kind == "tool_call" and e.summary_fields.get("path") == "pkg/mod_005.py"]
    assert [e.writer_id for e in edits] == ["agent-a", "agent-b"]
    store.set_status("conflict", node_id, "resolved", SESSION, SESSION, reason="kept agent b's version")
    assert store.node(node_id)["status"] == "resolved"


def test_concurrent_writer_processes_never_overwrite_each_other(tmp_path):
    path = tmp_path / "store"
    Store(path, project_id="p", min_free_bytes=0)
    script = textwrap.dedent(f"""
        import sys
        from agent_memory import Store
        from agent_memory.schema import EventInput
        s = Store({str(path)!r}, project_id="p", min_free_bytes=0)
        w = sys.argv[1]
        for i in range(40):
            s.append(EventInput(kind="note", session_id=w, writer_id=w, summary_fields={{"i": i}}))
    """)
    procs = [subprocess.Popen([sys.executable, "-c", script, f"w{n}"]) for n in range(4)]
    assert [p.wait(timeout=120) for p in procs] == [0, 0, 0, 0]
    store = Store(path, project_id="p", min_free_bytes=0)
    assert store.count() == 160
    for n in range(4):
        assert [e.writer_seq for e in store.events() if e.writer_id == f"w{n}"] == list(range(1, 41))
    assert store.verify()["ok"]


# ---------------------------------------------------------------- reconcile failure -> unknown
def test_a_failed_reconciliation_makes_verification_unknown(tmp_path, monkeypatch):
    repo, _ = scenarios.init_repo(tmp_path)
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    rec = store.reconciler(repo, SESSION)
    rec.run()
    env = {"python": "3.12"}
    check = store.record_verification(SESSION, SESSION, "pytest", "passed", 0, environment=env)
    assert store.verification_status(check.event_id, env)["status"] == "verified"

    def broken(*args, **kwargs):
        raise OSError("git is gone")

    with monkeypatch.context() as m:
        m.setattr(rec, "_dirty", broken)
        with pytest.raises(OSError):
            rec.run()
    assert reconcile_ok(store) is False
    status = store.verification_status(check.event_id, env)
    assert status["status"] == "unknown" and "reconciliation failed" in status["reasons"][0]
    rec.run()
    assert store.verification_status(check.event_id, env)["status"] == "verified"


# ---------------------------------------------------------------- checkpoints and recovery (8.2)
def test_checkpoints_are_taken_at_session_end_and_every_n_events(tmp_path):
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    store.checkpoint_every = 5
    for i in range(12):
        store.append(ev(summary_fields={"i": i}))
    store.append(ev("session_end"))
    from agent_memory import recovery
    report = recovery.checkpoints_report(store)
    assert [c["log_position"] for c in report] == [5, 10, 13]
    assert all(c["valid"] for c in report)


def test_recovery_from_a_checkpoint_matches_a_clean_replay(tmp_path):
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    store.checkpoint_every = 4
    build_history(store)
    report = store.recover()
    assert report["checkpoint"] is not None and report["repaired_tables"] == []
    assert snapshot(store) == structure.rebuild(store.events())
    assert list(store.events())[-1].kind == "recovery"
    assert store.verify()["ok"]


def test_a_corrupted_newest_checkpoint_falls_back_to_an_older_one(tmp_path):
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    store.checkpoint_every = 4
    build_history(store)
    conn = store._connect()
    rows = conn.execute("SELECT checkpoint_id, snapshot_object FROM checkpoints ORDER BY checkpoint_id").fetchall()
    conn.close()
    newest = store.archive.path(rows[-1][1])
    data = bytearray(newest.read_bytes())
    data[-1] ^= 0xFF
    newest.write_bytes(bytes(data))
    assert any(p["type"] == "checkpoint_invalid" for p in store.verify()["problems"])
    report = store.recover()
    assert report["checkpoint"]["checkpoint_id"] == rows[-2][0]
    assert report["skipped_checkpoints"]
    assert snapshot(store) == structure.rebuild(store.events())


def test_a_corrupted_index_is_detected_and_rebuilt_from_the_core(tmp_path):
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    build_history(store)
    conn = store._connect()
    conn.execute("DROP TRIGGER IF EXISTS edges_append_only_delete")
    conn.execute("DELETE FROM edges WHERE rowid IN (SELECT rowid FROM edges LIMIT 3)")
    conn.execute("DELETE FROM code_parse")
    conn.commit()
    conn.close()
    problems = store.verify()["problems"]
    assert any(p["type"] == "structure_mismatch" and p["table"] == "edges" for p in problems)
    report = store.recover()
    assert report["repaired_tables"] == ["edges"]
    assert store.verify()["ok"]


def test_a_corrupted_core_record_is_reported_and_never_dropped(tmp_path):
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    build_history(store)
    count = store.count()
    conn = store._connect()
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='events'").fetchall():
        conn.execute(f"DROP TRIGGER {name}")
    conn.execute("UPDATE events SET summary_fields = '{\"tampered\":true}' WHERE log_position = 3")
    conn.commit()
    conn.close()
    problems = store.verify()["problems"]
    assert any(p.get("log_position") == 3 or "3" in json.dumps(p) for p in problems)
    store.recover()
    assert store.count() == count + 1   # nothing dropped; only the recovery record was added
    assert not store.verify()["ok"]     # still reported: the log is never silently repaired


def test_the_engine_failing_never_fails_the_agent_and_the_gap_is_recorded(tmp_path, monkeypatch):
    """8.4: capture fails open; the spool keeps no content."""
    path = tmp_path / "store"
    store = Store(path, project_id="p", min_free_bytes=0)
    secret_text = b"the payload the engine failed to store"

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    with monkeypatch.context() as m:
        m.setattr(store, "append", boom)
        assert store.safe_append(ev("tool_result", payload=secret_text)) is None
    spooled = (path / "spool.jsonl").read_bytes()
    assert b"payload the engine failed" not in spooled
    reopened = Store(path, project_id="p", min_free_bytes=0)
    (gap,) = [e for e in reopened.events() if e.kind == "capture_gap"]
    assert gap.completeness == "unavailable" and gap.summary_fields["missed_kind"] == "tool_result"
    assert gap.summary_fields["size"] == len(secret_text)
    assert not (path / "spool.jsonl").exists()


KILL_WRITER = textwrap.dedent("""
    import sys
    from agent_memory import Store
    from agent_memory.schema import EventInput
    s = Store(sys.argv[1], project_id="p", min_free_bytes=0)
    s.checkpoint_every = 7
    parent = None
    for i in range(100000):
        kind = ("goal", "task", "note", "decision")[i % 4]
        fields = {"op": "create", "title": f"item {i}"} if kind in ("goal", "task", "decision") else {"i": i}
        e = s.append(EventInput(kind=kind, session_id="s", writer_id="w", summary_fields=fields,
                                payload=f"payload {i}".encode(), parent_id=parent))
        parent = e.event_id
        if i == 20:
            print("ready", flush=True)
""")


@pytest.mark.parametrize("trial", range(int(os.environ.get("AMEM_KILL_TRIALS", "5"))))
def test_recovery_after_a_random_kill_matches_a_clean_replay(tmp_path, trial):
    path = tmp_path / "store"
    Store(path, project_id="p", min_free_bytes=0)
    proc = subprocess.Popen([sys.executable, "-c", KILL_WRITER, str(path)], stdout=subprocess.PIPE)
    assert proc.stdout.readline().strip() == b"ready"
    time.sleep(random.Random(trial).uniform(0.05, 0.6))
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    store = Store(path, project_id="p", min_free_bytes=0)
    assert store.count() > 20
    store.recover()
    assert snapshot(store) == structure.rebuild(store.events())
    assert store.verify()["ok"], store.verify()["problems"]


# ---------------------------------------------------------------- the CLI
def test_amem_verify_rebuild_reconcile_checkpoint_and_recover(tmp_path, capsys):
    repo, _ = scenarios.init_repo(tmp_path)
    home = ["--project", str(repo)]
    assert amem([*home, "reconcile"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["changes"] > 0 and out["ok"] is True
    (repo / "pkg" / "mod_001.py").write_text("x = 2\n")
    assert amem([*home, "reconcile"]) == 0
    assert json.loads(capsys.readouterr().out)["by_attribution"] == {"external": 1}
    assert amem([*home, "checkpoint"]) == 0
    assert json.loads(capsys.readouterr().out)["checkpoint_id"] == 1
    assert amem([*home, "rebuild"]) == 0
    capsys.readouterr()
    assert amem([*home, "verify"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert amem([*home, "recover"]) == 0
    assert json.loads(capsys.readouterr().out)["checkpoint"]["checkpoint_id"] == 1
    assert amem([*home, "where"]) == 0
    assert capsys.readouterr().out.strip() == str(repo.resolve() / ".agent-memory")


def test_amem_verify_fails_when_something_is_wrong(tmp_path, capsys):
    repo, _ = scenarios.init_repo(tmp_path)
    assert amem(["--project", str(repo), "reconcile"]) == 0
    capsys.readouterr()
    db = repo / ".agent-memory" / "memory.db"
    conn = sqlite3.connect(db)
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='events'").fetchall():
        conn.execute(f"DROP TRIGGER {name}")
    conn.execute("UPDATE events SET kind = 'note' WHERE log_position = 1")
    conn.commit()
    conn.close()
    assert amem(["--project", str(repo), "verify"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


# ---------------------------------------------------------------- helpers
def build_history(store: Store) -> None:
    session = store.append(ev("session_start"))
    goal = store.create("goal", "s1", "w1", title="ship it")
    path = store.create("path", "s1", "w1", topic="db", description="approach A")
    for i in range(10):
        store.append(ev(payload=f"note {i}".encode(), parent_id=session.event_id,
                        summary_fields={"path_id": path, "title": f"note {i}"}))
    store.set_status("path", path, "abandoned", "s1", "w1", reason="too slow")
    store.relate(goal, path, "related_to", "s1", "w1")
    store.append(EventInput(kind="file_change", session_id="s1", writer_id="w1", payload=b"def f():\n    pass\n",
                            summary_fields={"path": "src/app.py", "change": "added"}, path="src/app.py"))
    store.update_code_graph()
    store.append(ev("session_end"))


def snapshot(store: Store) -> dict:
    conn = store._connect()
    try:
        return structure.snapshot(conn)
    finally:
        conn.close()
