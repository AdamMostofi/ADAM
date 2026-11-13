"""The engine never imports ADAM (Phase 2 decision, #47).

CI also runs this package's tests in its own environment, where ADAM isn't
installed, which proves the package runs with ADAM absent.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
ADAM_TOP_LEVEL = {"kernel", "memory", "learning", "interface", "scripts", "tests"}


def test_no_source_file_imports_adam():
    for path in (PACKAGE / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(), str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in ADAM_TOP_LEVEL, f"{path.name} imports {name}"


def test_importing_the_engine_loads_no_adam_module():
    code = ("import sys, agent_memory, agent_memory.cli; "
            f"bad = [m for m in sys.modules if m.split('.')[0] in {sorted(ADAM_TOP_LEVEL - {'tests'})!r}]; "
            "print(bad); sys.exit(1 if bad else 0)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=PACKAGE)
    assert result.returncode == 0, result.stdout + result.stderr
