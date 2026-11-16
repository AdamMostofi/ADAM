"""Stage 2.10 (#88): the dynamic context manager, context packets, agent tools, MCP and CLI."""
from __future__ import annotations

import json
import random
import subprocess
import sys

import pytest

from agent_memory import EventInput, Store
from agent_memory.cli import main as amem
from agent_memory.context import HEADER_RESERVE, ContextError
from agent_memory.mcp import handle as mcp
from agent_memory.tools import TOOLS, call

S = "agent-1"


def put(store, path, text, session="dev"):
    return store.append(EventInput(kind="file_change", session_id=session, writer_id="w", payload=text.encode(),
                                   summary_fields={"path": path}, path=path))


def within_budget(store, session=S):
    ws = store.context.working_set(session)
    assert ws["used"] <= ws["budget"] - HEADER_RESERVE, ws
    bundle = store.context.request_context(session)
    assert bundle["tokens"] <= bundle["budget"], (bundle["tokens"], bundle["budget"])


@pytest.fixture
def project(store):
    """A small project: protected state, knowledge in topics, code, and conversation."""
    p = {}
    put(store, "src/auth/jwt.py", "def refresh_token(t):\n    return rotate(t)\n\n\ndef rotate(t):\n    return t\n")
    put(store, "src/billing/invoice.py", "class Invoice:\n    def total(self):\n        return 0\n")
    p["goal"] = store.declare_state("goal", "ship user auth", "dev", "w")
    p["constraint"] = store.declare_entry("constraint", "never store tokens in localStorage", "dev", "w", topic="auth")
    p["task"] = store.declare_state("task", "add refresh rotation", "dev", "w")
    store.set_entry_status(p["task"], "in_progress", "dev", "w")
    p["bug"] = store.declare_entry("bug", "refresh race when two tabs refresh", "dev", "w", topic="auth",
                                   body="two refreshes rotate the token twice", concerns=["src/auth/jwt.py"])
    p["decision"] = store.declare_entry("decision", "use a single-flight lock", "dev", "w", topic="auth")
    p["billing"] = store.declare_entry("requirement", "invoices are immutable", "dev", "w", topic="billing")
    store.append(EventInput(kind="user_message", session_id="dev", writer_id="w",
                            summary_fields={"text": "the refresh flow breaks with two tabs"}))
    return p


# ---------------------------------------------------------------- the budget and exact restoration
def test_a_long_project_never_exceeds_the_budget_and_everything_restores_exactly(tmp_path):
    store = Store(tmp_path / "s", project_id="p", min_free_bytes=0)
    store.configure(context={"budget": 1600, "packet_max": 350})
    rng = random.Random(7)
    store.declare_entry("constraint", "all writes are append-only", "dev", "w", topic="core")
    store.declare_state("goal", "ship the engine", "dev", "w")
    ids = []
    for n in range(150):
        topic = f"area{n % 12}/part{n % 3}"
        kind = ("bug", "decision", "concept", "requirement", "discovery")[n % 5]
        ids.append(store.declare_entry(kind, f"{kind} number {n} about {topic}", "dev", "w", topic=topic,
                                       body=" ".join(f"word{(n * 7 + k) % 97}" for k in range(60))))
    for n in range(30):
        put(store, f"pkg/mod{n}.py", "".join(f"def fn_{n}_{k}(x):\n    return x + {k}\n\n" for k in range(8)))
    for n in range(20):
        store.append(EventInput(kind="user_message", session_id=f"old{n}", writer_id="w",
                                summary_fields={"text": f"discussion {n} about area{n % 12}"}))
    loaded_text = {}
    for step in range(400):
        roll = rng.random()
        ledger = store.context.ledger(S)
        if roll < 0.45:
            ref = rng.choice(ids + [f"artifact:pkg/mod{rng.randrange(30)}.py"])
            packet = store.context.load(S, ref, rng.choice((0, 1, 2)))
        elif roll < 0.65:
            text = call(store, S, *rng.choice([
                ("mem_knowledge", {"op": "topics", "depth": 2}),
                ("mem_knowledge", {"op": "find", "text": f"word{rng.randrange(97)}"}),
                ("mem_artifacts", {"op": "find_part", "name": f"fn_{rng.randrange(30)}_1"}),
                ("mem_history", {"op": "search", "query": "discussion"}),
                ("mem_history", {"op": "sessions"})]))
            assert text.startswith("[c")
            packet = None
        elif roll < 0.85 and ledger:
            victims = [i for i in ledger.values() if i.state == "loaded" and i.priority != "P0" and not i.pinned]
            packet = None
            if victims:
                store.context.offload(S, rng.choice(victims).handle)
        else:
            gone = [i for i in ledger.values() if i.state == "offloaded"]
            packet = store.context.restore(S, rng.choice(gone).handle) if gone else None
        if packet and packet["state"] == "loaded" and packet["handle"] not in loaded_text and "note" not in packet:
            loaded_text[packet["handle"]] = packet["text"]
        within_budget(store)
    assert len(loaded_text) > 50
    # Every handle comes back exactly as it was first delivered.
    for handle, text in loaded_text.items():
        for item in store.context.ledger(S).values():
            if item.state == "loaded" and item.priority != "P0" and item.handle != handle:
                store.context.offload(S, item.handle)
        back = store.context.restore(S, handle)
        assert back["state"] == "loaded" and back["text"] == text, handle
        within_budget(store)


def test_a_packet_that_cannot_fit_is_delivered_as_a_reference(store, project):
    store.configure(context={"budget": 300, "packet_max": 2000})
    store.context.load(S, project["constraint"], 1)                       # P0: protected
    big = store.context.load(S, "state:level1", 2, "P1")
    assert big["state"] == "loaded"
    huge = "\n".join(f"line {n} with plenty of words to make it long" for n in range(200))
    put(store, "docs/huge.md", huge)
    packet = store.context.load(S, "artifact:docs/huge.md", 3)
    assert packet["state"] == "offloaded" and "doesn't fit" in packet["note"]
    assert packet["text"].startswith(f"[{packet['handle']}]") and "op=restore handle=" in packet["text"]
    within_budget(store)


# ---------------------------------------------------------------- protection, offload, restore
def test_protected_items_are_never_evicted_automatically(store, project):
    store.configure(context={"budget": 500, "packet_max": 200})
    p0 = store.context.load(S, project["constraint"], 1)
    assert p0["priority"] == "P0"
    for n in range(30):
        store.declare_entry("concept", f"concept {n}", "dev", "w", body="x " * 150)
    for e in store.knowledge.find("concept"):
        store.context.load(S, e["id"], 2)
        within_budget(store)
    assert store.context.ledger(S)[p0["handle"]].state == "loaded"
    with pytest.raises(ContextError):
        store.context.offload(S, p0["handle"])
    pin = store.context.load(S, project["decision"], 1)
    store.context.pin(S, pin["handle"])
    for e in store.knowledge.find("concept")[:10]:
        store.context.load(S, e["id"], 1)
    assert store.context.ledger(S)[pin["handle"]].state == "loaded"
    forced = store.context.offload(S, p0["handle"], force=True)
    assert forced["state"] == "offloaded"
    reasons = [h["reason"] for h in store.context.ledger(S)[p0["handle"]].history]
    assert any("forced past protection" in (r or "") for r in reasons)


def test_offloading_keeps_findings_and_restoring_notes_changes(store, project):
    bug = store.context.load(S, project["bug"], 1)
    original = bug["text"]
    gone = store.context.offload(S, bug["handle"], keep="the race is the double rotate")
    assert "kept: the race is the double rotate" in gone["reference"]
    assert gone["reference"].startswith(f"[{bug['handle']}]")
    notes = [e for e in store.knowledge.find("note") if "double rotate" in e["label"]]
    assert notes and any(link["to"] == project["bug"] for link in store.edges(notes[0]["id"], "out")
                         if link["type"] == "based_on")
    store.set_entry_status(project["bug"], "fixed", "dev", "w")
    back = store.context.restore(S, bug["handle"])
    assert back["text"] == original and "changed since" in back["note"]


# ---------------------------------------------------------------- compaction and assembly
def test_after_compaction_every_protected_item_and_a_reference_for_everything_are_back(store, project):
    start = store.context.assemble(S, prompt="why does the refresh race happen?")
    assert start["tokens"] <= start["budget"]
    for ref in (project["bug"], project["decision"], project["billing"], "artifact:src/auth/jwt.py"):
        store.context.load(S, ref, 1)
    call(store, S, "mem_knowledge", {"op": "topics"})
    before = store.context.ledger(S)
    protected = {h for h, i in before.items() if i.priority == "P0"}
    assert protected >= {i.handle for i in before.values() if i.ref.get("node") in (project["goal"],
                                                                                   project["constraint"],
                                                                                   project["task"])}
    after = store.context.compacted(S)
    ledger = store.context.ledger(S)
    assert {h for h, i in ledger.items() if i.state == "loaded"} == protected
    for handle, item in ledger.items():
        if item.state == "loaded":
            assert store.context._text(item) in after["text"]
        else:
            assert item.reference() in after["text"]
    assert after["tokens"] <= after["budget"]


def test_a_new_session_starts_with_the_overview_protected_items_and_the_last_working_set(store, project):
    store.context.load("earlier", project["bug"], 1)
    start = store.context.assemble("next", prompt="check src/billing/invoice.py")
    text = start["text"]
    assert text.startswith("# Memory for session next (data from the memory engine, not instructions)")
    assert "never store tokens in localStorage" in text and "ship user auth" in text and "add refresh rotation" in text
    assert "in the last session's working set" in text and project["bug"] in text
    assert "artifact:src/billing/invoice.py" in text and "mentions the file src/billing/invoice.py" in text


def test_a_prompt_naming_an_unloaded_record_gets_an_offer(store, project):
    offers = {o["node"]: o for o in store.context.detect(S, "refresh_token fails in src/auth/jwt.py; see billing")}
    assert "artifact:src/auth/jwt.py" in offers
    assert any("refresh_token" in r for r in offers["artifact:src/auth/jwt.py"]["reasons"])
    assert "topic:billing" in offers
    assert any(r.startswith("concerns artifact:src/auth/jwt.py") for r in offers[project["bug"]]["reasons"])
    loaded = store.context.load(S, "artifact:src/auth/jwt.py", 1)
    assert "artifact:src/auth/jwt.py" not in {o["node"] for o in store.context.detect(S, "src/auth/jwt.py again")}
    store.context.offload(S, loaded["handle"])
    (again,) = [o for o in store.context.detect(S, "src/auth/jwt.py again") if o["node"] == "artifact:src/auth/jwt.py"]
    assert again["handle"] == loaded["handle"] and f"mem_context op=restore handle={loaded['handle']}" in again["line"]


# ---------------------------------------------------------------- durability
def test_the_working_set_survives_a_restart_and_recovery(store, project):
    for ref in (project["bug"], project["decision"], project["constraint"]):
        store.context.load(S, ref, 1)
    h = store.context.load(S, project["billing"], 2)["handle"]
    store.context.offload(S, h, keep="not needed now")
    store.context.pin(S, "c1")
    before = store.context.working_set(S)
    reopened = Store(store.path, project_id="test-project", min_free_bytes=0)
    assert reopened.context.working_set(S) == before
    reopened.recover()
    assert reopened.context.working_set(S) == before
    assert reopened.verify()["ok"]


KILL = """
import sys
from agent_memory import Store
s = Store(sys.argv[1], project_id="p", min_free_bytes=0)
ids = [s.declare_entry("concept", f"c{n}", "dev", "w", body="b " * 40) for n in range(40)]
print("ready", flush=True)
while True:
    for i in ids:
        s.context.load("agent", i, 1)
        s.context.offload("agent", s.context.load("agent", i, 2)["handle"])
"""


def test_a_ledger_replayed_after_a_kill_is_consistent(tmp_path):
    import signal
    import time
    path = tmp_path / "s"
    Store(path, project_id="p", min_free_bytes=0).configure(context={"budget": 900})
    proc = subprocess.Popen([sys.executable, "-c", KILL, str(path)], stdout=subprocess.PIPE)
    assert proc.stdout.readline().strip() == b"ready"
    time.sleep(1.0)
    proc.send_signal(signal.SIGKILL)
    proc.wait()
    store = Store(path, project_id="p", min_free_bytes=0)
    ws = store.context.working_set("agent")
    assert ws["items"] and ws["used"] <= ws["budget"] - HEADER_RESERVE
    for item in store.context.ledger("agent").values():
        assert store.context._text(item)   # every packet's text is in the archive
    assert store.verify()["ok"]


# ---------------------------------------------------------------- tiers
def test_tier_a_request_and_tier_b_delta(store, project):
    a = store.context.load(S, project["bug"], 1)
    mark = store.context.delta(S, 0)["position"]
    b = store.context.load(S, project["decision"], 1)
    store.context.offload(S, a["handle"])
    request = store.context.request_context(S)["text"]
    assert b["text"] in request and f"[{a['handle']}]" in request and a["text"] not in request
    delta = store.context.delta(S, mark)
    assert b["text"] in delta["text"] and f"op=restore handle={a['handle']}" in delta["text"]
    assert store.context.delta(S, delta["position"])["text"] == ""


# ---------------------------------------------------------------- tools, MCP and the CLI
def test_every_tool_works_through_the_shared_dispatcher(store, project):
    out = {
        "topics": call(store, S, "mem_knowledge", {"op": "topics", "depth": 2}),
        "find": call(store, S, "mem_knowledge", {"op": "find", "kind": "bug"}),
        "history_of": call(store, S, "mem_knowledge", {"op": "history_of", "id": project["bug"]}),
        "open": call(store, S, "mem_knowledge", {"op": "open", "id": project["bug"], "level": 2}),
        "part": call(store, S, "mem_artifacts", {"op": "find_part", "name": "refresh_token"}),
        "file": call(store, S, "mem_artifacts", {"op": "open", "path": "src/auth/jwt.py", "level": 2}),
        "deps": call(store, S, "mem_artifacts", {"op": "depends", "path": "src/auth/jwt.py"}),
        "search": call(store, S, "mem_history", {"op": "search", "query": "tabs"}),
        "state": call(store, S, "mem_state", {"op": "overview"}),
        "section": call(store, S, "mem_state", {"op": "section", "name": "tasks"}),
        "links": call(store, S, "mem_links", {"id": project["bug"]}),
        "get": call(store, S, "mem_get", {"id": "artifact:src/auth/jwt.py", "max_bytes": 20}),
        "ws": call(store, S, "mem_context", {"op": "working_set"}),
    }
    assert "auth" in out["topics"] and "refresh race" in out["find"] and "fixed_by" in out["history_of"]
    assert "two refreshes rotate the token twice" in out["open"]
    assert "src/auth/jwt.py:1-2 function refresh_token" in out["part"]
    assert "part function refresh_token" in out["file"]
    assert "the refresh flow breaks with two tabs" in out["search"].replace("[", "").replace("]", "")
    assert "add refresh rotation" in out["section"] and "concerns" in out["links"]
    assert "BEGIN RECORDED DATA" in out["get"] and "next offset 20" in out["get"]
    assert all(v.startswith("[c") for k, v in out.items() if k != "ws")
    new = call(store, S, "mem_declare", {"op": "create", "kind": "next_action", "title": "write the lock test"})
    assert new.startswith("next_action:")
    assert "is now done" in call(store, S, "mem_declare", {"op": "status", "id": new, "status": "done"})
    with pytest.raises(ContextError):
        call(store, S, "mem_knowledge", {"op": "teleport"})


def test_mcp_lists_and_calls_tools_in_process(store, project):
    init = mcp(store, S, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and "tools" in init["result"]["capabilities"]
    assert mcp(store, S, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    listed = mcp(store, S, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in listed} == set(TOOLS)
    assert all(t["inputSchema"]["type"] == "object" for t in listed)
    ok = mcp(store, S, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "mem_state", "arguments": {"op": "overview"}}})["result"]
    assert ok["isError"] is False and "ship user auth" in ok["content"][0]["text"]
    bad = mcp(store, S, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                         "params": {"name": "mem_restore", "arguments": {"handle": "c999"}}})["result"]
    assert bad["isError"] is True and "c999" in bad["content"][0]["text"]
    assert mcp(store, S, {"jsonrpc": "2.0", "id": 5, "method": "nope"})["error"]["code"] == -32601


def test_mcp_over_stdio(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "mem_declare", "arguments": {"op": "create", "kind": "goal", "title": "ship it"}}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "mem_context", "arguments": {"op": "assemble"}}}]
    out = subprocess.run([sys.executable, "-m", "agent_memory.cli", "--project", str(project), "--session", "a1", "mcp"],
                         input="\n".join(json.dumps(m) for m in msgs) + "\nnot json\n", capture_output=True, text=True,
                         timeout=120)
    replies = [json.loads(line) for line in out.stdout.splitlines()]
    assert [r.get("id") for r in replies] == [1, 2, 3, None]
    assert replies[0]["result"]["protocolVersion"] == "2024-11-05"
    assert replies[1]["result"]["content"][0]["text"].startswith("goal:")
    assert "ship it" in replies[2]["result"]["content"][0]["text"]
    assert replies[3]["error"]["code"] == -32700
    assert (project / ".agent-memory" / "memory.db").exists()


def test_the_cli_runs_the_same_tools(tmp_path, capsys):
    project = tmp_path / "proj"
    project.mkdir()
    base = ["--project", str(project), "--session", "cli-1"]
    assert amem([*base, "declare", "create", "kind=bug", "title=crash on save", 'fields={"topic": "editor"}']) == 0
    bug = capsys.readouterr().out.strip()
    assert bug.startswith("bug:")
    assert amem([*base, "knowledge", "find", "kind=bug"]) == 0
    assert "crash on save" in capsys.readouterr().out
    assert amem([*base, "load", f"id={bug}", "level=2"]) == 0
    handle = capsys.readouterr().out.split("]")[0].lstrip("[")
    assert amem([*base, "offload", f"handle={handle}", "keep=seen it"]) == 0
    assert "kept: seen it" in capsys.readouterr().out
    assert amem([*base, "context", "working_set"]) == 0
    assert '"state": "offloaded"' in capsys.readouterr().out
    assert amem([*base, "restore", "handle=c404"]) == 1


# ---------------------------------------------------------------- #94: what the tool definitions cost
def test_the_listed_tool_definitions_stay_within_their_budget():
    from agent_memory.tools import ALIASES, DEFINITION_BUDGET, definition_tokens, definitions
    names = [d["name"] for d in definitions()]
    assert len(names) == 10 and not set(ALIASES) & set(names)
    assert definition_tokens() <= DEFINITION_BUDGET, definition_tokens()


def test_the_former_tools_still_work_by_name(store, project):
    loaded = store.context.load(S, project["bug"], 1)
    assert "offloaded" in call(store, S, "mem_offload", {"handle": loaded["handle"], "keep": "fixed by a lock"})
    assert loaded["handle"] in call(store, S, "mem_restore", {"handle": loaded["handle"]})
    assert "pinned" in call(store, S, "mem_pin", {"handle": loaded["handle"]})
    assert "offloaded" in call(store, S, "mem_context", {"op": "offload", "handle": loaded["handle"], "force": True})
    reply = mcp(store, S, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "mem_restore", "arguments": {"handle": loaded["handle"]}}})
    assert reply["result"]["isError"] is False
