# agent-memory for Claude Code

A Claude Code plugin for the [Lossless Tree Memory engine](../../packages/agent-memory/).

**What it records:** every session, prompt, tool call, file change, test run, assistant message and compaction, losslessly, in `<project>/.agent-memory/`. That folder is encrypted and ignored by git.

**What it puts into context:**
- **At session start:** a short memory overview, the protected items (constraints, objectives, open conflicts, active work), the current state, and reference lines for the last session's working set. It stays within Claude Code's 10,000-character limit for added context.
- **On each prompt:** short offers for records the prompt names but the context lacks, about 180–250 tokens on real sessions.
- **After a compaction:** the protected items in full, and everything else as one-line references to restore.
- **Through MCP tools:** anything else, on demand: `mem_history`, `mem_artifacts`, `mem_knowledge`, `mem_state`, `mem_load`, `mem_context` (offload, restore, pin, and the working set), and more.

## Install

```bash
uv tool install /path/to/ADAM/packages/agent-memory   # the amem command; once per machine
claude plugin marketplace add AdamMostofi/ADAM        # once
claude plugin install agent-memory@adam
```

To try it without installing: `claude --plugin-dir /path/to/ADAM/plugins/claude-code`.

**When the plugin is enabled,** Claude Code asks:
- **Key storage:** `key-file` (the default), `passphrase`, or `keychain`, which needs the `keyring` package. This is decision D4: the choice is made at onboarding.
- **A passphrase,** used only for the `passphrase` option.
- **Domain profiles.**

**On Windows,** Claude Code running on Windows with a project inside WSL (`\\wsl.localhost\...`) runs `amem` inside WSL. Install it there.

**If `amem` isn't installed,** every hook exits 0 and Claude Code works as usual. The session start says that memory isn't being recorded, and how to install it.

## Remove

```bash
claude plugin uninstall agent-memory@adam
```

Nothing in the project changes: the store is in `.agent-memory/`, which git ignores. Delete that folder to delete the memory too.

## Guarantees and limits

| Guarantee | |
|---|---|
| Never blocks Claude Code | Every hook exits 0. A broken store, a bad payload or a failing handler becomes a `capture_gap` record |
| Replays store nothing twice | Every event's idempotency key comes from Claude Code's payload |
| Gaps are explicit | An assistant message taken only from the Stop hook (the transcript was unreadable) is marked `partial` |
| Secrets | Every payload is redacted before storage. `amem purge` removes anything found later |

**Latency.** Measured by replaying real Claude Code sessions (601 hooks) through this launcher: hook p50 is about **170 ms** and p95 about **300–400 ms**.
- **Where the time goes:**
  - Python start and import: about 60 ms;
  - one durable write: about 26 ms;
  - for Bash commands, a reconcile before and after.
- **The first session start** in a repository takes about 2 s: it records every existing file once.

This misses the 100 ms target in Stage 3.1. The options are recorded as decision D14 in `docs/DECISIONS.md`.
