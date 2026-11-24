"""ADAM's memory on the Yewtree engine (Stage 4.1, #46).

This is the only module in ADAM that imports the engine (`agent_memory`). The kernel never sees it; the rest of
ADAM uses `memory.store_contract.FactStore`.

**How ADAM's data maps onto the engine** (decision DSM.1: the engine stores, ADAM decides what it means):
- **A fact** is an `adam.fact` record keyed by its fact key. Its fields: the integer `id` ADAM's routes and
  vector index use, the triple, confidence, source, timestamp, text, origins, any pre-derivation proof
  chain, and `superseded_by`. Each change is a new version; nothing is overwritten.
- **A derivation** is an `adam.derivation` record (rule, rule version, ordered premises, confidence) with
  links whose basis is `recorded`: `based_on` to each premise, and `supports` to its conclusion.
- **Sources, passages, skills and traces** are `adam.source`, `adam.passage`, `adam.skill` and `adam.trace`
  records; a body (a book's text, a passage) is archived, compressed and encrypted.

The store is opened with project id `adam`, so its key file is `adam.key` in the engine's key folder, and a
copied store opens anywhere on the same machine.
"""
from __future__ import annotations

import time
from importlib import metadata
from pathlib import Path

from agent_memory import Store
from kernel.facts import Fact, Source
from memory.store_contract import (DERIVED, RECORD_KINDS, TraceMixin, UnderivedFactError, check_derived,
                                   fact_key)

FACT, DERIVATION = "adam.fact", "adam.derivation"
FACT_INDEX = ["id", "key", "subject", "predicate", "object", "source"]
DERIVATION_INDEX = ["id", "conclusion_id"]
SESSION, WRITER, AGENT = "adam", "adam:memory", "adam"
PROJECT_ID = "adam"


def _fact(fields: dict) -> Fact:
    return Fact(subject=fields["subject"], predicate=fields["predicate"], object=fields["object"],
                confidence=fields["confidence"], source=Source(fields["source"]), timestamp=fields["timestamp"])


class EngineStore(TraceMixin):
    backend = "engine"
    supports_records = True

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._engine = Store(self.path, project_id=PROJECT_ID, profiles=["generic"])
        # An index of the current fields, read once here and kept in step with every write this object
        # makes, so lookups and merges don't go back to the engine. One ADAM process owns a store.
        self._by_key: dict[str, dict] = {}
        self._key_of_id: dict[int, str] = {}     # in id order: ids are given out in increasing order
        self._text_lower: dict[int, str] = {}
        self._ids_by: dict[str, dict[str, list[int]]] = {f: {} for f in ("subject", "predicate", "object",
                                                                          "source")}
        self._derivations: dict[str, dict] = {}
        self._derivations_by_conclusion: dict[int, list[str]] = {}
        facts = sorted((r["fields"] for r in self._engine.records(FACT, include_retired=True)),
                       key=lambda f: f["id"])
        for fields in facts:
            self._remember(fields)
        derivations = self._engine.records(DERIVATION, include_retired=True)
        for rec in sorted(derivations, key=lambda r: r["fields"]["id"]):
            self._remember_derivation(rec["key"], rec["fields"])
        self._next_id = max(self._key_of_id, default=0) + 1
        self._next_derivation = max((r["fields"]["id"] for r in derivations), default=0) + 1
        self._count = len(facts)
        self._derivation_count = len(derivations)

    # ------------------------------------------------------------ helpers
    def _remember(self, fields: dict) -> None:
        """Keep a fact's current fields in the index (after the engine has stored them)."""
        key, fid = fields["key"], fields["id"]
        if fid not in self._key_of_id:     # the triple, source and text never change, so they're indexed once
            for name, by in self._ids_by.items():
                by.setdefault(fields[name], []).append(fid)
            self._text_lower[fid] = (fields["fact_text"] or "").lower()
        self._key_of_id[fid] = key
        self._by_key[key] = fields

    def _remember_derivation(self, dkey: str, fields: dict) -> None:
        if dkey not in self._derivations:
            self._derivations_by_conclusion.setdefault(fields["conclusion_id"], []).append(dkey)
        self._derivations[dkey] = fields

    def _current(self, key: str) -> dict | None:
        return self._by_key.get(key)

    def _by_id(self, fact_id: int) -> dict | None:
        key = self._key_of_id.get(fact_id)
        return self._by_key[key] if key is not None else None

    def _put(self, items: list[dict], links=()) -> None:
        # The index already knows which items changed, so the engine needn't look each one up again.
        self._engine.put_records(items, SESSION, WRITER, agent=AGENT, links=links, check_unchanged=False)

    def _merge(self, fact: Fact, proof_chain, existing: dict | None) -> tuple[dict, bool]:
        """A fact's fields after storing it (higher confidence, newer timestamp, origins added), and whether
        it's new: the same rules as the original store."""
        if existing is not None:
            fields = dict(existing)
            fields["confidence"] = max(fields["confidence"], fact.confidence)
            fields["timestamp"] = max(fields["timestamp"] or 0, fact.timestamp or 0)
            if fields.get("proof_chain") is None and proof_chain:
                fields["proof_chain"] = list(proof_chain)
            if fact.origin and fact.origin not in fields["origins"]:
                fields["origins"] = sorted([*fields["origins"], fact.origin])
            return fields, False
        fields = {"id": self._next_id, "key": fact_key(fact), "subject": fact.subject, "predicate": fact.predicate,
                  "object": fact.object, "confidence": fact.confidence, "source": fact.source.value,
                  "timestamp": fact.timestamp, "fact_text": str(fact),
                  "proof_chain": list(proof_chain) if proof_chain else None,
                  "origins": [fact.origin] if fact.origin else [], "superseded_by": None}
        self._next_id += 1
        self._count += 1
        return fields, True

    @staticmethod
    def _item(fields: dict) -> dict:
        return {"type": FACT, "key": fields["key"], "fields": fields, "index": FACT_INDEX}

    def _facts(self) -> list[dict]:
        return [self._by_key[key] for key in self._key_of_id.values()]

    def _find(self, field: str, value: str) -> list[Fact]:
        return [_fact(self._by_id(i)) for i in self._ids_by[field].get(value, [])]

    # ------------------------------------------------------------ facts
    def upsert(self, fact: Fact, proof_chain: list[str] | None = None) -> tuple[int, bool]:
        """Store a fact once. Returns (id, created). Storing it again keeps the higher confidence, the newer
        timestamp and any proof chain already recorded, and adds its origin."""
        if fact.source == DERIVED:
            raise UnderivedFactError(
                f"{fact} is derived; store it with its derivations (store_derived), "
                "so it keeps a path back to its inputs")
        next_id, count = self._next_id, self._count
        existing = self._current(fact_key(fact))
        fields, created = self._merge(fact, proof_chain, existing)
        if fields == existing:             # nothing changed: store nothing
            return fields["id"], False
        try:
            self._put([self._item(fields)])
        except BaseException:
            self._next_id, self._count = next_id, count
            raise
        self._remember(fields)
        return fields["id"], created

    def store(self, fact: Fact, proof_chain: list[str] | None = None) -> int:
        return self.upsert(fact, proof_chain)[0]

    def get(self, fact_id: int) -> Fact | None:
        fields = self._by_id(fact_id)
        return _fact(fields) if fields else None

    def get_with_proof(self, fact_id: int) -> tuple[Fact, list[str]] | None:
        fields = self._by_id(fact_id)
        if fields is None:
            return None
        fact = _fact(fields)
        if fact.source == DERIVED:
            return fact, self.render_trace(fact_id)
        return fact, list(fields.get("proof_chain") or [])

    def has(self, fact: Fact) -> bool:
        return self._current(fact_key(fact)) is not None

    def all_keys(self) -> set[str]:
        return set(self._by_key)

    def get_all(self) -> list[Fact]:
        return [_fact(f) for f in self._facts()]

    def get_all_with_ids(self) -> list[tuple[int, Fact]]:
        return [(f["id"], _fact(f)) for f in self._facts()]

    def find_by_subject(self, subject: str) -> list[Fact]:
        return self._find("subject", subject)

    def find_by_predicate(self, predicate: str) -> list[Fact]:
        return self._find("predicate", predicate)

    def find_by_object(self, obj: str) -> list[Fact]:
        return self._find("object", obj)

    def get_user_facts(self) -> list[Fact]:
        return self._find("source", Source.USER.value)

    def search_text(self, query: str) -> list[Fact]:
        """Facts whose text contains the query, ignoring case (as the original store's LIKE does)."""
        needle = query.lower()
        return [_fact(self._by_id(i)) for i, text in self._text_lower.items() if needle in text]

    def count(self) -> int:
        return self._count

    def count_by_source(self) -> dict[str, int]:
        return {source: len(ids) for source, ids in self._ids_by["source"].items()}

    # ------------------------------------------------------------ supersession and origins
    def supersede(self, fact: Fact, by_id: int) -> int | None:
        """Mark a stored fact as replaced by another. Nothing is deleted; the mark is a new version."""
        fields = self._current(fact_key(fact))
        if fields is None:
            return None
        if fields.get("superseded_by") != by_id:
            changed = dict(fields, superseded_by=by_id)
            self._put([self._item(changed)])
            self._remember(changed)
        return fields["id"]

    def superseded_ids(self) -> set[int]:
        return {f["id"] for f in self._facts() if f.get("superseded_by") is not None}

    def origins_of(self, fact_id: int) -> list[str]:
        fields = self._by_id(fact_id)
        return sorted(fields["origins"]) if fields else []

    def all_origins(self) -> dict[int, list[str]]:
        return {f["id"]: sorted(f["origins"]) for f in self._facts() if f["origins"]}

    # ------------------------------------------------------------ derivations
    def store_derived(self, entries: list[tuple[Fact, list[dict]]]) -> list[tuple[int, bool]]:
        """Store facts and their derivations in one transaction. Returns (id, created) per entry.

        Each entry is (fact, derivations); a derivation is a dict with "rule", "rule_version", "premises" (the
        premise Facts, in order) and "confidence". Premises are stored too if they aren't yet; a derived
        premise must itself be an entry. Storing the same derivation again keeps the higher confidence.
        """
        check_derived(entries)
        pending: dict[str, dict] = {}          # key -> fields, as this batch leaves them
        order: list[str] = []
        key_of: dict[int, str] = {}            # fact id -> key, for the links
        next_id, count, next_derivation = self._next_id, self._count, self._next_derivation

        def upsert(fact: Fact) -> tuple[int, bool]:
            key = fact_key(fact)
            existing = pending.get(key) if key in pending else self._current(key)
            fields, created = self._merge(fact, None, existing)
            if key not in pending:
                order.append(key)
            pending[key] = fields
            key_of[fields["id"]] = key
            return fields["id"], created

        try:
            results = [upsert(fact) for fact, _ in entries]
            links, now, new_derivations = [], time.time(), 0
            pending_derivations: dict[str, dict] = {}
            for (fact, derivations), (conclusion_id, _) in zip(entries, results):
                for d in derivations:
                    premise_ids = [upsert(p)[0] for p in d["premises"]]
                    premise_set = sorted(set(premise_ids))
                    dkey = f"{conclusion_id}|{d['rule']}|{premise_set}"
                    existing = pending_derivations.get(dkey) or self._derivations.get(dkey)
                    if existing is not None:
                        pending_derivations[dkey] = dict(existing, confidence=max(existing["confidence"],
                                                                                   d["confidence"]))
                        continue
                    fields = {"id": self._next_derivation, "conclusion_id": conclusion_id, "rule": d["rule"],
                              "rule_version": d["rule_version"], "premise_ids": premise_ids,
                              "premise_set": premise_set, "confidence": d["confidence"], "timestamp": now}
                    self._next_derivation += 1
                    new_derivations += 1
                    pending_derivations[dkey] = fields
                    rid = Store.record_id(DERIVATION, dkey)
                    links.append({"from": rid, "to": Store.record_id(FACT, key_of[conclusion_id]),
                                  "type": "supports", "basis": "recorded", "attrs": {"rule": d["rule"]}})
                    for position, pid in enumerate(premise_ids):
                        links.append({"from": rid, "to": Store.record_id(FACT, key_of[pid]),
                                      "type": "based_on", "basis": "recorded", "attrs": {"position": position}})
            # Only what this batch changed is stored; a fact or derivation it left as it was isn't.
            changed_facts = [k for k in order if pending[k] != self._by_key.get(k)]
            changed_derivations = [k for k, f in pending_derivations.items() if f != self._derivations.get(k)]
            items = [self._item(pending[k]) for k in changed_facts]
            items += [{"type": DERIVATION, "key": k, "fields": pending_derivations[k], "index": DERIVATION_INDEX}
                      for k in changed_derivations]
            if items or links:
                self._put(items, links)
        except BaseException:
            # Nothing was stored (one transaction): give the ids and counts back.
            self._next_id, self._count, self._next_derivation = next_id, count, next_derivation
            raise
        for k in changed_facts:
            self._remember(pending[k])
        for k in changed_derivations:
            self._remember_derivation(k, pending_derivations[k])
        self._derivation_count += new_derivations
        return results

    def derivations_of(self, fact_id: int) -> list[dict]:
        rows = [self._derivations[k] for k in self._derivations_by_conclusion.get(fact_id, [])]
        return [{"id": f["id"], "rule": f["rule"], "rule_version": f["rule_version"],
                 "premise_ids": list(f["premise_ids"]), "confidence": f["confidence"], "timestamp": f["timestamp"]}
                for f in rows]

    def underived(self) -> list[int]:
        """Ids of derived facts with no derivation. The engine store refuses them, so this stays empty."""
        return [f["id"] for f in self._facts()
                if f["source"] == DERIVED.value and not self._derivations_by_conclusion.get(f["id"])]

    def count_derivations(self) -> int:
        return self._derivation_count

    # ------------------------------------------------------------ records: sources, passages, skills, traces
    @staticmethod
    def _kind(kind: str) -> str:
        if kind not in RECORD_KINDS:
            raise ValueError(f"record kind must be one of {RECORD_KINDS}")
        return f"adam.{kind}"

    def put_record(self, kind: str, key: str, fields: dict, body: bytes | str | None = None) -> str:
        return self._engine.put_record(self._kind(kind), key, fields, SESSION, WRITER, body=body, agent=AGENT)

    def get_record(self, kind: str, key: str) -> dict | None:
        return self._engine.get_record(Store.record_id(self._kind(kind), key))

    def records(self, kind: str) -> list[dict]:
        return self._engine.records(self._kind(kind))

    def record_body(self, kind: str, key: str) -> bytes | None:
        return self._engine.record_body(Store.record_id(self._kind(kind), key))

    # ------------------------------------------------------------ the store itself
    def meta(self) -> dict[str, str]:
        try:
            engine = metadata.version("yewtree")
        except metadata.PackageNotFoundError:
            engine = "unknown"
        return {"backend": self.backend, "engine": f"yewtree {engine}", "path": str(self.path)}

    def verify(self) -> dict:
        """The engine's integrity check of this store."""
        return self._engine.verify()

    def location(self) -> str:
        return str(self.path)

    def export_to(self, archive: str | Path) -> None:
        """A consistent backup of the store (tar.gz), without its key (the key stays in the key folder)."""
        self._engine.export(archive)

    @classmethod
    def import_from(cls, archive: str | Path, path: str | Path) -> "EngineStore":
        """Open a store from a backup, unpacking it into `path` first if that folder is new."""
        from agent_memory.storage import import_backup
        target = Path(path)
        if not target.exists() or not any(p.name != ".gitignore" for p in target.iterdir()):
            import_backup(archive, target)
        return cls(target)

    def close(self) -> None:
        pass
