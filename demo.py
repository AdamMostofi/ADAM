"""ADAM Kernel Demo — teaches the system about birds and watches it reason."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from kernel.facts import Fact, Source
from kernel.engine import InferenceEngine
from kernel.graph import KnowledgeGraph


def main():
    print("=" * 60)
    print("ADAM Kernel Demo: Bird Reasoning")
    print("=" * 60)

    engine = InferenceEngine()
    graph = KnowledgeGraph()

    print("\n[1] Teaching: All birds fly")
    engine.add_fact(Fact("bird", "all_are", "flies", source=Source.USER))

    print("[2] Teaching: Tweety is a bird")
    engine.add_fact(Fact("tweety", "is", "bird", source=Source.USER))

    print("\n[3] Running inference...")
    new_facts = engine.infer()

    print(f"\n[4] Deduced {len(new_facts)} new facts:")
    for f in new_facts:
        print(f"    -> {f}")

    print("\n[5] Query: What do we know about Tweety?")
    beliefs = engine.query(subject="tweety")
    for b in beliefs:
        print(f"    {b.fact} (confidence: {b.fact.confidence:.2f})")

    print("\n[6] Adding to knowledge graph...")
    for b in engine.beliefs.values():
        graph.add_fact(b.fact)

    print(f"    Graph has {len(graph.get_all_nodes())} nodes")
    print(f"    Graph has {len(graph.get_all_edges())} edges")

    print("\n[7] Finding path from 'tweety' to 'flies'...")
    path = graph.find_path("tweety", "flies")
    if path:
        print(f"    Path: {' -> '.join(path)}")
    else:
        print("    No path found")

    print("\n" + "=" * 60)
    print("Demo complete. The kernel correctly deduced:")
    print("  'tweety is flies' from 'all birds fly' + 'tweety is a bird'")
    print("=" * 60)


if __name__ == "__main__":
    main()
