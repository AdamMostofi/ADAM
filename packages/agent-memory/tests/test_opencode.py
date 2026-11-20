"""Stage 3.3 (#58): the OpenCode adapter and plugin, and one project's memory shared by two agents.

The payload shapes are OpenCode 1.18's, recorded from live runs with a logging plugin (#58 has the study).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agent_memory import Store
from agent_memory.adapters import claude_code as cc
from agent_memory.adapters import opencode as oc
from agent_memory.location import store_path
from agent_memory.mcp import resolve_session
from agent_memory.tools import call

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins" / "opencode" / "index.js"
S = "ses_oc1"


def git_project(path: Path) -> Path:
    path.mkdir(parents=True)
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@example.invalid"],
                ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=path, check=True)
    (path / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (path / "notes.md").write_text("# Notes\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)
    return path


@pytest.fixture
def project(tmp_path):
    return git_project(tmp_path / "proj")


def ev(project, event, payload, store=None):
    out, code = oc.handle(event, json.dumps({"directory": str(project), **payload}).encode(),
                          dict(os.environ, AMEM_PROJECT=str(project)), store=store)
    assert code == 0
    return out


def claude(project, event, payload):
    out, code = cc.handle(event, json.dumps(payload).encode(), dict(os.environ, CLAUDE_PROJECT_DIR=str(project)))
    assert code == 0
    return out


def open_store(project):
    return Store(store_path(project), min_free_bytes=0)


def changes(store):
    return [e.summary_fields for e in store.events() if e.kind == "file_change"
            and e.summary_fields.get("attribution") != "baseline"]


def oc_edit(project, call_id, rel, new_text, session=S):
    """An OpenCode edit as the plugin reports it: before, the file written, after (file.edited is not sent)."""
    path = str(project / rel)
    ev(project, "tool_before", {"session_id": session, "call_id": call_id, "tool": "edit",
                                "args": {"filePath": path, "oldString": "x", "newString": "y"}})
    (project / rel).write_text(new_text)
    ev(project, "tool_after", {"session_id": session, "call_id": call_id, "tool": "edit",
                               "args": {"filePath": path}, "title": rel, "output": "Edit applied successfully.",
                               "metadata": {"diagnostics": {}}})


# ------------------------------------------------------------ the adapter
def test_an_opencode_session_is_captured_and_gets_memory(project):
    assert ev(project, "session", {"session_id": S, "title": "New session", "version": "1.18.35"}) == ""
    brief = ev(project, "system", {"session_id": S, "model": "deepseek-v4.1-flash-free"})
    assert brief and not brief.startswith("{")          # plain text for the system prompt, not hook JSON
    ev(project, "prompt", {"session_id": S, "message_id": "msg_1", "text": "add sub to calc.py",
                           "agent": "build", "model": "deepseek-v4.1-flash-free"})
    oc_edit(project, "call-1", "calc.py", "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    ev(project, "tool_before", {"session_id": S, "call_id": "call-2", "tool": "bash",
                                "args": {"command": "python3 -m pytest -q", "description": "run tests"}})
    ev(project, "tool_after", {"session_id": S, "call_id": "call-2", "tool": "bash",
                               "args": {"command": "python3 -m pytest -q"}, "title": "python3 -m pytest -q",
                               "output": "2 passed", "metadata": {"output": "2 passed", "exit": 0,
                                                                  "truncated": False}})
    ev(project, "text", {"session_id": S, "message_id": "msg_2", "part_id": "prt_1", "text": "Added sub."})
    ev(project, "idle", {"session_id": S})
    ev(project, "deleted", {"session_id": S})

    store = open_store(project)
    mine = [e for e in store.events(session_id=S) if not e.kind.startswith("context_")]
    assert {e.agent for e in mine if e.kind not in ("file_change", "verification")} == {"opencode"}
    assert [e.kind for e in mine if e.kind in ("session_start", "user_message", "assistant_message",
                                                "session_end")] == \
        ["session_start", "user_message", "assistant_message", "session_end"]
    edit = [c for c in changes(store) if c["path"] == "calc.py"]
    assert edit and edit[-1]["attribution"] == "agent_tool" and edit[-1]["by"] == f"opencode:{S}"
    assert not [e for e in store.events() if e.kind == "conflict"]
    verification = [e for e in store.events() if e.kind == "verification"]
    assert verification and verification[0].summary_fields["result"] == "passed"
    assert store.verify()["ok"]


def test_replays_store_nothing_twice(project):
    payloads = [("session", {"session_id": S}), ("prompt", {"session_id": S, "message_id": "m", "text": "hi"}),
                ("text", {"session_id": S, "message_id": "m2", "part_id": "p1", "text": "hello"})]
    for event, payload in payloads + payloads:
        ev(project, event, payload)
    store = open_store(project)
    counted = [e.kind for e in store.events(session_id=S) if e.kind in ("session_start", "user_message",
                                                                        "assistant_message")]
    assert counted == ["session_start", "user_message", "assistant_message"]


def test_a_failed_tool_and_a_failed_command_are_recorded_as_failures(project):
    ev(project, "session", {"session_id": S})
    ev(project, "tool_after", {"session_id": S, "call_id": "c1", "tool": "read", "args": {"filePath": "x"},
                               "error": "File not found: x"})
    ev(project, "tool_before", {"session_id": S, "call_id": "c2", "tool": "bash", "args": {"command": "pytest"}})
    ev(project, "tool_after", {"session_id": S, "call_id": "c2", "tool": "bash", "args": {"command": "pytest"},
                               "output": "1 failed", "metadata": {"exit": 1}})
    store = open_store(project)
    results = {e.summary_fields["tool_use_id"]: e.summary_fields for e in store.events(session_id=S)
               if e.kind == "tool_result"}
    assert results["c1"]["failed"] and results["c1"]["error"] == "File not found: x"
    assert results["c2"]["failed"] and results["c2"]["exit_code"] == 1
    assert [e.summary_fields["result"] for e in store.events() if e.kind == "verification"] == ["failed"]


def test_a_patch_names_every_file_it_changes(project):
    ev(project, "session", {"session_id": S})
    patch = "*** Begin Patch\n*** Update File: calc.py\n@@\n-x\n+y\n*** Add File: new.py\n+print(1)\n*** End Patch"
    ev(project, "tool_before", {"session_id": S, "call_id": "p1", "tool": "apply_patch", "args": {"patchText": patch}})
    (project / "calc.py").write_text("changed\n")
    (project / "new.py").write_text("print(1)\n")
    ev(project, "tool_after", {"session_id": S, "call_id": "p1", "tool": "apply_patch", "args": {"patchText": patch},
                               "output": "ok", "metadata": {}})
    ev(project, "idle", {"session_id": S})
    got = {c["path"]: c for c in changes(open_store(project))}
    assert got["calc.py"]["by"] == got["new.py"]["by"] == f"opencode:{S}"
    assert got["calc.py"]["attribution"] == got["new.py"]["attribution"] == "agent_tool"


def test_compaction_keeps_references_and_restores_memory_after(project):
    ev(project, "session", {"session_id": S})
    first = ev(project, "system", {"session_id": S})
    decision = call(open_store(project), S, "mem_declare", {"op": "create", "kind": "decision",
                                                            "title": "calc.py stays dependency-free"})
    call(open_store(project), S, "mem_get", {"id": decision.split()[0]})   # loaded now: a reference to keep
    keep = ev(project, "compacting", {"session_id": S})
    assert "mem_context op=restore" in keep
    ev(project, "compacted", {"session_id": S})
    after = ev(project, "system", {"session_id": S})
    assert after and after != first
    store = open_store(project)
    assert [e.summary_fields["phase"] for e in store.events(session_id=S) if e.kind == "compaction"] == \
        ["before", "after"]


def test_a_child_session_is_a_subagent_of_its_parent(project):
    ev(project, "session", {"session_id": S})
    ev(project, "session", {"session_id": "ses_child", "parent_id": S, "title": "explore (@explore subagent)"})
    assert ev(project, "system", {"session_id": "ses_child"}) == ""
    ev(project, "deleted", {"session_id": "ses_child"})
    store = open_store(project)
    assert [e.kind for e in store.events(session_id=S) if e.kind.startswith("subagent")] == \
        ["subagent_start", "subagent_stop"]
    assert not [e for e in store.events(session_id="ses_child") if e.kind == "session_start"]


def test_a_plugin_loaded_mid_session_records_a_resume(project):
    assert ev(project, "system", {"session_id": "ses_old"})
    starts = [e.summary_fields["source"] for e in open_store(project).events(session_id="ses_old")
              if e.kind == "session_start"]
    assert starts == ["resume"]


def test_a_broken_store_never_blocks_opencode(project):
    store_dir = store_path(project)
    store_dir.mkdir(parents=True)
    (store_dir / "memory.db").write_text("not a database")
    out = ev(project, "system", {"session_id": S})
    assert "isn't being remembered" in out
    assert ev(project, "prompt", {"session_id": S, "text": "hi"}) == ""


# ------------------------------------------------------------ two agents, one project
def test_a_claude_code_session_continues_in_opencode(project):
    """Work and a decision in Claude Code, then OpenCode starts with that state, and attribution stays apart."""
    claude(project, "SessionStart", {"session_id": "cc1", "source": "startup", "cwd": str(project)})
    claude(project, "UserPromptSubmit", {"session_id": "cc1", "prompt": "keep calc.py free of dependencies"})
    call(open_store(project), "cc1", "mem_declare", {"op": "create", "kind": "decision",
                                                      "title": "calc.py stays dependency-free (school machines)"})
    task = call(open_store(project), "cc1", "mem_declare", {"op": "create", "kind": "task", "title": "add sub to calc.py",
                                                      "fields": {"status": "in_progress"}})
    claude(project, "PreToolUse", {"session_id": "cc1", "tool_name": "Edit", "tool_use_id": "t1",
                                   "tool_input": {"file_path": str(project / "notes.md")}})
    (project / "notes.md").write_text("# Notes\nsub is next\n")
    claude(project, "PostToolUse", {"session_id": "cc1", "tool_name": "Edit", "tool_use_id": "t1",
                                    "tool_input": {"file_path": str(project / "notes.md")}, "tool_response": {}})
    claude(project, "SessionEnd", {"session_id": "cc1", "reason": "other"})

    ev(project, "session", {"session_id": S})
    brief = ev(project, "system", {"session_id": S})
    assert "add sub to calc.py" in brief                # the open task comes with the session
    offers = ev(project, "prompt", {"session_id": S, "message_id": "m1",
                                    "text": "why must calc.py stay dependency-free?"})
    assert "dependency-free (school machines)" in offers   # the decision is offered when the prompt touches it
    store = open_store(project)
    assert resolve_session(store, "auto") == S          # the memory tools now serve the OpenCode session
    oc_edit(project, "call-1", "calc.py", "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n")
    call(store, S, "mem_declare", {"op": "status", "id": task.split()[0], "status": "done"})
    ev(project, "idle", {"session_id": S})

    store = open_store(project)
    by = {c["path"]: c.get("by") for c in changes(store)}
    assert by == {"notes.md": "claude-code:cc1", "calc.py": f"opencode:{S}"}
    writers = {e.writer_id for e in store.events() if e.kind in ("decision", "task", "entry", "state_item",
                                                                  "goal", "path")}
    assert any(w == "claude-code:cc1" for w in writers) and any(w == f"opencode:{S}" for w in writers)
    assert store.verify()["ok"]


def test_two_agents_at_once_in_one_project_stay_apart(project):
    claude(project, "SessionStart", {"session_id": "cc1", "source": "startup", "cwd": str(project)})
    ev(project, "session", {"session_id": S})
    # Interleaved: Claude Code edits notes.md, OpenCode edits calc.py, both run commands.
    claude(project, "PreToolUse", {"session_id": "cc1", "tool_name": "Edit", "tool_use_id": "t1",
                                   "tool_input": {"file_path": str(project / "notes.md")}})
    oc_edit(project, "call-1", "calc.py", "changed by opencode\n")
    (project / "notes.md").write_text("changed by claude\n")
    claude(project, "PostToolUse", {"session_id": "cc1", "tool_name": "Edit", "tool_use_id": "t1",
                                    "tool_input": {"file_path": str(project / "notes.md")}, "tool_response": {}})
    for agent, call_id in (("claude", "t2"), ("opencode", "call-2")):
        if agent == "claude":
            claude(project, "PreToolUse", {"session_id": "cc1", "tool_name": "Bash", "tool_use_id": call_id,
                                           "tool_input": {"command": "touch shared.txt"}})
        else:
            ev(project, "tool_before", {"session_id": S, "call_id": call_id, "tool": "bash",
                                        "args": {"command": "touch shared.txt"}})
    (project / "shared.txt").write_text("")
    (project / "solo.txt").write_text("")
    ev(project, "tool_after", {"session_id": S, "call_id": "call-2", "tool": "bash",
                               "args": {"command": "touch shared.txt"}, "output": "", "metadata": {"exit": 0}})
    store = open_store(project)
    got = {c["path"]: c for c in changes(store)}
    assert got["notes.md"]["by"] == "claude-code:cc1"
    assert got["calc.py"]["by"] == f"opencode:{S}"
    # Both agents ran a command naming shared.txt: who did it isn't known, and the record says so.
    assert "by" not in got["shared.txt"] and got["shared.txt"]["by_candidates"] == ["claude-code:cc1",
                                                                                  f"opencode:{S}"]
    assert got["solo.txt"]["attribution"] == "unattributed" and "by" not in got["solo.txt"]


def test_two_worktrees_keep_separate_memories(tmp_path):
    main = git_project(tmp_path / "main")
    other = tmp_path / "feature"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "feature", str(other)], cwd=main, check=True)
    claude(main, "SessionStart", {"session_id": "cc1", "source": "startup", "cwd": str(main)})
    ev(other, "session", {"session_id": S})
    oc_edit(other, "call-1", "calc.py", "feature work\n")
    ev(other, "idle", {"session_id": S})
    assert store_path(main) != store_path(other)
    a, b = open_store(main), open_store(other)
    assert {e.agent for e in a.events() if e.kind == "session_start"} == {"claude-code"}
    assert {e.agent for e in b.events() if e.kind == "session_start"} == {"opencode"}
    assert [c["by"] for c in changes(b)] == [f"opencode:{S}"]
    assert not changes(a)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=other, capture_output=True, text=True).stdout
    assert ".agent-memory" not in status


# ------------------------------------------------------------ the plugin (JavaScript, run by node)
NODE = shutil.which("node") or shutil.which("bun")
AMEM = shutil.which("amem") or str(Path(sys.executable).parent / "amem")


@pytest.mark.skipif(NODE is None, reason="node or bun is needed to run the plugin")
def test_the_plugin_translates_opencode_hooks(project, tmp_path):
    """The real plugin file, driven with recorded OpenCode hook shapes, through the direct path (no server)."""
    script = tmp_path / "drive.mjs"
    script.write_text(DRIVER)
    env = dict(os.environ, AMEM_BIN=AMEM)
    run = subprocess.run([NODE, str(script), str(PLUGIN), str(project)], env=env, capture_output=True, text=True,
                         timeout=300)
    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout.strip().splitlines()[-1])
    assert report["mcp"][-1] == "mcp" and "--session" in report["mcp"]
    assert report["system"] and not report["system"].startswith("agent-memory couldn't")
    assert report["parts_after_prompt"] >= 1
    store = open_store(project)
    mine = [e.kind for e in store.events(session_id="ses_plugin") if not e.kind.startswith("context_")]
    for kind in ("session_start", "user_message", "tool_call", "tool_result", "assistant_message", "compaction"):
        assert kind in mine, (kind, mine)
    edit = [c for c in changes(store) if c["path"] == "calc.py"]
    assert edit[-1]["by"] == "opencode:ses_plugin"
    texts = [e for e in store.events(session_id="ses_plugin") if e.kind == "assistant_message"]
    assert len(texts) == 1                              # the user's own text part and the streaming parts are skipped


@pytest.mark.skipif(NODE is None, reason="node or bun is needed to run the plugin")
def test_the_plugin_never_blocks_opencode_without_amem(project, tmp_path):
    script = tmp_path / "drive.mjs"
    script.write_text("const { AgentMemory } = await import(process.argv[2]);\n"
                      "const hooks = await AgentMemory({ directory: process.argv[3] }, { amem: '/nonexistent/amem' });\n"
                      "console.log(JSON.stringify(Object.keys(hooks)));\n")
    run = subprocess.run([NODE, str(script), str(PLUGIN), str(project)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0 and run.stdout.strip() == "[]"


DRIVER = r"""
import { writeFileSync } from "node:fs";
const { AgentMemory } = await import(process.argv[2]);
const dir = process.argv[3];
const sid = "ses_plugin";
const hooks = await AgentMemory({ directory: dir, worktree: dir }, { mcp: true });
const cfg = {};
await hooks.config(cfg);
const report = { mcp: cfg.mcp["agent-memory"].command };
await hooks.event({ event: { type: "session.created", properties: { info: { id: sid, title: "t", version: "1.18.35" } } } });
const out = { system: [] };
await hooks["experimental.chat.system.transform"]({ sessionID: sid, model: { id: "m" } }, out);
report.system = out.system[0] || "";
await hooks.event({ event: { type: "message.updated", properties: { info: { id: "msg_u", role: "user", sessionID: sid } } } });
const msg = { message: { id: "msg_u", sessionID: sid, role: "user" },
              parts: [{ id: "prt_u", type: "text", text: "add sub to calc.py", messageID: "msg_u", sessionID: sid }] };
await hooks["chat.message"]({ sessionID: sid, agent: "build", model: { providerID: "p", modelID: "m" } }, msg);
report.parts_after_prompt = msg.parts.length;
await hooks.event({ event: { type: "message.part.updated", properties: { part: { id: "prt_u", type: "text",
  text: "add sub to calc.py", messageID: "msg_u", sessionID: sid, time: { start: 1, end: 2 } } } } });
await hooks.event({ event: { type: "message.updated", properties: { info: { id: "msg_a", role: "assistant", sessionID: sid } } } });
const args = { filePath: dir + "/calc.py", oldString: "a + b", newString: "a + b" };
await hooks["tool.execute.before"]({ tool: "edit", sessionID: sid, callID: "call-1" }, { args });
writeFileSync(dir + "/calc.py", "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n");
await hooks["tool.execute.after"]({ tool: "edit", sessionID: sid, callID: "call-1", args },
                                  { title: "calc.py", output: "Edit applied successfully.", metadata: {} });
await hooks.event({ event: { type: "message.part.updated", properties: { part: { id: "prt_a", type: "text",
  text: "Added s", messageID: "msg_a", sessionID: sid, time: { start: 3 } } } } });
await hooks.event({ event: { type: "message.part.updated", properties: { part: { id: "prt_a", type: "text",
  text: "Added sub.", messageID: "msg_a", sessionID: sid, time: { start: 3, end: 4 } } } } });
await hooks.event({ event: { type: "message.part.updated", properties: { part: { id: "prt_a", type: "text",
  text: "Added sub.", messageID: "msg_a", sessionID: sid, time: { start: 3, end: 4 } } } } });
await hooks.event({ event: { type: "session.idle", properties: { sessionID: sid } } });
const ctx = { context: [] };
await hooks["experimental.session.compacting"]({ sessionID: sid }, ctx);
await hooks.event({ event: { type: "session.compacted", properties: { sessionID: sid } } });
console.log(JSON.stringify(report));
"""
