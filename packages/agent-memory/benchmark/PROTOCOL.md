# Stage 3.2 benchmark protocol (pre-registered)

**Issue:** #57. **Status:** pre-registered: written and committed before any run. The commit that adds this
file fixes the scenarios, gold answers, checks, judge prompt and thresholds. Any later change is listed under
[Deviations](#deviations), with its reason and date, and the results say which runs it affects.

**The question:** does this engine reduce stale-state errors without raising token use, compared with what a
coding agent already has: its own compaction, and a well-kept notes file with git and grep?

## 1. Files

| File | What it fixes |
|---|---|
| `fixtures/tally/` | The seed of the main project: a small Python expense ledger with tests. |
| `fixtures/handbook/` | The seed of the non-code project (documents profile, verification question 6). |
| `fixtures/user-actions/` | Files the maintainer's scripted changes use. |
| `timeline.json` | The history: 43 agent sessions and 4 maintainer changes on tally, 3 sessions and 1 change on handbook, with checkpoints. |
| `probes.json` | 14 probes, each with required facts, stale-state errors and unsupported-history examples. |
| `checks.py` | Automated task checks for the 3 probes that ask for work, not an answer. |
| `judge.md` | The judge prompt and its JSON output. |
| `arms/` | The project instructions each arm gets. |

## 2. Arms

All arms use the same model, the same Claude Code version, the same fixture, the same prompts, and git. Each
arm has its own copy of the fixture and its own Claude Code configuration directory (`CLAUDE_CONFIG_DIR`).
Claude Code's own auto-memory is turned off in every arm, so no arm gets a memory system it isn't meant to
have. The dry run (section 9) confirms each of these before the history is built.

| Arm | Sessions | Instructions | Memory |
|---|---|---|---|
| **A: native compaction** | One conversation, resumed for every session; Claude Code compacts it as usual. Before probing, the harness compacts it once more, so every probe starts from a compacted history. | `CLAUDE.base.md` | The conversation and its compaction summaries. |
| **B: notes, git and grep** (the strong baseline) | A fresh session each time. | `CLAUDE.base.md` + `CLAUDE.arm-b.md` | `NOTES.md`, kept by the agent; git; grep. |
| **C: this engine** | A fresh session each time. | `CLAUDE.base.md` | The `agent-memory` plugin (hooks, MCP tools, session server), installed as a user would. |

- **A's probes** fork the compacted conversation, so the 5 runs of a probe start from the same state and don't
  see each other.
- **If Claude Code's headless mode can't compact on request,** A's probes fork the resumed conversation as it
  is. The results then report, for each checkpoint, whether a compaction had happened (from the transcript's
  compaction records).

## 3. History

Each arm builds the history in `timeline.json` **once**, in order:
- **Agent steps:** one headless Claude Code session each, with the step's prompt.
- **Maintainer steps:** the harness makes the change and commits it with the given message:
  - `revert_session`: `git revert` of that session's commit;
  - `discard_working_tree`: `git checkout -- .` and `git clean -fd`, keeping arm files;
  - `set_ledger_from_env`: rewrites `storage.ledger_path()` as described in the step;
  - `copy_file`: copies the file;
  - `replace_in_section`: changes only the first matching line in that section.
- **Commits:** after each agent step, the harness commits any changes as the maintainer (`session <id>`), except
  in S14.
- **The crash (S14):** the harness kills the agent 2 seconds after its first write to `tally/cli.py`, without a
  clean shutdown, and commits nothing.
- **Checkpoints:** the whole arm (workspace, git, notes, engine store, Claude Code configuration and
  transcripts) is copied as it is. Probes run on copies of a checkpoint and never change it.

**History variance isn't measured:** one history per arm is a cost decision, reported as a limitation. How
well an arm records its history varies; with one history, a lucky or unlucky history affects all of that arm's
probes the same way.

**If a maintainer step can't apply** (for example S06 wrote no commit to revert, or U3 matches nothing), the
harness stops. The step is applied by hand to match its description, and that is recorded as a deviation.

## 4. Probes and runs

- **Probes:** each probe in `probes.json` runs at each of its checkpoints as one fresh session with its prompt.
  This is 18 probe-checkpoint pairs.
- **Runs:** each pair runs **5 times per arm**: 18 × 3 × 5 = **270 probe runs**.
- **Long history:** `sqlite`, `rate_limit`, `december` and `csv_import` run at P1 (after 12 agent sessions) and
  again at P2 (after 30 more sessions of unrelated work, a crash, and the maintainer's last changes). The difference is the long-history result.
- **Tasks:** the three probes that ask for work (`refund`, `crash`, `tests_green`) are also scored by
  `checks.py`.
- **Live sessions:** at least one run is in a live, interactive Claude Code session. It is `ledger_location` at
  P2 in arm C, run by the owner in a terminal; arm B gets the same live run for comparison. Live runs are
  reported separately, and don't count toward the 5.

## 5. Metrics

Per probe run:

| Metric | Definition |
|---|---|
| **Recall** | Required facts present / required facts (judge). Probes without required facts are excluded. |
| **Stale-state errors** | Stale entries marked true by the judge. The exception is `refund`'s entry, which is about code, not the answer: `refund_uses_cents` scores it, and a failed check is one stale-state error (the decision that replaced float amounts wasn't followed). |
| **False claims** (hallucinated history) | Claims about the past that the judge marks unsupported by the ground-truth history. |
| **False "don't know"** | Required facts that the answer says aren't known or recorded, on answerable probes. |
| **Task success** | The probe's check passed (tasks only). |
| **Tokens** | From Claude Code's JSON result: input + cache creation + cache read + output tokens, summed over the session. Each part, and the reported cost, is also published. |
| **Time** | The session's wall-clock duration. |

Per arm:

| Metric | Definition |
|---|---|
| **Storage** | At P2: arm A, the transcript size; arm B, `NOTES.md`; arm C, the store directory. |
| **Hook latency** (C) | p50 and p95 of every hook during the history and the probes, timed by the harness around the plugin's launcher. |
| **RAM** (C) | The peak resident memory of the session server, sampled every second. |
| **Declared paths** | Of the 5 decision points marked in `timeline.json`, how many the agent recorded in that session: in C, a record in the store; in B, an entry in `NOTES.md`. Not applicable in A. |
| **Injected context** (C, verification question 3) | See section 7. |

## 6. Scoring and the decision

- **Judge:** each probe run's final answer is scored with `judge.md`, by `claude-opus-5-5` through headless
  Claude Code. The answer is blinded first (`judge.md`).
- **Second judge:** a random 20% of runs are judged a second time; agreement is reported.
- **Hand audit:** the owner and Claude audit 30 random judgements by hand, and every disagreement is
  published.
- **Agent model:** `claude-sonnet-5-5` for the history and all probes, at the default effort.

**Decision rule**, over all 270 probe runs, computed per arm:
- **stale-state error rate:** stale-state errors / runs;
- **mean recall;**
- **mean tokens per run.**

| Result | Condition | Action |
|---|---|---|
| **Go** | C's stale-state error rate ≤ 0.5 × A's **and** ≤ 0.5 × B's; **and** C's mean recall ≥ B's − 0.05; **and** C's mean tokens ≤ 1.10 × B's. | Continue with 3.3. |
| **Ties B** | Not Go, and C's stale-state error rate ≤ B's, and C's mean recall ≥ B's − 0.05. | Narrow the scope: publish where C helps and where it doesn't, and decide 3.3 to 3.6 with the owner. |
| **Loses** | Anything else. | No-go: close 3.3 to 3.6 as not planned; continue at 4.1. |

- **Recall tolerance:** the 0.05 absorbs judge noise. It is fixed here, before any run.
- **No room to improve:** if B makes no stale-state errors, C can't be 50% lower, and the result is not Go.
- **Spread:** the decision uses the point values above. The results also give each probe's mean and standard
  deviation over its 5 runs, and bootstrap 95% intervals for each arm's rates. If an interval makes the
  decision uncertain, the results say so.

In every case ADAM keeps the core, and every result is published, including negative ones.

## 7. Verification questions (owner review, 2026-11-16)

Each answer is test evidence, not a description:

| # | Question | Evidence |
|---|---|---|
| 1 | Are the four trees independently navigable? | `tests/test_four_trees.py`; and in arm C's `four_trees` runs, the tools the agent called for each part (`mem_state`, `mem_knowledge`, `mem_artifacts`, `mem_history`), from the transcript. |
| 2 | Does retrieval understand intent beyond explicit mentions? | `tests/test_retrieval.py` (80% on prompts that share no words with what they need); and for every arm C probe, whether the relevant record was offered at prompt time, from the engine's offer events. Several probes share no words with their records (`ledger_location` says "back up", the record says `ledger_path`). |
| 3 | What is injected, and what does it cost? | Measured with the model's own token counts. Four headless sessions on the P2 checkpoint, with one fixed prompt: (a) no plugin; (b) the MCP server only; (c) the full plugin with an empty store; (d) the full plugin with the P2 store. Each step's difference in input tokens gives, in turn, the tool definitions, the hooks and instructions, and the session-start bundle. Per-turn offers and explicit retrieval come from arm C's probe transcripts (`additionalContext` and tool results), counted the same way. |
| 4 | How does offloading work across a real compaction? | In a live Claude Code session on the P2 checkpoint (arm C): load three records, offload two, then `/compact`. Publish what the post-compaction context holds (from the transcript), the references that remain, and a byte comparison of each restored record with the original. |
| 5 | Protected context over budget? | `tests/test_protected_context.py` (#91): 50 constraints and 80 conflicts. |
| 6 | Does a non-code project work without architecture changes? | The handbook project (`stipend`, `per_diem`) in all three arms, with the engine's documents profile, and no code change between the tally and handbook runs. |

**Archive results:** reported for arm C's store at P2 and HP from `amem verify`:
- integrity;
- capture completeness within the instrumentation;
- known gaps;
- uncertain attribution.

## 8. What is published

Under `benchmark/results/` in the same repository:
- the harness and its configuration;
- every transcript (JSONL), probe answer and judge output;
- each arm's checkpoint metadata (sizes, verify output, `NOTES.md`);
- the raw metrics (one JSON line per run), and the summary with the decision.

The fixtures are already in this directory. **One exception:** transcripts may hold machine-specific paths and
are published as they are; nothing secret is in the fixtures.

## 9. Dry run

Before the history is built, a dry run checks the mechanics only. It uses the handbook project with 1 run of
each handbook probe per arm, and checks that:
- each arm is isolated (auto-memory off; the plugin only in C);
- A can be resumed and compacted;
- the crash kill works (on a scratch session);
- token and time numbers are captured;
- the judge returns valid JSON.

Dry-run results are published as such and are **not** counted. Only harness bugs are fixed after it: fixtures,
gold answers, thresholds and the engine stay as they are. Tuning the engine to the fixtures after seeing
results is out of scope (#57).

## 10. Known limitations, stated in advance

- **One history per arm** (section 3).
- **One model and one agent:** the two-agent scenario (Claude Code, then OpenCode) needs Stage 3.3, and runs in
  the repeat after it.
- **Two small, synthetic fixture projects;** real projects are larger and messier.
- **The judge is a model:** the second judge and the hand audit bound its error, but don't remove it.
- **Arm B's notes depend on the agent following instructions:** this is part of what B measures.

## Deviations

None yet.
