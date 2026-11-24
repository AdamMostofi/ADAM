"""The storage contract, run against every store (Stage 4.1, #46).

Each test runs once on the engine store (the default) and once on the original SQLite store. A store passes
when it behaves the same way on everything ADAM relies on: fact identity and merging, derivations and traces,
supersession, origins, lookups, counts, and surviving a reopen. Records (sources, passages, skills, traces)
are the engine store's alone; the original store must refuse them clearly.
"""
from __future__ import annotations

import pytest

from kernel.facts import Fact, Source
from memory.engine_store import EngineStore
from memory.exact_store import ExactStore
from memory.store_contract import FactStore, RecordsNotSupported, UnderivedFactError, fact_key

BACKENDS = ("engine", "exact")


def opener(backend, tmp_path):
    if backend == "engine":
        return lambda: EngineStore(tmp_path / "facts.engine")
    return lambda: ExactStore(str(tmp_path / "facts.db"))


@pytest.fixture(params=BACKENDS)
def make(request, tmp_path):
    return opener(request.param, tmp_path)


@pytest.fixture
def store(make):
    return make()


def given(s, p, o, **kw):
    return Fact(s, p, o, **kw)


def derived(s, p, o, **kw):
    return Fact(s, p, o, source=Source.DEDUCED, **kw)


def syllogism(store):
    man = given("socrates", "instance_of", "man")
    mortal = given("man", "subclass_of", "mortal")
    conclusion = derived("socrates", "instance_of", "mortal", confidence=0.9)
    [(cid, created)] = store.store_derived([(conclusion, [{"rule": "inheritance", "rule_version": "1",
                                                            "confidence": 0.9, "premises": [man, mortal]}])])
    return cid, created, man, mortal


# ------------------------------------------------------------ facts
def test_every_store_follows_the_contract(store):
    assert isinstance(store, FactStore) and store.backend in BACKENDS
    assert store.meta()


def test_a_fact_is_stored_once_whatever_its_case_or_spacing(store):
    first, created = store.upsert(given("Socrates", "is", "a  man", confidence=0.5, timestamp=10.0, origin="plato"))
    again, created_again = store.upsert(given("socrates", "IS", "a man", confidence=0.8, timestamp=5.0,
                                              origin="xenophon"))
    assert (first, created, again, created_again) == (1, True, 1, False)
    fact = store.get(1)
    assert fact.confidence == 0.8 and fact.timestamp == 10.0     # the higher confidence, the newer timestamp
    assert fact.subject == "Socrates"                             # the first spelling is kept
    assert store.origins_of(1) == ["plato", "xenophon"] and store.all_origins() == {1: ["plato", "xenophon"]}
    assert store.count() == 1 and store.has(given("SOCRATES", "is", "a man"))
    assert fact_key(given("socrates", "is", "a man")) in store.all_keys()


def test_the_same_terms_from_another_source_are_another_fact(store):
    store.upsert(given("a", "is", "b"))
    store.upsert(given("a", "is", "b", source=Source.LEARNED))
    assert store.count() == 2 and store.count_by_source() == {"user": 1, "learned": 1}


def test_ids_count_up_in_the_order_facts_are_first_stored(store):
    ids = [store.upsert(given(f"s{i}", "is", "x"))[0] for i in range(5)]
    assert ids == [1, 2, 3, 4, 5]
    assert [i for i, _ in store.get_all_with_ids()] == ids and len(store.get_all()) == 5
    assert store.get(99) is None


def test_a_proof_chain_is_kept_and_never_replaced(store):
    fid = store.store(given("a", "is", "b"), ["first proof"])
    store.store(given("a", "is", "b"), ["second proof"])
    assert store.get_with_proof(fid) == (store.get(fid), ["first proof"])
    plain = store.store(given("c", "is", "d"))
    assert store.get_with_proof(plain)[1] == []


def test_lookups_find_exact_terms_and_text(store):
    for s, p, o in (("rex", "is", "dog"), ("rex", "likes", "bones"), ("tom", "is", "cat")):
        store.upsert(given(s, p, o))
    store.upsert(given("felix", "is", "cat", source=Source.LEARNED))
    assert [str(f) for f in store.find_by_subject("rex")] == ["rex is dog", "rex likes bones"]
    assert [str(f) for f in store.find_by_predicate("likes")] == ["rex likes bones"]
    assert [str(f) for f in store.find_by_object("cat")] == ["tom is cat", "felix is cat"]
    assert store.find_by_subject("REX") == []                     # lookups are exact
    assert len(store.get_user_facts()) == 3
    assert [str(f) for f in store.search_text("IS CA")] == ["tom is cat", "felix is cat"]   # text: any case


# ------------------------------------------------------------ derivations
def test_a_derived_fact_needs_a_derivation(store):
    with pytest.raises(UnderivedFactError):
        store.upsert(derived("a", "is", "b"))
    with pytest.raises(UnderivedFactError):
        store.store_derived([(derived("a", "is", "b"), [])])
    with pytest.raises(UnderivedFactError):    # a derived premise must come with its own derivation
        store.store_derived([(derived("a", "is", "c"), [{"rule": "r", "rule_version": "1", "confidence": 1.0,
                                                         "premises": [derived("a", "is", "b")]}])])
    assert store.count() == 0


def test_a_derivation_stores_its_premises_and_traces_back_to_them(store):
    cid, created, man, mortal = syllogism(store)
    assert created and store.count() == 3 and store.count_derivations() == 1
    (d,) = store.derivations_of(cid)
    assert d["rule"] == "inheritance" and d["rule_version"] == "1" and d["confidence"] == 0.9
    assert [str(store.get(i)) for i in d["premise_ids"]] == [str(man), str(mortal)]   # in order
    assert cid == 1 and sorted(d["premise_ids"]) == [2, 3]   # the conclusion first, then its premises
    steps = store.trace(cid)
    assert [s["derivation"] is None for s in steps] == [True, True, False] and steps[-1]["id"] == cid
    assert store.render_trace(cid)[-1] == ("[inheritance] socrates instance_of man + man subclass_of mortal "
                                           "-> socrates instance_of mortal")
    fact, lines = store.get_with_proof(cid)
    assert fact.source == Source.DEDUCED and lines == store.render_trace(cid)
    assert store.underived() == []


def test_the_same_derivation_again_keeps_one_record_and_the_higher_confidence(store):
    cid, _, man, mortal = syllogism(store)
    store.store_derived([(derived("socrates", "instance_of", "mortal"),
                          [{"rule": "inheritance", "rule_version": "1", "confidence": 0.95,
                            "premises": [mortal, man]}])])        # the same premises, in another order
    assert store.count_derivations() == 1 and store.derivations_of(cid)[0]["confidence"] == 0.95
    store.store_derived([(derived("socrates", "instance_of", "mortal"),
                          [{"rule": "other_rule", "rule_version": "1", "confidence": 0.5, "premises": [man]}])])
    assert [d["rule"] for d in store.derivations_of(cid)] == ["inheritance", "other_rule"]
    assert store.trace(cid)[-1]["derivation"]["rule"] == "inheritance"   # the strongest derivation explains it


def test_a_refused_batch_stores_nothing(store):
    store.upsert(given("kept", "is", "here"))
    with pytest.raises(UnderivedFactError):
        store.store_derived([(given("a", "is", "b"), []), (derived("c", "is", "d"), [])])
    assert store.count() == 1
    assert store.upsert(given("next", "is", "fact"))[0] == 2      # no id was used up by the refused batch


def test_a_trace_reports_a_missing_fact(store):
    assert store.trace(42) is None and store.render_trace(42) == []


# ------------------------------------------------------------ supersession
def test_a_superseded_fact_stays_and_says_what_replaced_it(store):
    old = store.store(given("rex", "is", "dog"))
    new = store.store(given("rex", "instance_of", "dog"))
    assert store.supersede(given("REX", "is", "dog"), new) == old
    assert store.superseded_ids() == {old} and store.get(old) is not None and store.count() == 2
    assert store.supersede(given("nobody", "is", "here"), new) is None


# ------------------------------------------------------------ surviving a reopen
def test_everything_survives_a_reopen(make):
    store = make()
    store.upsert(given("a", "is", "b", origin="book"))
    cid, _, _, _ = syllogism(store)
    store.supersede(given("a", "is", "b"), cid)
    before = (store.get_all_with_ids(), store.all_origins(), store.superseded_ids(), store.derivations_of(cid),
              store.render_trace(cid), store.count(), store.count_derivations(), store.all_keys())
    again = make()
    assert (again.get_all_with_ids(), again.all_origins(), again.superseded_ids(), again.derivations_of(cid),
            again.render_trace(cid), again.count(), again.count_derivations(), again.all_keys()) == before
    assert again.upsert(given("fresh", "is", "fact"))[0] == 5      # ids carry on after a reopen


# ------------------------------------------------------------ records: sources, passages, skills, traces
def test_records_are_the_engine_stores_and_the_original_store_says_so(store):
    if not store.supports_records:
        with pytest.raises(RecordsNotSupported):
            store.put_record("source", "plato/apology.md", {"title": "Apology"})
        return
    text = b"Socrates is a man.\n"
    store.put_record("source", "plato/apology.md", {"title": "Apology"}, body=text)
    store.put_record("passage", "plato/apology.md#1", {"source": "plato/apology.md", "start": 0, "end": 18})
    assert store.get_record("source", "plato/apology.md")["fields"] == {"title": "Apology"}
    assert store.record_body("source", "plato/apology.md") == text
    assert [r["key"] for r in store.records("passage")] == ["plato/apology.md#1"]
    with pytest.raises(ValueError):
        store.put_record("unknown_kind", "k", {})
