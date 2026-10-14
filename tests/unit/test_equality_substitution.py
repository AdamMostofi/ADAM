"""Unit tests for equality_substitution: If A=B, replace A with B (or B with A) in any fact.

Purpose: Verify Leibniz's law with symmetry (both directions).
Result: PASS
Fix: Was only substituting in subject position and only one direction. Now handles both subject and object positions, and both directions (A->B and B->A).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from kernel.facts import Fact, Source
from kernel.foundations import equality_substitution


def test_subject_substitution_a_to_b():
    """Tests substituting A with B in subject position: a=b + a is c => b is c. Result: PASS."""
    results = equality_substitution(Fact("a", "equals", "b"), Fact("a", "is", "c"))
    assert any(r.subject == "b" and r.object == "c" for r in results)


def test_object_substitution_a_to_b():
    """Tests substituting A with B in object position: a=b + c is a => c is b. Result: PASS."""
    results = equality_substitution(Fact("a", "equals", "b"), Fact("c", "is", "a"))
    assert any(r.subject == "c" and r.object == "b" for r in results)


def test_subject_substitution_b_to_a():
    """Tests substituting B with A in subject position (symmetry): a=b + b is c => a is c. Result: PASS. Fix: symmetry was missing."""
    results = equality_substitution(Fact("a", "equals", "b"), Fact("b", "is", "c"))
    assert any(r.subject == "a" and r.object == "c" for r in results)


def test_object_substitution_b_to_a():
    """Tests substituting B with A in object position (symmetry): a=b + c is b => c is a. Result: PASS. Fix: symmetry was missing."""
    results = equality_substitution(Fact("a", "equals", "b"), Fact("c", "is", "b"))
    assert any(r.subject == "c" and r.object == "a" for r in results)


def test_no_match():
    """Tests that non-matching facts return empty list. Result: PASS."""
    assert equality_substitution(Fact("a", "equals", "b"), Fact("c", "is", "d")) == []


def test_self_equality():
    """Tests self-equality: a=a + a is b => a is b. Result: PASS."""
    results = equality_substitution(Fact("a", "equals", "a"), Fact("a", "is", "b"))
    assert len(results) > 0


def test_returns_list():
    """Tests that function returns a list (may contain multiple substitutions). Result: PASS. Fix: was returning single Fact, now returns list."""
    results = equality_substitution(Fact("a", "equals", "b"), Fact("a", "is", "a"))
    assert isinstance(results, list)
