"""Stage 2.6 (#85): four trees, the cross-tree layer, a basis on everything, profiles, format migration."""
from __future__ import annotations

import sqlite3
import subprocess

import pytest

from agent_memory import EventInput, SchemaError, Store, structure
from agent_memory.profiles import ProfileError
from test_structure import ev, history  # noqa: F401  (the shared development-history fixture)

TREES = ("history", "artifacts", "knowledge", "state")


def walk(nav) -> set[str]:
    """Every node reachable from a tree's root, using only what the listings return."""
    seen, stack = set(), [nav.root()["id"]]
    while stack:
        node = nav.open(stack.pop())
        assert node is not None
        seen.add(node["id"])
        stack += [i["id"] for i in node.get("items", [])]
    return seen


def db(store):
    return sqlite3.connect(store.path / "memory.db")


# ---------------------------------------------------------------- four trees
def test_each_tree_is_navigable_from_its_root_without_knowing_any_id(store, history):
    conn = db(store)
    by_tree = {t: {r[0] for r in conn.execute("SELECT node_id FROM nodes WHERE tree = ?", (t,))} for t in TREES}
    total = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    conn.close()
    for tree in TREES:
        assert walk(getattr(store, tree)) == by_tree[tree], tree
    assert sum(len(v) for v in by_tree.values()) == total   # the four trees partition every node


def test_each_tree_holds_its_own_kind_of_record(store, history):
    sessions = [s["label"] for s in store.history.sessions()]
    assert sessions == ["s1", "s2", "s3"]
    turn = store.history.session("s1")["items"][1]
    assert turn["type"] == "turn" and turn["children"] > 0

    assert [i["label"] for i in store.artifacts.root()["items"]] == ["api"]
    api = store.artifacts.open_path("api")
    assert sorted(i["label"] for i in api["items"]) == ["cache.py", "pool.py"]
    assert store.artifacts.open_path("api/cache.py")["attrs"]["path"] == "api/cache.py"

    groups = {g["label"]: g["children"] for g in store.knowledge.root()["items"]}
    assert groups["approaches"] >= 2 and groups["decisions"] == 2 and groups["notes"] == 1
    assert {e["label"] for e in store.knowledge.find("decision", "active")} == {"cache for 30 seconds"}

    sections = [s["label"] for s in store.state.root()["items"]]
    assert sections == ["objectives", "tasks", "blockers"]
    assert [i["label"] for i in store.state.section("objectives")] == ["the API responds in under 100 ms"]
    assert store.state.section("tasks") == []                       # done
    assert len(store.state.section("tasks", include_closed=True)) == 1


def test_a_tree_navigator_never_opens_another_trees_node(store, history):
    assert store.knowledge.open(history["msg1"].event_id) is None
    assert store.history.open(history["dec_user"]) is None
    assert store.history.open(history["msg1"].event_id)["type"] == "event"


def test_listings_are_short_and_contents_appear_only_when_opened(store, history):
    listing = store.knowledge.root()["items"][0]
    assert set(listing) == {"id", "type", "label", "status", "basis", "children", "links"}
    opened = store.knowledge.open(listing["id"])
    assert "attrs" in opened and all("attrs" not in i for i in opened["items"])


def test_tree_schemas_are_enforced_on_write(store):
    store.append(EventInput(kind="note", session_id="s", writer_id="w", summary_fields={"text": "x"}))
    conn = db(store)
    first = conn.execute("SELECT * FROM events LIMIT 1").fetchone()
    e = store._row(first)
    with pytest.raises(SchemaError):
        structure._add_node(conn, "x:1", "spaceship", e)
    with pytest.raises(SchemaError):   # a session can't contain an artifact
        structure._add_node(conn, "artifact:z.py", "artifact", e, parent="session:s")
    conn.close()
    with pytest.raises(SchemaError):
        store.relate("history:", "knowledge:", "contains", "s", "w")
    contains = [x for x in store.edges("history:", "out") if x["type"] == "contains"][0]
    with pytest.raises(SchemaError):
        store.retract(contains["edge_id"], "s", "w")


# ---------------------------------------------------------------- cross-tree layer
def test_links_between_trees_are_marked_indexed_and_followed_explicitly(store, history):
    conn = db(store)
    wrong = conn.execute("SELECT COUNT(*) FROM edges e JOIN nodes f ON f.node_id = e.from_id "
                         "JOIN nodes t ON t.node_id = e.to_id WHERE e.cross_tree != (f.tree != t.tree)").fetchone()[0]
    crosses = conn.execute("SELECT COUNT(*) FROM edges WHERE cross_tree = 1").fetchone()[0]
    conn.close()
    assert wrong == 0 and crosses > 0
    assert structure.check_trees(sqlite3.connect(store.path / "memory.db")) == []

    decision = history["dec_user"]
    to_history = store.knowledge.links(decision, "history")
    assert {link["node"] for link in to_history} >= {history["msg2"].event_id}
    assert all(link["tree"] == "history" for link in to_history)
    assert store.knowledge.open(decision)["links"]["history"] == len(store.links(decision, "history"))

    changes = store.artifacts.links("api/cache.py".join(["artifact:", ""]), "history", "modifies")
    assert {c["node"] for c in changes} == {history["change1"].event_id, history["change2"].event_id,
                                           history["revert"].event_id}


def test_a_legacy_file_id_still_names_the_artifact(store, history):
    store.relate("file:api/pool.py", history["dec_user"], "related_to", "s1", "w1")
    assert any(link["node"] == "artifact:api/pool.py" for link in store.links(history["dec_user"], "artifacts"))
    assert store.node("file:api/pool.py")["id"] == "artifact:api/pool.py"


# ---------------------------------------------------------------- basis on everything
def test_every_node_status_edge_and_attribution_has_a_basis(store, history):
    conn = db(store)
    for table in ("nodes", "edges", "statuses"):
        bases = {r[0] for r in conn.execute(f"SELECT DISTINCT basis FROM {table}")}
        assert bases <= set(structure.BASES), (table, bases)
    rows = conn.execute("SELECT attribution, attribution_basis FROM file_versions").fetchall()
    conn.close()
    assert rows and all(b == "declared" and a == "reported" for a, b in rows)   # reported by the adapter
    proposed = [n for n in store.knowledge.find("approach") if n["basis"] == "inferred"]
    assert proposed and all(store.node(p["id"])["attrs"]["rule"].startswith("structural signal") for p in proposed)


def test_reconciled_changes_carry_the_basis_of_their_attribution(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent / "fixtures" / "reconcile"))
    import scenarios
    repo, _ = scenarios.init_repo(tmp_path)
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0)
    rec = store.reconciler(repo, "a")
    rec.run()
    target = repo / "pkg" / "mod_001.py"
    store.record_tool_edit("a", "a", "pkg/mod_001.py", b"x = 1\n", target.read_bytes())
    target.write_bytes(b"x = 1\n")
    (repo / "pkg" / "mod_002.py").write_text("y = 2\n")
    got = {c.path: (c.attribution, c.basis) for c in rec.run().changes}
    assert got == {"pkg/mod_001.py": ("agent_tool", "observed"), "pkg/mod_002.py": ("unattributed", None)}
    versions = {v["attribution"]: v["attribution_basis"] for v in store.artifacts.versions("pkg/mod_001.py")}
    assert versions == {"baseline": "observed", "agent_tool": "observed"}


# ---------------------------------------------------------------- profiles
def test_profiles_are_remembered_and_gate_their_features(tmp_path):
    path = tmp_path / "notes-store"
    store = Store(path, project_id="p", min_free_bytes=0, profiles=("generic",))
    assert store.profiles == ("generic",)
    assert Store(path, project_id="p", min_free_bytes=0).profiles == ("generic",)
    with pytest.raises(ProfileError):
        store.record_verification("s", "w", "pytest", "passed")
    assert store.update_code_graph() == {"skipped": "the software profile is off"}
    with pytest.raises(ProfileError):
        Store(tmp_path / "x", project_id="p", min_free_bytes=0, profiles=("spaceships",))
    assert Store(tmp_path / "y", project_id="p", min_free_bytes=0).profiles == ("generic", "software")


def test_without_the_software_profile_a_git_repo_is_reconciled_by_walking(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a.md").write_text("# a\n")
    store = Store(tmp_path / "store", project_id="p", min_free_bytes=0, profiles=("generic",))
    rec = store.reconciler(repo, "s")
    assert rec.is_git is False
    assert [c.path for c in rec.run().changes] == ["a.md"]


# ---------------------------------------------------------------- store format migration
OLD_SCHEMA = """
CREATE TABLE nodes (node_id TEXT PRIMARY KEY, node_type TEXT NOT NULL, label TEXT, attrs TEXT NOT NULL,
    source_event TEXT NOT NULL, log_position INTEGER NOT NULL);
CREATE TABLE edges (edge_id INTEGER PRIMARY KEY AUTOINCREMENT, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
    type TEXT NOT NULL, basis TEXT NOT NULL, ord INTEGER, attrs TEXT NOT NULL, source_event TEXT NOT NULL,
    log_position INTEGER NOT NULL);
CREATE TABLE retractions (edge_id INTEGER NOT NULL, retracted_by TEXT NOT NULL, reason TEXT,
    log_position INTEGER NOT NULL);
CREATE TABLE statuses (node_id TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, basis TEXT NOT NULL,
    source_event TEXT NOT NULL, log_position INTEGER NOT NULL, at TEXT NOT NULL);
CREATE TABLE file_versions (version_id TEXT PRIMARY KEY, path TEXT NOT NULL, object_id TEXT, size INTEGER,
    change TEXT NOT NULL, git_blob TEXT, git_commit TEXT, renamed_from TEXT, path_id TEXT, path_role TEXT,
    source_event TEXT NOT NULL, log_position INTEGER NOT NULL);
CREATE TABLE verification_files (event_id TEXT NOT NULL, path TEXT NOT NULL, object_id TEXT,
    log_position INTEGER NOT NULL);
INSERT INTO nodes VALUES ('project', 'project', 'project', '{}', 'x', 1);
"""


def test_a_store_written_in_the_old_format_rebuilds_and_verifies(tmp_path, history, store):
    # A checkpoint as format 1 wrote it: a snapshot with no format tag.
    import hashlib
    import json
    from agent_memory import recovery
    events = store.count()
    conn = db(store)
    snapshot = json.dumps({"nodes": [], "edges": []}).encode()
    oid = store.archive.put(snapshot)
    conn.execute("INSERT INTO checkpoints (log_position, chain_heads, snapshot_object, snapshot_hash, reason, "
                 "created_at) VALUES (?, ?, ?, ?, 'format 1', 'then')",
                 (events, json.dumps(recovery._heads(conn, events), sort_keys=True), oid,
                  hashlib.sha256(snapshot).hexdigest()))
    conn.commit()
    structure.drop(conn)
    conn.executescript(OLD_SCHEMA)
    conn.execute("UPDATE meta SET value = '1' WHERE key = 'store_format'")
    conn.commit()
    conn.close()

    upgraded = Store(store.path, project_id="test-project", min_free_bytes=0)
    report = upgraded.verify()
    assert report["ok"], report["problems"]
    assert upgraded.count() == events + 1   # only the migration record was added; no event changed
    migration = list(upgraded.events())[-1]
    assert (migration.kind, migration.summary_fields["from_format"]) == ("recovery", 1)
    assert [s["label"] for s in upgraded.history.sessions()] == ["s1", "s2", "s3", "engine"]   # engine: migration
    assert upgraded.knowledge.find("decision")
    report = recovery.checkpoints_report(upgraded)
    old_one = [c for c in report if c["log_position"] == events and not c["valid"]]
    assert old_one and old_one[0]["superseded"]          # the format-1 snapshot is superseded, not "corrupt"
    assert report[-1]["valid"] and report[-1]["log_position"] == events + 1   # a fresh one after migrating
    assert Store(store.path, project_id="test-project", min_free_bytes=0).count() == events + 1   # once only
