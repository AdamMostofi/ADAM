"""Tests for scripts/memory_probe.py: the /proc probe and the budget check."""
import os
import subprocess
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))

import memory_probe as mp

linux_only = pytest.mark.skipif(not os.path.exists("/proc/self/status"), reason="needs Linux /proc")


@linux_only
def test_probe_reads_this_process():
    tree = mp.tree_memory()
    assert tree.processes[0].pid == os.getpid()
    assert tree.total_rss_mb > 1
    assert tree.processes[0].hwm_kb >= tree.processes[0].rss_kb


@linux_only
def test_probe_counts_child_processes():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        for _ in range(50):
            if child.pid in mp.descendants(os.getpid()):
                break
            time.sleep(0.1)
        tree = mp.tree_memory()
        assert child.pid in [p.pid for p in tree.processes]
        assert tree.total_rss_mb > tree.main_rss_mb
    finally:
        child.kill()
        child.wait()


def test_budget_violation_reported_for_enforced_state():
    states = {"startup": 210.0, "chat": 565.0, "ingest": 900.0}
    violations = mp.budget_violations(states, 400, ("startup", "chat"))
    assert violations == ["chat: 565.0 MB exceeds the 400 MB budget"]


def test_unenforced_states_never_fail_the_budget():
    assert mp.budget_violations({"ingest": 900.0, "peak": 950.0}, 400, ("startup", "chat")) == []


def test_within_budget_has_no_violations():
    assert mp.budget_violations({"startup": 200.0, "chat": 399.9}, 400, ("startup", "chat")) == []
