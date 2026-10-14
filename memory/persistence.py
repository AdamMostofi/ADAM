"""Persistence layer for MemorySystem.

Handles save/load of all 3 storage layers to disk.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3

from kernel.facts import Fact, Source
from memory.system import MemorySystem


def save(system: MemorySystem, path: str) -> None:
    os.makedirs(path, exist_ok=True)
    shutil.copy(system.exact.db_path, os.path.join(path, "memory.db"))
    graph_data = {
        "nodes": list(system.graph.get_all_nodes()),
        "edges": [(u, v, d) for u, v, d in system.graph.get_all_edges()],
    }
    with open(os.path.join(path, "graph.json"), "w") as f:
        json.dump(graph_data, f)


def load(path: str, lance_path: str = "adam_vectors.lance") -> MemorySystem:
    db_path = os.path.join(path, "memory.db")
    system = MemorySystem(db_path=db_path, lance_path=lance_path)
    graph_path = os.path.join(path, "graph.json")
    if os.path.exists(graph_path):
        with open(graph_path) as f:
            graph_data = json.load(f)
        for node in graph_data.get("nodes", []):
            system.graph.graph.add_node(node)
        for u, v, data in graph_data.get("edges", []):
            system.graph.graph.add_edge(u, v, **data)
    user_facts = system.exact.get_user_facts()
    system.engine.add_facts(user_facts)
    system.engine.infer()
    for fact in system.exact.get_all():
        system.graph.add_fact(fact)
    return system


def export_facts(system: MemorySystem, path: str) -> None:
    facts = system.exact.get_all()
    data = [
        {
            "subject": f.subject,
            "predicate": f.predicate,
            "object": f.object,
            "confidence": f.confidence,
            "source": f.source.value,
            "timestamp": f.timestamp,
        }
        for f in facts
    ]
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def import_facts(path: str, system: MemorySystem) -> int:
    with open(path) as f:
        data = json.load(f)
    count = 0
    for item in data:
        fact = Fact(
            subject=item["subject"],
            predicate=item["predicate"],
            object=item["object"],
            confidence=item.get("confidence", 1.0),
            source=Source(item.get("source", "user")),
            timestamp=item.get("timestamp", 0.0),
        )
        system.store(fact)
        count += 1
    return count
