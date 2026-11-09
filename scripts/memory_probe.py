"""Standard-library memory probe for ADAM processes (Linux /proc only).

Reports, for a process and every process it started:
- RSS: resident memory, counting shared libraries in full for each process.
- PSS: resident memory with shared pages split between the processes using them.
- HWM: the process's peak RSS so far.

The budget (docs/design/memory-budget.md) is checked against total RSS,
which is the conservative figure; PSS is recorded alongside it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

KB = 1024


@dataclass
class ProcessMemory:
    pid: int
    name: str
    rss_kb: int
    pss_kb: int | None
    hwm_kb: int


@dataclass
class TreeMemory:
    processes: list[ProcessMemory] = field(default_factory=list)

    @property
    def total_rss_mb(self) -> float:
        return sum(p.rss_kb for p in self.processes) / KB

    @property
    def total_pss_mb(self) -> float | None:
        if any(p.pss_kb is None for p in self.processes):
            return None
        return sum(p.pss_kb for p in self.processes) / KB

    @property
    def main_rss_mb(self) -> float:
        return self.processes[0].rss_kb / KB if self.processes else 0.0

    def as_dict(self) -> dict:
        return {
            "total_rss_mb": round(self.total_rss_mb, 1),
            "total_pss_mb": None if self.total_pss_mb is None else round(self.total_pss_mb, 1),
            "main_rss_mb": round(self.main_rss_mb, 1),
            "processes": [
                {"pid": p.pid, "name": p.name, "rss_mb": round(p.rss_kb / KB, 1),
                 "pss_mb": None if p.pss_kb is None else round(p.pss_kb / KB, 1),
                 "hwm_mb": round(p.hwm_kb / KB, 1)}
                for p in self.processes
            ],
        }


def _status_fields(pid: int) -> dict[str, str]:
    fields = {}
    with open(f"/proc/{pid}/status", encoding="utf-8") as handle:
        for line in handle:
            key, _, value = line.partition(":")
            fields[key] = value.strip()
    return fields


def _kb(value: str) -> int:
    return int(value.split()[0]) if value else 0


def _pss_kb(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/smaps_rollup", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("Pss:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def children(pid: int) -> list[int]:
    """Direct children of a process."""
    result = []
    task_dir = f"/proc/{pid}/task"
    try:
        tasks = os.listdir(task_dir)
    except OSError:
        return result
    for tid in tasks:
        try:
            with open(f"{task_dir}/{tid}/children", encoding="utf-8") as handle:
                result.extend(int(c) for c in handle.read().split())
        except OSError:
            continue
    return result


def descendants(pid: int) -> list[int]:
    out, stack = [], children(pid)
    while stack:
        child = stack.pop()
        out.append(child)
        stack.extend(children(child))
    return out


def process_memory(pid: int) -> ProcessMemory | None:
    try:
        fields = _status_fields(pid)
    except OSError:
        return None
    return ProcessMemory(
        pid=pid,
        name=fields.get("Name", "?"),
        rss_kb=_kb(fields.get("VmRSS", "")),
        pss_kb=_pss_kb(pid),
        hwm_kb=_kb(fields.get("VmHWM", "")),
    )


def tree_memory(pid: int | None = None) -> TreeMemory:
    """Memory of `pid` (default: this process) and all its descendants."""
    pid = os.getpid() if pid is None else pid
    tree = TreeMemory()
    for p in [pid] + descendants(pid):
        info = process_memory(p)
        if info is not None:
            tree.processes.append(info)
    return tree


def budget_violations(states: dict[str, float], budget_mb: float, enforced: tuple[str, ...]) -> list[str]:
    """States whose total RSS exceeds the budget. Only `enforced` states count."""
    return [
        f"{state}: {states[state]:.1f} MB exceeds the {budget_mb:.0f} MB budget"
        for state in enforced
        if state in states and states[state] > budget_mb
    ]
