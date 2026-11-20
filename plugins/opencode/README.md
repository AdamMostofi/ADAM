# agent-memory for OpenCode

An OpenCode plugin for the [Lossless Tree Memory engine](../../packages/agent-memory/). It shares one project's
memory with the [Claude Code plugin](../claude-code/README.md): a session started in one agent continues in the
other, and every record says which agent made it.

**What it records:** every session, prompt, tool call, file change, test run, assistant message and compaction,
in `<project>/.agent-memory/` (encrypted, ignored by git).

**What it puts into context:**
- **System prompt:** a short memory overview: protected items, current state, and references to the last
  session's working set. It is added once per session and kept unchanged until the next compaction, so
  provider prompt caching keeps working.
- **On each prompt:** short offers for records the prompt touches but the context lacks, added to your message
  as a synthetic part.
- **At compaction:** the summary is asked to keep the memory reference lines, and the next request gets the
  restored memory.
- **Tools:** the 10 memory tools over MCP. OpenCode names them `agent-memory_mem_state`,
  `agent-memory_mem_context`, and so on.

## Install

```bash
uv tool install /path/to/ADAM/packages/agent-memory   # the amem command; once per machine
```

Then list the plugin in `opencode.json` (the project's, or `~/.config/opencode/opencode.json`):

```json
{ "plugin": ["/path/to/ADAM/plugins/opencode/index.js"] }
```

Listing the plugin turns everything on, the memory tools included: it registers `amem mcp` itself, which also
runs the session server the plugin hands its events to.

**Options:** `"plugin": [["/path/to/plugins/opencode/index.js", { "amem": "/path/to/amem", "mcp": false }]]`
- `amem`: where `amem` is. Default: `$AMEM_BIN`, then `amem` on the PATH, then `~/.local/bin/amem`.
- `mcp: false`: don't register the memory tools. The plugin then runs `amem serve` beside OpenCode.

**Key storage** (key file, passphrase or keychain) is the engine's: set `AMEM_KEY_SOURCE` and, for a passphrase,
`AMEM_PASSPHRASE`, as for Claude Code.

**If `amem` is missing,** OpenCode starts as usual without memory, and says so on stderr.

## How it works

The plugin only translates. Each OpenCode hook or bus event becomes one engine event
(`agent_memory/adapters/opencode.py` has the table). Events go one at a time and in order, to the project's
session server first (8–46 ms each in live runs), and otherwise to `amem hook opencode <event>`.

**What it doesn't send, and why:**
- **Reasoning text.**
- **`session.error`:** the failed turn's tool parts are captured instead.
- **`file.edited`:** OpenCode publishes it before the edit tool's result, so acting on it recorded the change as
  unattributed and the tool's own report as a conflict. The tool result already carries the edit.

## Tested with

- **OpenCode 1.18.35,** with the free `opencode/deepseek-v4.1-flash-free` model, in live runs:
  - edits, tests and a recorded decision;
  - a continued session;
  - a compaction through OpenCode's server API;
  - a new session that answered the decision's reason from memory, without reading files.
- **The plugin file itself,** driven with recorded OpenCode hook shapes under Node, in
  `packages/agent-memory/tests/test_opencode.py`.
