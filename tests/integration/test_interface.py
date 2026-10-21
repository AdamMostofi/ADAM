"""Interface tests — ADAMCore facade + Flask endpoints."""
import sys, os, tempfile, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from interface.core import ADAMCore
from interface.web.app import app


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


def test_flask_index():
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200


def test_flask_chat():
    with app.test_client() as client:
        res = client.post("/api/chat", json={"message": "hello"})
        assert res.status_code == 200
        data = res.get_json()
        assert "response" in data


def test_flask_chat_simple():
    with app.test_client() as client:
        res = client.post("/api/chat", json={"message": "hello", "mode": "simple"})
        assert res.status_code == 200


def test_flask_chat_no_message():
    with app.test_client() as client:
        res = client.post("/api/chat", json={})
        assert res.status_code == 400


def test_flask_facts_get():
    with app.test_client() as client:
        res = client.get("/api/facts")
        assert res.status_code == 200
        assert isinstance(res.get_json(), list)


def test_flask_facts_post():
    with app.test_client() as client:
        res = client.post("/api/facts", json={"subject": "bird", "predicate": "can", "object": "fly"})
        assert res.status_code == 200


def test_flask_facts_post_invalid():
    with app.test_client() as client:
        res = client.post("/api/facts", json={"subject": "bird"})
        assert res.status_code == 400


def test_flask_graph():
    with app.test_client() as client:
        res = client.get("/api/graph")
        assert res.status_code == 200
        data = res.get_json()
        assert "nodes" in data
        assert "edges" in data


def test_flask_skills():
    with app.test_client() as client:
        res = client.get("/api/skills")
        assert res.status_code == 200
        assert isinstance(res.get_json(), list)


def test_flask_stats():
    with app.test_client() as client:
        res = client.get("/api/stats")
        assert res.status_code == 200
        data = res.get_json()
        assert "facts" in data
        assert "skills" in data


def test_flask_save():
    with app.test_client() as client:
        res = client.post("/api/save", json={})
        assert res.status_code == 200


def test_flask_static():
    with app.test_client() as client:
        res = client.get("/static/css/tokens.css")
        assert res.status_code == 200


def test_flask_static_js():
    with app.test_client() as client:
        res = client.get("/static/js/app.js")
        assert res.status_code == 200


def test_flask_index_has_new_shell():
    with app.test_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        assert b"Primarch Adam" in res.data
