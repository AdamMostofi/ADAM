"""Verification records and their current status (design section 7.3).

A verification stays historically true forever: what ran, against which
files and environment, and with what result. Its current status is computed
on demand, by comparing what it ran against with the present:

* **verified:** every relevant file and the environment still match;
* **stale:** something relevant changed, and each reason names it, for
  example `api/jwt.py changed in event 42`, `Python 3.12 -> 3.13`, or
  `lockfile uv.lock changed`;
* **unknown:** it can't be checked, and the cause is given, for example
  when the environment wasn't supplied or a reconciliation failed.

Relevant files come from the first available of these:
1. coverage data (`coverage`);
2. the import closure of the tested files in the code graph
   (`import_closure`);
3. the whole tree (`whole_tree`), marked as such so the status stays
   conservative.
"""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path

LOCKFILES = ("uv.lock", "poetry.lock", "Pipfile.lock", "pdm.lock", "requirements.txt", "requirements-dev.txt",
             "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "Cargo.lock", "go.sum", "Gemfile.lock",
             "composer.lock")
INTERPRETERS = {"python": [sys.executable, "--version"], "node": ["node", "--version"]}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def tree_hash(files: dict[str, str]) -> str:
    """One hash over every (path, content id) pair."""
    return _sha256("\n".join(f"{p}\0{o}" for p, o in sorted(files.items())).encode())


def capture_environment(project_root: str | os.PathLike, env_names=(), interpreters=None) -> dict:
    """A fingerprint of the environment a check ran in. Environment variable values are never recorded."""
    root = Path(project_root)
    versions = {}
    for name, cmd in (interpreters or INTERPRETERS).items():
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            text = (out.stdout or out.stderr).strip()
            if out.returncode == 0 and text:
                versions[name] = text.split()[-1].lstrip("v")
        except (OSError, subprocess.TimeoutExpired):
            continue
    lockfiles = {}
    for base in [root, *(p for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith("."))] \
            if root.is_dir() else []:
        for name in LOCKFILES:
            f = base / name
            if f.is_file():
                lockfiles[str(f.relative_to(root))] = _sha256(f.read_bytes())
    return {
        "interpreters": versions,
        "os": platform.system() + " " + platform.release(),
        "lockfiles": lockfiles,
        "dependencies_hash": _sha256("\n".join(f"{k}\0{v}" for k, v in sorted(lockfiles.items())).encode()),
        "env_vars_checked": sorted(env_names),
        "env_vars_present": sorted(n for n in env_names if n in os.environ),
    }


def environment_reasons(recorded: dict, current: dict) -> list[str]:
    reasons = []
    for name in sorted(set(recorded.get("interpreters", {})) | set(current.get("interpreters", {}))):
        old, new = recorded.get("interpreters", {}).get(name), current.get("interpreters", {}).get(name)
        if old != new:
            label = {"python": "Python", "node": "Node"}.get(name, name)
            reasons.append(f"{label} {old or 'absent'} -> {new or 'absent'}")
    if recorded.get("os") != current.get("os"):
        reasons.append(f"OS {recorded.get('os')} -> {current.get('os')}")
    old_locks, new_locks = recorded.get("lockfiles", {}), current.get("lockfiles", {})
    for name in sorted(set(old_locks) | set(new_locks)):
        if name not in new_locks:
            reasons.append(f"lockfile {name} removed")
        elif name not in old_locks:
            reasons.append(f"lockfile {name} added")
        elif old_locks[name] != new_locks[name]:
            reasons.append(f"lockfile {name} changed")
    # Only the variables the check depended on are compared, by presence; values are never recorded.
    old_env, new_env = set(recorded.get("env_vars_present", [])), set(current.get("env_vars_present", []))
    for name in sorted(recorded.get("env_vars_checked", [])):
        if name in old_env and name not in new_env:
            reasons.append(f"environment variable {name} no longer set")
        elif name in new_env and name not in old_env:
            reasons.append(f"environment variable {name} now set")
    return reasons


def status(summary: dict, current_files: dict[str, tuple[str, str]], environment: dict | None,
           reconciled: bool = True) -> dict:
    """The current status of one verification record."""
    if not reconciled:
        return {"status": "unknown", "reasons": ["the last reconciliation failed, so the files can't be trusted"]}
    relevant = summary.get("relevant_files")
    method = summary.get("relevance_method")
    if relevant is None:
        return {"status": "unknown", "reasons": ["the verification has no relevant-file record"]}
    reasons = []
    for path, oid in sorted(relevant.items()):
        now = current_files.get(path)
        if now is None:
            reasons.append(f"{path} was deleted")
        elif now[0] != oid:
            reasons.append(f"{path} changed in event {now[1]}")
    if method == "whole_tree":
        for path in sorted(set(current_files) - set(relevant)):
            reasons.append(f"{path} was added (whole-tree relevance)")
    if environment is None:
        if reasons:
            return {"status": "stale", "reasons": reasons, "method": method}
        return {"status": "unknown", "reasons": ["the current environment wasn't supplied, so it can't be compared"],
                "method": method}
    reasons += environment_reasons(summary.get("environment", {}), environment)
    return {"status": "stale" if reasons else "verified", "reasons": reasons, "method": method}
