"""Seeded file-change scenarios for reconciliation (Stage 2.1 spike, #50; kept for Stage 2.5).

Each scenario step changes a real git repository and says what a correct
reconciler must report afterwards:

* the changes it must detect (path, kind, and how the change came about);
* what an agent adapter would have observed (tool calls with before/after
  hashes, and Bash command boundaries with the command text).

The reconciler under test gets the observations and the files; it never sees
the expected answer. Attribution labels follow the design (section 8.1):
agent_tool, agent_bash, external, git_operation, unattributed. A correct
reconciler may answer unattributed when the evidence can't separate two
causes, but must never give a wrong confident label.

No ADAM imports: this lives with the engine package.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


# Every content a step wrote or found, by sha256, so a test driving the real
# store can report tool edits with the store's own keyed content ids.
CONTENT: dict[str, bytes] = {}


def sha(data: bytes) -> str:
    digest = hashlib.sha256(data).hexdigest()
    CONTENT[digest] = data
    return digest


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@dataclass
class Expected:
    path: str
    kind: str                  # added | modified | deleted | renamed
    attribution: str           # agent_tool | agent_bash | external | git_operation | unattributed
    old_path: str | None = None
    acceptable: tuple[str, ...] = ()   # other labels that are not wrong (e.g. unattributed when ambiguous)


@dataclass
class Step:
    name: str
    observations: list[dict] = field(default_factory=list)
    expected: list[Expected] = field(default_factory=list)
    conflicts: int = 0         # conflict records a correct reconciler must produce
    full_scan: bool = False    # the step relies on a full hash rather than size and mtime


def init_repo(root: Path, files: int = 40, lines: int = 8) -> tuple[Path, Path]:
    """A repository with `files` small Python modules, and a bare remote it pushes to."""
    remote = root / "remote.git"
    repo = root / "repo"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "user.name", "fixture")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "pkg").mkdir()
    for i in range(files):
        body = "".join(f"value_{i}_{j} = {j}\n" for j in range(lines))
        (repo / "pkg" / f"mod_{i:03d}.py").write_text(f"import os\n{body}")
    (repo / ".gitignore").write_text("build/\n*.log\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "initial")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    return repo, remote


def _write(path: Path, text: str) -> tuple[str, str]:
    before = sha(path.read_bytes()) if path.exists() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return before, sha(text.encode())


def _bash(repo: Path, command: str, writer: str = "agent-a") -> list[dict]:
    """Run a shell command the way an agent's Bash tool would, and the observations it produces."""
    start = {"type": "bash_start", "writer": writer, "command": command, "cwd": str(repo)}
    subprocess.run(["bash", "-c", command], cwd=repo, check=True, capture_output=True)
    return [start, {"type": "bash_end", "writer": writer, "command": command, "exit_code": 0}]


def run_scenario(root: Path, big_checkout_files: int = 500, on_init=None):
    """Yield (step, repo) in order; each step has already been applied when it is yielded.

    The caller reconciles after each step, as the plugin would: after each tool
    batch, after each Bash command, and at session start. `on_init(repo)` runs
    once on the initial commit, before any step, so a baseline can be taken.
    """
    repo, remote = init_repo(root)
    if on_init is not None:
        on_init(repo)
    pkg = repo / "pkg"

    # 1. The agent edits a file through its edit tool.
    before, after = _write(pkg / "mod_000.py", "import os\nvalue = 'agent edit'\n")
    yield Step("agent tool edit", [{"type": "tool_edit", "writer": "agent-a", "path": "pkg/mod_000.py",
                                    "before": before, "after": after}],
               [Expected("pkg/mod_000.py", "modified", "agent_tool")]), repo

    # 2. The agent creates a new file through its write tool.
    before, after = _write(pkg / "new_tool.py", "print('created by the agent')\n")
    yield Step("agent tool create", [{"type": "tool_edit", "writer": "agent-a", "path": "pkg/new_tool.py",
                                      "before": before, "after": after}],
               [Expected("pkg/new_tool.py", "added", "agent_tool")]), repo

    # 3. The user edits a file in their editor between agent actions (session start reconcile).
    _write(pkg / "mod_001.py", "import os\nvalue = 'user edit'\n")
    yield Step("external edit", [{"type": "session_start", "writer": "agent-a"}],
               [Expected("pkg/mod_001.py", "modified", "external")]), repo

    # 4. The agent runs sed through Bash on three files.
    obs = _bash(repo, "sed -i 's/= 1$/= 100/' pkg/mod_002.py pkg/mod_003.py pkg/mod_004.py")
    yield Step("sed through bash", obs, [Expected(f"pkg/mod_00{i}.py", "modified", "agent_bash") for i in (2, 3, 4)]), repo

    # 5. The agent deletes a file through Bash.
    obs = _bash(repo, "rm pkg/mod_005.py")
    yield Step("delete through bash", obs, [Expected("pkg/mod_005.py", "deleted", "agent_bash")]), repo

    # 6. The user deletes a file outside the agent.
    (pkg / "mod_006.py").unlink()
    yield Step("external delete", [{"type": "session_start", "writer": "agent-a"}],
               [Expected("pkg/mod_006.py", "deleted", "external")]), repo

    # 7. The agent renames with git mv through Bash.
    obs = _bash(repo, "git mv pkg/mod_007.py pkg/renamed_007.py")
    yield Step("rename through bash", obs,
               [Expected("pkg/renamed_007.py", "renamed", "agent_bash", old_path="pkg/mod_007.py")]), repo

    # 8. The user renames a file with mv outside the agent.
    os.rename(pkg / "mod_008.py", pkg / "moved_008.py")
    yield Step("external rename", [{"type": "session_start", "writer": "agent-a"}],
               [Expected("pkg/moved_008.py", "renamed", "external", old_path="pkg/mod_008.py")]), repo

    # 9. touch changes mtime but not content: nothing to report.
    os.utime(pkg / "mod_009.py", None)
    yield Step("touch without change", [{"type": "session_start", "writer": "agent-a"}], []), repo

    # 10. Ignored files change: nothing to report.
    (repo / "build").mkdir(exist_ok=True)
    (repo / "build" / "out.bin").write_bytes(os.urandom(256))
    (repo / "run.log").write_text("log line\n")
    yield Step("ignored files", [{"type": "session_start", "writer": "agent-a"}], []), repo

    # 11. Same size, same mtime, different content: only a full hash finds it.
    target = pkg / "mod_010.py"
    stat = target.stat()
    original = target.read_bytes()
    target.write_bytes(original.replace(b"value_10_0", b"VALUE_10_0"))
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    yield Step("same size and mtime", [{"type": "session_start", "writer": "agent-a"}],
               [Expected("pkg/mod_010.py", "modified", "external")], full_scan=True), repo

    # Commit the agent's work so the git operations below start from a clean tree.
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "work so far")
    git(repo, "push", "-q", "origin", "main")
    yield Step("commit through bash", _bash_obs_only(repo, "git add -A && git commit -m 'work so far' && git push"),
               []), repo

    # 12. Someone else pushes; the agent pulls through Bash.
    other = root / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    git(other, "config", "user.email", "other@example.invalid")
    git(other, "config", "user.name", "other")
    git(other, "config", "commit.gpgsign", "false")
    (other / "pkg" / "mod_011.py").write_text("import os\nvalue = 'from the remote'\n")
    (other / "pkg" / "remote_new.py").write_text("print('new upstream file')\n")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "upstream change")
    git(other, "push", "-q", "origin", "main")
    obs = _bash(repo, "git pull -q --ff-only origin main")
    yield Step("git pull through bash", obs, [Expected("pkg/mod_011.py", "modified", "git_operation"),
                                              Expected("pkg/remote_new.py", "added", "git_operation")]), repo

    # 13. The user resets one commit back in a terminal.
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    yield Step("git reset outside the agent", [{"type": "session_start", "writer": "agent-a"}],
               [Expected("pkg/mod_011.py", "modified", "git_operation"),
                Expected("pkg/remote_new.py", "deleted", "git_operation")]), repo

    # 14. Checkout of a branch that changes two files. The branch is prepared and
    # left before the reconcile, so the net change of the preparation is nothing.
    git(repo, "checkout", "-q", "-b", "feature")
    (pkg / "mod_012.py").write_text("import os\nvalue = 'feature'\n")
    (pkg / "feature_only.py").write_text("FEATURE = True\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feature work")
    git(repo, "checkout", "-q", "main")
    yield Step("prepare feature branch", [{"type": "session_start", "writer": "agent-a"}], []), repo
    git(repo, "checkout", "-q", "feature")
    yield Step("checkout outside the agent", [{"type": "session_start", "writer": "agent-a"}],
               [Expected("pkg/mod_012.py", "modified", "git_operation"),
                Expected("pkg/feature_only.py", "added", "git_operation")]), repo
    git(repo, "checkout", "-q", "main")
    yield Step("checkout back to main", [{"type": "session_start", "writer": "agent-a"}],
               [Expected("pkg/mod_012.py", "modified", "git_operation"),
                Expected("pkg/feature_only.py", "deleted", "git_operation")]), repo

    # 15. A large git operation: a branch that touches many files, checked out through Bash.
    git(repo, "checkout", "-q", "-b", "bulk")
    bulk_dir = pkg / "bulk"
    bulk_dir.mkdir()
    for i in range(big_checkout_files):
        (bulk_dir / f"gen_{i:04d}.py").write_text(f"GEN = {i}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "bulk")
    git(repo, "checkout", "-q", "main")
    yield Step("prepare bulk branch", [{"type": "session_start", "writer": "agent-a"}], []), repo
    obs = _bash(repo, "git checkout -q bulk")
    yield Step("large checkout through bash", obs,
               [Expected(f"pkg/bulk/gen_{i:04d}.py", "added", "git_operation") for i in range(big_checkout_files)]), repo
    obs = _bash(repo, "git checkout -q main")
    yield Step("large checkout back", obs,
               [Expected(f"pkg/bulk/gen_{i:04d}.py", "deleted", "git_operation") for i in range(big_checkout_files)]), repo

    # 16. Two agents edit the same file; the second didn't see the first's edit.
    path = pkg / "mod_013.py"
    base = sha(path.read_bytes())
    _, after_a = _write(path, "import os\nvalue = 'agent a'\n")
    _, after_b = _write(path, "import os\nvalue = 'agent b'\n")
    yield Step("parallel edits", [
        {"type": "tool_edit", "writer": "agent-a", "path": "pkg/mod_013.py", "before": base, "after": after_a},
        {"type": "tool_edit", "writer": "agent-b", "path": "pkg/mod_013.py", "before": base, "after": after_b},
    ], [Expected("pkg/mod_013.py", "modified", "agent_tool")], conflicts=1), repo

    # 17. While the agent's Bash command runs, the user edits a file the command doesn't mention.
    start = {"type": "bash_start", "writer": "agent-a", "command": "python -c 'import time; time.sleep(0.2)'"}
    proc = subprocess.Popen(["bash", "-c", "python3 -c 'import time; time.sleep(0.2)'"], cwd=repo)
    _write(pkg / "mod_014.py", "import os\nvalue = 'user, during the command'\n")
    proc.wait()
    yield Step("external edit during a bash command",
               [start, {"type": "bash_end", "writer": "agent-a", "command": start["command"], "exit_code": 0}],
               [Expected("pkg/mod_014.py", "modified", "external", acceptable=("unattributed",))]), repo

    # 18. A Bash command whose effect isn't visible in its text (a script edits a file).
    (repo / "tool.sh").write_text("#!/bin/bash\necho 'value = 1' >> pkg/mod_015.py\n")
    git(repo, "add", "tool.sh")
    git(repo, "commit", "-q", "-m", "add script")
    yield Step("commit script", [{"type": "session_start", "writer": "agent-a"}],
               [Expected("tool.sh", "added", "external", acceptable=("unattributed",))]), repo
    obs = _bash(repo, "bash tool.sh")
    yield Step("bash script with hidden effect", obs,
               [Expected("pkg/mod_015.py", "modified", "agent_bash", acceptable=("unattributed",))]), repo

    # 19. The user edits one file while the agent edits another through its tool.
    before, after = _write(pkg / "mod_016.py", "import os\nvalue = 'agent'\n")
    _write(pkg / "mod_017.py", "import os\nvalue = 'user, between tool calls'\n")
    yield Step("external edit between tool calls",
               [{"type": "tool_edit", "writer": "agent-a", "path": "pkg/mod_016.py", "before": before, "after": after}],
               [Expected("pkg/mod_016.py", "modified", "agent_tool"),
                Expected("pkg/mod_017.py", "modified", "external", acceptable=("unattributed",))]), repo

    # 20. The agent edits a file, then the user changes the same file before the reconcile.
    before, after = _write(pkg / "mod_018.py", "import os\nvalue = 'agent'\n")
    _write(pkg / "mod_018.py", "import os\nvalue = 'agent, then the user'\n")
    yield Step("external edit after an agent edit",
               [{"type": "tool_edit", "writer": "agent-a", "path": "pkg/mod_018.py", "before": before, "after": after}],
               [Expected("pkg/mod_018.py", "modified", "external", acceptable=("unattributed",))]), repo


def _bash_obs_only(repo: Path, command: str) -> list[dict]:
    return [{"type": "bash_start", "writer": "agent-a", "command": command},
            {"type": "bash_end", "writer": "agent-a", "command": command, "exit_code": 0}]


def make_large_repo(root: Path, files: int = 20_000) -> Path:
    """A repository with many small files, for timing (about 3 MB of content)."""
    repo, _ = init_repo(root, files=files, lines=2)
    return repo
