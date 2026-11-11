"""Interface tests — ADAMCore facade + Flask endpoints."""
import sys, os, tempfile, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from interface.core import ADAMCore
import pytest
from interface.web.app import create_app


@pytest.fixture
def app(tmp_path):
    core = ADAMCore(db_path=str(tmp_path / "web.db"), lance_path=str(tmp_path / "web.lance"))
    return create_app(core)


def test_core_chat():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ADAMCore(db_path=os.path.join(tmpdir, "test.db"), lance_path=os.path.join(tmpdir, "vectors.lance"))
        result = core.chat("hello")
        assert "response" in result
        assert "state" in result
        assert "params" in result


def test_core_chat_simple_mode():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ADAMCore(db_path=os.path.join(tmpdir, "test.db"), lance_path=os.path.join(tmpdir, "vectors.lance"))
        result = core.chat("hello", mode="simple")
        assert "response" in result


def test_core_add_fact():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ADAMCore(db_path=os.path.join(tmpdir, "test.db"), lance_path=os.path.join(tmpdir, "vectors.lance"))
        fid = core.add_fact("cat", "is", "animal")
        assert isinstance(fid, int)


def test_core_query_knowledge():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ADAMCore(db_path=os.path.join(tmpdir, "test.db"), lance_path=os.path.join(tmpdir, "vectors.lance"))
        core.add_fact("cat", "is", "animal")
        results = core.query_knowledge("cat")
        assert isinstance(results, list)


def test_core_get_graph_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ADAMCore(db_path=os.path.join(tmpdir, "test.db"), lance_path=os.path.join(tmpdir, "vectors.lance"))
        data = core.get_graph_data()
        assert "nodes" in data
        assert "edges" in data


def test_core_get_skills():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ADAMCore(db_path=os.path.join(tmpdir, "test.db"), lance_path=os.path.join(tmpdir, "vectors.lance"))
        skills = core.get_skills()
        assert isinstance(skills, list)


def test_core_get_stats():
    with tempfile.TemporaryDirectory() as tmpdir:
        core = ADAMCore(db_path=os.path.join(tmpdir, "test.db"), lance_path=os.path.join(tmpdir, "vectors.lance"))
        stats = core.get_stats()
        assert "facts" in stats
        assert "skills" in stats
        assert "nodes" in stats
        assert "edges" in stats
        assert "baseline" in stats


def test_core_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        db = os.path.join(tmpdir, "test.db")
        lance = os.path.join(tmpdir, "vectors.lance")
        core = ADAMCore(db_path=db, lance_path=lance)
        core.add_fact("dog", "is", "animal")
        save_path = os.path.join(tmpdir, "save")
        core.save(save_path)
        assert os.path.exists(save_path)


def test_flask_index(app):
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200


def test_flask_chat(app):
    with app.test_client() as client:
        res = client.post("/api/chat", json={"message": "hello"})
        assert res.status_code == 200
        data = res.get_json()
        assert "response" in data


def test_flask_chat_simple(app):
    with app.test_client() as client:
        res = client.post("/api/chat", json={"message": "hello", "mode": "simple"})
        assert res.status_code == 200


def test_flask_chat_no_message(app):
    with app.test_client() as client:
        res = client.post("/api/chat", json={})
        assert res.status_code == 400


def test_flask_facts_get(app):
    with app.test_client() as client:
        res = client.get("/api/facts")
        assert res.status_code == 200
        assert isinstance(res.get_json(), list)


def test_flask_facts_post(app):
    with app.test_client() as client:
        res = client.post("/api/facts", json={"subject": "bird", "predicate": "can", "object": "fly"})
        assert res.status_code == 200


def test_flask_facts_post_invalid(app):
    with app.test_client() as client:
        res = client.post("/api/facts", json={"subject": "bird"})
        assert res.status_code == 400


def test_flask_graph(app):
    with app.test_client() as client:
        res = client.get("/api/graph")
        assert res.status_code == 200
        data = res.get_json()
        assert "nodes" in data
        assert "edges" in data


def test_flask_skills(app):
    with app.test_client() as client:
        res = client.get("/api/skills")
        assert res.status_code == 200
        assert isinstance(res.get_json(), list)


def test_flask_stats(app):
    with app.test_client() as client:
        res = client.get("/api/stats")
        assert res.status_code == 200
        data = res.get_json()
        assert "facts" in data
        assert "skills" in data


def test_flask_save(app):
    with app.test_client() as client:
        res = client.post("/api/save", json={})
        assert res.status_code == 200


def test_flask_static(app):
    with app.test_client() as client:
        res = client.get("/static/css/tokens.css")
        assert res.status_code == 200


def test_flask_static_js(app):
    with app.test_client() as client:
        res = client.get("/static/js/app.js")
        assert res.status_code == 200


def test_flask_index_has_new_shell(app):
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        assert b"Primarch Adam" in res.data


def test_import_creates_no_store(tmp_path):
    """Importing the web module must not build a core or touch any store."""
    import subprocess
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    env = {**os.environ, "PYTHONPATH": repo, "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("ADAM_DB", None)
    env.pop("ADAM_LANCE", None)
    subprocess.run([sys.executable, "-c", "import interface.web.app"], cwd=tmp_path, env=env, check=True)
    assert list(tmp_path.iterdir()) == []


def test_two_apps_do_not_share_facts(tmp_path):
    first = create_app(ADAMCore(db_path=str(tmp_path / "a.db"), lance_path=str(tmp_path / "a.lance")))
    second = create_app(ADAMCore(db_path=str(tmp_path / "b.db"), lance_path=str(tmp_path / "b.lance")))
    with first.test_client() as client:
        assert client.post("/api/facts", json={"subject": "cat", "predicate": "is", "object": "animal"}).status_code == 200
    with second.test_client() as client:
        assert client.get("/api/facts").get_json() == []
    with first.test_client() as client:
        assert len(client.get("/api/facts").get_json()) == 1


def test_create_app_default_core_uses_env_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("ADAM_DB", str(tmp_path / "env.db"))
    monkeypatch.setenv("ADAM_LANCE", str(tmp_path / "env.lance"))
    app = create_app()
    with app.test_client() as client:
        client.post("/api/facts", json={"subject": "dog", "predicate": "is", "object": "animal"})
    assert (tmp_path / "env.db").exists()


def test_flask_reports_and_classifies_an_ambiguous_is(app):
    """Stage 1.3 (#29): an ambiguous "is" is flagged, listed, and can be classified."""
    with app.test_client() as client:
        res = client.post("/api/facts", json={"subject": "rex", "predicate": "is", "object": "dog"})
        assert res.get_json()["ambiguous"] is True
        res = client.post("/api/facts", json={"subject": "dog", "predicate": "subclass_of", "object": "mammal"})
        assert res.get_json()["ambiguous"] is False
        assert client.get("/api/ambiguous").get_json() == [{"subject": "rex", "predicate": "is", "object": "dog"}]
        res = client.post("/api/classify", json={"subject": "rex", "predicate": "is", "object": "dog", "as": "instance_of"})
        assert res.get_json() == {"subject": "rex", "predicate": "instance_of", "object": "dog"}
        assert client.get("/api/ambiguous").get_json() == []
        res = client.post("/api/classify", json={"subject": "rex", "predicate": "is", "object": "dog", "as": "bogus"})
        assert res.status_code == 400
