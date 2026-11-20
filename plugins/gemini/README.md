# agent-memory for Gemini CLI

**Status: built from the Gemini CLI documentation (read 2026-11-20); not tested against a real Gemini CLI
install.** See [docs/agents.md](../../docs/agents.md).

A Gemini CLI extension for the [Lossless Tree Memory engine](../../packages/agent-memory/): lossless capture
through Gemini CLI's hooks, memory context at session start and on each prompt, and the memory tools over MCP.

## Layout

- `gemini-extension.json`: the manifest, with the MCP server and `GEMINI.md` as context.
- `hooks/hooks.json`: `SessionStart`, `BeforeAgent`, `BeforeTool`, `AfterTool`, `AfterAgent`, `PreCompress` and
  `SessionEnd`, each running `scripts/amem-run` with `AMEM_AGENT=gemini`.
- `scripts/amem-run`: the shared launcher.

## Install

```bash
uv tool install /path/to/ADAM/packages/agent-memory
gemini extensions install /path/to/ADAM/plugins/gemini
```

## Known gaps, from the docs

- **Antigravity:** the docs say Gemini CLI was replaced by Antigravity CLI for unpaid and Google One users on
  2026-06-18. They don't say what that means for extensions.
- **`hooks/hooks.json` format:** the docs don't show its exact wrapper. This uses the same `{"hooks": {...}}`
  shape as `settings.json`.
- **Tool calls** carry no call id, so a call and its result are paired by tool name and input.
- **Replies:** only each turn's final reply is captured, marked `partial`.
