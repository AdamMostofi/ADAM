"""#92: prompt-time retrieval follows the current task and recorded links, and says how sure it is.

The fixture's prompts share no words with the records they need (the hard case for keyword retrieval). Core
retrieval uses no model, so it can only reach those records through the current task or recorded links. The
last prompt is about work nobody is doing, with nothing linking it to the prompt: it stays a miss, and the test
says so rather than hiding it.
"""
from __future__ import annotations

import pytest

from agent_memory import EventInput
from agent_memory.context import CONFIDENCE

S = "agent-1"


def put(store, path, text):
    store.append(EventInput(kind="file_change", session_id="dev", writer_id="w", payload=text.encode(),
                            summary_fields={"path": path}, path=path))


@pytest.fixture
def project(store):
    put(store, "src/auth/jwt.py", "def refresh_token(t):\n    return sign(t)\n")
    put(store, "src/auth/keys.py", "KEYS = {}\n")
    put(store, "src/billing/invoice.py", "class Invoice:\n    pass\n")
    r = {}
    r["bug"] = store.declare_entry("bug", "auth failure after token refresh", "dev", "w", topic="auth",
                                   concerns=["src/auth/jwt.py"])
    r["solution"] = store.declare_entry("solution", "re-sign with the rotated key", "dev", "w", topic="auth",
                                        fixes=[r["bug"]], concerns=["src/auth/keys.py"])
    r["decision"] = store.declare_entry("decision", "rotate refresh tokens on every use", "dev", "w", topic="auth",
                                        concerns=["src/auth/jwt.py"])
    r["billing"] = store.declare_entry("decision", "invoices are immutable once issued", "dev", "w",
                                       topic="billing", concerns=["src/billing/invoice.py"])
    store.declare_state("task", "harden sign-in", "dev", "w", status="in_progress", concerns=["src/auth/jwt.py"])
    store.declare_state("focus", "sign-in work", "dev", "w", concerns=["src/auth/jwt.py"])
    return r


# prompt -> the records it needs (none shares a word with the prompt)
CASES = [
    ("the login problem is back", ["bug", "solution"]),
    ("users get kicked out after a while", ["bug"]),
    ("why do we renew credentials each time", ["decision"]),
    ("money documents should never change", ["billing"]),   # unrelated to the current work: a known miss
]


def recall(store, project, detect):
    hits = total = 0
    per_case = []
    for n, (prompt, wanted) in enumerate(CASES):   # each prompt in its own session: can this prompt reach it?
        offered = {o["node"] for o in detect(f"{S}-{n}", prompt)}
        got = [w for w in wanted if project[w] in offered]
        hits += len(got)
        total += len(wanted)
        per_case.append((prompt, len(got), len(wanted)))
    return hits / total, per_case


def test_retrieval_reaches_records_through_the_current_task(store, project):
    score, per_case = recall(store, project, store.context.detect)
    by_prompt = {p: (got, want) for p, got, want in per_case}
    assert by_prompt["the login problem is back"] == (2, 2)
    assert by_prompt["users get kicked out after a while"] == (1, 1)
    assert by_prompt["why do we renew credentials each time"] == (1, 1)
    assert by_prompt["money documents should never change"] == (0, 1)   # honest: no link, no shared word
    assert score == pytest.approx(4 / 5)


def test_every_offer_says_how_sure_it_is_and_why(store, project):
    offers = store.context.detect(S, "the login problem is back")
    assert offers and len(offers) <= 8
    for o in offers:
        assert o["confidence"] in CONFIDENCE and o["reasons"]
        assert f"[{o['confidence']}]" in o["line"]
    bug = next(o for o in offers if o["node"] == project["bug"])
    assert bug["confidence"] == "task"
    assert any("(current work" in r for r in bug["reasons"])


def test_a_named_record_is_exact_and_its_links_are_linked(store, project):
    offers = {o["node"]: o for o in store.context.detect(S, f"look at {project['bug']}")}
    assert offers[project["bug"]]["confidence"] == "exact"
    assert offers[project["solution"]]["confidence"] in ("linked", "task")
    assert any(r.startswith("fixes ") for r in offers[project["solution"]]["reasons"])


def test_two_hops_reach_the_bug_a_named_file_fixed(store, project):
    # keys.py <- the solution concerns it <- the solution fixes the bug: two hops, read from the bug's side.
    offers = {o["node"]: o for o in store.context.detect(S, "keys.py", limit=20)}
    assert offers["artifact:src/auth/keys.py"]["confidence"] == "exact"
    assert f"concerns artifact:src/auth/keys.py" in offers[project["solution"]]["reasons"]
    assert f"{project['solution']} fixes it (2 hops)" in offers[project["bug"]]["reasons"]
    assert "artifact:src/auth/keys.py" not in [r.split()[-1] for r in offers[project["bug"]]["reasons"]]


def test_without_current_work_the_unworded_prompts_miss(store):
    # The same records, but nobody is working on anything: only words and links are left, and these prompts
    # have neither. This is the limit of retrieval without a model.
    put(store, "src/auth/jwt.py", "def refresh_token(t):\n    return sign(t)\n")
    bug = store.declare_entry("bug", "auth failure after token refresh", "dev", "w", topic="auth",
                              concerns=["src/auth/jwt.py"])
    assert bug not in {o["node"] for o in store.context.detect(S, "the login problem is back")}


def test_task_context_is_offered_once_per_session_and_again_after_compaction(store, project):
    first = {o["node"] for o in store.context.detect(S, "the login problem is back")}
    assert project["bug"] in first
    again = {o["node"] for o in store.context.detect(S, "and it is still back")}
    assert project["bug"] not in again          # offered already: no repeat cost every turn
    store.context.compacted(S)
    after = {o["node"] for o in store.context.detect(S, "the login problem is back")}
    assert project["bug"] in after              # the compaction dropped the earlier offer, so it comes back


def test_session_start_offers_the_current_tasks_records(store, project):
    text = store.context.assemble(S)["text"]
    assert project["bug"] in text and project["decision"] in text
    assert project["bug"] not in {o["node"] for o in store.context.detect(S, "the login problem is back")}
