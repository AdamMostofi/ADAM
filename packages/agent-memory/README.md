# agent-memory

**Status:** in development inside the ADAM repository (Phase 2). Working
name; the final name is decision D8.

The Lossless Tree Memory Engine is a complete, navigable, verifiable memory
of a development project, for coding agents. Design:
[`docs/design/2026-11-06-agent-memory-engine.md`](../../docs/design/2026-11-06-agent-memory-engine.md).

This package never imports ADAM; a test enforces it, and CI runs its tests in
an environment where ADAM isn't installed.

## What works so far

- **Stage 2.2:**
  - the canonical event format;
  - an append-only, per-writer hash-chained event log;
  - a lossless raw archive: compressed, encrypted and content-addressed;
  - secret redaction before any write, and path exclusions;
  - gap records instead of partial copies;
  - a configurable store location.
- **Stage 2.3:**
  - the historical tree (project, session, turn, event);
  - typed relationships with a basis on every edge;
  - development paths with status history;
  - goals, tasks, blockers, decisions and notes;
  - every navigation in design 6.1, and `trace()` along relationships.
  - All of it is append-only, and `verify()` rebuilds it from the log.
- **Stage 2.4:**
  - every file version, with renames and automatic revert detection;
  - an incremental tree-sitter dependency graph for Python and TypeScript;
  - verification records with relevant files and an environment fingerprint;
  - computed `verified` / `stale` / `unknown` status, with reasons.

```bash
cd packages/agent-memory
uv sync --locked --extra dev
uv run pytest -q
```
