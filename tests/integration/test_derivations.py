"""Proofs as structured derivation records (Stage 1.4, #30).

DR4.1: the record is the truth; English is a projection. Every derived fact
in the engine and in the store carries derivation records naming its rule,
the rule's version, every premise and its confidence, and any fact can be
walked back to the inputs it rests on.
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings

from interface.core import ADAMCore
from interface.web.app import create_app
from kernel.engine import InferenceEngine
from kernel.facts import Derivation, Fact, Source
from kernel.rules import KERNEL_RULES_VERSION
from learning.engine import LearningEngine
from memory.exact_store import SCHEMA_VERSION, ExactStore, UnderivedFactError
from memory.system import MemorySystem
from tests.integration.test_prove_agreement import fact_sets

SOCRATES = [Fact("man", "implies", "mortal", confidence=0.8), Fact("socrates", "instance_of", "man")]


def engine_with(facts):
    engine = InferenceEngine()
    engine.add_facts(facts)
    engine.infer()
    return engine


def memory_at(path) -> MemorySystem:
    return MemorySystem(db_path=str(Path(path) / "facts.db"), lance_path=str(Path(path) / "vectors.db"))


# --------------------------------------------------- acceptance criteria


def test_the_socrates_record_names_both_premises():
    engine = engine_with(SOCRATES)
    record = engine.beliefs[("socrates", "instance_of", "mortal")].proofs[0]
    assert record.rule == "inheritance_implies"
    assert set(record.premises) == {("man", "implies", "mortal"), ("socrates", "instance_of", "man")}
    assert record.confidence == pytest.approx(0.8)
    assert record.rule_version == KERNEL_RULES_VERSION


def test_the_socrates_record_is_stored_with_both_premises(tmp_path):
    engine = engine_with(SOCRATES)
    memory = memory_at(tmp_path)
    [fact_id] = memory.store_beliefs(engine, [("socrates", "instance_of", "mortal")])
    [derivation] = memory.exact.derivations_of(fact_id)
    premises = {str(memory.exact.get(i)) for i in derivation["premise_ids"]}
    assert premises == {"man implies mortal", "socrates instance_of man"}
    assert derivation["rule"] == "inheritance_implies"
    assert derivation["confidence"] == pytest.approx(0.8)


STORE_SETTINGS = settings(max_examples=60, deadline=None,
                          suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture])


@STORE_SETTINGS
@given(fact_sets)
def test_every_stored_derived_fact_walks_back_to_inputs(facts):
    engine = engine_with(facts)
    with tempfile.TemporaryDirectory() as tmp:
        memory = memory_at(tmp)
        memory.store_beliefs(engine, list(engine.beliefs))
        store = memory.exact
        assert store.underived() == []
        for fact_id, fact in store.get_all_with_ids():
            steps = store.trace(fact_id)
            assert steps is not None, f"{fact} has no path to its inputs"
            assert steps[-1]["id"] == fact_id
            seen = set()
            for step in steps:
                if step["derivation"] is None:
                    assert step["fact"].source != Source.DEDUCED  # walks end only at inputs
                else:
                    assert set(step["derivation"]["premise_ids"]) <= seen  # premises come first
                seen.add(step["id"])
        # Storing everything again adds no row and no derivation.
        rows, derivations = store.count(), store.count_derivations()
        memory.store_beliefs(engine, list(engine.beliefs))
        assert (store.count(), store.count_derivations()) == (rows, derivations)


def test_repeating_a_derivation_adds_no_row_and_no_evidence(tmp_path):
    engine = engine_with(SOCRATES)
    key = ("socrates", "instance_of", "mortal")
    evidence = engine.beliefs[key].evidence
    engine.add_facts(SOCRATES)  # given again
    engine.infer()
    assert engine.beliefs[key].evidence == evidence
    assert len(engine.beliefs[key].proofs) == 1
    memory = memory_at(tmp_path)
    for _ in range(3):
        memory.store_beliefs(engine, [key])
    assert memory.exact.count_derivations() == 1


def test_multi_word_terms_round_trip_exactly(tmp_path):
    facts = [Fact("new york", "instance_of", "big city"), Fact("big city", "subclass_of", "place with traffic")]
    engine = engine_with(facts)
    memory = memory_at(tmp_path)
    [fact_id] = memory.store_beliefs(engine, [("new york", "instance_of", "place with traffic")])
    steps = memory.explain(fact_id)
    assert [(s["fact"].subject, s["fact"].predicate, s["fact"].object) for s in steps] == [
        ("big city", "subclass_of", "place with traffic"),
        ("new york", "instance_of", "big city"),
        ("new york", "instance_of", "place with traffic"),
    ]
    patterns = LearningEngine(skills_dir=str(tmp_path / "skills")).learn_from_belief(
        engine.beliefs[("new york", "instance_of", "place with traffic")], engine)
    assert {str(p) for p in patterns[0].premises} == {"new york instance_of big city",
                                                       "big city subclass_of place with traffic"}


# -------------------------------------------------------- store rules


def test_a_derived_fact_cannot_be_stored_without_a_derivation(tmp_path):
    memory = memory_at(tmp_path)
    with pytest.raises(UnderivedFactError):
        memory.store(Fact("x", "instance_of", "y", source=Source.DEDUCED))
    with pytest.raises(UnderivedFactError):
        memory.exact.store_derived([(Fact("x", "instance_of", "y", source=Source.DEDUCED), [])])
    assert memory.count() == 0


def test_a_failed_write_stores_nothing(tmp_path):
    store = ExactStore(str(tmp_path / "facts.db"))
    good = Fact("a", "subclass_of", "b")
    derived_premise = Fact("p", "instance_of", "q", source=Source.DEDUCED)
    entries = [(good, []), (Fact("a", "subclass_of", "c", source=Source.DEDUCED),
                            [{"rule": "r", "rule_version": "1", "confidence": 1.0,
                              "premises": [good, derived_premise]}])]
    with pytest.raises(UnderivedFactError):
        store.store_derived(entries)
    assert store.count() == 0 and store.count_derivations() == 0


def test_a_schema_1_store_is_migrated_in_place(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE facts (id INTEGER PRIMARY KEY AUTOINCREMENT, fact_key TEXT NOT NULL UNIQUE,
                        subject TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT NOT NULL,
                        confidence REAL DEFAULT 1.0, source TEXT DEFAULT 'user', timestamp REAL,
                        fact_text TEXT, proof_chain TEXT, metadata TEXT)""")
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")
        conn.execute("INSERT INTO facts (fact_key, subject, predicate, object, source, fact_text, proof_chain) "
                     "VALUES ('k', 'old', 'is', 'derived', 'deduced', 'old is derived', ?)",
                     (json.dumps(["[old] text proof"]),))
        conn.execute("PRAGMA user_version = 1")
    store = ExactStore(str(path))
    assert store.count() == 1
    assert store.meta()["schema_version"] == str(SCHEMA_VERSION) and "migrated_from_1" in store.meta()
    assert store.count_derivations() == 0
    assert store.underived() == [1]  # reported, never deleted
    assert store.get_with_proof(1)[1] == []  # no derivation: nothing to render
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_proof_text_is_rendered_from_the_records(tmp_path):
    engine = engine_with(SOCRATES)
    memory = memory_at(tmp_path)
    [fact_id] = memory.store_beliefs(engine, [("socrates", "instance_of", "mortal")])
    _, lines = memory.exact.get_with_proof(fact_id)
    assert lines[-1] == "[inheritance_implies] man implies mortal + socrates instance_of man -> socrates instance_of mortal"
    assert all(line.startswith("[given] ") for line in lines[:-1])
    with sqlite3.connect(memory.exact.db_path) as conn:
        assert conn.execute("SELECT proof_chain FROM facts WHERE id = ?", (fact_id,)).fetchone()[0] is None


# ---------------------------------------------------- engine walk-back


def test_explain_ends_at_given_facts_and_orders_premises_first():
    engine = engine_with([Fact("tweety", "instance_of", "penguin"), Fact("penguin", "subclass_of", "bird"),
                          Fact("bird", "subclass_of", "animal")])
    steps = engine.explain("tweety", "instance_of", "animal")
    explained = set()
    for key, derivation in steps:
        if derivation is None:
            assert engine.beliefs[key].given
        else:
            assert set(derivation.premises) <= explained
        explained.add(key)
    assert steps[-1][0] == ("tweety", "instance_of", "animal")
    assert engine.render_explanation("tweety", "instance_of", "animal")[-1].endswith("-> tweety instance_of animal")


def test_explain_is_not_trapped_by_cycles():
    # a = b and b = a support each other; x is red only through the given a = b.
    engine = engine_with([Fact("a", "equals", "b"), Fact("a", "instance_of", "red")])
    steps = engine.explain("b", "instance_of", "red")
    assert steps is not None and steps[-1][0] == ("b", "instance_of", "red")
    assert all(engine.beliefs[k].given for k, d in steps if d is None)


def test_explain_of_a_given_fact_is_the_fact_itself():
    engine = engine_with(SOCRATES)
    assert engine.explain("man", "implies", "mortal") == [(("man", "implies", "mortal"), None)]
    assert engine.explain("nobody", "instance_of", "here") is None


def test_a_derivation_keeps_its_best_confidence_when_a_premise_rises():
    engine = engine_with([Fact("x", "instance_of", "a", confidence=0.5), Fact("a", "subclass_of", "b")])
    engine.add_fact(Fact("x", "instance_of", "a", confidence=0.9))
    engine.infer()
    [record] = engine.beliefs[("x", "instance_of", "b")].proofs
    assert record.confidence == pytest.approx(0.9)


def test_records_are_plain_data_for_the_thought_trace():
    engine = engine_with(SOCRATES)
    record = engine.beliefs[("socrates", "instance_of", "mortal")].proofs[0]
    data = record.to_record(("socrates", "instance_of", "mortal"))
    assert data == {"conclusion": ["socrates", "instance_of", "mortal"], "rule": "inheritance_implies",
                    "rule_version": KERNEL_RULES_VERSION,
                    "premises": [["man", "implies", "mortal"], ["socrates", "instance_of", "man"]],
                    "confidence": pytest.approx(0.8)}
    assert Derivation("r", (("a", "b", "c"), ("d", "e", "f")), 1.0).identity == \
        Derivation("r", (("d", "e", "f"), ("a", "b", "c")), 0.5).identity


# --------------------------------------------------------------- chat and web


class QuietMouth:
    def format_response(self, message, params, context=""):
        return "ok"


def test_chat_stores_derived_facts_with_derivations(tmp_path):
    core = ADAMCore(db_path=str(tmp_path / "web.db"), lance_path=str(tmp_path / "web.vec"), mouth=QuietMouth())
    core.add_fact("socrates", "instance_of", "man")
    core.add_fact("man", "subclass_of", "mortal")
    core.chat("tell me about socrates")
    store = core.memory.exact
    derived = [i for i, f in store.get_all_with_ids() if f.source == Source.DEDUCED]
    assert derived, "chat should have stored the derived facts"
    assert store.underived() == []


def test_trace_endpoint_walks_back_to_inputs(tmp_path):
    core = ADAMCore(db_path=str(tmp_path / "web.db"), lance_path=str(tmp_path / "web.vec"))
    engine = engine_with(SOCRATES)
    [fact_id] = core.memory.store_beliefs(engine, [("socrates", "instance_of", "mortal")])
    with create_app(core).test_client() as client:
        steps = client.get(f"/api/facts/{fact_id}/trace").get_json()
        assert steps[-1]["rule"] == "inheritance_implies"
        assert {s["source"] for s in steps if s["rule"] is None} == {"user"}
        listed = client.get("/api/facts").get_json()
        assert any(f["id"] == fact_id for f in listed)
        assert client.get("/api/facts/99999/trace").status_code == 404
