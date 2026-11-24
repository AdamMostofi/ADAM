"""The storage boundary (Stage 4.1, #46).

- `memory/engine_store.py` is the only module in ADAM that imports the engine (`agent_memory`).
- The kernel imports nothing from the engine, nor from the memory layer.
- ADAM's core and web routes use the memory layer, never a store's internals.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("kernel", "memory", "learning", "interface")


def imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def modules():
    for package in PACKAGES:
        yield from (ROOT / package).rglob("*.py")


def test_only_the_engine_store_imports_the_engine():
    importers = sorted(str(p.relative_to(ROOT)) for p in modules()
                       if any(n == "agent_memory" or n.startswith("agent_memory.") for n in imports(p)))
    assert importers == ["memory/engine_store.py"]


def test_the_kernel_imports_neither_the_engine_nor_the_memory_layer():
    for path in (ROOT / "kernel").rglob("*.py"):
        bad = [n for n in imports(path) if n.split(".")[0] in ("agent_memory", "memory")]
        assert not bad, f"{path.relative_to(ROOT)} imports {bad}"


def test_core_and_routes_never_reach_into_a_store():
    for rel in ("interface/core.py", "interface/web/app.py"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for reach in ("memory.exact", "memory.fact_store", "memory.semantic.", "memory.graph.", "memory.graph\n",
                      "ExactStore", "EngineStore"):
            assert reach not in text, f"{rel} reaches into storage: {reach}"
