"""Stage 4.2 (#24): the source library. Markdown in, exact passages out, ingested once, searched with FTS5."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from memory.engine_store import EngineStore
from memory.exact_store import ExactStore
from memory.source_library import (SOURCE, SourceError, SourceLibrary, main, paragraphs, passage_key,
                                   passages_path_for, sha256)

ROOT = Path(__file__).resolve().parents[2]

BOOK = (
    "# Apology\n"
    "\n"
    "Socrates is a man, and every man is mortal.\r\n"
    "He said so in court.\n"
    "\n"
    "\n"
    "   \n"
    "- The unexamined life\n"
    "- is not worth living.\n"
    "\n"
    "Ἀπολογία Σωκράτους — the defence of Socrates, in Athens.\n"
)


@pytest.fixture
def workspace(tmp_path):
    folder = tmp_path / "workspace"
    folder.mkdir()
    (folder / "apology.md").write_text(BOOK, encoding="utf-8", newline="")
    return folder


@pytest.fixture
def store(tmp_path):
    return EngineStore(tmp_path / "facts.engine")


@pytest.fixture
def library(store, tmp_path, workspace):
    return SourceLibrary(store, tmp_path / "facts.passages.db", workspace)


# ------------------------------------------------------------ acceptance
def test_a_markdown_file_ingests_exactly_once(library, workspace):
    first = library.ingest("apology.md")
    assert first["created"] and first["passages_added"] == 4 == first["passages"]
    again = library.ingest("apology.md")
    assert not again["created"] and again["passages_added"] == 0 and again["passages"] == 4
    (workspace / "copy.md").write_bytes((workspace / "apology.md").read_bytes())
    copy = library.ingest("copy.md")                                   # the same bytes under another name
    assert not copy["created"] and copy["passages_added"] == 0 and copy["name"] == "apology.md"
    assert len(library.sources()) == 1
    assert len(library.store.records("passage")) == 4 and len(library.store.records(SOURCE)) == 1


def test_passages_persist_with_their_source_offsets_and_hash(library, store, tmp_path, workspace):
    key = library.ingest("apology.md")["source"]
    assert key == sha256(BOOK.encode())
    reopened = SourceLibrary(EngineStore(tmp_path / "facts.engine"), tmp_path / "facts.passages.db", workspace)
    stored = reopened.passages(key)
    assert [(p.name, p.ordinal) for p in stored] == [("apology.md", i) for i in range(4)]
    for p in stored:
        assert p.key == passage_key(key, p.ordinal) and p.sha256 == sha256(p.text) and p.start < p.end
    fields = [r["fields"] for r in sorted(store.find_records("passage", source=key), key=lambda r: r["fields"]["ordinal"])]
    assert [(f["start"], f["end"], f["sha256"]) for f in fields] == [(p.start, p.end, p.sha256) for p in stored]
    assert "text" not in fields[0]            # the text is only in the encrypted body, never in the fields


def test_text_from_start_to_end_is_the_passage_exactly(library):
    key = library.ingest("apology.md")["source"]
    text = library.source_text(key)
    assert text == BOOK                                                 # nothing here looks like a secret
    passages = library.passages(key)
    assert [text[p.start:p.end] for p in passages] == [p.text for p in passages] == [
        "# Apology",
        "Socrates is a man, and every man is mortal.\r\nHe said so in court.",
        "- The unexamined life\n- is not worth living.",
        "Ἀπολογία Σωκράτους — the defence of Socrates, in Athens.",
    ]


def test_search_returns_the_matching_passage(library):
    library.ingest("apology.md")
    (best, *_) = library.search_passages("Who said the unexamined life is not worth living?")
    assert best.text.startswith("- The unexamined life") and best.score > 0
    assert library.search_passages("mortal")[0].ordinal == 1
    assert library.search_passages("mortals")[0].ordinal == 1           # stemmed
    assert library.search_passages("Σωκράτους")[0].ordinal == 3
    assert library.search_passages("zebra") == [] and library.search_passages("?!") == []
    for hostile in ('"', "NEAR(", "life AND", "*", "text:life", "') OR 1=1 --"):
        library.search_passages(hostile)                                # FTS5 syntax in a query does nothing
    assert len(library.search_passages("Socrates", limit=1)) == 1
    with pytest.raises(ValueError):
        library.search_passages("Socrates", limit=0)


def test_no_embedding_model_or_vector_store_is_loaded(tmp_path, workspace):
    script = (
        "import sys\n"
        "from memory import source_library\n"
        f"assert source_library.main(['--db', {str(tmp_path / 'cli.db')!r}, 'ingest', 'apology.md']) == 0\n"
        f"assert source_library.main(['--db', {str(tmp_path / 'cli.db')!r}, 'search', 'mortal']) == 0\n"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in "
        "('onnxruntime', 'lancedb', 'fastembed', 'tokenizers', 'sentence_transformers', 'llama_cpp')))\n"
    )
    out = subprocess.run([sys.executable, "-c", script], cwd=workspace, capture_output=True, text=True,
                         env={**os.environ, "PYTHONPATH": str(ROOT)}, check=True).stdout.splitlines()
    assert out[0].startswith("ingested apology.md: 4 passages added")
    assert json.loads(out[1])["ordinal"] == 1
    assert out[-1] == "[]"


def test_a_path_outside_the_workspace_is_rejected(library, workspace, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret plans\n")
    (workspace / "link.md").symlink_to(outside)
    for path in (outside, "../outside.md", "link.md", "/etc/passwd"):
        with pytest.raises(SourceError, match="outside the workspace"):
            library.ingest(path)
    assert library.sources() == [] and library.store.records(SOURCE) == []


# ------------------------------------------------------------ what else ingest refuses or keeps
def test_only_utf8_markdown_files_are_ingested(library, workspace):
    (workspace / "notes.txt").write_text("plain text\n")
    (workspace / "latin1.md").write_bytes("caf\xe9\n".encode("latin-1"))
    (workspace / "folder.md").mkdir()
    for path, reason in (("notes.txt", "not Markdown"), ("latin1.md", "not UTF-8"), ("folder.md", "not a file"),
                         ("missing.md", "no such file")):
        with pytest.raises(SourceError, match=reason):
            library.ingest(path)


def test_a_secret_in_a_source_is_redacted_and_the_passages_follow_the_kept_text(library, workspace):
    fake_key = "AKIA" + "IOSFODNN7" + "EXAMPLE"      # AWS's documented example key, assembled so none is committed
    (workspace / "keys.md").write_text(f"Intro.\n\nThe key was {fake_key} once.\n\nOutro.\n")
    result = library.ingest("keys.md")
    (source,) = library.sources()
    assert source["redacted"] and source["sha256"] == result["source"] != source["stored_sha256"]
    text = library.source_text(result["source"])
    assert fake_key not in text
    assert [text[p.start:p.end] for p in library.passages(result["source"])] == ["Intro.", text.split("\n\n")[1],
                                                                                  "Outro."]
    assert library.ingest("keys.md")["passages_added"] == 0            # still once: keyed by the file's bytes


def test_an_interrupted_ingest_is_finished_and_never_doubled(store, tmp_path, workspace):
    data = (workspace / "apology.md").read_bytes()
    key = sha256(data)
    store.put_record(SOURCE, key, {"name": "apology.md", "sha256": key, "size": len(data), "status": "ingesting"},
                     body=data, index=("name", "status"))              # stopped after the first transaction
    library = SourceLibrary(store, tmp_path / "facts.passages.db", workspace)   # opening finishes it
    assert [s["passages"] for s in library.sources()] == [4]
    assert library.ingest("apology.md")["passages_added"] == 0
    assert len(store.records("passage")) == 4


def test_the_index_is_rebuilt_from_the_records(library, tmp_path, workspace):
    key = library.ingest("apology.md")["source"]
    before = library.passages(key)
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(str(tmp_path / "facts.passages.db") + suffix).unlink(missing_ok=True)
    rebuilt = SourceLibrary(library.store, tmp_path / "facts.passages.db", workspace)
    assert rebuilt.passages(key) == before and rebuilt.search_passages("mortal")[0].ordinal == 1


def test_an_empty_source_is_kept_with_no_passages(library, workspace):
    (workspace / "empty.md").write_text("\n\n  \n")
    result = library.ingest("empty.md")
    assert result["created"] and result["passages"] == 0 and library.passages(result["source"]) == []


def test_the_original_store_cant_hold_a_library(tmp_path, workspace):
    with pytest.raises(SourceError, match="keeps records"):
        SourceLibrary(ExactStore(str(tmp_path / "facts.db")), tmp_path / "x.passages.db", workspace)


def test_the_cli_reports_a_second_ingest_and_refuses_bad_paths(tmp_path, workspace, capsys, monkeypatch):
    monkeypatch.chdir(workspace)
    db = str(tmp_path / "cli.db")
    assert main(["--db", db, "ingest", "apology.md"]) == 0
    assert main(["--db", db, "ingest", "apology.md"]) == 0
    assert main(["--db", db, "ingest", "../outside.md"]) == 2
    assert main(["--db", db, "list"]) == 0
    out, err = capsys.readouterr()
    assert "already in the library (4 passages); nothing added" in out and "apology.md\t4 passages" in out
    assert "error:" in err
    assert passages_path_for(db).name == "cli.passages.db" and passages_path_for(db).exists()


# ------------------------------------------------------------ paragraphs
@settings(max_examples=300, deadline=None)
@given(st.text(alphabet=st.sampled_from(list("ab \t\n\r#-é")), max_size=80))
def test_paragraph_spans_are_exact_ordered_and_trimmed(text):
    spans = paragraphs(text)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
    for start, end in spans:
        piece = text[start:end]
        assert piece and piece == piece.strip() and not any(
            line.strip() == "" for line in piece.replace("\r\n", "\n").split("\n")[1:-1])
    covered = "".join(text[s:e] for s, e in spans)
    assert "".join(text.split()) == "".join(covered.split())          # no text is lost
