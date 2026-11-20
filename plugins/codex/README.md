# agent-memory for Codex

**Status: built from the Codex documentation (read 2026-11-20); not tested against a real Codex install.** See
[docs/agents.md](../../docs/agents.md).

A Codex plugin for the [Lossless Tree Memory engine](../../packages/agent-memory/): lossless capture through
Codex's lifecycle hooks, memory context at session start and on each prompt, and the memory tools over MCP.
It shares one project's memory with the other agents' plugins.

## Layout

- `.codex-plugin/plugin.json`: the manifest. It names `./hooks/hooks.json`.
- `hooks/hooks.json`: `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `PreCompact`,
  `PostCompact`, `SubagentStart`, `SubagentStop` and `SessionEnd`, each running `scripts/amem-run` with
  `AMEM_AGENT=codex`.
- `.mcp.json`: the memory tools.
- `scripts/amem-run`: the same launcher as the Claude Code plugin. It uses the session server when one runs,
  and works from Windows into WSL.

## Install

```bash
uv tool install /path/to/ADAM/packages/agent-memory   # the amem command
codex plugin marketplace add /path/to/a/marketplace   # with this plugin listed in it
```

Then:
1. Install it from `/plugins`.
2. Start a new session.
3. **Review and trust its hooks in `/hooks`:** Codex skips hooks nobody has trusted.

## Known gaps, from the docs

- **Replies:** Codex's transcript format isn't documented as stable, so only each turn's final reply is
  captured, marked `partial`.
- **`PreCompact`:** Codex reads no context from it, so the reference lines can't be kept through compaction.
  After compaction, `SessionStart` (with source `compact`) restores the memory.
- **MCP file name:** the docs disagree on `.mcp.json` and `mcp.json`. This uses `.mcp.json`, which the plugin
  scaffolder generates.
- **Where plugin hooks run:** the docs say they run for plugins installed manually in the Codex desktop app;
  whether the CLI runs them isn't clear.
