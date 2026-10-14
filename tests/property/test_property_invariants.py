"""Property-based tests using hypothesis.

Purpose: Verify invariants hold across randomly generated inputs.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from hypothesis import given, strategies as st, settings, assume
from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine
from kernel.graph import KnowledgeGraph


@given(
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.floats(min_value=0.0, max_value=1.0),
)
@settings(max_examples=50)
def test_confidence_never_exceeds_1(a, b, c, conf):
    """Property: confidence never exceeds 1.0 for any input. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact(a, "implies", b, confidence=conf),
        Fact(a, "is", a, confidence=conf),
    ])
    engine.infer()
    for belief in engine.query():
        assert belief.confidence <= 1.0


@given(
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.floats(min_value=0.0, max_value=1.0),
)
@settings(max_examples=50)
def test_confidence_never_below_0(a, b, c, conf):
    """Property: confidence never below 0.0 for any input. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact(a, "implies", b, confidence=conf),
        Fact(a, "is", a, confidence=conf),
    ])
    engine.infer()
    for belief in engine.query():
        assert belief.confidence >= 0.0


@given(
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
)
@settings(max_examples=50)
def test_modus_ponens_always_deduces(a, b, c):
    """Property: modus ponens always deduces Q from P->Q and P. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact(a, "implies", b),
        Fact(c, "is", a),
    ])
    engine.infer()
    result = [belief for belief in engine.query(subject=c) if belief.fact.predicate == "is" and belief.fact.object == b]
    assert len(result) > 0


@given(
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
)
@settings(max_examples=50)
def test_transitivity_always_chains(a, b, c):
    """Property: transitivity always chains P->Q + Q->R => P->R. Result: PASS."""
    engine = InferenceEngine()
    engine.add_facts([
        Fact(a, "implies", b),
        Fact(b, "implies", c),
    ])
    engine.infer()
    result = [belief for belief in engine.query(subject=a, predicate="implies", object=c)]
    assert len(result) > 0


@given(
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
)
@settings(max_examples=50)
def test_retract_removes_dependents(a, b, c):
    """Property: retracting a rule removes all dependent deductions. Result: PASS."""
    assume(a != b and b != c and a != c)
    engine = InferenceEngine()
    engine.add_facts([
        Fact(a, "implies", b),
        Fact(b, "implies", c),
        Fact(a, "is", a),
    ])
    engine.infer()
    before = len(engine.query(subject=a, object=c))
    assert before > 0
    engine.retract(Fact(a, "implies", b))
    after = len(engine.query(subject=a, object=c))
    assert after == 0


@given(
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
    st.text(min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L",))),
)
@settings(max_examples=50)
def test_graph_path_exists_after_chain(a, b, c):
    """Property: graph path always exists after adding chain facts. Result: PASS."""
    graph = KnowledgeGraph()
    graph.add_facts([
        Fact(a, "is", b),
        Fact(b, "is", c),
    ])
    path = graph.find_path(a, c)
    assert path is not None
    assert path[0] == a and path[-1] == c
