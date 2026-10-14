"""Layer 1: Immutable foundational logic rules.

These rules are hardcoded and cannot be modified at runtime.
They form the bedrock of ADAM's reasoning capabilities.
"""

from __future__ import annotations

from kernel.facts import Fact, Source


def modus_ponens(p_implies_q: Fact, p: Fact) -> Fact | None:
    """If P->Q and P, then Q. The #1 rule — 70% of all reasoning."""
    if (
        p_implies_q.predicate == "implies"
        and p.predicate == "is"
        and p.object == p_implies_q.subject
    ):
        return Fact(
            subject=p.subject,
            predicate="is",
            object=p_implies_q.object,
            confidence=p_implies_q.confidence * p.confidence,
            source=Source.DEDUCED,
        )
    return None


def modus_tollens(p_implies_q: Fact, not_q: Fact) -> Fact | None:
    """If P->Q and not Q, then not P. For debugging."""
    if (
        p_implies_q.predicate == "implies"
        and not_q.object == p_implies_q.object
        and not_q.predicate == "not_is"
    ):
        return Fact(
            subject=not_q.subject,
            predicate="not_is",
            object=p_implies_q.subject,
            confidence=p_implies_q.confidence * not_q.confidence * 0.9,
            source=Source.DEDUCED,
        )
    return None


def transitivity(p_implies_q: Fact, q_implies_r: Fact) -> Fact | None:
    """If P->Q and Q->R, then P->R. For chaining rules."""
    if (
        p_implies_q.predicate == "implies"
        and q_implies_r.predicate == "implies"
        and p_implies_q.object == q_implies_r.subject
    ):
        return Fact(
            subject=p_implies_q.subject,
            predicate="implies",
            object=q_implies_r.object,
            confidence=p_implies_q.confidence * q_implies_r.confidence,
            source=Source.DEDUCED,
        )
    return None


def subtype_transitivity(x_is_y: Fact, y_implies_z: Fact) -> Fact | None:
    """If X is Y and Y implies Z, then X implies Z. Type hierarchy reasoning."""
    if (
        x_is_y.predicate == "is"
        and y_implies_z.predicate == "implies"
        and x_is_y.object == y_implies_z.subject
    ):
        return Fact(
            subject=x_is_y.subject,
            predicate="implies",
            object=y_implies_z.object,
            confidence=x_is_y.confidence * y_implies_z.confidence,
            source=Source.DEDUCED,
        )
    return None


def is_transitivity(x_is_y: Fact, y_is_z: Fact) -> Fact | None:
    """If X is Y and Y is Z, then X is Z. Type hierarchy transitivity."""
    if (
        x_is_y.predicate == "is"
        and y_is_z.predicate == "is"
        and x_is_y.object == y_is_z.subject
    ):
        return Fact(
            subject=x_is_y.subject,
            predicate="is",
            object=y_is_z.object,
            confidence=x_is_y.confidence * y_is_z.confidence,
            source=Source.DEDUCED,
        )
    return None


def universal_instantiation(all_x_are_y: Fact, a_is_x: Fact) -> Fact | None:
    """If All X are Y, and a is X, then a is Y."""
    if (
        all_x_are_y.predicate == "all_are"
        and a_is_x.predicate == "is"
        and a_is_x.object == all_x_are_y.subject
    ):
        return Fact(
            subject=a_is_x.subject,
            predicate="is",
            object=all_x_are_y.object,
            confidence=all_x_are_y.confidence * a_is_x.confidence,
            source=Source.DEDUCED,
        )
    return None


def existential_generalization(a_is_x: Fact) -> Fact | None:
    """If a is X, then there exists X."""
    if a_is_x.predicate == "is":
        return Fact(
            subject="exists",
            predicate="is",
            object=a_is_x.object,
            confidence=a_is_x.confidence,
            source=Source.DEDUCED,
        )
    return None


def equality_substitution(a_equals_b: Fact, fact_with_a: Fact) -> list[Fact]:
    """If A = B, replace A with B or B with A in any fact. Leibniz's law with symmetry."""
    if a_equals_b.predicate != "equals":
        return []
    results = []
    if fact_with_a.subject == a_equals_b.subject:
        results.append(Fact(
            subject=a_equals_b.object,
            predicate=fact_with_a.predicate,
            object=fact_with_a.object,
            confidence=a_equals_b.confidence * fact_with_a.confidence * 0.95,
            source=Source.DEDUCED,
        ))
    if fact_with_a.subject == a_equals_b.object:
        results.append(Fact(
            subject=a_equals_b.subject,
            predicate=fact_with_a.predicate,
            object=fact_with_a.object,
            confidence=a_equals_b.confidence * fact_with_a.confidence * 0.95,
            source=Source.DEDUCED,
        ))
    if fact_with_a.object == a_equals_b.subject:
        results.append(Fact(
            subject=fact_with_a.subject,
            predicate=fact_with_a.predicate,
            object=a_equals_b.object,
            confidence=a_equals_b.confidence * fact_with_a.confidence * 0.95,
            source=Source.DEDUCED,
        ))
    if fact_with_a.object == a_equals_b.object:
        results.append(Fact(
            subject=fact_with_a.subject,
            predicate=fact_with_a.predicate,
            object=a_equals_b.subject,
            confidence=a_equals_b.confidence * fact_with_a.confidence * 0.95,
            source=Source.DEDUCED,
        ))
    return results


def disjunctive_syllogism(a_or_b: Fact, not_a: Fact) -> Fact | None:
    """If A or B and not A, then B. For decision making."""
    if (
        a_or_b.predicate == "or"
        and not_a.predicate == "not_is"
        and not_a.subject == a_or_b.subject
    ):
        return Fact(
            subject=a_or_b.object,
            predicate="is",
            object="true",
            confidence=a_or_b.confidence * not_a.confidence,
            source=Source.DEDUCED,
        )
    return None


def contradiction_detection(p: Fact, not_p: Fact) -> Fact | None:
    """If tape has P and not P, flag it. Don't explode — ask for priority."""
    if (
        p.subject == not_p.subject
        and p.object == not_p.object
        and (
            (p.predicate == "is" and not_p.predicate == "not_is")
            or (p.predicate == "not_is" and not_p.predicate == "is")
        )
    ):
        return Fact(
            subject=p.subject,
            predicate="contradiction",
            object=p.object,
            confidence=1.0,
            source=Source.DEDUCED,
        )
    return None


def specificity_resolution(general: Fact, specific: Fact) -> Fact:
    """Exception handling: more specific rule wins over general rule.
    E.g., 'penguin not_is flies' overrides 'bird all_are flies' because
    penguin is a subtype of bird (more specific subject).
    """
    return specific


def de_morgan_and(not_a_and_b: Fact) -> list[Fact]:
    """NOT(A AND B) -> (NOT A, NOT B). Returns two separate facts."""
    if not_a_and_b.predicate == "not_and":
        return [
            Fact(
                subject=not_a_and_b.subject,
                predicate="not_is",
                object="true",
                confidence=not_a_and_b.confidence,
                source=Source.DEDUCED,
            ),
            Fact(
                subject=not_a_and_b.object,
                predicate="not_is",
                object="true",
                confidence=not_a_and_b.confidence,
                source=Source.DEDUCED,
            ),
        ]
    return []


def de_morgan_or(not_a_or_b: Fact) -> list[Fact]:
    """NOT(A OR B) -> (NOT A, NOT B). Returns two separate facts."""
    if not_a_or_b.predicate == "not_or":
        return [
            Fact(
                subject=not_a_or_b.subject,
                predicate="not_is",
                object="true",
                confidence=not_a_or_b.confidence,
                source=Source.DEDUCED,
            ),
            Fact(
                subject=not_a_or_b.object,
                predicate="not_is",
                object="true",
                confidence=not_a_or_b.confidence,
                source=Source.DEDUCED,
            ),
        ]
    return []


def double_negation(not_not_p: Fact) -> Fact | None:
    """NOT(NOT P) -> P."""
    if not_not_p.predicate == "not_not":
        return Fact(
            subject=not_not_p.subject,
            predicate="is",
            object=not_not_p.object,
            confidence=not_not_p.confidence,
            source=Source.DEDUCED,
        )
    return None


def conditional_proof(p: Fact, q: Fact) -> Fact | None:
    """If assuming P leads to Q, then P->Q."""
    if p.predicate == "assumes" and q.predicate == "derives":
        return Fact(
            subject=p.subject,
            predicate="implies",
            object=q.object,
            confidence=p.confidence * q.confidence * 0.9,
            source=Source.DEDUCED,
        )
    return None


def universal_generalization(a_is_x: Fact) -> Fact | None:
    """If it holds for arbitrary c, it holds for all X."""
    if a_is_x.predicate == "is" and a_is_x.subject.startswith("arbitrary_"):
        return Fact(
            subject=a_is_x.subject.replace("arbitrary_", "all_"),
            predicate="all_are",
            object=a_is_x.object,
            confidence=a_is_x.confidence * 0.9,
            source=Source.DEDUCED,
        )
    return None
