"""Forward-chaining inference engine.

Takes a set of facts and rules, applies foundational logic,
and produces new deduced facts with full reasoning traces.
"""

from __future__ import annotations

from kernel.facts import Belief, Fact, Source
from kernel.foundations import (
    conditional_proof,
    contradiction_detection,
    de_morgan_and,
    de_morgan_or,
    disjunctive_syllogism,
    double_negation,
    equality_substitution,
    existential_generalization,
    is_transitivity,
    modus_ponens,
    modus_tollens,
    subtype_transitivity,
    transitivity,
    universal_generalization,
    universal_instantiation,
)
from kernel.contradictions import ContradictionResolver


class InferenceEngine:
    def __init__(self):
        self.beliefs: dict[str, Belief] = {}
        self.trace: list[str] = []
        self.resolver = ContradictionResolver()

    def add_fact(self, fact: Fact) -> None:
        key = str(fact)
        if key not in self.beliefs:
            self.beliefs[key] = Belief(fact=fact)
            self._check_contradictions(fact)

    def add_facts(self, facts: list[Fact]) -> None:
        for f in facts:
            self.add_fact(f)

    def retract(self, fact: Fact) -> None:
        key = str(fact)
        if key not in self.beliefs:
            return
        remaining = [
            b.fact for k, b in self.beliefs.items()
            if k != key and b.fact.source == Source.USER
        ]
        self.beliefs.clear()
        self.trace.clear()
        self.add_facts(remaining)
        self.infer()

    def infer(self, max_iterations: int = 1000) -> list[Fact]:
        """Run forward chaining until no new facts can be deduced or max iterations reached."""
        all_new_facts: list[Fact] = []
        for _ in range(max_iterations):
            new_facts: list[Fact] = []
            facts_list = list(self.beliefs.values())

            for b in facts_list:
                f = b.fact
                results = self._apply_rules(f, facts_list)
                for result in results:
                    key = str(result)
                    if key not in self.beliefs:
                        rule_name = self._get_rule_name(f, result)
                        proof = f"[{rule_name}] {b.fact} -> {result}"
                        self.beliefs[key] = Belief(fact=result, proof_chain=[proof])
                        new_facts.append(result)
                        all_new_facts.append(result)
                        self.trace.append(proof)

            if not new_facts:
                break

        return all_new_facts

    def _get_rule_name(self, source_fact: Fact, result: Fact) -> str:
        """Determine which rule produced this result."""
        if result.predicate == "is" and source_fact.predicate == "implies":
            return "modus_ponens"
        if result.predicate == "not_is" and source_fact.predicate == "implies":
            return "modus_tollens"
        if result.predicate == "implies" and source_fact.predicate == "implies":
            return "transitivity"
        if result.predicate == "implies" and source_fact.predicate == "is":
            return "subtype_transitivity"
        if result.predicate == "is" and source_fact.predicate == "is":
            return "is_transitivity"
        if result.predicate == "is" and source_fact.predicate == "all_are":
            return "universal_instantiation"
        if source_fact.predicate == "equals":
            return "equality_substitution"
        if result.predicate == "is" and source_fact.predicate == "or":
            return "disjunctive_syllogism"
        if result.predicate == "contradiction":
            return "contradiction_detection"
        if result.predicate == "not_is" and source_fact.predicate == "not_and":
            return "de_morgan_and"
        if result.predicate == "not_is" and source_fact.predicate == "not_or":
            return "de_morgan_or"
        if result.predicate == "is" and source_fact.predicate == "not_not":
            return "double_negation"
        if result.predicate == "implies" and source_fact.predicate == "assumes":
            return "conditional_proof"
        if result.predicate == "all_are":
            return "universal_generalization"
        return "unknown"

    def _apply_rules(self, fact: Fact, all_beliefs: list[Belief]) -> list[Fact]:
        results: list[Fact] = []
        all_facts = [b.fact for b in all_beliefs]

        if fact.predicate == "implies":
            for other in all_facts:
                r = modus_ponens(fact, other)
                if r:
                    results.append(r)
                r = transitivity(fact, other)
                if r:
                    results.append(r)
            for other in all_facts:
                r = modus_tollens(fact, other)
                if r:
                    results.append(r)

        if fact.predicate == "is":
            r = existential_generalization(fact)
            if r:
                results.append(r)
            for other in all_facts:
                r = subtype_transitivity(fact, other)
                if r:
                    results.append(r)
                r = is_transitivity(fact, other)
                if r:
                    results.append(r)

        if fact.predicate == "all_are":
            for other in all_facts:
                r = universal_instantiation(fact, other)
                if r:
                    results.append(r)
            r = universal_generalization(fact)
            if r:
                results.append(r)

        if fact.predicate == "equals":
            for other in all_facts:
                results.extend(equality_substitution(fact, other))

        if fact.predicate == "or":
            for other in all_facts:
                r = disjunctive_syllogism(fact, other)
                if r:
                    results.append(r)

        if fact.predicate == "not_and":
            results.extend(de_morgan_and(fact))

        if fact.predicate == "not_or":
            results.extend(de_morgan_or(fact))

        if fact.predicate == "not_not":
            r = double_negation(fact)
            if r:
                results.append(r)

        if fact.predicate == "assumes":
            for other in all_facts:
                r = conditional_proof(fact, other)
                if r:
                    results.append(r)

        for other in all_facts:
            r = contradiction_detection(fact, other)
            if r:
                results.append(r)

        return results

    def _check_contradictions(self, new_fact: Fact) -> None:
        """Check if new fact contradicts any existing belief."""
        for key, belief in self.beliefs.items():
            if key == str(new_fact):
                continue
            contradiction = contradiction_detection(new_fact, belief.fact)
            if contradiction:
                self.add_fact(contradiction)

    def query(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,
    ) -> list[Belief]:
        """Query beliefs by subject, predicate, and/or object."""
        results = []
        for belief in self.beliefs.values():
            if subject and belief.fact.subject != subject:
                continue
            if predicate and belief.fact.predicate != predicate:
                continue
            if object and belief.fact.object != object:
                continue
            results.append(belief)
        return results

    def get_trace(self) -> list[str]:
        return list(self.trace)
