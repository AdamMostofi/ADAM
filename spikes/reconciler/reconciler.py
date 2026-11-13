"""Throwaway prototype: detect and attribute file changes (Stage 2.1 spike, #50).

Not engine code. It exists to measure whether the design's reconciliation
(section 8.1) works: git status plus file hashes for detection, and the
reflog, agent observations and command text for attribution.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Reflog actions that change the working tree. A commit only records it.
WORKTREE_GIT = re.compile(r"^(checkout|pull|reset|merge|rebase|cherry-pick|revert|switch|am|stash)\b")
GROUP_THRESHOLD = 100


def _git(repo: Path, *args: str, check: bool = True) -> str:
    # --no-optional-locks: never refresh .git/index, so reconciling writes nothing in the project.
    return subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *args],
                          capture_output=True, text=True, check=check).stdout


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class Change:
    path: str
    kind: str
    attribution: str
    old_path: str | None = None
    group: int | None = None


@dataclass
class Result:
    changes: list[Change] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    groups: list[dict] = field(default_factory=list)
    hashed: int = 0


class Reconciler:
    """mode="walk": stat every listed file (size + mtime fast path).
    mode="git_status": ask git which files differ from the index, and hash only
    those, files dirty last time, and files that changed between the old and
    new HEAD. git's index stat check also uses ctime and inode."""

    def __init__(self, repo: Path, mode: str = "walk"):
        self.repo = repo
        self.mode = mode
        self.dirty: set[str] = set()
        self.snapshot: dict[str, tuple[int, int, str]] = {}
        self.head = self._head()
        self.reflog = self._reflog()
        self.snapshot, _ = self._scan(full=True)

    # ------------------------------------------------------------ observation
    def _head(self) -> str | None:
        out = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True, text=True)
        return out.stdout.strip() or None

    def _reflog(self) -> list[str]:
        return _git(self.repo, "reflog", "--format=%gs", check=False).splitlines()

    def _files(self) -> list[str]:
        out = _git(self.repo, "ls-files", "-co", "--exclude-standard", "-z")
        return sorted({p for p in out.split("\0") if p and (self.repo / p).is_file()})

    def _status_paths(self) -> set[str]:
        out = _git(self.repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
        paths = set()
        for entry in out.split("\0"):
            if len(entry) > 3:
                paths.add(entry[3:])
        return paths

    def _scan_git(self, full: bool, head: str | None):
        if full or not self.snapshot:
            snap, hashed = self._scan_walk(full=True)
            self.dirty = self._status_paths()
            return snap, hashed
        dirty = self._status_paths()
        candidates = dirty | self.dirty
        if head != self.head and self.head and head:
            candidates |= set(_git(self.repo, "diff", "--name-only", "--no-renames", self.head, head).splitlines())
        snap, hashed = dict(self.snapshot), 0
        for rel in candidates:
            path = self.repo / rel
            if path.is_file():
                st = os.stat(path)
                snap[rel] = (st.st_size, st.st_mtime_ns, _hash(path))
                hashed += 1
            else:
                snap.pop(rel, None)
        self.dirty = dirty
        return snap, hashed

    def _scan(self, full: bool, head: str | None = None):
        if self.mode == "git_status":
            return self._scan_git(full, head)
        return self._scan_walk(full)

    def _scan_walk(self, full: bool):
        snap, hashed = {}, 0
        for rel in self._files():
            st = os.stat(self.repo / rel)
            old = self.snapshot.get(rel)
            if not full and old and old[0] == st.st_size and old[1] == st.st_mtime_ns:
                snap[rel] = old
            else:
                snap[rel] = (st.st_size, st.st_mtime_ns, _hash(self.repo / rel))
                hashed += 1
        return snap, hashed

    # ------------------------------------------------------------ reconcile
    def reconcile(self, observations: list[dict], full: bool = False) -> Result:
        new, hashed = self._scan(full, self._head())
        old = self.snapshot
        result = Result(hashed=hashed)

        added = {p for p in new if p not in old}
        deleted = {p for p in old if p not in new}
        modified = {p for p in new if p in old and new[p][2] != old[p][2]}

        # Renames: a deleted and an added path with the same content, paired one to one.
        renames = {}
        by_hash = {}
        for p in sorted(deleted):
            by_hash.setdefault(old[p][2], []).append(p)
        for p in sorted(added):
            candidates = by_hash.get(new[p][2])
            if candidates:
                renames[p] = candidates.pop(0)
        added -= set(renames)
        deleted -= set(renames.values())

        # Git operations since the last reconcile, from the reflog.
        head, reflog = self._head(), self._reflog()
        fresh = reflog[: max(0, len(reflog) - len(self.reflog))]
        git_files: set[str] = set()
        if head != self.head and any(WORKTREE_GIT.match(entry) for entry in fresh):
            if self.head and head:
                git_files = set(_git(self.repo, "diff", "--name-only", "--no-renames", self.head, head).splitlines())
            dirty = {line[3:] for line in _git(self.repo, "status", "--porcelain", "--no-renames").splitlines()}
            git_files -= dirty

        tool_after = {}
        last_after: dict[str, str] = {}
        for obs in observations:
            if obs["type"] != "tool_edit":
                continue
            known = last_after.get(obs["path"], old.get(obs["path"], (0, 0, None))[2])
            if obs["before"] != known:
                result.conflicts.append({"path": obs["path"], "writer": obs["writer"],
                                         "expected_before": known, "reported_before": obs["before"]})
            last_after[obs["path"]] = obs["after"]
            tool_after[obs["path"]] = obs["after"]

        commands = [obs["command"] for obs in observations if obs["type"] == "bash_start"]
        mentioned = set()
        for command in commands:
            try:
                tokens = shlex.split(command)
            except ValueError:
                tokens = command.split()
            mentioned.update(t.lstrip("./") for t in tokens)
        agent_active = any(obs["type"] in ("tool_edit", "bash_start") for obs in observations)

        def attribute(path: str, current: str | None, old_path: str | None = None) -> str:
            if path in git_files or (old_path and old_path in git_files):
                return "git_operation"
            if current is not None and tool_after.get(path) == current:
                return "agent_tool"
            if commands and (path in mentioned or (old_path and old_path in mentioned)):
                return "agent_bash"
            if not agent_active:
                return "external"
            return "unattributed"

        for p in sorted(added):
            result.changes.append(Change(p, "added", attribute(p, new[p][2])))
        for p in sorted(modified):
            result.changes.append(Change(p, "modified", attribute(p, new[p][2])))
        for p in sorted(deleted):
            result.changes.append(Change(p, "deleted", attribute(p, None)))
        for p, was in sorted(renames.items()):
            result.changes.append(Change(p, "renamed", attribute(p, new[p][2], was), old_path=was))

        git_changes = [c for c in result.changes if c.attribution == "git_operation"]
        if len(git_changes) > GROUP_THRESHOLD:
            group_id = len(result.groups)
            result.groups.append({"id": group_id, "files": len(git_changes), "reflog": fresh})
            for c in git_changes:
                c.group = group_id

        self.snapshot, self.head, self.reflog = new, head, reflog
        return result
