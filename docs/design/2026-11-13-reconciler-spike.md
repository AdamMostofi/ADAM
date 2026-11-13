# Reconciler and replay spike: results

**Status:** Current. These are the results of the Stage 2.1 spike
([#50](https://github.com/AdamMostofi/ADAM/issues/50)), which tested the design's
sections 8.1 and 8.2 before any engine code exists.

**Verdict: continue.** Both risky ideas work. Change detection should be
driven by `git status` rather than a file walk, and attribution needs three
precise rules. The design doc's section 8.1 is updated to match.

## What was tested

- **Fixtures**, kept in `packages/agent-memory/tests/fixtures/reconcile/scenarios.py`.
  These are real git repositories (with a bare remote and a second clone) and 31
  seeded steps:
  - tool edits and creates, external edits and deletes;
  - `sed` and `rm` through Bash, `git mv`, a plain `mv`;
  - `git pull`, `git reset --hard`, branch checkouts both ways, and a 500-file
    checkout both ways;
  - two agents editing one file;
  - traps that must report nothing (`touch`, ignored files, a commit), and a
    same-size, same-mtime rewrite;
  - four deliberately ambiguous cases: an external edit during a Bash command,
    a script whose effect isn't in its command text, an external edit between
    tool calls, and an external edit right after the agent's own edit.

  Each step says what must be detected and how it was caused, and what an
  adapter would have observed.
- **Prototype reconciler** (throwaway). It reads the repository's files, git's
  view of them, the reflog, and the adapter's observations, then reports each
  change with an attribution.
- **Prototype log and replay** (throwaway). A writer appends hash-chained
  events to SQLite (WAL, `synchronous=FULL`), sometimes several per
  transaction, and checkpoints every 50 events. It was killed with SIGKILL at
  random points, then recovered from the newest valid checkpoint plus replay.

The prototype code is in commit `d30a927` (`spikes/reconciler/`), and was removed
in the next commit, as the issue asks. To rerun it: `git show d30a927:spikes/reconciler/run_attribution.py`, and the same for `reconciler.py` and `replay.py`.

## Results

### Detection and attribution

These are the totals over all seeded steps, the same in both scan modes:

| | Count |
|---|---|
| Changes expected | 1,026 |
| Detected | **1,026 (100%)** |
| Attributed exactly | 1,022 |
| `unattributed` where the truth was ambiguous (accepted) | 4 |
| **Wrong confident attributions** | **0** |
| Spurious changes (touch, ignored files, commit) | 0 |
| Conflicts expected and found (two agents, one file) | 1 of 1 |
| Large git operations grouped | 2 of 2 (500 files each) |

The four `unattributed` results are the deliberately ambiguous cases. Without
OS-level file monitoring, a reconciler can't tell who changed a file while the
agent was active, unless the evidence names the path. Answering
`unattributed` there is what the design's "never guesses" rule requires.

### Timing

Measured on a 20,000-file repository, WSL2:

| | File walk (size + mtime) | `git status`-driven |
|---|---|---|
| First full scan | 0.62 s | 0.64 s |
| Warm, nothing changed | 0.32 s | **0.031 s** |
| Warm, 10 files changed | 0.31 s | **0.039 s** |
| Full rehash | 0.61 s | 0.65 s |
| Same size and mtime, different content | **missed** (caught only by full rehash) | caught |

A 40-file repository takes about 0.01 s either way. All the reports are in
`docs/measurements/2026-11-13-reconciler-attribution.json`.

### Replay after a crash

| | Result |
|---|---|
| Random SIGKILL trials | 300 |
| Recovered state equal to a clean replay | **300 of 300** |
| Events written before the kill | 150 to 51,365 |
| Trials with the newest checkpoint corrupted | 50; all 50 skipped, falling back to an older checkpoint |
| Slowest recovery | 0.13 s |

All the reports are in `docs/measurements/2026-11-13-reconciler-replay.json`.

## What changes in the design

These are the updates to section 8.1:

1. **Detect with `git status`, not a walk.** Ask git which files differ
   (`git --no-optional-locks status --porcelain -z --untracked-files=all`).
   Hash only those, plus files that were dirty at the last reconcile, plus
   files that differ between the old and new `HEAD`. Together that set is
   complete.
   - **Faster.** It is 10× faster when warm.
   - **Catches same-mtime rewrites.** git's index also compares ctime and
     inode, so a same-size, same-mtime rewrite is caught without a full
     rehash.
   - **Writes nothing.** `--no-optional-locks` stops git from refreshing
     `.git/index`, so reconciling writes nothing in the project.
   - **Fallbacks.** The walk remains for folders without git and for the
     periodic full check.
2. **Only working-tree git operations explain changes.** Read the reflog's
   action: `checkout`, `pull`, `reset`, `merge`, `rebase`, `cherry-pick`,
   `revert`, `switch`, `am` and `stash` change files; a `commit` doesn't. A
   change counts as a git operation only if the file now matches `HEAD`.
3. **A Bash command explains only the paths its text names.** A change made
   during a Bash command is `agent_bash` only if the command names the path
   (or the old path, for a rename). Otherwise it is `unattributed`, because a
   user may have edited it at the same moment.
4. **A tool edit explains a change only if the hashes match.** It counts as
   `agent_tool` only when the file's content equals the tool's reported
   after-hash. If someone changed it again before the reconcile, the change is
   `unattributed`.
5. **Reconcile before each Bash command too**, not only after. That keeps each
   command's window to its own changes. Section 8.1's "runs" list now says so.
6. **Renames** are a deleted path and an added path with the same content,
   paired one to one.

The checkpoint design (8.2) needs one clarification, added to the doc:
- write a checkpoint in its own transaction, after the events it covers are
  committed;
- accept a checkpoint only if its chain hash matches the verified chain at its
  position and its snapshot hash is intact.

## Limits

- **Small fixtures.** The fixtures are small and synthetic; real agent sessions
  come in Stage 3.1.
- **Concurrent edits.** User edits made while the agent is active remain
  `unattributed` unless the evidence names them. OS file monitoring could
  narrow this, but it isn't planned.
- **Linux only.** Timings are from Linux on WSL2. A Windows-native filesystem
  (for example a repository on `/mnt/c`) is much slower for both git and
  Python, which is one more reason to keep repositories and the store on the
  Linux side.
