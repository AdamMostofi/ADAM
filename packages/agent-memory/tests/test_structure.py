"""Stage 2.3 (#52): historical tree, relationship graph, development paths, planning records."""
from __future__ import annotations

import sqlite3

import pytest

from agent_memory import EventInput, SchemaError


def ev(store, kind, session="s1", writer="w1", parent=None, **summary):
    return store.append(EventInput(kind=kind, session_id=session, writer_id=writer, parent_id=parent,
                                   summary_fields=summary, agent="claude-code"))


@pytest.fixture
def history(store):
    """A small but complete development history across three sessions."""
    h = {}
    h["start1"] = ev(store, "session_start", git_branch="main")
    h["msg1"] = ev(store, "user_message", text="add caching to the API")
    h["call1"] = ev(store, "tool_call", tool="Edit", path="api/cache.py")
    h["change1"] = ev(store, "file_change", parent=h["call1"].event_id, path="api/cache.py")
    h["fail"] = ev(store, "verification", command="pytest tests/api", result="failed", exit_code=1,
                   verifies=[h["change1"].event_id])
    h["cause"] = ev(store, "note", note_type="cause", text="connection pool exhausted under the cache",
                    based_on=[h["fail"].event_id])
    h["msg2"] = ev(store, "user_message", text="fix the pool problem")
    h["call2"] = ev(store, "tool_call", tool="Edit", path="api/pool.py")
    h["fix"] = ev(store, "file_change", parent=h["call2"].event_id, path="api/pool.py")
    store.relate(h["fix"].event_id, f"note:{h['cause'].event_id}", "based_on", "s1", "w1",
                 reason="the fix addresses the cause")
    h["pass"] = ev(store, "verification", command="pytest tests/api", result="passed", exit_code=0,
                   verifies=[h["fix"].event_id])

    # Development paths: two approaches to one question.
    h["pg"] = store.create("path", "s1", "w1", topic="database", description="PostgreSQL",
                           evidence=[h["msg1"].event_id])
    h["lite"] = store.create("path", "s1", "w1", topic="database", description="SQLite",
                             alternative_to=[h["pg"]])
    store.set_status("path", h["pg"], "exploring", "s1", "w1")
    store.set_status("path", h["pg"], "abandoned", "s1", "w1", reason="needs a server the user doesn't run",
                     evidence=[h["fail"].event_id])
    store.set_status("path", h["lite"], "selected", "s1", "w1", reason="embedded, zero setup")

    # Decisions, goals, tasks, blockers.
    h["dec_agent"] = store.create("decision", "s1", "w1", title="cache for 60 seconds", based_on=[h["msg1"].event_id])
    h["dec_user"] = store.create("decision", "s1", "w1", title="cache for 30 seconds",
                                 from_user_message=h["msg2"].event_id, supersedes=[h["dec_agent"]],
                                 based_on=[h["msg2"].event_id])
    h["goal"] = store.create("goal", "s1", "w1", title="the API responds in under 100 ms")
    h["task"] = store.create("task", "s1", "w1", title="add a response cache", advances=[h["goal"]])
    h["blocker"] = store.create("blocker", "s1", "w1", title="no load-test environment", blocks=[h["task"]])
    store.set_status("task", h["task"], "blocked", "s1", "w1", reason="waiting for the load-test box")
    store.set_status("blocker", h["blocker"], "resolved", "s1", "w1")
    store.set_status("task", h["task"], "done", "s1", "w1")
    h["end1"] = ev(store, "session_end")

    # Session 2 resumes session 1 on a new branch; session 3 forks session 2.
    h["start2"] = ev(store, "session_start", session="s2", resumed_from="s1", continues=["s1"],
                     git_branch="feature/cache")
    h["msg3"] = ev(store, "user_message", session="s2", text="try SQLite again")
    store.set_status("path", h["pg"], "reconsidered", "s2", "w1", reason="the user now runs a server")
    h["change2"] = ev(store, "file_change", session="s2", path="api/cache.py", path_id=h["lite"],
                      path_role="accepted")
    h["start3"] = ev(store, "session_start", session="s3", forked_from="s2")
    h["revert"] = ev(store, "file_change", session="s3", path="api/cache.py", restores_version=True)
    return h


# ------------------------------------------------------------ the tree

def test_the_tree_has_project_sessions_turns_and_events_in_order(store, history):
    tree = store.tree("project", depth=3)
    assert [s["id"] for s in tree["children"]] == ["session:s1", "session:s2", "session:s3"]
    s1 = tree["children"][0]
    turns = [c for c in s1["children"] if c["type"] == "turn"]
    assert [t["id"] for t in turns] == ["turn:s1:2", "turn:s1:3"]
    assert s1["children"][0]["id"] == history["start1"].event_id   # before the first user message
    turn1 = [c["id"] for c in turns[0]["children"]]
    assert turn1[:3] == [history["msg1"].event_id, history["call1"].event_id, history["change1"].event_id]


# ------------------------------------------------------------ every navigation in design 6.1

def test_project_navigation(store, history):
    view = store.project_view()
    assert view["sessions"] == ["session:s1", "session:s2", "session:s3"]
    assert {history["pg"], history["lite"]} <= set(view["paths"])
    assert view["goals"] == [history["goal"]]
    assert view["decisions"] == [history["dec_agent"], history["dec_user"]]


def test_session_navigation(store, history):
    s2 = store.session_view("s2")
    assert s2["turns"] == ["turn:s2:2"]
    assert history["change2"].event_id in s2["events"]
    assert history["lite"] in s2["paths"]
    assert "session:s1" in s2["continued_from"]
    assert store.session_view("s3")["forked_from"] == ["session:s2"]


def test_event_navigation(store, history):
    change = store.event_view(history["change1"].event_id)
    assert change["files"] == ["file:api/cache.py"]
    assert change["verifications"] == [history["fail"].event_id]
    assert change["triggered_by"] == [history["call1"].event_id]
    assert history["change1"].event_id in store.event_view(history["call1"].event_id)["caused"]


def test_file_navigation(store, history):
    f = store.file_view("api/cache.py")
    assert f["changes"] == [history["change1"].event_id, history["change2"].event_id, history["revert"].event_id]


def test_decision_navigation(store, history):
    agent = store.decision_view(history["dec_agent"])
    user = store.decision_view(history["dec_user"])
    assert agent["status_history"][0]["status"] == "proposed"      # agent-declared decisions start proposed
    assert user["status_history"][0]["status"] == "active"         # one from a user message is active
    assert agent["status"] == "superseded" and agent["replaced_by"] == [history["dec_user"]]
    assert user["replaces"] == [history["dec_agent"]]
    assert history["msg2"].event_id in user["discussion"]


def test_verification_navigation(store, history):
    v = store.verification_view(history["fail"].event_id)
    assert v["command"] == "pytest tests/api" and v["result"] == "failed" and v["exit_code"] == 1
    assert v["verifies"] == [history["change1"].event_id]


def test_path_navigation(store, history):
    lite = store.path_view(history["lite"])
    assert lite["topic"] == "database" and lite["status"] == "selected" and lite["reason"] == "embedded, zero setup"
    assert lite["alternatives"] == [history["pg"]]
    assert lite["selected_over"] == [history["pg"]]
    assert {"record": history["change2"].event_id, "role": "accepted"} in lite["attempts"]


# ------------------------------------------------------------ paths keep their history

def test_an_abandoned_path_keeps_its_reason_and_evidence_and_can_be_reconsidered(store, history):
    pg = store.path_view(history["pg"])
    assert [h["status"] for h in pg["status_history"]] == ["proposed", "exploring", "abandoned", "reconsidered"]
    abandoned = pg["status_history"][2]
    assert abandoned["reason"] == "needs a server the user doesn't run"
    assert pg["abandoned_because"] == [history["fail"].event_id]
    assert pg["status"] == "reconsidered" and pg["reason"] == "the user now runs a server"
    assert history["msg1"].event_id in pg["evidence"]


def test_structural_signals_propose_unnamed_paths(store, history):
    proposals = [p for p in store.project_view()["paths"] if store.path_view(p)["source"] == "recorded"]
    signals = {store.node(p)["attrs"]["signal"] for p in proposals}
    assert signals == {"git_branch", "session_fork", "revert"}
    for p in proposals:
        view = store.path_view(p)
        assert view["status"] == "proposed" and view["topic"] is None   # proposed, never named by the engine


# ------------------------------------------------------------ basis labels

def test_inferred_edges_are_always_labelled(store, history):
    store.relate(history["change1"].event_id, history["fix"].event_id, "related_to", "s1", "w1",
                 basis="inferred", reason="same module, heuristic")
    inferred = [e for e in store.edges(history["change1"].event_id, "out") if e["type"] == "related_to"]
    assert inferred and all(e["basis"] == "inferred" for e in inferred)
    for step in store.trace(history["change1"].event_id, direction="both", depth=3):
        assert step["basis"] in ("recorded", "declared", "inferred")
    with pytest.raises(SchemaError):
        store.relate(history["change1"].event_id, history["fix"].event_id, "caused_by", "s1", "w1", basis="recorded")


def test_the_engine_never_claims_causes_it_did_not_observe(store, history):
    # The pass after the fix is recorded as verifying the fix, not as caused by it.
    assert not [e for e in store.edges(history["pass"].event_id, "out") if e["type"] == "caused_by"]


# ------------------------------------------------------------ causal chain

def test_a_causal_chain_can_be_followed_end_to_end(store, history):
    """change -> failure -> cause -> fix -> pass, followed back from the pass."""
    walked = store.trace(history["pass"].event_id, types=("verifies", "based_on"), direction="out", depth=6)
    reached = [step["to"] for step in walked]
    cause = f"note:{history['cause'].event_id}"
    assert reached == [history["fix"].event_id, cause, history["fail"].event_id, history["change1"].event_id]
    assert [s["basis"] for s in walked] == ["recorded", "declared", "declared", "recorded"]


# ------------------------------------------------------------ append-only, retraction, integrity

def test_edges_are_never_deleted_and_retractions_are_honoured(store, history):
    edge = store.relate(history["change1"].event_id, history["change2"].event_id, "related_to", "s2", "w1")
    edge_id = [e for e in store.edges(history["change1"].event_id, "out") if e["type"] == "related_to"][0]["edge_id"]
    store.retract(edge_id, "s2", "w1", reason="not actually related")
    assert not [e for e in store.edges(history["change1"].event_id, "out") if e["type"] == "related_to"]
    kept = [e for e in store.edges(history["change1"].event_id, "out", include_retracted=True)
            if e["type"] == "related_to"]
    assert kept and kept[0]["retracted_by"] is not None
    conn = sqlite3.connect(store.path / "memory.db")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM edges WHERE edge_id = ?", (edge_id,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE statuses SET status = 'selected'")


def test_invalid_declarations_store_nothing(store, history):
    before = store.count()
    bad = [
        ("path", {"op": "status", "id": "path:nope", "status": "selected"}),
        ("path", {"op": "status", "id": history["pg"], "status": "finished"}),
        ("task", {"op": "create"}),
        ("decision", {"op": "create", "title": "x", "supersedes": [history["goal"]]}),
        ("relation", {"from": history["pg"], "to": "nothing", "type": "supports"}),
        ("relation", {"from": history["pg"], "to": history["lite"], "type": "loves"}),
        ("retraction", {"edge_id": 999_999}),
        ("file_change", {"path": "a.py", "path_id": history["goal"]}),
    ]
    for kind, summary in bad:
        with pytest.raises(SchemaError):
            ev(store, kind, **summary)
    assert store.count() == before


def test_structure_equals_a_rebuild_from_the_log(store, history):
    assert store.verify()["ok"]


def test_tampering_with_structure_is_detected(store, history):
    conn = sqlite3.connect(store.path / "memory.db")
    conn.execute("DROP TRIGGER statuses_append_only_update")
    conn.execute("UPDATE statuses SET status = 'selected' WHERE node_id = ?", (history["pg"],))
    conn.commit()
    report = store.verify()
    assert not report["ok"]
    assert {"type": "structure_mismatch", "table": "statuses",
            "detail": "doesn't match a rebuild from the event log"} in report["problems"]


def test_secrets_in_declared_records_are_redacted(store):
    key = "AK" + "IA" + "Q3EGRZUXBYJKLMNO"
    goal = store.create("goal", "s1", "w1", title=f"rotate the leaked key {key}")
    assert key not in store.node(goal)["label"]


# ------------------------------------------------------------ property: structure is a function of the log

from hypothesis import HealthCheck, given, settings          # noqa: E402
from hypothesis import strategies as st                       # noqa: E402

OPS = st.lists(st.tuples(
    st.sampled_from(["user_message", "tool_call", "file_change", "verification", "note", "session_start",
                     "path", "path_status", "goal", "relation", "retraction", "bad"]),
    st.sampled_from(["s1", "s2", "s3"]),
    st.integers(0, 50),
), min_size=1, max_size=40)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(OPS)
def test_stored_structure_always_equals_a_rebuild_from_the_log(tmp_path_factory, ops):
    from agent_memory import Store
    store = Store(tmp_path_factory.mktemp("prop") / "s", project_id="p", min_free_bytes=0)
    events, paths = [], []
    for kind, session, n in ops:
        def pick(xs, n=n):
            return xs[n % len(xs)]
        try:
            if kind == "path":
                paths.append(store.create("path", session, "w", topic="t", description=f"p{n}",
                                          alternative_to=[pick(paths)] if paths and n % 2 else None))
            elif kind == "path_status" and paths:
                store.set_status("path", pick(paths), ["exploring", "abandoned", "selected", "reconsidered"][n % 4],
                                 session, "w", reason=f"r{n}", evidence=[pick(events).event_id] if events else None)
            elif kind == "goal":
                store.create("goal", session, "w", title=f"g{n}")
            elif kind == "relation" and len(events) > 1:
                store.relate(pick(events).event_id, events[(n + 1) % len(events)].event_id, "related_to",
                             session, "w", basis=["declared", "inferred"][n % 2])
            elif kind == "retraction":
                conn = sqlite3.connect(store.path / "memory.db")
                ids = [r[0] for r in conn.execute("SELECT edge_id FROM edges")]
                conn.close()
                store.retract(ids[n % len(ids)], session, "w", reason="x") if ids else None
            elif kind == "bad":
                with pytest.raises(SchemaError):
                    ev(store, "path", session=session, op="status", id="path:missing", status="selected")
            elif kind in ("user_message", "tool_call", "note", "session_start", "verification", "file_change"):
                summary = {"path": f"f{n % 4}.py"} if kind == "file_change" else {}
                if kind == "verification" and events:
                    summary = {"verifies": [pick(events).event_id], "result": "passed"}
                if kind == "session_start" and n % 3 == 0:
                    summary = {"forked_from": "s1", "git_branch": f"b{n % 5}"}
                events.append(ev(store, kind, session=session, writer="w",
                                 parent=pick(events).event_id if events and n % 3 == 0 else None, **summary))
        except SchemaError:
            pass
    assert store.verify()["ok"]
