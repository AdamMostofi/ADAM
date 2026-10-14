"""Forward-chaining inference engine with predicate-indexed agenda.

Uses a work queue (agenda) and predicate indexing to achieve O(n) inference
instead of O(n^3). Thread-safe via RLock.
"""

from __future__ import annotations

import collections
import threading

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
        self.lock = threading.RLock()
        self.agenda: collections.deque[Fact] = collections.deque()
        self.index: dict[str, set[str]] = {
            "implies": set(),
            "is": set(),
            "all_are": set(),
            "equals": set(),
            "or": set(),
            "not_is": set(),
            "not_and": set(),
            "not_or": set(),
            "not_not": set(),
            "assumes": set(),
            "derives": set(),
            "contradiction": set(),
        }

    def add_fact(self, fact: Fact) -> None:
        with self.lock:
            key = str(fact)
            if key not in self.beliefs:
                self.beliefs[key] = Belief(fact=fact)
                self.index[fact.predicate].add(key)
                self.agenda.append(fact)
                self._check_contradictions(fact)

    def add_facts(self, facts: list[Fact]) -> None:
        for f in facts:
            self.add_fact(f)

    def retract(self, fact: Fact) -> None:
        with self.lock:
            key = str(fact)
            if key not in self.beliefs:
                return
            remaining = [
                b.fact for k, b in self.beliefs.items()
                if k != key and b.fact.source == Source.USER
            ]
            self.beliefs.clear()
            self.trace.clear()
            self.agenda.clear()
            for pred_set in self.index.values():
                pred_set.clear()
            self.add_facts(remaining)
            self.infer()

    def infer(self, max_iterations: int = 10000) -> list[Fact]:
        with self.lock:
            all_new_facts: list[Fact] = []
            iterations = 0
            while self.agenda and iterations < max_iterations:
                fact = self.agenda.popleft()
                results = self._apply_rules_indexed(fact)
                for result in results:
                    key = str(result)
                    if key not in self.beliefs:
                        rule_name = self._get_rule_name(fact, result)
                        proof = f"[{rule_name}] {fact} -> {result}"
                        self.beliefs[key] = Belief(fact=result, proof_chain=[proof])
                        self.index[result.predicate].add(key)
                        self.agenda.append(result)
                        all_new_facts.append(result)
                        self.trace.append(proof)
                iterations += 1
            return all_new_facts

    def _apply_rules_indexed(self, fact: Fact) -> list[Fact]:
        results: list[Fact] = []

        if fact.predicate == "implies":
            for other_key in self.index["is"]:
                other = self.beliefs[other_key].fact
                r = modus_ponens(fact, other)
                if r:
                    results.append(r)
            for other_key in self.index["implies"]:
                other = self.beliefs[other_key].fact
                r = transitivity(fact, other)
                if r:
                    results.append(r)
            for other_key in self.index["not_is"]:
                other = self.beliefs[other_key].fact
                r = modus_tollens(fact, other)
                if r:
                    results.append(r)

        if fact.predicate == "is":
            r = existential_generalization(fact)
            if r:
                results.append(r)
            for other_key in self.index["implies"]:
                other = self.beliefs[other_key].fact
                r = subtype_transitivity(fact, other)
                if r:
                    results.append(r)
            for other_key in self.index["is"]:
                other = self.beliefs[other_key].fact
                r = is_transitivity(fact, other)
                if r:
                    results.append(r)

        if fact.predicate == "all_are":
            for other_key in self.index["is"]:
                other = self.beliefs[other_key].fact
                r = universal_instantiation(fact, other)
                if r:
                    results.append(r)
            r = universal_generalization(fact)
            if r:
                results.append(r)

        if fact.predicate == "equals":
            for other_key in self.index["is"]:
                other = self.beliefs[other_key].fact
                results.extend(equality_substitution(fact, other))
            for other_key in self.index["equals"]:
                other = self.beliefs[other_key].fact
                results.extend(equality_substitution(fact, other))

        if fact.predicate == "or":
            for other_key in self.index["not_is"]:
                other = self.beliefs[other_key].fact
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
            for other_key in self.index["derives"]:
                other = self.beliefs[other_key].fact
                r = conditional_proof(fact, other)
                if r:
                    results.append(r)

        for other_key in self.index["is"]:
            other = self.beliefs[other_key].fact
            r = contradiction_detection(fact, other)
            if r:
                results.append(r)
        for other_key in self.index["not_is"]:
            other = self.beliefs[other_key].fact
            r = contradiction_detection(fact, other)
            if r:
                results.append(r)

        return results

    def _get_rule_name(self, source_fact: Fact, result: Fact) -> str:
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

    def _check_contradictions(self, new_fact: Fact) -> None:
        for key in self.index["is"]:
            if key == str(new_fact):
                continue
            belief = self.beliefs[key]
            contradiction = contradiction_detection(new_fact, belief.fact)
            if contradiction:
                self.add_fact(contradiction)
        for key in self.index["not_is"]:
            if key == str(new_fact):
                continue
            belief = self.beliefs[key]
            contradiction = contradiction_detection(new_fact, belief.fact)
            if contradiction:
                self.add_fact(contradiction)

    def query(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        object: str | None = None,
    ) -> list[Belief]:
        with self.lock:
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
        with self.lock:
            return list(self.trace)
