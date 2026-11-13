"""A restarted ADAM knows what it knew before (Stage 1.6, #36).

DS1: SQLite stays the source of truth. At startup the engine and the graph
are rebuilt from it; nothing else is persisted as a second truth.
"""
from __future__ import annotations

import sqlite3

from interface.core import ADAMCore
from interface.web.app import create_app
from kernel.facts import Fact, Source


class QuietMouth:
    def format_response(self, message, params, context=""):
        return "ok"


def start(tmp_path) -> ADAMCore:
    return ADAMCore(db_path=str(tmp_path / "adam_memory.db"), lance_path=str(tmp_path / "adam_vectors.db"),
                    mouth=QuietMouth())


def teach(core: ADAMCore) -> None:
    core.add_fact("socrates", "instance_of", "man")
    core.add_fact("man", "subclass_of", "mortal")
    core.add_fact("mortal", "subclass_of", "being")
    core.add_fact("rex", "is", "dog")
    core.chat("tell me about socrates")


def snapshot(core: ADAMCore) -> dict:
    db = core.memory.exact.db_path
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT id, subject, predicate, object, source FROM facts ORDER BY id").fetchall()
        derivations = conn.execute(
            "SELECT conclusion_id, rule, premise_ids FROM derivations ORDER BY id").fetchall()
    edges = sorted((u, v, d.get("predicate"), d.get("source")) for u, v, d in core.memory.graph.get_all_edges())
    beliefs = {k: (b.given, frozenset(b.derivations)) for k, b in core.engine.beliefs.items()}
    return {"rows": rows, "derivations": derivations, "edges": edges, "beliefs": beliefs,
            "vectors": core.memory.semantic.count()}


def test_facts_graph_and_proofs_match_after_a_restart(tmp_path):
    first = start(tmp_path)
    teach(first)
    before = snapshot(first)
    assert before["edges"] and before["derivations"]
    after = snapshot(start(tmp_path))
    assert after == before


def test_three_restarts_add_zero_rows(tmp_path):
    teach(start(tmp_path))
    counts = []
    for _ in range(3):
        core = start(tmp_path)
        store = core.memory.exact
        counts.append((store.count(), store.count_derivations(), core.memory.semantic.count(),
                       len(core.memory.graph.get_all_edges())))
    assert counts[0] == counts[1] == counts[2]


def test_the_graph_api_is_populated_after_a_restart(tmp_path):
    teach(start(tmp_path))
    with create_app(start(tmp_path)).test_client() as client:
        graph = client.get("/api/graph").get_json()
    assert graph["nodes"] and graph["edges"]


def test_the_engine_knows_derived_facts_after_a_restart(tmp_path):
    teach(start(tmp_path))
    core = start(tmp_path)
    assert core.engine.query("socrates", "instance_of", "being")
    assert core.engine.explain("socrates", "instance_of", "being") is not None


def test_a_classified_fact_stays_classified_after_a_restart(tmp_path):
    core = start(tmp_path)
    teach(core)
    core.add_fact("dog", "subclass_of", "animal")
    core.classify_fact("rex", "is", "dog", "instance_of")
    before = snapshot(core)
    restarted = start(tmp_path)
    assert restarted.ambiguous_facts() == []
    assert restarted.engine.query("rex", "instance_of", "animal")
    assert not restarted.engine.query("rex", "is", "dog")
    assert snapshot(restarted)["edges"] == before["edges"]
    assert restarted.memory.count() == core.memory.count()  # the original row is kept, marked superseded


def test_compiled_skills_give_the_same_beliefs_after_a_restart(tmp_path):
    core = start(tmp_path)
    core.learning.compile_skill("friendship", "social",
                                [Fact("?a", "likes", "?b"), Fact("?b", "likes", "?a")],
                                Fact("?a", "friends", "?b"), 0.9)
    core.engine.add_rule(core.learning.skill_compiler.rules()[0])
    core.add_fact("ann", "likes", "bob")
    core.add_fact("bob", "likes", "ann")
    core.chat("who are friends")
    before = snapshot(core)
    assert core.engine.query("ann", "friends", "bob")
    assert snapshot(start(tmp_path)) == before


def test_origins_survive_a_restart(tmp_path):
    core = start(tmp_path)
    for origin in ("book A", "book B"):
        fact = Fact("x", "instance_of", "safe", origin=origin)
        core.engine.add_fact(fact)
        core.memory.store(fact)
    restarted = start(tmp_path)
    assert restarted.engine.attribution("x", "instance_of", "safe") == ["book A", "book B"]


def test_recalled_derived_facts_do_not_become_given(tmp_path):
    core = start(tmp_path)
    teach(core)
    core.chat("socrates mortal being")
    derived = core.engine.beliefs[("socrates", "instance_of", "mortal")]
    assert not derived.given


def test_startup_cost_is_recorded(tmp_path):
    teach(start(tmp_path))
    core = start(tmp_path)
    startup = core.memory.startup
    assert startup["given_facts"] == 4 and startup["rows"] >= 4
    assert startup["seconds"] >= 0 and "inferred" in startup


def test_startup_is_read_only_and_the_next_write_stores_new_conclusions(tmp_path):
    core = start(tmp_path)
    # Facts stored without inference, as if the previous session stopped before inferring.
    core.memory.store(Fact("a", "subclass_of", "b"))
    core.memory.store(Fact("b", "subclass_of", "c"))
    db = tmp_path / "adam_memory.db"
    with sqlite3.connect(db) as conn:
        before = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    restarted = start(tmp_path)
    assert restarted.engine.query("a", "subclass_of", "c")  # known in memory at once
    assert restarted.memory.count() == before  # but startup wrote nothing
    assert restarted.memory.startup["not_yet_stored"] == 1
    restarted.chat("tell me about a")  # the next write stores it, with its derivation
    rows = restarted.memory.count()
    assert rows == before + 1 and restarted.memory.exact.underived() == []
    assert any(f.source == Source.DEDUCED for _, f in restarted.memory.exact.get_all_with_ids())
    assert start(tmp_path).memory.count() == rows


def test_a_restart_leaves_the_store_files_unchanged(tmp_path):
    import hashlib
    teach(start(tmp_path))
    start(tmp_path)  # a first restart may migrate the schema; after that, starting must not write

    def digest():
        return {name: hashlib.sha1((tmp_path / name).read_bytes()).hexdigest()
                for name in ("adam_memory.db", "adam_vectors.db")}

    before = digest()
    start(tmp_path)
    start(tmp_path)
    assert digest() == before
