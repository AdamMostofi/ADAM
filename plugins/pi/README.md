# agent-memory for Pi

A Pi package for the [Lossless Tree Memory engine](../../packages/agent-memory/). It shares one project's
memory with the [Claude Code](../claude-code/README.md) and [OpenCode](../opencode/README.md) plugins, and maps
Pi's session tree onto memory branches.

**What it records:** every session, prompt, tool call, file change, test run, assistant message, compaction and
branch, in `<project>/.agent-memory/` (encrypted, ignored by git).

**What it puts into context:**
- **System prompt:** an `agent_memory` section holding a short memory overview: protected items, current state,
  and references to the last session's working set. It stays unchanged until a compaction or a branch change,
  so prompt caching keeps working.
- **On each prompt:** short offers for records the prompt touches but the context lacks, added to the run as a
  hidden custom message.
- **After a compaction:** the section is refreshed with the restored memory. Pi keeps the system prompt across
  compaction, so the memory overview is never summarised away.
- **Tools:** the 10 memory tools over MCP, declared directly. Pi names them `mcp__agent_memory__mem_state`, and
  so on.

## Install

```bash
uv tool install /path/to/ADAM/packages/agent-memory   # the amem command; once per machine
pi install /path/to/ADAM/plugins/pi                  # turns on capture, context and the tools
```

To try it for one run without installing: `pi -e /path/to/ADAM/plugins/pi`.

**Environment variables:**
- `AMEM_BIN`: where `amem` is. Default: `amem` on the PATH, then `~/.local/bin/amem`.
- `AMEM_PI_MCP=0`: don't register the memory tools.
- `AMEM_KEY_SOURCE` and `AMEM_PASSPHRASE`: key storage, as for the other plugins.

**If `amem` is missing,** Pi starts as usual without memory, and says so on stderr.

## Branches

Pi's sessions form a tree, and the engine records each line of it separately:
- **A fork or clone** (`/fork`, `/clone`, `pi --fork`): a new Pi session. Its record names the session it came
  from, so the memory links the two and proposes the fork as a development path.
- **A branch inside a session** (`/tree`): the session continues as `<session>~<entry>`, forked from the line
  it left. Records made on the branch stay on it. Pi's summary of the abandoned branch, when there is one, is
  kept as a note.

The memory tools follow the current branch.

## How it works

The extension only translates. Each Pi event becomes one engine event (`agent_memory/adapters/pi.py` has the
table). Events go one at a time and in order: to the project's session server first, which `amem mcp` runs
(10–75 ms per event in the runs below, and about 200 ms for a session start), and otherwise to `amem hook pi <event>`.

**Not captured:** reasoning text. Pi has no hook for adding instructions to its compaction summary; the memory
section survives compaction instead.

## Tested with

**Pi 1.4.0, running for real,** driven by a scripted model built on Pi's own faux provider: no network, no
account and no cost. The session went through:
1. `pi install`;
2. an edit, a decision recorded through the memory tools, and a test run;
3. a `/tree` branch with its own edit;
4. a compaction;
5. a resumed session;
6. a `pi --fork`.

The real-runtime test is in `packages/agent-memory/tests/test_pi.py`, and is skipped where Pi isn't installed.
No live model has been run: this machine has no cloud model set up for Pi.
