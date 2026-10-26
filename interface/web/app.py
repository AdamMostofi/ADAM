"""ADAM Web UI — Flask app with custom HTML/JS frontend."""
from __future__ import annotations

import os
import tempfile
from flask import Flask, render_template, request, jsonify, send_from_directory

from interface.core import ADAMCore


app = Flask(__name__)
core = ADAMCore(
    db_path=os.environ.get("ADAM_DB", "adam_memory.db"),
    lance_path=os.environ.get("ADAM_LANCE", "adam_vectors.lance"),
)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "message required"}), 400
    mode = data.get("mode", "full")
    result = core.chat(data["message"], mode=mode)
    return jsonify(result)


@app.route("/api/facts", methods=["GET"])
def facts():
    query = request.args.get("q", "")
    if query:
        return jsonify(core.query_knowledge(query))
    all_facts = core.memory.get_all_facts()
    return jsonify([
        {"subject": f.subject, "predicate": f.predicate, "object": f.object,
         "confidence": f.confidence, "source": f.source.value}
        for f in all_facts
    ])


@app.route("/api/graph", methods=["GET"])
def graph():
    return jsonify(core.get_graph_data())


@app.route("/api/skills", methods=["GET"])
def skills():
    return jsonify(core.get_skills())


@app.route("/api/stats", methods=["GET"])
def stats():
    return jsonify(core.get_stats())


@app.route("/api/facts", methods=["POST"])
def add_fact():
    data = request.get_json()
    if not data or not all(k in data for k in ("subject", "predicate", "object")):
        return jsonify({"error": "subject, predicate, object required"}), 400
    fact_id = core.add_fact(data["subject"], data["predicate"], data["object"])
    return jsonify({"id": fact_id})


@app.route("/api/save", methods=["POST"])
def save():
    data = request.get_json()
    path = data.get("path", "adam_save")
    core.save(path)
    return jsonify({"saved": path})


@app.route("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(os.path.join(app.root_path, "static"), filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=7860, debug=False)
