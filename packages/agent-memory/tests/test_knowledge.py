"""Stage 2.8 (#87): knowledge kinds, the topic hierarchy, supersession, and knowledge and history search."""
from __future__ import annotations

import pytest

from agent_memory import EventInput, SchemaError, structure

S, W = "s1", "w1"


def say(store, kind, text, session=S, payload=None):
    return store.append(EventInput(kind=kind, session_id=session, writer_id=W, summary_fields={"text": text},
                                   payload=payload))


# ---------------------------------------------------------------- every kind
ALL_KINDS = ("decision", "approach", *structure.ENTRY_KINDS)
SECOND_STATUS = {"decision": "active", "approach": "exploring", "requirement": "met", "constraint": "lifted",
                 "concept": "superseded", "explanation": "superseded", "discovery": "refuted", "bug": "fixed",
                 "solution": "applied", "question": "answered", "reference": "superseded"}


def test_every_core_kind_is_declared_changed_and_found(store):
    ids = {}
    for kind in ALL_KINDS:
        ids[kind] = store.declare_entry(kind, f"the {kind} title", S, W, topic="Auth / Tokens",
                                        body=f"zebra{kind} details")
    for kind, node_id in ids.items():
        assert node_id.startswith(("path" if kind == "approach" else kind) + ":")
        assert store.knowledge.open(node_id)["type"] == kind
        store.set_entry_status(node_id, SECOND_STATUS[kind], S, W, reason="moved on")
    for kind, node_id in ids.items():
        assert [e["id"] for e in store.knowledge.find(kind)] == [node_id]
        assert [e["id"] for e in store.knowledge.find(kind, SECOND_STATUS[kind])] == [node_id]
        assert [e["id"] for e in store.knowledge.find(text=f"zebra{kind}")] == [node_id]
    assert len(store.knowledge.find(topic="auth")) == len(ALL_KINDS)          # a parent topic includes subtopics
    assert len(store.knowledge.find(topic="AUTH/tokens")) == len(ALL_KINDS)   # topic paths are case-insensitive
    assert store.knowledge.find(topic="billing") == []
    assert store.verify()["ok"]


def test_bad_declarations_are_refused(store):
    with pytest.raises(SchemaError):
        store.declare_entry("spaceship", "x", S, W)
    with pytest.raises(SchemaError):
        store.declare("entry", S, W, op="create", entry_kind="decision", title="use the decision kind instead")
    bug = store.declare_entry("bug", "crash", S, W)
    with pytest.raises(SchemaError):
        store.set_entry_status(bug, "finished", S, W)
    question = store.declare_entry("question", "why?", S, W)
    with pytest.raises(SchemaError):
        store.declare_entry("solution", "fix", S, W, fixes=[question])     # fixes must name a bug
    with pytest.raises(SchemaError):
        store.declare_entry("concept", "x", S, W, supersedes=[bug])         # supersedes must be the same kind
    with pytest.raises(SchemaError):
        store.declare_topic(" / ", S, W)


# ---------------------------------------------------------------- the bug story
def test_a_bug_links_to_its_solution_its_evidence_and_the_history_where_they_arose(store):
    report = say(store, "user_message", "refresh fails randomly in prod")
    store.append(EventInput(kind="file_change", session_id=S, writer_id=W, payload=b"def refresh(): ...\n",
                            summary_fields={"path": "src/auth/jwt.py"}, path="src/auth/jwt.py"))
    bug = store.declare_entry("bug", "refresh race when two tabs refresh at once", S, W, topic="auth",
                              discussed_in=[report.event_id], concerns=["src/auth/jwt.py"],
                              body="two refreshes rotate the token twice")
    run = store.append(EventInput(kind="verification", session_id=S, writer_id=W,
                                  summary_fields={"command": "pytest tests/auth", "result": "passed"}))
    solution = store.declare_entry("solution", "single-flight lock on refresh", S, W, topic="auth",
                                   fixes=[bug], evidence=[run.event_id], concerns=["src/auth/jwt.py"])
    store.set_entry_status(bug, "fixed", S, W, reason="lock added")

    b = store.knowledge.history_of(bug)
    assert [f["id"] for f in b["fixed_by"]] == [solution]
    assert b["status"] == "fixed" and [h["status"] for h in b["status_history"]] == ["open", "fixed"]
    assert b["discussed_in"] == [{"id": report.event_id, "basis": "declared", "tree": "history"}]
    assert b["concerns"][0]["id"] == "artifact:src/auth/jwt.py" and b["concerns"][0]["tree"] == "artifacts"
    assert b["body"] == "two refreshes rotate the token twice"
    s = store.knowledge.history_of(solution)
    assert [f["id"] for f in s["fixes"]] == [bug]
    assert s["evidence"] == [{"id": run.event_id, "basis": "declared", "tree": "history"}]
    # Both arose in history: the events that declared them are in the history tree, linked across trees.
    for record in (bug, solution):
        declared = store.knowledge.history_of(record)["declared_in"]
        assert declared and all(store.history.open(e) for e in declared)
        assert any(link["tree"] == "history" for link in store.links(record, "history"))
    assert {link["node"] for link in store.artifacts.links("artifact:src/auth/jwt.py", "knowledge")} == {bug, solution}


def test_supersession_chains_are_followed_both_ways(store):
    a = store.declare_entry("concept", "tokens live in cookies", S, W, topic="auth")
    b = store.declare_entry("concept", "tokens live in memory", S, W, topic="auth", supersedes=[a])
    c = store.declare_entry("concept", "tokens live in a worker", S, W, topic="auth", supersedes=[b])
    assert store.knowledge.history_of(a)["replaced_by"] == [b, c]
    assert store.knowledge.history_of(c)["replaces"] == [b, a]
    assert store.knowledge.history_of(a)["status"] == "superseded"
    assert [e["id"] for e in store.knowledge.find("concept", "current")] == [c]


# ---------------------------------------------------------------- topics
def test_topics_nest_and_browsing_never_loads_bodies(store):
    store.declare_topic("Auth/JWT", S, W, description="token signing and rotation")
    store.declare_entry("decision", "sign with EdDSA", S, W, topic="auth/jwt", body="SECRET-LOOKING BODY TEXT")
    store.declare_entry("requirement", "tokens expire in 15 minutes", S, W, topic="auth")
    root = store.knowledge.topics()
    (auth,) = [t for t in root["items"] if t["label"] == "Auth"]
    assert auth["type"] == "topic" and auth["children"] == 2         # the jwt subtopic and the requirement
    deep = store.knowledge.topics(depth=3)
    assert "BODY TEXT" not in repr(deep)                               # listings only, at any depth
    topic = store.knowledge.topic("auth/jwt")
    assert topic["attrs"]["description"] == "token signing and rotation"
    (decision,) = topic["items"]
    assert set(decision) == {"id", "type", "label", "status", "basis", "children", "links"}
    assert store.knowledge.open(decision["id"])["attrs"]["body"] == "SECRET-LOOKING BODY TEXT"


def test_extra_topics_and_an_inferred_topic(store):
    store.append(EventInput(kind="file_change", session_id=S, writer_id=W, payload=b"export const a = 1;\n",
                            summary_fields={"path": "web/app.ts"}, path="web/app.ts"))
    filed = store.declare_entry("discovery", "the bundle is 2 MB", S, W, topic="performance", filed_under=["web"])
    unfiled = store.declare_entry("question", "is SSR worth it?", S, W, concerns=["web/app.ts"])
    assert {e["id"] for e in store.knowledge.find(topic="web")} == {filed, unfiled}
    assert [e["id"] for e in store.knowledge.find(topic="unfiled")] == [unfiled]   # its home is still unfiled
    proposal = [x for x in store.edges(unfiled, "out") if x["type"] == "filed_under"][0]
    assert proposal["basis"] == "inferred" and proposal["attrs"]["rule"] == "inferred from the artifact web/app.ts"
    declared = [x for x in store.edges(filed, "out") if x["type"] == "filed_under"][0]
    assert declared["basis"] == "declared"


# ---------------------------------------------------------------- history search
def test_history_search_finds_conversation_text_but_never_a_secret(store):
    token = "gh" + "p_" + "Ab3dEf6hIj9kLm2nOp5qRs8tUv1wXy4zAb7d"
    say(store, "user_message", "the login page flickers on Safari")
    say(store, "assistant_message", "I will check the CSS transitions", payload=f"use token {token} here".encode())
    say(store, "user_message", "also check Safari on iOS", session="s2")
    hits = store.history.search("Safari")
    assert {h["session_id"] for h in hits} == {"s1", "s2"}
    assert [h["kind"] for h in store.history.search("CSS transitions")] == ["assistant_message"]
    assert [h["session_id"] for h in store.history.search("Safari", session_id="s2")] == ["s2"]
    assert store.history.search(token) == []
    assert "[flickers]" in store.history.search("flickers")[0]["snippet"]


def test_the_search_index_is_incremental_and_rebuildable(store):
    store.declare_entry("explanation", "why WAL mode", S, W, body="readers never block the writer")
    say(store, "user_message", "explain WAL")
    before = (store.knowledge.find(text="readers"), store.history.search("WAL"))
    assert store.search_index.update() == {"knowledge": 0, "history": 0}   # already up to date
    counts = store.rebuild_derived()
    assert counts["searched"]["history"] == 1 and counts["searched"]["knowledge"] >= 1
    assert (store.knowledge.find(text="readers"), store.history.search("WAL")) == before
    assert store.verify()["ok"]
