"""Stage 4.6 (#35): every chat turn records a typed thought trace, readable at /api/traces/<id>."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from memory.trace_log import NODE_TYPES, TRACE_VERSION, TraceLog, node, render

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "interface" / "web" / "static" / "js"


class QuietMouth:
    def format_response(self, message, params, context=""):
        return ""


@pytest.fixture
def core(tmp_path):
    from interface.core import ADAMCore
    core = ADAMCore(db_path=str(tmp_path / "adam_memory.db"), lance_path=str(tmp_path / "adam_vectors.db"),
                    mouth=QuietMouth())
    for f in (("socrates", "instance_of", "man"), ("man", "subclass_of", "mortal")):
        core.add_fact(*f)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "apology.md").write_text("# Apology\n\nThe unexamined life is not worth living.\n")
    library = core.memory.source_library()
    library.workspace = workspace.resolve()
    library.ingest("apology.md")
    return core


def trace_of(core, result):
    return core.read_trace(result["trace_id"])


# ------------------------------------------------------------ acceptance
def test_a_proof_answer_yields_a_trace_linked_to_its_proof_records(core):
    result = core.chat("Is Socrates mortal?")
    trace = trace_of(core, result)
    assert [n["type"] for n in trace["nodes"]] == ["PERCEIVE", "RECALL", "INFER", "ANSWER"]
    assert trace["version"] == TRACE_VERSION and trace["conversation"] == result["conversation"]
    for n in trace["nodes"]:
        assert set(n) == {"type", "inputs", "outputs", "confidence", "provenance", "at"}
    infer = trace["nodes"][2]
    (proof,) = infer["outputs"]["proofs"]
    assert proof["claim"] == "socrates instance_of mortal"
    # linked by id to the stored fact and its Stage 1.4 derivation record (#30)
    assert proof["fact_id"] is not None and proof["derivation_ids"]
    stored = core.memory.fact_store.derivations_of(proof["fact_id"])
    assert [d["id"] for d in stored] == proof["derivation_ids"]
    assert infer["confidence"] == pytest.approx(core.engine.beliefs[("socrates", "instance_of", "mortal")].confidence,
                                                abs=1e-4)
    assert trace["nodes"][3]["outputs"]["answer_source"] == "proof"


def test_a_passage_answer_yields_a_trace_linked_to_its_citation(core):
    result = core.chat("Is the unexamined life worth living?")
    trace = trace_of(core, result)
    answer, recall = trace["nodes"][3], trace["nodes"][1]
    assert answer["outputs"]["answer_source"] == "passage"
    (cite,) = answer["outputs"]["citations"]
    assert cite == {k: result["citations"][0][k] for k in ("source", "name", "ordinal", "start", "end", "sha256")}
    assert recall["outputs"]["library_searched"] and recall["outputs"]["passages"] == [f"{cite['source']}#1"]


def test_english_is_generated_from_the_trace_and_never_stored(core, tmp_path):
    result = core.chat("Is Socrates mortal?")
    trace = trace_of(core, result)
    assert trace["text"] == render(trace)
    assert trace["text"][0] == "Perceived “Is Socrates mortal?” as a question."
    assert any("Proved “socrates instance_of mortal” from 2 given facts" in line for line in trace["text"])
    assert trace["text"][-1] == "Answered from a proof."
    with sqlite3.connect(tmp_path / "adam_memory.traces.db") as conn:
        stored = conn.execute("SELECT nodes FROM traces WHERE id = ?", (result["trace_id"],)).fetchone()[0]
    assert "Perceived" not in stored and "Answered from" not in stored and result["response"] not in stored
    assert json.loads(stored) == trace["nodes"]


def test_every_turn_gets_a_trace_and_a_turn_number(core):
    ids = [core.chat(m, conversation="web-test-1")["trace_id"] for m in ("hello", "Is Socrates mortal?", "I like pizza")]
    traces = [core.read_trace(i) for i in ids]
    assert [t["turn"] for t in traces] == [1, 2, 3] and len(set(ids)) == 3
    assert [t["nodes"][0]["outputs"]["route"] for t in traces] == ["small_talk", "question", "chatter"]


def test_api_chat_returns_the_trace_id_and_the_read_endpoint_serves_it(core):
    from interface.web.app import create_app
    client = create_app(core).test_client()
    body = client.post("/api/chat", json={"message": "Is Socrates mortal?", "conversation": "web-abc"}).get_json()
    assert {"response", "intent", "state", "params", "memories_used", "answer_source", "evidence", "frustration",
            "citations", "trace_id", "conversation"} <= set(body)
    assert body["conversation"] == "web-abc"
    read = client.get(f"/api/traces/{body['trace_id']}")
    assert read.status_code == 200 and read.get_json()["text"][-1] == "Answered from a proof."
    assert client.get("/api/traces/0123abcd").status_code == 404
    assert client.get("/api/traces/..%2Fetc").status_code == 404
    # a malformed conversation id is ignored, not stored
    bad = client.post("/api/chat", json={"message": "hi", "conversation": "../../x"}).get_json()
    assert bad["conversation"].startswith("run-")


def test_no_ui_status_claims_work_that_did_not_occur():
    chat = (JS / "chat.js").read_text()
    for claim in ("Consulting the archives", "Cross-checking the vaults", "Testing propositions",
                  "Forming the response", "setInterval"):
        assert claim not in chat, claim
    assert 'const WORKING = "Working…"' in chat
    # the trace panel puts the server's lines in as text
    panel = chat[chat.index("export function tracePanel"):chat.index("export function answerFooter")]
    assert 'el("li", { text: line })' in panel and "innerHTML" not in panel and "html:" not in panel


# ------------------------------------------------------------ retention: the last 5,000 conversations
def test_traces_are_kept_for_the_last_conversations_without_a_limit_per_conversation(tmp_path):
    log = TraceLog(tmp_path / "t.db", keep=3)
    n = [node("PERCEIVE", {"message": "x"}, {"route": "chatter"}, None, ["user"])]
    long_conversation = [log.record("c1", n) for _ in range(50)]          # no limit within a conversation
    others = {c: log.record(c, n) for c in ("c2", "c3")}
    assert log.counts() == {"conversations": 3, "traces": 52}
    newest = log.record("c4", n)                                          # a fourth conversation pushes out c1
    assert log.counts() == {"conversations": 3, "traces": 3}
    assert log.get(long_conversation[0]) is None and log.get(newest) and log.get(others["c2"])
    log.record("c2", n)                                                   # c2 is used again: now the most recent
    log.record("c5", n)                                                   # so c3 goes, not c2
    assert log.get(others["c3"]) is None and log.get(others["c2"])


def test_the_default_is_five_thousand_conversations(tmp_path):
    assert TraceLog(tmp_path / "t.db").keep == 5000


def test_bad_traces_are_refused(tmp_path):
    log = TraceLog(tmp_path / "t.db")
    with pytest.raises(ValueError):
        node("THINK", {}, {}, None, [])
    with pytest.raises(ValueError):
        log.record("../x", [])
    with pytest.raises(ValueError):
        log.record("c", [{"type": "THINK"}])
    assert NODE_TYPES == ("PERCEIVE", "RECALL", "INFER", "ANSWER")


def test_frustration_is_read_per_conversation(core):
    for text in ("it failed", "still broken"):
        upset = core.chat(text, conversation="web-upset")
    assert upset["frustration"]["frustrated"]
    assert not core.chat("it failed", conversation="web-calm")["frustration"]["frustrated"]


def test_restored_turns_keep_a_valid_trace_id_only():
    store = (JS / "store.js").read_text()
    assert re.search(r'typeof turn\.trace_id === "string" && /\^\[0-9a-f\]\{1,64\}\$/\.test\(turn\.trace_id\)', store)
