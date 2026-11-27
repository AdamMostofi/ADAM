"""The storage contract (Stage 4.1, #46): every operation ADAM's memory needs from a store.

ADAM's core, routes and memory layer talk to storage only through this contract. Two stores implement it:
- `memory.engine_store.EngineStore`, on the Yewtree memory engine (the default);
- `memory.exact_store.ExactStore`, the original SQLite store (`ADAM_STORE=exact`).

The same contract tests run against both (`tests/contract/`).

**What a store keeps:**
- **Facts:** one per (subject, predicate, object, source), compared ignoring case and extra spaces. Storing
  a fact again keeps the higher confidence and the newer timestamp, and adds its origin. Facts get integer
  ids, in the order they were first stored.
- **Derivations** (Stage 1.4): a derived fact is stored only with at least one derivation naming its rule,
  rule version, ordered premises and confidence. Storing the same derivation again keeps the higher
  confidence.
- **Supersession:** a fact replaced by another stays, marked with the id that replaced it. Nothing is deleted.
- **Records** (sources, passages, skills, traces): versioned records with a key, fields and an optional body.
  Fields named in `index` can be looked up with `find_records`. `put_records` stores many records in one
  transaction, all or none; each item is {kind, key, fields, body?, index?}. A put that changes nothing stores
  nothing. A body is stored as the engine keeps it: anything shaped like a secret is redacted first, so a
  caller that needs exact text reads the body back. Only stores with `supports_records` keep records; the
  original SQLite store doesn't.

**Decision DSM.1:** the store keeps and retrieves. What a fact means, and what ADAM believes, stays in ADAM.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from kernel.facts import Fact, Source

DERIVED = Source.DEDUCED
RECORD_KINDS = ("source", "passage", "skill", "trace")


class UnderivedFactError(ValueError):
    """A derived fact was stored without any derivation."""


class RecordsNotSupported(NotImplementedError):
    """This store keeps facts and derivations only (the original SQLite store)."""


def normalize_term(term: str) -> str:
    """Case- and whitespace-insensitive form of a term, used only for the uniqueness key."""
    return " ".join(term.split()).lower()


def fact_key(fact: Fact) -> str:
    """One key per (subject, predicate, object, source), ignoring case and extra spaces."""
    parts = (normalize_term(fact.subject), normalize_term(fact.predicate),
             normalize_term(fact.object), fact.source.value)
    return "\x1f".join(parts)


def check_derived(entries: list[tuple[Fact, list[dict]]]) -> None:
    """Refuse a batch in which a derived fact, or a derived premise, would arrive without a derivation."""
    derived_keys = {fact_key(f) for f, derivations in entries if derivations}
    for fact, derivations in entries:
        if fact.source == DERIVED and not derivations:
            raise UnderivedFactError(f"{fact} is derived but has no derivation")
        for d in derivations:
            for premise in d["premises"]:
                if premise.source == DERIVED and fact_key(premise) not in derived_keys:
                    raise UnderivedFactError(f"premise {premise} of {fact} is derived but not stored with it")


@runtime_checkable
class FactStore(Protocol):
    backend: str
    supports_records: bool

    # facts
    def upsert(self, fact: Fact, proof_chain: list[str] | None = None) -> tuple[int, bool]: ...
    def store(self, fact: Fact, proof_chain: list[str] | None = None) -> int: ...
    def get(self, fact_id: int) -> Fact | None: ...
    def get_with_proof(self, fact_id: int) -> tuple[Fact, list[str]] | None: ...
    def has(self, fact: Fact) -> bool: ...
    def id_of(self, fact: Fact) -> int | None: ...
    def all_keys(self) -> set[str]: ...
    def get_all(self) -> list[Fact]: ...
    def get_all_with_ids(self) -> list[tuple[int, Fact]]: ...
    def find_by_subject(self, subject: str) -> list[Fact]: ...
    def find_by_predicate(self, predicate: str) -> list[Fact]: ...
    def find_by_object(self, obj: str) -> list[Fact]: ...
    def get_user_facts(self) -> list[Fact]: ...
    def search_text(self, query: str) -> list[Fact]: ...
    def count(self) -> int: ...
    def count_by_source(self) -> dict[str, int]: ...
    # supersession and origins
    def supersede(self, fact: Fact, by_id: int) -> int | None: ...
    def superseded_ids(self) -> set[int]: ...
    def origins_of(self, fact_id: int) -> list[str]: ...
    def all_origins(self) -> dict[int, list[str]]: ...
    # derivations
    def store_derived(self, entries: list[tuple[Fact, list[dict]]]) -> list[tuple[int, bool]]: ...
    def derivations_of(self, fact_id: int) -> list[dict]: ...
    def trace(self, fact_id: int) -> list[dict] | None: ...
    def render_trace(self, fact_id: int) -> list[str]: ...
    def underived(self) -> list[int]: ...
    def count_derivations(self) -> int: ...
    # records: sources, passages, skills, traces (stores with supports_records)
    def put_record(self, kind: str, key: str, fields: dict, body: bytes | str | None = None,
                   index: tuple[str, ...] = ()) -> str: ...
    def put_records(self, items: list[dict]) -> list[str]: ...
    def get_record(self, kind: str, key: str) -> dict | None: ...
    def records(self, kind: str) -> list[dict]: ...
    def find_records(self, kind: str, **equals) -> list[dict]: ...
    def record_body(self, kind: str, key: str) -> bytes | None: ...
    # the store itself
    def meta(self) -> dict[str, str]: ...
    def close(self) -> None: ...


class TraceMixin:
    """Walking a fact back to its inputs, shared by every store, from `get()` and `derivations_of()` alone."""

    def trace(self, fact_id: int) -> list[dict] | None:
        """Walk a fact back to the inputs it rests on.

        Returns steps, inputs first: {"id", "fact", "derivation"} where
        "derivation" is None for an input (any fact not derived) and
        otherwise the derivation used, whose premises all appear earlier.
        The walk is well-founded, so cycles among derivations can't trap it.
        Returns None if the fact doesn't exist, or if a derived fact has no
        derivation that reaches inputs (see underived()).
        """
        facts: dict[int, Fact] = {}
        derivations: dict[int, list[dict]] = {}
        stack = [fact_id]
        while stack:
            current = stack.pop()
            if current in facts:
                continue
            fact = self.get(current)
            if fact is None:
                return None
            facts[current] = fact
            if fact.source == DERIVED:
                derivations[current] = self.derivations_of(current)
                for d in derivations[current]:
                    stack.extend(d["premise_ids"])
        explained: dict[int, dict | None] = {i: None for i, f in facts.items() if f.source != DERIVED}
        order = sorted(explained)
        while fact_id not in explained:
            ready = []
            for i in sorted(set(facts) - set(explained)):
                usable = [d for d in derivations[i] if all(p in explained for p in d["premise_ids"])]
                if usable:
                    ready.append((i, max(usable, key=lambda d: (d["confidence"], -d["id"]))))
            if not ready:
                return None
            for i, d in ready:
                explained[i] = d
                order.append(i)
        used, stack = set(), [fact_id]
        while stack:
            i = stack.pop()
            if i not in used:
                used.add(i)
                if explained[i] is not None:
                    stack.extend(explained[i]["premise_ids"])
        return [{"id": i, "fact": facts[i], "derivation": explained[i]} for i in order if i in used]

    def render_trace(self, fact_id: int) -> list[str]:
        """trace() as readable lines, rendered from the records."""
        steps = self.trace(fact_id) or []
        by_id = {s["id"]: s["fact"] for s in steps}
        lines = []
        for step in steps:
            d = step["derivation"]
            if d is None:
                lines.append(f"[given] {step['fact']}")
            else:
                premises = " + ".join(str(by_id[p]) for p in d["premise_ids"])
                lines.append(f"[{d['rule']}] {premises} -> {step['fact']}")
        return lines
