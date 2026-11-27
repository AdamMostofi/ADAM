"""Stage 4.5 (#25): exact citations in /api/chat and the web chat's Sources block."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from interface.core import SNIPPET_CHARS, citations

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "interface" / "web" / "static" / "js"

OLD_KEYS = {"response", "intent", "state", "params", "memories_used", "answer_source", "evidence", "frustration"}
LONG = ("The unexamined life is not worth living, said Socrates to the jury, and he went on at length about "
        "virtue, the soul, the gods, his daimonion, the oracle at Delphi and the question that it raised for "
        "him: whether any man in Athens was wiser than he, which he set out to test by questioning the "
        "politicians, the poets and the craftsmen, one after another, until he understood the oracle.")
HOSTILE = "Socrates wrote <img src=x onerror=alert(1)> and <b>bold</b> claims about the trial."


class QuietMouth:
    def format_response(self, message, params, context=""):
        return ""


@pytest.fixture
def core(tmp_path):
    from interface.core import ADAMCore
    core = ADAMCore(db_path=str(tmp_path / "adam_memory.db"), lance_path=str(tmp_path / "adam_vectors.db"),
                    mouth=QuietMouth())
    core.add_fact("socrates", "instance_of", "man")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "apology.md").write_text(f"# Apology\n\n{LONG}\n\n{HOSTILE}\n")
    library = core.memory.source_library()
    library.workspace = workspace.resolve()
    core.source_key = library.ingest("apology.md")["source"]
    core.library = library
    return core


def test_a_query_returns_the_matching_passage_with_an_exact_citation(core):
    result = core.chat("What did Socrates say about the unexamined life?")
    assert result["answer_source"] == "passage"
    (c,) = result["citations"]
    text = core.library.source_text(core.source_key)
    passage = text[c["start"]:c["end"]]
    assert passage == LONG and c["name"] == "apology.md" and c["ordinal"] == 1 and c["source"] == core.source_key
    assert __import__("hashlib").sha256(passage.encode()).hexdigest() == c["sha256"]
    assert c["truncated"] and c["snippet"] == passage[:SNIPPET_CHARS]          # a prefix, never altered


def test_no_match_returns_an_empty_citation_list(core):
    for message in ("Who won the 1998 World Cup?", "hello", "Is Socrates a man?", "I like pizza"):
        assert core.chat(message)["citations"] == [], message


def test_api_chat_keeps_every_key_and_adds_citations(core):
    from interface.web.app import create_app
    body = create_app(core).test_client().post("/api/chat", json={"message": "Is Socrates a man?"}).get_json()
    assert OLD_KEYS <= set(body) and body["citations"] == []
    assert body["answer_source"] == "proof" and body["evidence"]


def test_a_passage_holding_html_comes_back_as_plain_text(core):
    (c,) = core.chat("What did Socrates write about the trial?")["citations"]
    assert c["snippet"] == HOSTILE and not c["truncated"]           # the API returns it exactly; the page shows text


def test_citations_ignore_proofs():
    assert citations([{"type": "proof", "claim": "a is b", "steps": []}]) == []


# ------------------------------------------------------------ the page renders citations as text, never HTML
def test_every_citation_field_reaches_the_page_through_textContent():
    chat = (JS / "chat.js").read_text()
    body = chat[chat.index("export function citationSources"):]
    body = body[:body.index("\n}\n")]
    assert "innerHTML" not in body and "html:" not in body
    assert re.search(r"title: `\$\{c\.name\}.*characters \$\{c\.start\}–\$\{c\.end\}`", body)
    sources = (JS / "components" / "sources.js").read_text()
    for field in ("title", "description", "meta"):
        assert re.search(rf'class: "adam-source-[a-z]+", text: {field}\b', sources), field


def test_evidence_replies_are_shown_as_text_not_markdown():
    """A quoted passage holding "<img src=…>" must read as those characters, and never make the browser fetch
    anything (the Markdown sanitizer allows http images). Found in the Stage 4.5 browser check."""
    chat = (JS / "chat.js").read_text()
    assert 'const plain = typeof result.answer_source === "string"' in chat
    assert "plain ? plainHtml(result.response) : renderMarkdown(result.response)" in chat
    assert 'turn.plain ? el("p", { text: turn.text })' in chat
    escape = chat[chat.index("export function plainHtml"):]
    for ch, entity in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"), ("'", "&#39;")):
        assert f'"{ch}": "{entity}"' in escape or f"'{ch}': \"{entity}\"" in escape or f"\"'\": \"{entity}\"" in escape


def test_restored_turns_keep_only_known_citation_fields():
    store = (JS / "store.js").read_text()
    assert "function cleanCitations" in store and "clean.citations = citations" in store
