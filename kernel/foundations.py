"""Layer 1: Immutable foundational logic rules.

These rules are hardcoded and cannot be modified at runtime. They form the
bedrock of ADAM's reasoning. Each rule is checked for soundness in
tests/unit/test_rule_soundness.py; docs/design/kernel-rules.md lists them.

How facts are read
------------------
Facts are triples (subject, predicate, object). Two kinds of statement share
the same predicates:

* Class statements: "x is C" means x belongs to class C. "P implies Q" and
  "P all_are Q" mean every member of P is a member of Q. "x not_is C" means x
  does not belong to C.

* Propositions: the reserved object TRUE turns a term into a statement that
  holds or fails. "rain is true" means rain holds; "rain not_is true" means it
  fails. "P implies Q" between propositions means P -> Q. "P or Q",
  "P not_and Q", "P not_or Q" and "P not_not true" combine propositions.

* Negated terms: inside "or", "not_and" and "not_or", a term written
  "not:p" stands for the negation of p, so "not:rain or not:cold" says at
  least one of rain and cold fails. Rules never assert "not:p is true";
  they assert the canonical form "p not_is true" instead.

Reserved terms: "true", "exists", the "not:" prefix, and the "arbitrary_"
prefix (an arbitrary member of a class, used by universal generalization).

Distinguishing membership from subclassing ("rex is dog" vs "dog is
mammal") is Stage 1.3; until then "is" covers both, which makes
is_transitivity and subtype_transitivity valid only for the subclass reading.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

from kernel.facts import Fact, Source

TRUE = "true"
EXISTS = "exists"
NOT_PREFIX = "not:"
ARBITRARY_PREFIX = "arbitrary_"


# ---------------------------------------------------------------- literals
@lru_cache(maxsize=65_536)
def split_term(term: str) -> tuple[str, bool]:
    """(base term, negated?) after cancelling pairs of "not:" prefixes."""
    count = 0
    while term.startswith(NOT_PREFIX) and len(term) > len(NOT_PREFIX):
        term = term[len(NOT_PREFIX):]
        count += 1
    return term, count % 2 == 1


def canonical_term(term: str) -> str:
    """"not:not:a" is "a"; "not:not:not:a" is "not:a"."""
    base, negated = split_term(term)
    return NOT_PREFIX + base if negated else base


def negate_term(term: str) -> str:
    """The negation of a propositional term, in canonical form."""
    base, negated = split_term(term)
    return base if negated else NOT_PREFIX + base


def is_reserved(term: str) -> bool:
    """"true" and "exists" (with any negations) are never propositions or classes in their own right."""
    return split_term(term)[0] in (TRUE, EXISTS)


def literal_triple(term: str) -> tuple[str, str, str]:
    """The canonical (subject, predicate, object) saying `term` holds."""
    base, negated = split_term(term)
    return (base, "not_is" if negated else "is", TRUE)


def canonical_fact(fact: Fact) -> Fact:
    """The same statement in canonical form, so every rule recognises it.

    Terms lose cancelling "not:" pairs, and a negated proposition moves its
    negation into the predicate: "not:rain is true" becomes "rain not_is true",
    and "not:rain not_is true" becomes "rain is true".
    """
    if not fact.subject.startswith(NOT_PREFIX) and not fact.object.startswith(NOT_PREFIX):
        return fact  # fast path: nothing to cancel or move
    subject, obj, predicate = canonical_term(fact.subject), canonical_term(fact.object), fact.predicate
    if obj == TRUE and predicate in ("is", "not_is"):
        base, negated = split_term(subject)
        flipped = negated != (predicate == "not_is")
        subject, predicate = base, "not_is" if flipped else "is"
    if (subject, predicate, obj) == (fact.subject, fact.predicate, fact.object):
        return fact
    return replace(fact, subject=subject, predicate=predicate, object=obj)


def literal_true(term: str, confidence: float) -> Fact:
    """The canonical fact saying `term` holds."""
    subject, predicate, obj = literal_triple(term)
    return Fact(subject, predicate, obj, confidence=confidence, source=Source.DEDUCED)


def literal_false(term: str, confidence: float) -> Fact:
    """The canonical fact saying `term` fails."""
    return literal_true(negate_term(term), confidence)


def says_false(fact: Fact, term: str) -> bool:
    """Whether `fact` states that `term` fails."""
    return (fact.subject, fact.predicate, fact.object) == literal_triple(negate_term(term))


def says_true(fact: Fact, term: str) -> bool:
    """Whether `fact` states that `term` holds."""
    return says_false(fact, negate_term(term))


# Facts relating a term to itself under these predicates are always true and
# carry no information, so no rule derives them.
TRIVIAL_WHEN_REFLEXIVE = frozenset({"is", "implies", "all_are", "equals"})


def _deduced(subject: str, predicate: str, obj: str, confidence: float) -> Fact | None:
    if subject == obj and predicate in TRIVIAL_WHEN_REFLEXIVE:
        return None
    return Fact(subject=subject, predicate=predicate, object=obj, confidence=confidence, source=Source.DEDUCED)


# ------------------------------------------------------------ implication
def modus_ponens(p_implies_q: Fact, p: Fact) -> Fact | None:
    """P -> Q with P gives Q.

    Class form: "x is P" and "P implies Q" give "x is Q".
    Proposition form: a fact saying P holds and "P implies Q" give the fact
    saying Q holds; P and Q may be negated terms ("not:p").
    """
    if p_implies_q.predicate != "implies" or p.predicate not in ("is", "not_is"):
        return None
    if p.object != TRUE and p.object != p_implies_q.subject:
        return None  # cheap filter: neither form can match
    if is_reserved(p_implies_q.subject) or is_reserved(p_implies_q.object):
        return None
    confidence = p_implies_q.confidence * p.confidence
    if p.object == TRUE:
        if says_true(p, p_implies_q.subject):
            return literal_true(p_implies_q.object, confidence)
        return None
    if p.predicate == "is" and p.object == p_implies_q.subject and p_implies_q.object != TRUE:
        return _deduced(p.subject, "is", p_implies_q.object, confidence)
    return None


def modus_tollens(p_implies_q: Fact, not_q: Fact) -> Fact | None:
    """P -> Q with not-Q gives not-P.

    Class form: "x not_is Q" and "P implies Q" give "x not_is P".
    Proposition form: a fact saying Q fails and "P implies Q" give the fact
    saying P fails; P and Q may be negated terms.
    The 0.9 factor marks reasoning backwards from a failure.
    """
    if p_implies_q.predicate != "implies" or not_q.predicate not in ("is", "not_is"):
        return None
    if not_q.object != TRUE and not_q.object != p_implies_q.object:
        return None  # cheap filter: neither form can match
    if is_reserved(p_implies_q.subject) or is_reserved(p_implies_q.object):
        return None
    confidence = p_implies_q.confidence * not_q.confidence * 0.9
    if not_q.object == TRUE:
        if says_false(not_q, p_implies_q.object):
            return literal_false(p_implies_q.subject, confidence)
        return None
    if not_q.predicate == "not_is" and not_q.object == p_implies_q.object:
        return _deduced(not_q.subject, "not_is", p_implies_q.subject, confidence)
    return None


def transitivity(p_implies_q: Fact, q_implies_r: Fact) -> Fact | None:
    """P -> Q and Q -> R give P -> R."""
    if (
        p_implies_q.predicate == "implies"
        and q_implies_r.predicate == "implies"
        and p_implies_q.object == q_implies_r.subject
        and p_implies_q.subject != q_implies_r.object
    ):
        return _deduced(p_implies_q.subject, "implies", q_implies_r.object,
                        p_implies_q.confidence * q_implies_r.confidence)
    return None


def subtype_transitivity(x_is_y: Fact, y_implies_z: Fact) -> Fact | None:
    """X is Y and Y implies Z give X implies Z (X read as a subclass of Y)."""
    if (
        x_is_y.predicate == "is"
        and y_implies_z.predicate == "implies"
        and not is_reserved(x_is_y.subject)
        and x_is_y.object != TRUE
        and y_implies_z.object != TRUE
        and x_is_y.object == y_implies_z.subject
        and x_is_y.subject != y_implies_z.object
    ):
        return _deduced(x_is_y.subject, "implies", y_implies_z.object, x_is_y.confidence * y_implies_z.confidence)
    return None


# ----------------------------------------------------------- class membership
def is_transitivity(x_is_y: Fact, y_is_z: Fact) -> Fact | None:
    """X is Y and Y is Z give X is Z (valid when "is" means subclass; see Stage 1.3)."""
    if (
        x_is_y.predicate == "is"
        and y_is_z.predicate == "is"
        and x_is_y.object != TRUE
        and y_is_z.object != TRUE
        and x_is_y.object == y_is_z.subject
        and x_is_y.subject != y_is_z.object
    ):
        return _deduced(x_is_y.subject, "is", y_is_z.object, x_is_y.confidence * y_is_z.confidence)
    return None


def universal_instantiation(all_x_are_y: Fact, a_is_x: Fact) -> Fact | None:
    """All X are Y and a is X give a is Y."""
    if (
        all_x_are_y.predicate == "all_are"
        and a_is_x.predicate == "is"
        and a_is_x.object != TRUE
        and all_x_are_y.object != TRUE
        and a_is_x.object == all_x_are_y.subject
    ):
        return _deduced(a_is_x.subject, "is", all_x_are_y.object, all_x_are_y.confidence * a_is_x.confidence)
    return None


def existential_generalization(a_is_x: Fact) -> Fact | None:
    """a is X gives "exists is X": something is an X.

    Not applied to propositions ("p is true") or to facts already about "exists".
    """
    if a_is_x.predicate == "is" and a_is_x.object != TRUE and a_is_x.subject != EXISTS:
        return _deduced(EXISTS, "is", a_is_x.object, a_is_x.confidence)
    return None


def universal_generalization(arbitrary_is_x: Fact) -> Fact | None:
    """An arbitrary member of T is X gives "T all_are X".

    "arbitrary_man is mortal" gives "man all_are mortal". Only sound when the
    arbitrary member really is arbitrary: nothing else may be asserted about it.
    """
    if arbitrary_is_x.predicate != "is" or arbitrary_is_x.object == TRUE:
        return None
    if not arbitrary_is_x.subject.startswith(ARBITRARY_PREFIX):
        return None
    kind = arbitrary_is_x.subject[len(ARBITRARY_PREFIX):]
    if not kind or kind == arbitrary_is_x.object:
        return None
    return _deduced(kind, "all_are", arbitrary_is_x.object, arbitrary_is_x.confidence * 0.9)


# -------------------------------------------------------------- equality
def equality_substitution(a_equals_b: Fact, fact_with_a: Fact) -> list[Fact]:
    """If A = B, a fact about A also holds for B, in subject or object position (Leibniz's law).

    Works in both directions. Never produces reflexive equalities ("x equals x").
    """
    if a_equals_b.predicate != "equals" or a_equals_b.subject == a_equals_b.object:
        return []
    if {a_equals_b.subject, a_equals_b.object} & {TRUE, EXISTS}:
        return []  # reserved words are not terms that can be equal to something
    a, b = a_equals_b.subject, a_equals_b.object
    confidence = a_equals_b.confidence * fact_with_a.confidence * 0.95
    results = []
    for old, new in ((a, b), (b, a)):
        if fact_with_a.subject == old:
            results.append((new, fact_with_a.predicate, fact_with_a.object))
        if fact_with_a.object == old:
            results.append((fact_with_a.subject, fact_with_a.predicate, new))
    out, seen = [], set()
    for subject, predicate, obj in results:
        key = (subject, predicate, obj)
        if key in seen or key == (fact_with_a.subject, fact_with_a.predicate, fact_with_a.object):
            continue
        seen.add(key)
        fact = _deduced(subject, predicate, obj, confidence)
        if fact is not None:
            out.append(fact)
    return out


def equality_symmetry(a_equals_b: Fact) -> Fact | None:
    """A = B gives B = A."""
    if (a_equals_b.predicate == "equals" and a_equals_b.subject != a_equals_b.object
            and not {a_equals_b.subject, a_equals_b.object} & {TRUE, EXISTS}):
        return _deduced(a_equals_b.object, "equals", a_equals_b.subject, a_equals_b.confidence)
    return None


# ----------------------------------------------------------- propositions
def disjunctive_syllogism(a_or_b: Fact, not_a: Fact) -> Fact | None:
    """A or B with not-A gives B; with not-B gives A.

    Works with negated terms: "not:a or b" with "a is true" gives "b is true".
    """
    if a_or_b.predicate != "or":
        return None
    a, b = a_or_b.subject, a_or_b.object
    if is_reserved(a) or is_reserved(b):
        return None
    confidence = a_or_b.confidence * not_a.confidence
    if says_false(not_a, a):
        return literal_true(b, confidence)
    if says_false(not_a, b):
        return literal_true(a, confidence)
    return None


def de_morgan_and(not_a_and_b: Fact) -> list[Fact]:
    """not(A and B) gives (not A) or (not B).

    Neither negation follows on its own; pairing the result with a known fact
    through disjunctive syllogism gives the other one.
    """
    if not_a_and_b.predicate != "not_and":
        return []
    a, b = not_a_and_b.subject, not_a_and_b.object
    if is_reserved(a) or is_reserved(b):
        return []
    if canonical_term(a) == canonical_term(b):
        return [literal_false(a, not_a_and_b.confidence)]
    return [Fact(negate_term(a), "or", negate_term(b), confidence=not_a_and_b.confidence, source=Source.DEDUCED)]


def de_morgan_or(not_a_or_b: Fact) -> list[Fact]:
    """not(A or B) gives not A and not B."""
    if not_a_or_b.predicate != "not_or":
        return []
    a, b = not_a_or_b.subject, not_a_or_b.object
    if is_reserved(a) or is_reserved(b):
        return []
    first = literal_false(a, not_a_or_b.confidence)
    if canonical_term(a) == canonical_term(b):
        return [first]
    return [first, literal_false(b, not_a_or_b.confidence)]


def double_negation(not_not_p: Fact) -> Fact | None:
    """not(not(S is O)) gives S is O; for a proposition ("p not_not true") it gives the fact saying p holds."""
    if not_not_p.predicate != "not_not" or is_reserved(not_not_p.subject):
        return None
    if not_not_p.object == TRUE:
        return literal_true(not_not_p.subject, not_not_p.confidence)
    return _deduced(not_not_p.subject, "is", not_not_p.object, not_not_p.confidence)


def conditional_proof(assumes: Fact, derives: Fact) -> Fact | None:
    """Assuming P in a context and deriving Q in the same context gives P implies Q.

    "c1 assumes rain" and "c1 derives wet" give "rain implies wet". The two
    facts must share a context (their subject); otherwise nothing follows.
    """
    if (
        assumes.predicate == "assumes"
        and derives.predicate == "derives"
        and assumes.subject == derives.subject
        and assumes.object != derives.object
        and not is_reserved(assumes.object)
        and not is_reserved(derives.object)
    ):
        return _deduced(assumes.object, "implies", derives.object, assumes.confidence * derives.confidence * 0.9)
    return None


# --------------------------------------------------------- contradictions
def contradiction_detection(p: Fact, not_p: Fact) -> Fact | None:
    """S is O together with S not_is O is flagged, never used to derive anything else."""
    if (
        p.subject == not_p.subject
        and p.object == not_p.object
        and {p.predicate, not_p.predicate} == {"is", "not_is"}
    ):
        return _deduced(p.subject, "contradiction", p.object, 1.0)
    return None


def specificity_resolution(general: Fact, specific: Fact) -> Fact:
    """Placeholder: exceptions overriding general rules are Stage 1.5 (#31). Not registered."""
    return specific
