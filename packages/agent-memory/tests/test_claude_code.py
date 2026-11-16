"""Stage 3.1 (#56): the adapter contract, the Claude Code adapter and plugin, key sources, and failure modes."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from agent_memory import Store, keys
from agent_memory.adapters import claude_code as cc
from agent_memory.cli import main as amem
from agent_memory.location import store_path
from agent_memory.mcp import handle as mcp

ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins" / "claude-code"
LAUNCHER = PLUGIN / "scripts" / "amem-run"
S = "sess-1"


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@example.invalid"],
                ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=p, check=True)
    (p / "jwt.py").write_text("def refresh():\n    return 1\n")
    (p / "README.md").write_text("# Project\n")
    subprocess.run(["git", "add", "-A"], cwd=p, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=p, check=True)
    return p


def hook(project, event, payload, **env):
    environ = dict(os.environ, CLAUDE_PROJECT_DIR=str(project), **env)
    out, code = cc.handle(event, json.dumps(payload).encode(), environ)
    assert code == 0
    return json.loads(out) if out.startswith("{") else out


def open_store(project):
    return Store(store_path(project), min_free_bytes=0)


def kinds(store, session=S):
    return [e.kind for e in store.events(session_id=session) if not e.kind.startswith("context_")]


def session_payloads(project, transcript):
    jwt = str(project / "jwt.py")
    return [
        ("SessionStart", {"session_id": S, "source": "startup", "model": "claude-opus-5", "cwd": str(project)}),
        ("UserPromptSubmit", {"session_id": S, "prompt": "refresh in jwt.py returns the wrong value"}),
        ("PreToolUse", {"session_id": S, "tool_name": "Edit", "tool_use_id": "t1",
                        "tool_input": {"file_path": jwt, "old_string": "1", "new_string": "2"}}),
        ("EDIT", None),
        ("PostToolUse", {"session_id": S, "tool_name": "Edit", "tool_use_id": "t1", "tool_input": {"file_path": jwt},
                         "tool_response": {"filePath": jwt, "type": "update"}}),
        ("PreToolUse", {"session_id": S, "tool_name": "Bash", "tool_use_id": "t2",
                        "tool_input": {"command": "uv run pytest -q", "description": "run the tests"}}),
        ("PostToolUse", {"session_id": S, "tool_name": "Bash", "tool_use_id": "t2", "tool_input": {"command":
                         "uv run pytest -q"}, "tool_response": {"stdout": "3 passed", "stderr": ""}}),
        ("PreToolUse", {"session_id": S, "tool_name": "Bash", "tool_use_id": "t3", "tool_input": {"command": "false"}}),
        ("PostToolUseFailure", {"session_id": S, "tool_name": "Bash", "tool_use_id": "t3",
                                "tool_input": {"command": "false"}, "error": "Exit code 1\n"}),
        ("SubagentStart", {"session_id": S, "agent_type": "Explore", "agent_id": "a1"}),
        ("SubagentStop", {"session_id": S, "agent_type": "Explore", "agent_id": "a1",
                          "last_assistant_message": "found it"}),
        ("Stop", {"session_id": S, "transcript_path": str(transcript), "last_assistant_message": "Done."}),
        ("PreCompact", {"session_id": S, "trigger": "auto", "custom_instructions": None}),
        ("PostCompact", {"session_id": S, "trigger": "auto", "compact_summary": "We fixed refresh."}),
        ("SessionStart", {"session_id": S, "source": "compact", "cwd": str(project)}),
        ("SessionEnd", {"session_id": S, "reason": "other"}),
    ]


def write_transcript(path):
    lines = [{"type": "user", "uuid": "u0", "message": {"role": "user", "content": "refresh is wrong"}},
             {"type": "assistant", "uuid": "a1", "message": {"role": "assistant", "content": [
                 {"type": "text", "text": "Let me look at jwt.py."}, {"type": "tool_use", "id": "t1", "name": "Edit"}]}},
             {"type": "assistant", "uuid": "a2", "message": {"role": "assistant", "content": [
                 {"type": "text", "text": "Fixed: refresh now returns 2, and the tests pass."}]}}]
    path.write_text("".join(json.dumps(x) + "\n" for x in lines))


def replay(project, transcript):
    outputs = {}
    for event, payload in session_payloads(project, transcript):
        if event == "EDIT":
            (project / "jwt.py").write_text("def refresh():\n    return 2\n")
            continue
        outputs.setdefault(event, []).append(hook(project, event, payload))
    return outputs


# ---------------------------------------------------------------- a whole session
def test_a_replayed_session_stores_every_event_or_records_each_gap(project, tmp_path):
    transcript = tmp_path / "t.jsonl"
    write_transcript(transcript)
    out = replay(project, transcript)
    store = open_store(project)
    got = kinds(store)
    for kind in ("session_start", "user_message", "tool_call", "tool_result", "file_change", "verification",
                 "subagent_start", "subagent_stop", "assistant_message", "compaction", "session_end"):
        assert kind in got, kind
    assert got.count("assistant_message") == 3 and got.count("compaction") == 2 and got.count("session_start") == 2
    assert all(e.completeness == "captured" for e in store.events(session_id=S))
    # The edit: an intent, then the result, then the reconciled change attributed to the agent's tool.
    (change,) = [v for v in store.artifacts.versions("jwt.py") if v["attribution"] != "baseline"]
    assert (change["attribution"], change["attribution_basis"]) == ("agent_tool", "observed")
    checks = [e for e in store.events(session_id=S) if e.kind == "verification"]
    assert [c.summary_fields["result"] for c in checks] == ["passed"]           # `false` isn't a test command
    env = cc._State(store).get("session", f"env:{S}")
    assert env["os"] and checks[0].summary_fields["environment"] == env        # the environment, captured (#82)
    assert store.verification_status(checks[0].event_id, env)["status"] == "verified"
    failure = [e for e in store.events(session_id=S) if e.kind == "tool_result" and e.summary_fields.get("failed")]
    assert failure[0].summary_fields["exit_code"] == 1
    summary = [e for e in store.events(session_id=S) if e.kind == "compaction" and e.payload_object]
    assert store.payload(summary[0]) == b"We fixed refresh."
    # What was delivered back to Claude Code.
    start = out["SessionStart"][0]["hookSpecificOutput"]
    assert start["hookEventName"] == "SessionStart" and len(start["additionalContext"]) <= cc.INJECT_CHARS
    offer = out["UserPromptSubmit"][0]["hookSpecificOutput"]["additionalContext"]
    assert "artifact:jwt.py" in offer and "mentions the file jwt.py" in offer
    assert out["SessionStart"][1]["hookSpecificOutput"]["additionalContext"].startswith("# Memory restored after compaction")
    assert store.verify()["ok"]

    # Replaying the identical session stores nothing twice.
    def captured(s):
        return [(e.kind, e.idempotency_key) for e in s.events() if not e.kind.startswith("context_")
                and e.kind not in ("file_change", "recovery")]

    before = captured(store)
    replay(project, transcript)
    after = open_store(project)
    assert captured(after) == before   # every captured event is stored once, however often it is replayed
    assert kinds(after).count("user_message") == 1 and kinds(after).count("assistant_message") == 3
    assert kinds(after).count("verification") == 1


def test_a_missing_transcript_is_a_partial_capture_not_a_silent_loss(project):
    hook(project, "SessionStart", {"session_id": S, "source": "startup"})
    hook(project, "Stop", {"session_id": S, "transcript_path": "/nowhere/t.jsonl", "last_assistant_message": "Done."})
    store = open_store(project)
    (msg,) = [e for e in store.events(session_id=S) if e.kind == "assistant_message"]
    assert msg.completeness == "partial" and "transcript unreadable" in msg.summary_fields["missing"]
    assert store.payload(msg) == b"Done."


def test_the_transcript_is_read_incrementally(project, tmp_path):
    t = tmp_path / "t.jsonl"
    write_transcript(t)
    hook(project, "Stop", {"session_id": S, "transcript_path": str(t)})
    with open(t, "a") as f:
        f.write(json.dumps({"type": "assistant", "uuid": "a3", "message": {"content": [{"type": "text",
                                                                                         "text": "One more."}]}}) + "\n")
        f.write('{"type": "assistant", "uuid": "a4", "mess')   # a line still being written
    hook(project, "Stop", {"session_id": S, "transcript_path": str(t)})
    assert kinds(open_store(project)).count("assistant_message") == 3


# ---------------------------------------------------------------- never block the agent
def test_a_broken_store_never_blocks_claude_code(project):
    hook(project, "SessionStart", {"session_id": S, "source": "startup"})
    key = next((Path(os.environ["XDG_CONFIG_HOME"]) / "agent-memory" / "keys").glob("*.key"))
    good = key.read_bytes()
    key.write_bytes(os.urandom(32))   # the wrong key: the store can't be unlocked
    started = time.perf_counter()
    out = hook(project, "SessionStart", {"session_id": "s2", "source": "startup"})
    assert "couldn't open this project's memory" in out["hookSpecificOutput"]["additionalContext"]
    assert hook(project, "PreToolUse", {"session_id": "s2", "tool_name": "Read", "tool_input": {}}) == ""
    assert time.perf_counter() - started < 10
    key.write_bytes(good)
    store = open_store(project)   # the spool becomes gap records
    gaps = [e for e in store.events(session_id="s2") if e.kind == "capture_gap"]
    assert len(gaps) == 2 and all(g.completeness == "unavailable" for g in gaps)
    assert {g.summary_fields["missed_kind"] for g in gaps} == {"claude-code SessionStart", "claude-code PreToolUse"}


def test_bad_input_and_unknown_events_are_ignored(project):
    assert cc.handle("PreToolUse", b"not json", dict(os.environ, CLAUDE_PROJECT_DIR=str(project))) == ("", 0)
    assert cc.handle("Notification", b"{}", dict(os.environ, CLAUDE_PROJECT_DIR=str(project))) == ("", 0)


def test_a_failing_handler_records_a_gap(project, monkeypatch):
    monkeypatch.setitem(cc.HANDLERS, "Stop", lambda h: 1 / 0)
    assert hook(project, "Stop", {"session_id": S}) == ""
    (gap,) = [e for e in open_store(project).events(session_id=S) if e.kind == "capture_gap"]
    assert gap.summary_fields["missed_kind"] == "Stop" and "ZeroDivisionError" in gap.summary_fields["reason"]


# ---------------------------------------------------------------- paths, project, MCP
def test_windows_paths_into_wsl_become_linux_paths():
    assert cc.native("\\\\wsl.localhost\\Ubuntu\\home\\adam\\ADAM\\a.py") == "/home/adam/ADAM/a.py"
    assert cc.native("//wsl$/Ubuntu/home/x") == "/home/x"
    assert cc.native("/home/x/a.py") == "/home/x/a.py"
    assert cc.relative("/home/x", "\\\\wsl.localhost\\Ubuntu\\home\\x\\src\\a.py") == "src/a.py"
    assert cc._outside(cc.relative("/home/x", "/etc/passwd"))


def test_a_session_leaves_the_project_unchanged(project, tmp_path):
    files = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob("*")
             if p.is_file() and ".git" not in p.parts}
    write_transcript(tmp_path / "t.jsonl")
    for event, payload in session_payloads(project, tmp_path / "t.jsonl"):
        if event != "EDIT":
            hook(project, event, payload)
    assert subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True,
                          text=True).stdout == ""                                 # the store ignores itself
    assert {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in project.rglob("*")
            if p.is_file() and ".git" not in p.parts and ".agent-memory" not in p.parts} == files


def test_the_mcp_server_follows_the_session_the_hooks_started(project):
    hook(project, "SessionStart", {"session_id": "live-7", "source": "startup"})
    store = open_store(project)
    reply = mcp(store, "auto", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": "mem_context", "arguments": {"op": "working_set"}}})
    assert '"session": "live-7"' in reply["result"]["content"][0]["text"]


def test_the_cli_hook_command_reads_stdin(project, monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(json.dumps({"session_id": S, "source": "startup"})
                                                                 .encode())))
    assert amem(["--project", str(project), "hook", "claude-code", "SessionStart"]) == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["hookEventName"] == "SessionStart"


# ---------------------------------------------------------------- the plugin package
DOCUMENTED_EVENTS = {"SessionStart", "Setup", "UserPromptSubmit", "UserPromptExpansion", "PreToolUse",
                     "PermissionRequest", "PermissionDenied", "PostToolUse", "PostToolUseFailure", "PostToolBatch",
                     "Notification", "MessageDisplay", "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted",
                     "Stop", "StopFailure", "TeammateIdle", "InstructionsLoaded", "ConfigChange", "CwdChanged",
                     "DirectoryAdded", "FileChanged", "WorktreeCreate", "WorktreeRemove", "PreCompact", "PostCompact",
                     "PreModelSwitch", "PostModelSwitch", "Elicitation", "ElicitationResult", "SessionEnd"}


def test_the_plugin_manifests_follow_the_documented_formats():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "agent-memory" and "claude" not in manifest["name"]
    for option in manifest["userConfig"].values():
        assert set(option) <= {"type", "title", "description", "required", "default", "options", "multiple",
                               "sensitive", "min", "max"} and {"type", "title", "description"} <= set(option)
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())
    assert set(hooks["hooks"]) <= DOCUMENTED_EVENTS and set(hooks["hooks"]) == set(cc.HANDLERS)
    for groups in hooks["hooks"].values():
        for group in groups:
            for h in group["hooks"]:
                assert h["type"] == "command" and h["command"] == "bash"
                assert h["args"][0] == "${CLAUDE_PLUGIN_ROOT}/scripts/amem-run" and h["args"][1] == "hook"
    servers = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]
    assert servers["agent-memory"]["args"] == ["${CLAUDE_PLUGIN_ROOT}/scripts/amem-run", "mcp"]
    assert LAUNCHER.is_file() and (PLUGIN / "skills" / "memory" / "SKILL.md").is_file()
    assert not (PLUGIN / "bin").exists() and not (PLUGIN / "CLAUDE.md").exists()
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    (entry,) = market["plugins"]
    assert market["owner"]["name"] and entry["source"].startswith("./") and ".." not in entry["source"]
    assert (ROOT / entry["source"]).resolve() == PLUGIN.resolve()


def run_launcher(args, payload, env):
    return subprocess.run(["bash", str(LAUNCHER), *args], input=json.dumps(payload).encode(), capture_output=True,
                          env=env, timeout=120)


def test_the_launcher_explains_a_missing_install_and_never_blocks(project, tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_PROJECT_DIR": str(project)}
    start = run_launcher(["hook", "SessionStart"], {"session_id": S}, env)
    assert start.returncode == 0
    assert "amem command is not installed" in json.loads(start.stdout)["hookSpecificOutput"]["additionalContext"]
    other = run_launcher(["hook", "PreToolUse"], {"session_id": S}, env)
    assert (other.returncode, other.stdout) == (0, b"")
    server = run_launcher(["mcp"], {}, env)
    assert server.returncode == 1 and b"uv tool install" in server.stderr


def test_the_launcher_runs_amem_with_the_users_choices(project, tmp_path):
    amem_bin = Path(sys.executable).parent / "amem"
    env = dict(os.environ, AMEM_BIN=str(amem_bin), CLAUDE_PROJECT_DIR=str(project),
               CLAUDE_PLUGIN_OPTION_KEY_STORAGE="passphrase", CLAUDE_PLUGIN_OPTION_PASSPHRASE="correct horse",
               XDG_RUNTIME_DIR=str(tmp_path / "run"))
    (tmp_path / "run").mkdir()
    out = run_launcher(["hook", "SessionStart"], {"session_id": S, "source": "startup"}, env)
    assert out.returncode == 0 and json.loads(out.stdout)["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    conn = __import__("sqlite3").connect(store_path(project) / "memory.db")
    assert conn.execute("SELECT value FROM meta WHERE key = 'kek_source'").fetchone()[0] == "passphrase"
    conn.close()
    assert list((tmp_path / "run" / "agent-memory").glob("*.kek"))   # the session key cache (#83)


# ---------------------------------------------------------------- key sources (D4)
def test_a_passphrase_store_uses_the_session_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("AMEM_PASSPHRASE", "correct horse battery")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    (tmp_path / "run").mkdir()
    Store(tmp_path / "s", project_id="p", min_free_bytes=0)
    (cache,) = (tmp_path / "run" / "agent-memory").glob("*.kek")
    assert oct(cache.stat().st_mode & 0o777) == "0o600"
    started = time.perf_counter()
    Store(tmp_path / "s", project_id="p", min_free_bytes=0)
    assert time.perf_counter() - started < 0.1                     # no scrypt on the second open
    monkeypatch.setenv("AMEM_PASSPHRASE", "wrong")
    with pytest.raises(keys.KeyError_):
        Store(tmp_path / "s", project_id="p", min_free_bytes=0)


def test_the_keychain_source(tmp_path, monkeypatch):
    import types
    vault = {}
    fake = types.ModuleType("keyring")
    fake.get_password = lambda service, name: vault.get((service, name))
    fake.set_password = lambda service, name, value: vault.__setitem__((service, name), value)
    errors = types.ModuleType("keyring.errors")
    errors.KeyringError = RuntimeError
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setitem(sys.modules, "keyring.errors", errors)
    monkeypatch.setenv("AMEM_KEY_SOURCE", "keychain")
    s = Store(tmp_path / "s", project_id="p", min_free_bytes=0)
    e = s.append(__import__("agent_memory").EventInput(kind="note", session_id="x", writer_id="w", payload=b"kept"))
    assert ("agent-memory", "p") in vault
    monkeypatch.delenv("AMEM_KEY_SOURCE")
    assert Store(tmp_path / "s", project_id="p", min_free_bytes=0).payload(e) == b"kept"   # the source is remembered
    monkeypatch.delitem(sys.modules, "keyring")
    monkeypatch.setitem(sys.modules, "keyring", None)
    with pytest.raises(keys.KeyError_, match="keyring"):
        Store(tmp_path / "s", project_id="p", min_free_bytes=0)
    with pytest.raises(keys.KeyError_):
        keys.normalize_source("vault")


def test_test_commands_are_recognised():
    for cmd in ("pytest -q", "uv run pytest tests/", "cd x && npm test", "npm run test", "go test ./...",
                "python -m pytest", "cargo test --all", "pnpm test"):
        assert cc.TEST_COMMAND.search(cmd), cmd
    for cmd in ("ls", "git commit -m 'test'", "cat pytest.ini", "echo testing"):
        assert not cc.TEST_COMMAND.search(cmd), cmd
