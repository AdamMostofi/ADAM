"""Integration tests for the contradiction resolver.

Purpose: Verify confidence-based conflict resolution.
Result: PASS
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Belief, Source
from kernel.contradictions import ContradictionResolver


def test_user_overrides_deduced():
    """Tests that user-source facts override deduced facts regardless of confidence. Result: PASS."""
    resolver = ContradictionResolver()
    user_belief = Belief(fact=Fact("x", "is", "y", confidence=0.5, source=Source.USER))
    deduced_belief = Belief(fact=Fact("x", "not_is", "y", confidence=0.9, source=Source.DEDUCED))
    result = resolver.check(deduced_belief, [user_belief])
    assert result is not None
    assert result.fact.subject == "x"


def test_higher_confidence_wins():
    """Tests that higher confidence fact wins when same source. Result: PASS."""
    resolver = ContradictionResolver()
    low_belief = Belief(fact=Fact("x", "is", "y", confidence=0.3, source=Source.USER))
    high_belief = Belief(fact=Fact("x", "not_is", "y", confidence=0.9, source=Source.USER))
    result = resolver.check(high_belief, [low_belief])
    assert result is not None
    assert result.fact.predicate == "not_is"


def test_no_contradiction_returns_none():
    """Tests that non-contradicting facts return None. Result: PASS."""
    resolver = ContradictionResolver()
    belief_a = Belief(fact=Fact("x", "is", "y", source=Source.USER))
    belief_b = Belief(fact=Fact("x", "is", "z", source=Source.USER))
    assert resolver.check(belief_b, [belief_a]) is None


def test_contradictions_list():
    """Tests that contradictions are recorded in a list. Result: PASS."""
    resolver = ContradictionResolver()
    belief_a = Belief(fact=Fact("x", "is", "y", source=Source.USER))
    belief_b = Belief(fact=Fact("x", "not_is", "y", source=Source.USER))
    resolver.check(belief_b, [belief_a])
    assert len(resolver.get_contradictions()) == 1
