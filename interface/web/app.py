"""ADAM Web UI — Flask app with custom HTML/JS frontend.

Use `create_app()` to build the app. Importing this module creates no core,
database, or vector store; a core is built only when `create_app()` is called
without one. Run the console with `python -m interface.web.app`.
"""
from __future__ import annotations

import os

from flask import Flask, current_app, jsonify, render_template, request, send_from_directory

from interface.core import ADAMCore
from kernel.facts import Fact
from kernel.foundations import is_ambiguous


def _default_core() -> ADAMCore:
    return ADAMCore(
        db_path=os.environ.get("ADAM_DB", "adam_memory.db"),
        lance_path=os.environ.get("ADAM_VECTORS") or os.environ.get("ADAM_LANCE") or "adam_vectors.db",
    )


def get_core() -> ADAMCore:
    """The core bound to the current app."""
    return current_app.extensions["adam_core"]


def create_app(core: ADAMCore | None = None) -> Flask:
    """Build the web app around `core`, or a core from ADAM_DB / ADAM_VECTORS (ADAM_LANCE still accepted)."""
    app = Flask(__name__)
    app.extensions["adam_core"] = core if core is not None else _default_core()

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/chat", methods=["POST"])
    def chat():
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "message required"}), 400
        mode = data.get("mode", "full")
        result = get_core().chat(data["message"], mode=mode)
        return jsonify(result)

    @app.route("/api/facts", methods=["GET"])
    def facts():
        query = request.args.get("q", "")
        if query:
            return jsonify(get_core().query_knowledge(query))
        all_facts = get_core().memory.get_all_facts()
        return jsonify([
            {"subject": f.subject, "predicate": f.predicate, "object": f.object,
             "confidence": f.confidence, "source": f.source.value}
            for f in all_facts
        ])

    @app.route("/api/graph", methods=["GET"])
    def graph():
        return jsonify(get_core().get_graph_data())

    @app.route("/api/skills", methods=["GET"])
    def skills():
        return jsonify(get_core().get_skills())

    @app.route("/api/stats", methods=["GET"])
    def stats():
        return jsonify(get_core().get_stats())

    @app.route("/api/facts", methods=["POST"])
    def add_fact():
        data = request.get_json()
        if not data or not all(k in data for k in ("subject", "predicate", "object")):
            return jsonify({"error": "subject, predicate, object required"}), 400
        fact_id = get_core().add_fact(data["subject"], data["predicate"], data["object"])
        ambiguous = is_ambiguous(Fact(data["subject"], data["predicate"], data["object"]))
        return jsonify({"id": fact_id, "ambiguous": ambiguous})

    @app.route("/api/ambiguous", methods=["GET"])
    def ambiguous():
        return jsonify(get_core().ambiguous_facts())

    @app.route("/api/classify", methods=["POST"])
    def classify():
        data = request.get_json()
        if not data or not all(k in data for k in ("subject", "predicate", "object", "as")):
            return jsonify({"error": "subject, predicate, object, as required"}), 400
        try:
            fact = get_core().classify_fact(data["subject"], data["predicate"], data["object"], data["as"])
        except (ValueError, KeyError) as err:
            return jsonify({"error": str(err)}), 400
        return jsonify(fact)

    @app.route("/api/save", methods=["POST"])
    def save():
        data = request.get_json()
        path = data.get("path", "adam_save")
        get_core().save(path)
        return jsonify({"saved": path})

    @app.route("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(os.path.join(app.root_path, "static"), filename)

    return app


def main() -> None:
    create_app().run(host="127.0.0.1", port=7860, debug=False)


if __name__ == "__main__":
    main()
