"""#91: protected context larger than its budget is ranked by importance, referenced, and never silently lost."""
from __future__ import annotations

import pytest

from agent_memory import EventInput
from agent_memory.tools import call

S = "agent-1"
SESSION_BUDGET = 2300   # what the Claude Code adapter gives session start


def conflict(store, title):
    return "conflict:" + store.append(EventInput(kind="conflict", session_id="dev", writer_id="reconciler",
                                                 summary_fields={"op": "create", "title": title})).event_id


@pytest.fixture
def big(store):
    """50 active constraints and 80 open conflicts, with a current task on auth."""
    ids = {"global": [], "auth": [], "billing": [], "conflicts": []}
    for i in range(10):
        ids["global"].append(store.declare_entry("constraint", f"global rule {i}: every write is append-only",
                                                 "dev", "w"))
    for i in range(20):
        ids["auth"].append(store.declare_entry("constraint", f"auth rule {i}: tokens never leave the server",
                                               "dev", "w", topic="auth/jwt"))
    for i in range(20):
        ids["billing"].append(store.declare_entry("constraint", f"billing rule {i}: invoices are immutable",
                                                  "dev", "w", topic="billing"))
    for i in range(80):
        ids["conflicts"].append(conflict(store, f"conflicting edits to module_{i}.py"))
    ids["task"] = store.declare_state("task", "add refresh rotation", "dev", "w", status="in_progress")
    ids["focus"] = store.declare_state("focus", "auth work", "dev", "w", filed_under=["auth"])
    ids["blocked"] = store.declare_state("task", "migrate the billing tables", "dev", "w", status="blocked")
    return ids


def tiers(store):
    return {r["node"]: r["tier"] for r in store.context.protected()}


def test_protected_records_are_ranked_in_tiers(store, big):
    t = tiers(store)
    assert {t[i] for i in big["global"]} == {1}
    assert {t[i] for i in big["auth"]} == {2}        # under auth/jwt; the focus is on auth
    assert t[big["task"]] == 2                         # in progress: the current task
    assert {t[i] for i in big["conflicts"]} == {3}
    assert t[big["blocked"]] == 3
    assert {t[i] for i in big["billing"]} == {4}      # scoped to a topic nobody is working on
    ranked = [r["tier"] for r in store.context.protected()]
    assert ranked == sorted(ranked)


def check(store, bundle):
    ranked = store.context.protected()
    loaded = {i.ref.get("node") for i in store.context.ledger(S).values() if i.state == "loaded"}
    text = bundle["text"]
    assert bundle["tokens"] <= SESSION_BUDGET
    # Every protected record is in full, referenced, or counted.
    shown = [r for r in ranked if r["node"] in loaded or r["node"] in text]
    hidden = len(ranked) - len(shown)
    assert hidden == bundle["protected"]["not_shown"]
    if hidden:
        assert f"+{hidden} more protected records not shown: mem_context protected lists them all" in text
    # Tiers are respected: nothing in full ranks below a record that was only referenced or counted.
    worst_full = max((r["tier"] for r in ranked if r["node"] in loaded), default=0)
    best_missing = min((r["tier"] for r in ranked if r["node"] not in loaded), default=9)
    assert worst_full <= best_missing
    # References keep rank order too: the shown ones are a prefix of the ranking.
    not_full = [r for r in ranked if r["node"] not in loaded]
    referenced = [r for r in not_full if r["node"] in text]
    assert referenced == not_full[:len(referenced)]
    return loaded, ranked


def test_fifty_constraints_and_eighty_conflicts_fit_the_session_budget(store, big):
    bundle = store.context.assemble(S, budget=SESSION_BUDGET)
    loaded, ranked = check(store, bundle)
    assert set(big["global"]) <= loaded                       # the top tier is in full
    assert "## Protected, not loaded in full (over the context budget)" in bundle["text"]
    assert bundle["protected"]["referenced"] > 0
    # Records that don't fit cost no events: only what was loaded is in the ledger.
    loads = [e for e in store.events(session_id=S) if e.kind == "context_load"]
    assert len(loads) < len(ranked)


def test_the_same_holds_after_compaction(store, big):
    store.context.assemble(S, budget=SESSION_BUDGET)
    bundle = store.context.compacted(S, budget=SESSION_BUDGET)
    loaded, _ = check(store, bundle)
    assert set(big["global"]) <= loaded


def test_a_large_budget_loads_everything_in_full(store, big):
    bundle = store.context.assemble(S)    # the default budget, 12,000 tokens
    ranked = store.context.protected()
    loaded = {i.ref.get("node") for i in store.context.ledger(S).values() if i.state == "loaded"}
    assert bundle["tokens"] <= bundle["budget"]
    assert bundle["protected"]["not_shown"] == 0
    assert all(r["node"] in loaded or r["node"] in bundle["text"] for r in ranked)


def test_a_finished_task_is_not_brought_back_after_compaction(store, big):
    store.context.assemble(S)
    store.set_status("task", big["task"], "done", "dev", "w")
    assert big["task"] not in tiers(store)
    store.context.compacted(S)
    loaded = {i.ref.get("node") for i in store.context.ledger(S).values() if i.state == "loaded"}
    assert big["task"] not in loaded


def test_the_protected_tool_lists_every_protected_record_ranked(store, big):
    store.context.assemble(S, budget=SESSION_BUDGET)
    out = call(store, S, "mem_context", {"op": "protected"}).splitlines()
    assert len(out) == len(store.context.protected()) == 10 + 20 + 20 + 80 + 2
    assert out[0].startswith("1. [tier 1: global constraint or objective]")
    assert any(" - loaded" in line for line in out) and any(" - mem_load " in line for line in out)


def test_nothing_protected_says_so(store):
    assert call(store, S, "mem_context", {"op": "protected"}) == "(nothing is protected)"
