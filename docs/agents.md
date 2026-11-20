# Agent support (Stage 3.5, #60)

**Status:** Current: what each agent gets from agent-memory, and how far each claim has been tested. Written 2026-11-20.

**Rule:** a row says "tested" only for what was run. Agents built from their documentation say so, with the date
the docs were read, and no version. Their formats can change, and nothing here was checked against a real
install of them. #60's owner decision: none of Codex, Gemini CLI or Cursor was installed for testing.

## Tiers

| Tier | Needs | Gets | What the records say |
|---|---|---|---|
| **Hooks** | Lifecycle hooks or an in-process plugin | Everything: prompts, tools, file edits with their tool call, replies, compactions, memory at session start and on each prompt, the tools | Per event. A file change an agent's tool explains names that agent (`by`) |
| **MCP only** | MCP | The tools; a session for the agent; files reconciled before each tool call | The conversation: a capture gap (`unavailable`). File changes: `unattributed`, never naming the agent |
| **CLI only** | A shell | A memory brief the agent reads (`amem brief`); file reconciliation (`amem reconcile`) | No conversation. File changes: `git_operation` when the agent commits, otherwise `unattributed` or `external`; never naming the agent |

## By agent

| Agent | Tier | Install | Captures | Memory at session start | On each prompt | Compaction | Tools | Tested |
|---|---|---|---|---|---|---|---|---|
| **Claude Code** | Hooks | `claude plugin install agent-memory@adam` ([plugin](../plugins/claude-code/README.md)) | Prompts, tool calls and results, transcript messages, subagents, compactions, session end | `SessionStart` `additionalContext` | Offers (`UserPromptSubmit`) | Keeps reference lines; restores after | MCP | Hook payloads rebuilt from real Claude Code transcripts and replayed through the real launcher (3.1, #90). The Claude Code version wasn't recorded. |
| **OpenCode** | Hooks (plugin) | `"plugin": [".../plugins/opencode/index.js"]` ([plugin](../plugins/opencode/README.md)) | Prompts, tool calls and results, assistant text, compactions, child sessions | System prompt | A synthetic part on the user's message | Keeps reference lines; restores after | MCP, registered by the plugin | **OpenCode 1.18.35, live**, with the free `opencode/deepseek-v4.1-flash-free` model (3.3) |
| **Pi** | Hooks (extension) | `pi install .../plugins/pi` ([package](../plugins/pi/README.md)) | Prompts, tool calls and results, assistant messages, compactions, forks and `/tree` branches | An `agent_memory` system-prompt section | A hidden custom message | The section survives compaction; restored after | MCP (`pi.registerMcpServer`) | **Pi 1.4.0, real runtime**, driven by a scripted model on Pi's faux provider: no live model (3.4) |
| **Codex** | Hooks (plugin) | The [plugin](../plugins/codex/README.md) through a marketplace, then trust its hooks in `/hooks` | Prompts, tool calls and results (patches per file), each turn's final reply (`partial`), compactions, subagents, session end | `SessionStart` `additionalContext` | Offers (`UserPromptSubmit`) | Recorded; Codex reads no context from `PreCompact` | MCP (`.mcp.json`) | **Not tested against an install.** Built from developers.openai.com/codex docs (read 2026-11-20) |
| **Gemini CLI** | Hooks (extension) | `gemini extensions install .../plugins/gemini` ([extension](../plugins/gemini/README.md)) | Prompts, tool calls and results (paired by tool and input: no call id), each turn's final reply (`partial`), compression, session end | `SessionStart` `additionalContext` | Offers (`BeforeAgent`) | Recorded | MCP (in `gemini-extension.json`) | **Not tested against an install.** Built from geminicli.com docs (read 2026-11-20). Those docs say unpaid and Google One users were moved to Antigravity CLI on 2026-06-18; what that means for extensions isn't documented |
| **Cursor** | Hooks | `amem setup cursor` (`.cursor/hooks.json`, `mcp.json`, an always-on rule) | Prompts, tool results, file edits (no "before" content, so no conflict detection), replies, compactions, subagent ends, session end | `sessionStart` `additional_context`. Cursor's docs say the agent doesn't wait for it; the rule asks the agent to call `mem_context` | None: Cursor documents no way to add context to a prompt | Recorded (observational) | MCP | **Not tested against an install.** Built from cursor.com/docs (read 2026-11-20). Whether hooks run in the Cursor CLI isn't documented |
| **Windsurf / Devin Desktop** | MCP only | `amem setup windsurf` (`.devin/mcp_config.json`, an always-on rule) | Memory tool calls only; the conversation is a recorded gap | The rule asks the agent to call `mem_context` | None | Not seen | MCP | **Not tested against an install.** windsurf.com's docs now redirect to Devin's (read 2026-11-20). Devin documents Claude-style hooks, which could make it a hooks agent later |
| **Cline** | MCP only | `amem setup cline` (`.clinerules/agent-memory.md`, the CLI's MCP settings; the IDE's JSON is printed to paste) | As Windsurf | As Windsurf | None | Not seen | MCP | **Not tested against an install.** Built from docs.cline.bot (read 2026-11-20). Cline's TypeScript SDK plugins have hooks; not used |
| **Aider** | CLI only | `amem setup aider` (`.agent-memory/brief.md`, read through `.aider.conf.yml`) | Files only | The brief, as a read-only file | None | Not seen | None (no MCP documented) | **Not tested against an install.** Built from aider.chat docs (read 2026-11-20) |

## What every supported agent passes

`packages/agent-memory/tests/test_adapter_suite.py` runs one scenario through all six adapters (Claude Code,
OpenCode, Pi, Codex, Gemini CLI, Cursor):
- start, prompt, an edit, a test run, a reply, a compaction, end;
- each in that agent's own payload shapes (recorded for the first three, from the docs for the last three).

Each must:
- capture the session;
- name the agent on its own events, and on the edit it explains (`by`);
- record the test run as a verification;
- deliver memory at session start in the agent's format;
- store a replayed session once;
- never block when the store is broken;
- ignore events it doesn't know.

The same file checks the lower tiers:
- **MCP only:** the conversation is a recorded gap, and a file change is `unattributed`.
- **CLI only:** a brief is written, and a file change is `unattributed`.
- **`amem setup`:** it keeps the user's own configuration, can run twice, and installs no permission hook that
  could block or approve an action.

## Not covered

- **Agents not listed** (Kilo, Roo, Continue, Copilot, Amp, Goose, Factory Droid and others): not supported.
  #60 rules out promising support for agents that weren't tested.
- **Untested agents:** the formats above need a real install to confirm. Those checks are the follow-up.
- **Windows:** the Cursor desktop app runs hooks through PowerShell. `amem setup cursor` writes POSIX commands,
  so on Windows it is for projects inside WSL; this is untested.
