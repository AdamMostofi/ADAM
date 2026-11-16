"""#93: `amem verify` reports integrity, capture, known gaps and attribution separately.

Integrity proves the captured records are intact and continuous. It can't prove nothing was missed before
capture, so the report gives the evidence for that separately, and the exit code stays tied to integrity.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess

from agent_memory import EventInput, Store
from agent_memory.cli import main as amem
from agent_memory.location import store_path

S = "sess-v"


def git_project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@example.invalid"],
                ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=p, check=True)
    (p / "a.py").write_text("a = 1\n")
    (p / "b.py").write_text("b = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=p, check=True)
    return p


def store_with_gap_and_unattributed_change(tmp_path):
    p = git_project(tmp_path)
    store = Store(store_path(p), min_free_bytes=0)
    store.append(EventInput(kind="session_start", session_id=S, writer_id="agent", summary_fields={}))
    store.reconciler(p, S).run()
    # The agent is active (a tool call), and a file changes that no tool or command named: unattributed.
    store.append(EventInput(kind="tool_call", session_id=S, writer_id="agent", summary_fields={"tool": "Read"}))
    (p / "b.py").write_text("b = 2\n")
    store.reconciler(p, S).run()
    store.append(EventInput(kind="capture_gap", session_id=S, writer_id="agent", completeness="unavailable",
                            summary_fields={"missed_kind": "PostToolUse", "reason": "handler failed"}))
    return p, store


def test_a_gap_and_an_unattributed_change_leave_integrity_ok_and_are_listed(tmp_path):
    _, store = store_with_gap_and_unattributed_change(tmp_path)
    for report in (store.verify(full=True), store.verify(full=False)):
        assert report["ok"] and report["integrity"]["ok"]
        assert report["known_gaps"]["capture_gaps"] == 1
        assert report["known_gaps"]["examples"][0]["missed"] == "PostToolUse"
        assert report["attribution"]["unattributed"] == 1
        assert report["attribution"]["examples"][0]["path"] == "b.py"
        assert report["capture"]["sessions"] == 1 and report["capture"]["not_ended"] == 1
        assert report["capture"]["last_reconcile"] == {"ok": True, "error": None}
        lines = report["statement"]
        assert lines[0].startswith("archive integrity: verified")
        assert "1 never recorded an end" in lines[1]
        assert lines[2] == "known gaps: 1 capture gap(s), 0 partial record(s)"
        assert lines[3] == "uncertain attribution: 1 file change(s) unattributed"


def test_a_tampered_store_fails_integrity_and_only_integrity_sets_the_exit_code(tmp_path, capsys):
    p, store = store_with_gap_and_unattributed_change(tmp_path)
    assert amem(["--project", str(p), "verify", "--full"]) == 0      # gaps don't fail verify
    out = capsys.readouterr()
    assert json.loads(out.out)["known_gaps"]["capture_gaps"] == 1
    assert "known gaps: 1 capture gap(s)" in out.err
    conn = sqlite3.connect(store.path / "memory.db")
    conn.execute("DROP TRIGGER IF EXISTS events_append_only_update")
    conn.execute("UPDATE events SET summary_fields = ? WHERE log_position = 2", (json.dumps({"x": 1}),))
    conn.commit()
    conn.close()
    report = Store(store_path(p), min_free_bytes=0).verify(full=True)
    assert not report["ok"] and not report["integrity"]["ok"]
    assert report["statement"][0].startswith("archive integrity: FAILED")
    assert amem(["--project", str(p), "verify", "--full"]) == 1


def test_a_clean_session_reports_no_gaps(store):
    store.append(EventInput(kind="session_start", session_id=S, writer_id="agent", summary_fields={}))
    store.append(EventInput(kind="session_end", session_id=S, writer_id="agent", summary_fields={}))
    report = store.verify()
    assert report["capture"]["ended_cleanly"] == 1 and report["capture"]["not_ended"] == 0
    assert report["known_gaps"]["capture_gaps"] == report["known_gaps"]["partial"] == 0
    assert report["attribution"]["unattributed"] == 0
