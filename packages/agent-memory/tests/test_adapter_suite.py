"""The shared adapter suite (Stage 3.5, #60): one scenario, every supported agent, the same checks.

Each driver turns a step (start, prompt, edit, test run, reply, compaction, end) into that agent's own hook or
plugin payloads, in the shapes its adapter documents:
- recorded from real runs: Claude Code, OpenCode, Pi;
- from the official docs (read 2026-11-20), not from a real install: Codex, Gemini CLI, Cursor.
Every agent then has to pass the same checks, and the lower tiers (MCP only, CLI only) are checked for saying
honestly that they don't know who changed a file.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from agent_memory import Store
from agent_memory.adapters import AGENTS, hooked, run
from agent_memory.location import store_path
from agent_memory.mcp import close_mcp_only_session, open_mcp_only_session, serve
from agent_memory.setup import CURSOR_EVENTS, setup

ROOT = Path(__file__).resolve().parents[3]
SID = "s-1"


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@example.invalid"],
                ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=p, check=True)
    (p / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=p, check=True)
    return p


class Driver:
    """Steps in one agent's shapes. `send` returns the adapter's stdout."""
    agent = ""

    def __init__(self, project: Path):
        self.project = project

    def send(self, event: str, payload: dict) -> str:
        out, code = run(self.agent, event, json.dumps(payload).encode(), dict(os.environ, AMEM_PROJECT=str(self.project)))
        assert code == 0
        return out

    def write(self, rel: str, text: str) -> None:
        (self.project / rel).write_text(text)

    def context(self, out: str) -> str:
        """The memory text in a session start's reply."""
        return json.loads(out)["hookSpecificOutput"]["additionalContext"] if out else ""


class ClaudeCode(Driver):
    agent = "claude-code"

    def start(self): return self.send("SessionStart", {"session_id": SID, "source": "startup", "cwd": str(self.project)})
    def prompt(self, text): self.send("UserPromptSubmit", {"session_id": SID, "prompt": text})

    def edit(self, rel, text):
        ti = {"file_path": str(self.project / rel)}
        self.send("PreToolUse", {"session_id": SID, "tool_name": "Edit", "tool_use_id": "t1", "tool_input": ti})
        self.write(rel, text)
        self.send("PostToolUse", {"session_id": SID, "tool_name": "Edit", "tool_use_id": "t1", "tool_input": ti,
                                  "tool_response": {"type": "update"}})

    def test_run(self, command):
        ti = {"command": command}
        self.send("PreToolUse", {"session_id": SID, "tool_name": "Bash", "tool_use_id": "t2", "tool_input": ti})
        self.send("PostToolUse", {"session_id": SID, "tool_name": "Bash", "tool_use_id": "t2", "tool_input": ti,
                                  "tool_response": {"stdout": "1 passed", "stderr": ""}})

    def reply(self, text): self.send("Stop", {"session_id": SID, "last_assistant_message": text})
    def compact(self): self.send("PreCompact", {"session_id": SID, "trigger": "auto"})
    def end(self): self.send("SessionEnd", {"session_id": SID, "reason": "other"})


class Codex(ClaudeCode):
    agent = "codex"

    def edit(self, rel, text):
        patch = f"*** Begin Patch\n*** Update File: {rel}\n@@\n-x\n+y\n*** End Patch"
        ti = {"command": patch}
        self.send("PreToolUse", {"session_id": SID, "turn_id": "u1", "tool_name": "apply_patch", "tool_use_id": "t1",
                                 "tool_input": ti, "cwd": str(self.project), "model": "m"})
        self.write(rel, text)
        self.send("PostToolUse", {"session_id": SID, "turn_id": "u1", "tool_name": "apply_patch", "tool_use_id": "t1",
                                  "tool_input": ti, "tool_response": "Success. Updated the following files"})

    def test_run(self, command):
        ti = {"command": command}
        self.send("PreToolUse", {"session_id": SID, "turn_id": "u1", "tool_name": "Bash", "tool_use_id": "t2",
                                 "tool_input": ti})
        self.send("PostToolUse", {"session_id": SID, "turn_id": "u1", "tool_name": "Bash", "tool_use_id": "t2",
                                  "tool_input": ti, "tool_response": "1 passed"})

    def reply(self, text): self.send("Stop", {"session_id": SID, "turn_id": "u1", "last_assistant_message": text,
                                              "stop_hook_active": False})


class Gemini(Driver):
    agent = "gemini"

    def start(self): return self.send("SessionStart", {"session_id": SID, "source": "startup", "cwd": str(self.project),
                                                       "hook_event_name": "SessionStart"})
    def prompt(self, text): self.send("BeforeAgent", {"session_id": SID, "prompt": text})

    def edit(self, rel, text):
        ti = {"file_path": str(self.project / rel), "content": text}
        self.send("BeforeTool", {"session_id": SID, "tool_name": "write_file", "tool_input": ti})
        self.write(rel, text)
        self.send("AfterTool", {"session_id": SID, "tool_name": "write_file", "tool_input": ti,
                                "tool_response": {"llmContent": "Successfully wrote", "returnDisplay": "ok"}})

    def test_run(self, command):
        ti = {"command": command}
        self.send("BeforeTool", {"session_id": SID, "tool_name": "run_shell_command", "tool_input": ti})
        self.send("AfterTool", {"session_id": SID, "tool_name": "run_shell_command", "tool_input": ti,
                                "tool_response": {"llmContent": "1 passed", "returnDisplay": "1 passed"}})

    def reply(self, text): self.send("AfterAgent", {"session_id": SID, "prompt": "p", "prompt_response": text})
    def compact(self): self.send("PreCompress", {"session_id": SID, "trigger": "auto"})
    def end(self): self.send("SessionEnd", {"session_id": SID, "reason": "exit"})


class Cursor(Driver):
    agent = "cursor"

    def common(self, **extra):
        return {"conversation_id": SID, "generation_id": "g1", "workspace_roots": [str(self.project)],
                "cursor_version": "1.7.2", **extra}

    def start(self): return self.send("sessionStart", self.common(session_id=SID, is_background_agent=False))
    def context(self, out): return json.loads(out).get("additional_context", "")
    def prompt(self, text): self.send("beforeSubmitPrompt", self.common(prompt=text))

    def edit(self, rel, text):
        self.write(rel, text)
        self.send("afterFileEdit", self.common(file_path=str(self.project / rel),
                                               edits=[{"old_string": "x", "new_string": "y"}]))

    def test_run(self, command):
        self.send("postToolUse", self.common(tool_name="Shell", tool_input={"command": command}, tool_use_id="t2",
                                             tool_output="1 passed", duration=10))

    def reply(self, text): self.send("afterAgentResponse", self.common(text=text))
    def compact(self): self.send("preCompact", self.common(trigger="auto", context_usage_percent=90))
    def end(self): self.send("sessionEnd", self.common(session_id=SID, reason="completed", duration_ms=10))


class OpenCode(Driver):
    agent = "opencode"

    def start(self):
        self.send("session", {"session_id": SID, "directory": str(self.project)})
        return self.send("system", {"session_id": SID})
    def context(self, out): return out
    def prompt(self, text): self.send("prompt", {"session_id": SID, "message_id": "m1", "text": text})

    def edit(self, rel, text):
        args = {"filePath": str(self.project / rel)}
        self.send("tool_before", {"session_id": SID, "call_id": "c1", "tool": "edit", "args": args})
        self.write(rel, text)
        self.send("tool_after", {"session_id": SID, "call_id": "c1", "tool": "edit", "args": args, "output": "ok"})

    def test_run(self, command):
        args = {"command": command}
        self.send("tool_before", {"session_id": SID, "call_id": "c2", "tool": "bash", "args": args})
        self.send("tool_after", {"session_id": SID, "call_id": "c2", "tool": "bash", "args": args,
                                 "output": "1 passed", "metadata": {"exit": 0}})

    def reply(self, text): self.send("text", {"session_id": SID, "message_id": "m2", "part_id": "p1", "text": text})
    def compact(self): self.send("compacting", {"session_id": SID})
    def end(self): self.send("deleted", {"session_id": SID})


class Pi(Driver):
    agent = "pi"

    def start(self):
        self.send("session", {"session_id": SID, "reason": "startup", "cwd": str(self.project)})
        return self.send("brief", {"session_id": SID})
    def context(self, out): return out
    def prompt(self, text): self.send("prompt", {"session_id": SID, "text": text})

    def edit(self, rel, text):
        args = {"path": rel, "edits": [{"oldText": "x", "newText": "y"}]}
        self.send("tool_before", {"session_id": SID, "call_id": "c1", "tool": "edit", "args": args})
        self.write(rel, text)
        self.send("tool_after", {"session_id": SID, "call_id": "c1", "tool": "edit", "args": args,
                                 "content": [{"type": "text", "text": "ok"}], "is_error": False})

    def test_run(self, command):
        args = {"command": command}
        self.send("tool_before", {"session_id": SID, "call_id": "c2", "tool": "bash", "args": args})
        self.send("tool_after", {"session_id": SID, "call_id": "c2", "tool": "bash", "args": args,
                                 "content": [{"type": "text", "text": "1 passed"}], "is_error": False,
                                 "structured": {"exit_code": 0}})

    def reply(self, text): self.send("text", {"session_id": SID, "text": text, "timestamp": 1})
    def compact(self): self.send("compacting", {"session_id": SID, "reason": "manual"})
    def end(self): self.send("shutdown", {"session_id": SID, "reason": "quit"})


DRIVERS = {d.agent: d for d in (ClaudeCode, Codex, Gemini, Cursor, OpenCode, Pi)}


def test_every_registered_agent_has_a_driver():
    assert set(DRIVERS) == set(AGENTS)


def scenario(d: Driver) -> str:
    out = d.start()
    d.prompt("add sub to calc.py")
    d.edit("calc.py", "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    d.test_run("python3 -m pytest -q")
    d.reply("Added sub; the tests pass.")
    d.compact()
    d.end()
    return out


def store_of(project) -> Store:
    return Store(store_path(project), min_free_bytes=0)


@pytest.fixture(params=sorted(DRIVERS))
def driver(request, project):
    return DRIVERS[request.param](project)


def test_the_session_is_captured_and_says_who_did_it(driver, project):
    scenario(driver)
    store = store_of(project)
    mine = [e for e in store.events(session_id=SID) if not e.kind.startswith("context_")]
    kinds = {e.kind for e in mine}
    assert {"session_start", "user_message", "tool_result", "assistant_message", "compaction",
            "session_end"} <= kinds, kinds
    agents = {e.agent for e in mine if e.writer_id != "reconciler" and e.kind != "verification"}
    assert agents == {driver.agent}
    edits = [e.summary_fields for e in store.events() if e.kind == "file_change"
             and e.summary_fields["attribution"] != "baseline"]
    assert edits and edits[-1]["path"] == "calc.py"
    assert edits[-1]["attribution"] == "agent_tool" and edits[-1]["by"] == f"{driver.agent}:{SID}"
    assert [e.summary_fields["result"] for e in store.events() if e.kind == "verification"] == ["passed"]
    assert store.verify()["ok"]


def test_memory_arrives_at_session_start_in_the_agents_format(driver, project):
    out = driver.start()
    assert "Memory for session" in driver.context(out)


def test_a_replayed_session_is_stored_once(driver, project):
    scenario(driver)
    first = len(list(store_of(project).events()))
    scenario(driver)
    events = [e for e in store_of(project).events() if not e.kind.startswith("context_")
              and e.kind not in ("file_change", "session_start")]
    again = [e for e in list(store_of(project).events())[first:] if e.kind not in
             ("file_change", "session_start", "session_end", "context_load", "context_unload")]
    assert not [e for e in again if e.kind in ("user_message", "tool_call", "tool_result", "assistant_message",
                                               "verification")], [e.kind for e in again]
    assert events


def test_a_broken_store_never_blocks_the_agent(driver, project):
    (store_path(project)).mkdir(parents=True)
    (store_path(project) / "memory.db").write_text("not a database")
    out = driver.start()
    if driver.agent in ("gemini", "cursor"):
        json.loads(out)                              # still the JSON these agents parse
    driver.prompt("hi")


def test_unknown_events_are_ignored(driver, project):
    out = driver.send("SomethingNew", {"session_id": SID})
    assert out in ("", "{}")


# ------------------------------------------------------------ the lower tiers say what they don't know
def test_the_mcp_only_tier_records_the_gap_and_never_names_who_changed_a_file(project):
    store = store_of(project)
    store.reconciler(str(project), "setup").run()          # the project as it was
    session = open_mcp_only_session(store, "cline", str(project))
    (project / "calc.py").write_text("changed while Cline worked\n")
    calls = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": "mem_state", "arguments": {"op": "overview"}}}) + "\n")
    serve(store, session, stdin=calls, stdout=io.StringIO(),
          before_call=lambda: store.reconciler(str(project), session, agent_unseen=True).run())
    close_mcp_only_session(store, "cline", session)
    events = list(store_of(project).events(session_id=session))
    assert [e.kind for e in events if e.kind in ("session_start", "capture_gap", "session_end")] == \
        ["session_start", "capture_gap", "session_end"]
    gap = [e for e in events if e.kind == "capture_gap"][0]
    assert gap.completeness == "unavailable" and gap.summary_fields["missed_kind"] == "conversation"
    change = [e.summary_fields for e in events if e.kind == "file_change"][0]
    assert change["attribution"] == "unattributed" and "by" not in change


def test_the_cli_only_tier_writes_a_brief_and_never_names_who_changed_a_file(project):
    lines = setup("aider", project)
    assert (store_path(project) / "brief.md").read_text().startswith("# Project memory")
    assert "brief.md" in (project / ".aider.conf.yml").read_text()
    assert any("unattributed" in line for line in lines)
    (project / "calc.py").write_text("changed by aider\n")
    store_of(project).reconciler(str(project), "after-aider", agent_unseen=True).run()
    change = [e.summary_fields for e in store_of(project).events() if e.kind == "file_change"
              and e.summary_fields["attribution"] != "baseline"][-1]
    assert change["attribution"] == "unattributed" and "by" not in change


def test_setup_merges_config_and_can_run_twice(project):
    hooks = project / ".cursor" / "hooks.json"
    hooks.parent.mkdir()
    hooks.write_text(json.dumps({"version": 1, "hooks": {"afterFileEdit": [{"command": "./format.sh"}]}}))
    setup("cursor", project)
    setup("cursor", project)
    data = json.loads(hooks.read_text())
    assert {"command": "./format.sh"} in data["hooks"]["afterFileEdit"]       # the user's own hook stays
    for event in CURSOR_EVENTS:
        ours = [e for e in data["hooks"][event] if f"hook cursor {event}" in e["command"]]
        assert len(ours) == 1                                                  # once, however often it runs
    assert json.loads((project / ".cursor" / "mcp.json").read_text())["mcpServers"]["agent-memory"]["type"] == "stdio"
    assert "alwaysApply: true" in (project / ".cursor" / "rules" / "agent-memory.mdc").read_text()
    # No permission hook: a memory hook must never block or approve an action.
    assert not {"preToolUse", "beforeShellExecution", "beforeMCPExecution", "beforeReadFile",
                "subagentStart"} & set(data["hooks"])


def test_setup_dry_run_writes_nothing(project, tmp_path, monkeypatch):
    monkeypatch.setenv("CLINE_MCP_SETTINGS_PATH", str(tmp_path / "cline.json"))
    lines = setup("cline", project, dry_run=True)
    assert all(not line.startswith("wrote") for line in lines)
    assert not (project / ".clinerules").exists() and not (tmp_path / "cline.json").exists()


# ------------------------------------------------------------ the plugin packages
def test_the_codex_and_gemini_packages_hook_every_event_the_adapter_handles():
    codex = json.loads((ROOT / "plugins" / "codex" / "hooks" / "hooks.json").read_text())["hooks"]
    gemini = json.loads((ROOT / "plugins" / "gemini" / "hooks" / "hooks.json").read_text())["hooks"]
    for agent, table in (("codex", codex), ("gemini", gemini)):
        for event, groups in table.items():
            assert hooked.TRANSLATE[agent](event, {"session_id": SID}), (agent, event)
            command = groups[0]["hooks"][0]["command"]
            assert f"AMEM_AGENT={agent}" in command and command.endswith(f"hook {event}")
    assert codex["SessionEnd"][0]["hooks"][0]["timeout"] <= 3                   # Codex allows at most 3 s
    manifest = json.loads((ROOT / "plugins" / "codex" / ".codex-plugin" / "plugin.json").read_text())
    assert manifest["hooks"] == "./hooks/hooks.json"
    extension = json.loads((ROOT / "plugins" / "gemini" / "gemini-extension.json").read_text())
    assert extension["name"] == "agent-memory" and "agent-memory" in extension["mcpServers"]


def test_every_plugin_ships_the_same_launcher():
    launchers = [(ROOT / "plugins" / p / "scripts" / "amem-run").read_bytes() for p in ("claude-code", "codex", "gemini")]
    assert launchers[0] == launchers[1] == launchers[2]
