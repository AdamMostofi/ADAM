"""Stage 2.2 (#51): canonical events, append-only log, lossless raw archive, secrets, exclusions, gaps."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from agent_memory import EventInput, SchemaError, Store
from agent_memory.keys import KeyError_
from agent_memory.location import project_id, store_path, synced_folder_warnings


def ev(kind="tool_result", payload=None, writer="w1", session="s1", **kw) -> EventInput:
    return EventInput(kind=kind, session_id=session, writer_id=writer, payload=payload, **kw)


def raw_bytes(root: Path) -> bytes:
    """Every byte the store has on disk: database, WAL, archive objects."""
    return b"".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())


# ------------------------------------------------------------ lossless

def test_a_50000_line_output_comes_back_byte_for_byte(store):
    output = "".join(f"line {i:05d}: some build output with tabs\tand unicode é ✓\n" for i in range(50_000)).encode()
    stored = store.append(ev(payload=output, summary_fields={"tool": "Bash", "exit_code": 0}))
    assert store.payload(stored) == output
    assert store.payload(stored.event_id) == output


def test_binary_content_round_trips(store):
    data = bytes(range(256)) * 400
    assert store.payload(store.append(ev("file_change", payload=data, path="assets/logo.bin"))) == data


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.binary(max_size=5000))
def test_any_payload_is_kept_whole_or_its_redactions_are_recorded(store, data):
    stored = store.append(ev(payload=data))
    if not stored.redactions:
        assert store.payload(stored) == data


def test_identical_content_is_stored_once(store):
    a = store.append(ev(payload=b"same content"))
    b = store.append(ev(payload=b"same content"))
    assert a.payload_object == b.payload_object
    assert len(store.archive.ids()) == 1


# ------------------------------------------------------------ the log

def test_events_carry_the_canonical_fields(store):
    e = store.append(ev("user_message", payload="hello", agent="claude-code", agent_version="2.1",
                        adapter_version="0.1", completeness="captured"))
    assert e.schema_version == 1 and e.writer_seq == 1 and e.log_position == 1
    assert e.prev_hash == "genesis:w1" and len(e.record_hash) == 64
    assert e.occurred_at and e.recorded_at


def test_each_writer_has_its_own_chain(store):
    a1 = store.append(ev(writer="a"))
    b1 = store.append(ev(writer="b"))
    a2 = store.append(ev(writer="a"))
    assert (a1.writer_seq, b1.writer_seq, a2.writer_seq) == (1, 1, 2)
    assert a2.prev_hash == a1.record_hash and b1.prev_hash == "genesis:b"
    assert store.verify()["ok"]


def test_the_log_refuses_updates_and_deletes(store):
    store.append(ev())
    conn = sqlite3.connect(store.path / "memory.db")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE events SET kind = 'note'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM events")


def test_unknown_kinds_and_completeness_are_rejected(store):
    with pytest.raises(SchemaError):
        store.append(ev(kind="made_up"))
    with pytest.raises(SchemaError):
        store.append(ev(completeness="mostly"))


# ------------------------------------------------------------ idempotency

def test_retrying_the_same_hook_stores_one_event(store):
    first = store.append(ev(payload="x", idempotency_key="claude:session-1:tool-42"))
    again = store.append(ev(payload="x", idempotency_key="claude:session-1:tool-42"))
    assert again.event_id == first.event_id and store.count() == 1


def test_concurrent_retries_store_one_event(tmp_path):
    path = tmp_path / "store"
    Store(path, project_id="p", min_free_bytes=0)
    ids, errors = [], []

    def retry():
        try:
            s = Store(path, project_id="p", min_free_bytes=0)
            ids.append(s.append(ev(payload="same", idempotency_key="hook-7")).event_id)
        except Exception as err:   # pragma: no cover - reported below
            errors.append(err)

    threads = [threading.Thread(target=retry) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(set(ids)) == 1
    assert Store(path, project_id="p", min_free_bytes=0).count() == 1


# ------------------------------------------------------------ tampering

def _tamper(store: Store, sql: str, *args) -> None:
    conn = sqlite3.connect(store.path / "memory.db")
    conn.execute("DROP TRIGGER events_append_only_update")
    conn.execute("DROP TRIGGER events_append_only_delete")
    conn.execute(sql, args)
    conn.commit()


def test_an_altered_record_is_detected(store):
    for i in range(5):
        store.append(ev(payload=f"event {i}", summary_fields={"i": i}))
    _tamper(store, "UPDATE events SET summary_fields = ? WHERE log_position = 3", json.dumps({"i": 99}))
    report = store.verify()
    assert not report["ok"]
    assert any(p["type"] == "record_altered" and p["log_position"] == 3 for p in report["problems"])


def test_a_deleted_record_is_detected(store):
    for i in range(5):
        store.append(ev(payload=f"event {i}"))
    _tamper(store, "DELETE FROM events WHERE log_position = 2")
    types = {p["type"] for p in store.verify()["problems"]}
    assert {"sequence_gap", "chain_break"} <= types


def test_an_altered_or_swapped_object_is_detected(store):
    a = store.append(ev(payload=b"first object"))
    b = store.append(ev(payload=b"second object"))
    path_a, path_b = store.archive.path(a.payload_object), store.archive.path(b.payload_object)
    blob = bytearray(path_a.read_bytes())
    blob[-1] ^= 0x01
    path_a.write_bytes(bytes(blob))
    report = store.verify()
    assert any(p["type"] == "object_problem" and p["object_id"] == a.payload_object for p in report["problems"])
    path_a.write_bytes(path_b.read_bytes())          # a valid object, but not this one
    assert any(p["object_id"] == a.payload_object for p in store.verify()["problems"])


def test_a_missing_object_is_detected(store):
    a = store.append(ev(payload=b"will vanish"))
    store.archive.path(a.payload_object).unlink()
    assert any("missing" in p["detail"] for p in store.verify()["problems"])


# ------------------------------------------------------------ secrets

# Fake secrets, assembled at run time so no secret-shaped literal sits in the repository.
CANARIES = {
    "aws-access-key": "AK" + "IA" + "Q3EGRZUXBYJKLMNO",
    "github-token": "gh" + "p_" + "Ab3dEf6hIj9kLm2nOp5qRs8tUv1wXy4zAb7d",
    "anthropic-api-key": "sk-" + "ant-api03-" + "Zq8Xw2Vt6Rp1Nm5Lk9Jh3Gf7Dd4Sa0Qe",
    "private-key": "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIEowIBAAKCAQEAu1SU1LfVLPHCozMxH2Mo4lgOEePzNm0tRgeLezV6ffAt0gun\n"
                   "-----END RSA " + "PRIVATE KEY-----",
    "generic-secret-assignment": "Kx9#mQ2$vL7@pR4!wT8z",
}


def test_canaries_appear_nowhere_in_the_stores_raw_bytes(store):
    text = "\n".join(f"{name}: {value}" if name != "generic-secret-assignment" else f"DB_PASSWORD={value}"
                     for name, value in CANARIES.items())
    e = store.append(ev(payload=f"output follows\n{text}\nend",
                        summary_fields={"command": f"curl -H 'Authorization: token {CANARIES['github-token']}' x",
                                        "nested": {"env": [f"AWS_KEY={CANARIES['aws-access-key']}"]}}))
    on_disk = raw_bytes(store.path)
    readable = store.payload(e) + json.dumps(e.summary_fields).encode()
    for name, value in CANARIES.items():
        assert value.encode() not in on_disk, name
        assert value.encode() not in readable, name
    rules = {r["rule"] for r in e.redactions}
    assert set(CANARIES) <= rules
    for r in e.redactions:
        assert set(r) == {"field", "rule", "start", "end", "fingerprint"}
        assert all(v.encode() not in json.dumps(r).encode() for v in CANARIES.values())
    assert f"[SECRET:aws-access-key:".encode() in readable


def test_the_same_secret_has_the_same_fingerprint(store):
    a = store.append(ev(payload=f"key {CANARIES['aws-access-key']}"))
    b = store.append(ev(payload=f"again {CANARIES['aws-access-key']}"))
    assert a.redactions[0]["fingerprint"] == b.redactions[0]["fingerprint"]


@pytest.mark.parametrize("text", [
    "password = os.environ['DB_PASSWORD']",
    "token: ${GITHUB_TOKEN}",
    "api_key=<your-key-here>",
    "def test_secret_handling(): pass",
    "the access_key is configured in the settings page",
    "commit 3f7a2ea4c8e1b9d0 fixed the parser",
])
def test_ordinary_text_is_not_redacted(store, text):
    e = store.append(ev(payload=text))
    assert e.redactions == [] and store.payload(e) == text.encode()


# ------------------------------------------------------------ exclusions and gaps

def test_excluded_paths_are_recorded_but_not_stored(store):
    secret_env = b"DATABASE_URL=postgres://admin:hunter2-very-long@db/prod\n"
    e = store.append(ev("file_change", payload=secret_env, path="config/.env"))
    assert e.kind == "exclusion" and e.completeness == "unavailable" and e.payload_object is None
    assert e.summary_fields["path"] == "config/.env" and e.summary_fields["excluded_kind"] == "file_change"
    assert b"hunter2" not in raw_bytes(store.path)


def test_a_payload_that_cant_be_stored_whole_becomes_a_gap(tmp_path):
    s = Store(tmp_path / "small", project_id="p", quota_bytes=2_000, min_free_bytes=0)
    big = os.urandom(50_000)          # incompressible: can't fit the quota
    e = s.append(ev("tool_result", payload=big, summary_fields={"tool": "Bash"}))
    assert e.kind == "capture_gap" and e.completeness == "unavailable" and e.payload_object is None
    assert e.summary_fields["missed_kind"] == "tool_result" and e.summary_fields["size"] == 50_000
    assert "quota" in e.summary_fields["reason"]
    assert s.archive.ids() == []      # nothing partial was kept
    assert s.verify()["ok"]


def test_a_failing_disk_write_becomes_a_gap(store, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(os, "replace", broken)
    e = store.append(ev(payload=b"lost to a full disk"))
    assert e.kind == "capture_gap" and "No space left" in e.summary_fields["reason"]
    assert not list(store.archive.root.rglob("*.tmp"))


# ------------------------------------------------------------ keys and location

def test_the_store_reopens_with_its_key_and_refuses_another(tmp_path):
    path = tmp_path / "s"
    e = Store(path, project_id="p", min_free_bytes=0).append(ev(payload=b"kept"))
    assert Store(path, project_id="p", min_free_bytes=0).payload(e) == b"kept"
    key = Path(os.environ["XDG_CONFIG_HOME"]) / "agent-memory" / "keys" / "p.key"
    assert oct(key.stat().st_mode & 0o777) == "0o600"
    key.write_bytes(os.urandom(32))
    with pytest.raises(KeyError_):
        Store(path, project_id="p", min_free_bytes=0)


def test_a_passphrase_store_needs_its_passphrase(tmp_path, monkeypatch):
    path = tmp_path / "s"
    monkeypatch.setenv("AMEM_PASSPHRASE", "correct horse battery staple")
    e = Store(path, project_id="p", min_free_bytes=0).append(ev(payload=b"locked"))
    assert Store(path, project_id="p", min_free_bytes=0).payload(e) == b"locked"
    monkeypatch.setenv("AMEM_PASSPHRASE", "wrong")
    with pytest.raises(KeyError_):
        Store(path, project_id="p", min_free_bytes=0)
    monkeypatch.delenv("AMEM_PASSPHRASE")
    with pytest.raises(KeyError_, match="AMEM_PASSPHRASE"):
        Store(path, project_id="p", min_free_bytes=0)


def test_payloads_are_not_readable_on_disk(store):
    store.append(ev(payload=b"a distinctive plaintext sentence that must be encrypted"))
    assert b"distinctive plaintext" not in raw_bytes(store.path)


def test_the_store_lives_inside_the_project_by_default(tmp_path):
    """D3 (owner, 2026-11-13): the store is part of the project, and git ignores it."""
    project = tmp_path / "my project"
    project.mkdir()
    path = store_path(project)
    assert path == project.resolve() / ".agent-memory"
    store = Store(path, min_free_bytes=0)
    assert (path / ".gitignore").read_text().splitlines()[-1] == "*"
    assert store.project_id == project_id(project)   # not ".agent-memory", which every project would share


def test_the_store_location_can_be_overridden(tmp_path, monkeypatch):
    project = tmp_path / "my project"
    project.mkdir()
    monkeypatch.setenv("AMEM_HOME", str(tmp_path / "elsewhere"))
    assert store_path(project).parent == tmp_path / "elsewhere"
    assert store_path(project, home=tmp_path / "explicit").parent == tmp_path / "explicit"
    assert project_id(project).startswith("my-project-") and project_id(project) == project_id(str(project) + "/")


@pytest.mark.parametrize("folder", ["OneDrive - Contoso", "Dropbox", "Google Drive", "iCloud Drive"])
def test_a_synced_folder_is_warned_about(tmp_path, folder):
    path = tmp_path / folder / "agent-memory"
    assert synced_folder_warnings(path)
    with pytest.warns(UserWarning, match="synced folder"):
        Store(path, project_id="p", min_free_bytes=0)
    assert synced_folder_warnings(tmp_path / "plain" / "agent-memory") == []


# Fake tokens, assembled at run time so no token-shaped literal sits in the repository
# (GitHub's push protection, rightly, refuses them).
MORE_FORMATS = [
    "AWS_SECRET_ACCESS_KEY=" + "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYzEXAMPLEKEYzz",
    "gl" + "pat-" + "xY9zA8bC7dE6fG5hI4jK",
    "np" + "m_" + "aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV3wX4",
    "h" + "f_" + "aBcDeFgHiJkLmNoPqRsTuVwXyZaBcDeFgH",
    "Authorization: Bearer " + "abcDEF123ghiJKL456mnoPQR789",
    "postgres://user:s3cr3tP4ssw0rd@db.example.com/prod",
    '{"api_key": "Zx8Qw2Er4Ty6Ui8Op0As2Df4Gh6Jk"}',
    "client_secret: 9fK3jL0pQ8wE5rT2yU7iO1aS6dF4gH",
]


@pytest.mark.parametrize("text", MORE_FORMATS)
def test_common_secret_formats_are_caught(store, text):
    assert store.append(ev(payload=text)).redactions


@pytest.mark.parametrize("text", [
    '"max_tokens": max_tokens,',
    "this.options.tokenizer=this.options.tokenizer||new w",
    "walkTokens:null}}function n(t){return t}",
    "* each match becomes `[SECRET:<rule>:<fingerprint>]`",
])
def test_code_and_markers_are_not_secrets(store, text):
    assert store.append(ev(payload=text)).redactions == []


def test_real_source_code_is_not_redacted(store):
    """The engine's own source is real code full of words like token, secret and key."""
    src = Path(__file__).resolve().parents[1] / "src" / "agent_memory"
    for path in sorted(src.glob("*.py")):
        assert store.append(ev(payload=path.read_bytes())).redactions == [], path.name
