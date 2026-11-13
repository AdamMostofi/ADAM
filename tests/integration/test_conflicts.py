"""Contradictions as state, defaults with exceptions, and source attribution (Stage 1.5, #31)."""
from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from interface.core import ADAMCore
from interface.web.app import create_app
from kernel.engine import InferenceEngine
from kernel.facts import Fact

PENGUIN = [
    Fact("bird", "typically", "flier"),
    Fact("penguin", "subclass_of", "bird"),
    Fact("penguin", "typically_not", "flier"),
    Fact("pingu", "instance_of", "penguin"),
]
FLIES = ("pingu", "instance_of", "flier")
DOES_NOT_FLY = ("pingu", "not_instance_of", "flier")


def engine_with(facts):
    engine = InferenceEngine()
    engine.add_facts(facts)
    engine.infer()
    return engine


# --------------------------------------------------- acceptance criteria


def test_penguin_one_active_answer_one_defeated_belief_one_conflict():
    engine = engine_with(PENGUIN)
    assert engine.query(*DOES_NOT_FLY)
    assert not engine.query(*FLIES)
    assert engine.status(*FLIES) == "defeated"
    assert engine.query(*FLIES, include_inactive=True)  # kept, only marked
    [conflict] = engine.conflicts()
    assert conflict.resolution == "more_specific_default"
    assert conflict.winner == DOES_NOT_FLY and conflict.loser == FLIES
    assert conflict.positive_proofs and conflict.negative_proofs  # both sides with their derivations


def test_specific_evidence_about_the_individual_beats_the_default():
    engine = engine_with([Fact("bird", "typically", "flier"), Fact("penguin", "subclass_of", "bird"),
                          Fact("pingu", "instance_of", "penguin"), Fact(*DOES_NOT_FLY)])
    assert engine.query(*DOES_NOT_FLY) and not engine.query(*FLIES)
    [conflict] = engine.conflicts()
    assert conflict.resolution == "strict_beats_default" and conflict.winner == DOES_NOT_FLY


def test_stats_and_api_report_the_conflict(tmp_path):
    core = ADAMCore(db_path=str(tmp_path / "web.db"), lance_path=str(tmp_path / "web.vec"))
    for f in PENGUIN:
        core.engine.add_fact(f)
    core.engine.infer()
    assert core.get_stats()["contradictions"] == 1
    with create_app(core).test_client() as client:
        assert client.get("/api/stats").get_json()["contradictions"] == 1
        [record] = client.get("/api/conflicts").get_json()
        assert record["resolution"] == "more_specific_default"
        assert record["winner"] == list(DOES_NOT_FLY)
        assert record["positive_proofs"][0]["rule"] == "default_inheritance"


def test_removing_the_specific_evidence_restores_the_general_conclusion():
    engine = engine_with(PENGUIN)
    engine.retract(Fact("penguin", "typically_not", "flier"))
    assert engine.query(*FLIES)
    assert engine.status(*FLIES) == "active"
    assert engine.conflicts() == []
    engine = engine_with(PENGUIN[:2] + PENGUIN[3:] + [Fact(*DOES_NOT_FLY)])
    engine.retract(Fact(*DOES_NOT_FLY))
    assert engine.query(*FLIES)


def test_two_disagreeing_sources_keep_separate_attribution():
    engine = engine_with([
        Fact("x", "instance_of", "safe", origin="book A"),
        Fact("x", "not_instance_of", "safe", origin="book B"),
        Fact("safe", "subclass_of", "harmless", origin="book A"),
    ])
    [conflict] = engine.conflicts()
    assert conflict.kind == "strict" and conflict.resolution == "unresolved"
    assert conflict.positive_sources == ("book A",) and conflict.negative_sources == ("book B",)
    # Neither source is overruled or deleted, and A's conclusion is attributed to A only.
    assert engine.query("x", "instance_of", "safe") and engine.query("x", "not_instance_of", "safe")
    assert engine.attribution("x", "instance_of", "harmless") == ["book A"]


def test_the_same_fact_from_two_sources_is_attributed_to_both():
    engine = engine_with([Fact("x", "instance_of", "safe", origin="book A"),
                          Fact("x", "instance_of", "safe", origin="book B")])
    assert engine.attribution("x", "instance_of", "safe") == ["book A", "book B"]
    engine.retract(Fact("y", "instance_of", "z"))  # a no-op retract keeps origins
    engine.retract(Fact("x", "instance_of", "safe"))
    assert engine.beliefs == {}


# -------------------------------------------------------- how conflicts end


def test_a_strict_contradiction_is_recorded_and_nothing_is_withdrawn():
    engine = engine_with([Fact("rex", "instance_of", "cat"), Fact("rex", "not_instance_of", "cat")])
    [conflict] = engine.conflicts()
    assert conflict.resolution == "unresolved" and conflict.winner is None
    assert engine.query("rex", "instance_of", "cat") and engine.query("rex", "not_instance_of", "cat")
    assert engine.query("rex", "contradiction", "cat")


def test_strict_rules_are_never_defeated_by_a_default():
    engine = engine_with([Fact("bird", "subclass_of", "flier"), Fact("penguin", "subclass_of", "bird"),
                          Fact("penguin", "typically_not", "flier"), Fact("pingu", "instance_of", "penguin")])
    assert engine.query(*FLIES)  # strict: every bird is a flier, so pingu is one
    assert engine.status(*DOES_NOT_FLY) == "defeated"


def test_incomparable_defaults_are_contested():
    """The Nixon diamond: quakers are typically pacifists, republicans typically not."""
    engine = engine_with([Fact("quaker", "typically", "pacifist"), Fact("republican", "typically_not", "pacifist"),
                          Fact("nixon", "instance_of", "quaker"), Fact("nixon", "instance_of", "republican")])
    assert engine.status("nixon", "instance_of", "pacifist") == "contested"
    assert engine.status("nixon", "not_instance_of", "pacifist") == "contested"
    assert not engine.query("nixon", "instance_of", "pacifist")
    assert not engine.query("nixon", "not_instance_of", "pacifist")
    [conflict] = engine.conflicts()
    assert conflict.resolution == "contested"


def test_consequences_of_a_defeated_belief_are_unsupported():
    engine = engine_with(PENGUIN + [Fact("flier", "subclass_of", "airborne")])
    assert engine.status("pingu", "instance_of", "airborne") == "unsupported"
    assert not engine.query("pingu", "instance_of", "airborne")
    assert not engine.query("pingu", "contradiction", "flier")  # rests on the defeated side
    assert len(engine.conflicts()) == 1


def test_a_default_with_no_exception_holds():
    engine = engine_with([Fact("bird", "typically", "flier"), Fact("tweety", "instance_of", "bird")])
    assert engine.query("tweety", "instance_of", "flier")
    assert engine.status("tweety", "instance_of", "flier") == "active"
    assert engine.beliefs[("tweety", "instance_of", "flier")].proofs[0].rule == "default_inheritance"


def test_prove_never_proves_a_default_conclusion():
    engine = engine_with([Fact("bird", "typically", "flier"), Fact("tweety", "instance_of", "bird")])
    assert engine.prove("tweety", "instance_of", "flier") is None
    assert engine.prove("tweety", "instance_of", "bird") is not None


def test_the_legacy_resolver_reports_recorded_conflicts():
    engine = engine_with(PENGUIN)
    [(positive, negative)] = engine.resolver.get_contradictions()
    assert (positive.fact.subject, positive.fact.predicate) == ("pingu", "instance_of")
    assert negative.fact.predicate == "not_instance_of"


def test_origins_are_stored(tmp_path):
    from memory.system import MemorySystem
    memory = MemorySystem(db_path=str(tmp_path / "f.db"), lance_path=str(tmp_path / "v.db"))
    engine = engine_with([Fact("x", "instance_of", "safe", origin="book A"),
                          Fact("x", "instance_of", "safe", origin="book B")])
    [fact_id] = memory.store_beliefs(engine, [("x", "instance_of", "safe")])
    assert memory.exact.origins_of(fact_id) == ["book A", "book B"]


# --------------------------------------------------- order independence

TERMS = ["a", "b", "c", "x"]
default_facts = st.lists(st.one_of(
    st.builds(Fact, st.sampled_from(TERMS), st.sampled_from(["typically", "typically_not", "subclass_of"]),
              st.sampled_from(TERMS)),
    st.builds(Fact, st.just("x"), st.sampled_from(["instance_of", "not_instance_of"]), st.sampled_from(TERMS)),
), min_size=1, max_size=6, unique_by=lambda f: (f.subject, f.predicate, f.object))


def outcome(engine):
    statuses = {k: engine.status(*k) for k in engine.beliefs}
    conflicts = sorted((c.positive, c.negative, c.resolution, c.winner) for c in engine.conflicts())
    return statuses, conflicts


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(default_facts, st.data())
def test_statuses_and_conflicts_do_not_depend_on_order(facts, data):
    expected = outcome(engine_with(facts))
    shuffled = data.draw(st.permutations(facts))
    engine = InferenceEngine()
    for f in shuffled:
        engine.add_fact(f)
        engine.infer()
    assert outcome(engine) == expected
    # Only defaults can lose: a given fact is never defeated or withheld.
    for k, status in expected[0].items():
        if engine.beliefs[k].given:
            assert status == "active"
