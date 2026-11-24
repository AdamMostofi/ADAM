# The source library

**Status:** Current. Stage 4.2, Open the Data-Vault ([#24](https://github.com/AdamMostofi/ADAM/issues/24)).

The source library keeps the texts ADAM learns from, cut into passages it can cite exactly. The console calls
it the Data-Vault (decision D3.4); the code is `memory/source_library.py`.

This first slice proves provenance without embeddings:
- **One format.** Markdown only (D3.1).
- **Exact retrieval.** SQLite FTS5 with BM25 ranking (D3.2).
- **One way in.** The command line only (D3.3).

## Using it

```bash
.venv/bin/python -m memory.source_library ingest books/apology.md
.venv/bin/python -m memory.source_library search "the unexamined life" --limit 3
.venv/bin/python -m memory.source_library list
```

- **The store.** It uses ADAM's store: `ADAM_DB` (default `adam_memory.db`), or `--db`. The library needs the
  engine store, which is the default. With `ADAM_STORE=exact` it refuses and says why.
- **The workspace.** Only files inside the workspace can be ingested: `--workspace`, or `ADAM_WORKSPACE`, or
  the current folder. A path that resolves outside it is refused, including `..` and a symbolic link that
  points out.
- **What it accepts.** Files must be UTF-8 Markdown (`.md`, `.markdown`) of at most 64 MB.
- **Search results.** Each result is one JSON line: the passage's key, source, name, ordinal, offsets, hash,
  text and score.

In code: `open_library()`, then `ingest(path)`, `search_passages(query, limit)`, `passages(source)`,
`sources()` and `source_text(source)`.

## What is kept, and where

The engine store is the truth, written through the storage contract ([storage-contract.md](storage-contract.md)):

| Record | Key | Fields | Body |
|---|---|---|---|
| `source` | SHA-256 of the file's bytes | name (path in the workspace), `sha256`, `stored_sha256`, `redacted`, size, passage count, status, time | the text, as kept |
| `passage` | `<source sha256>#<ordinal>` | source, ordinal, `start`, `end`, `sha256` of the passage | none |

**A passage's text is not in its fields.** Fields are stored unencrypted, so the text is kept only in the
source's body, which the engine compresses and encrypts. The passage is `text[start:end]` of that body.

**A source is kept as the engine keeps it.** Before storing, the engine replaces anything shaped like a secret
(an access key, a token) with a marker. The passages are therefore cut from the kept text, not from the file,
and `text[start:end]` is exact for the text the library holds:
- `sha256` is the hash of the file's bytes: this is what makes ingest idempotent;
- `stored_sha256` is the hash of the kept text;
- `redacted` is true when the two differ.

**The passage index** (`adam_memory.passages.db`, beside the store) has the tables `sources`, `passages` and
`passage_fts` (FTS5, Porter stemming over Unicode words). It is derived from the records:
- when the library opens, it indexes any source the index lacks, and drops any the store no longer has;
- deleting the index loses nothing;
- every passage is checked against its hash as it is indexed.

**The index is not encrypted.** Full-text search needs readable text, so the index holds every passage in plain
SQLite. A library of private texts is then readable on disk, unlike the engine store. It is listed in the store
guard, backups and reset like the other stores.

## Passages

A passage is a paragraph: a run of lines between blank lines. A blank line is any line of whitespace only
(spaces, tabs, a `\r` from `\r\n` endings, Unicode spaces). It doesn't include its surrounding whitespace. Offsets count characters (Python
string positions), not bytes.

- **Headings and list items.** A heading followed by a blank line is its own passage. A list without blank
  lines is one passage.
- **Code blocks.** A fenced code block with blank lines inside is split at them. Markdown structure isn't parsed
  in this slice.

## Ingest is idempotent

- **The same bytes add nothing.** A file whose bytes are already a source adds nothing, even under another
  name. The second ingest reports `already in the library` and the passage count.
- **Changed content is a new source.** A changed file is a new source, because it has a new hash. The old one
  stays.
- **An interrupted ingest finishes.** Ingest takes two transactions:
  1. The first stores the source with status `ingesting`.
  2. The second stores every passage, and the source again with status `ingested`.

  If it stops between them, the next ingest finishes it, and so does opening the library. No passage is ever
  added twice, because a passage's key is its source and ordinal.

## Measured

From `scripts/measure_sources.py` ([raw report](../measurements/2026-11-24-source-library.json)), on a
generated 966 KB Markdown book of 5,200 paragraphs (2026-11-24, WSL):

| | |
|---|---|
| First ingest | 2.7 s |
| Second ingest (adds nothing) | 1.4 ms |
| Search, median (p95) | 3.2 ms (3.6) |
| Rebuilding the index from the records | 0.09 s |
| Engine store on disk | 17.6 MB |
| Passage index on disk | 3.6 MB |
| Peak RSS of the process | 97 MB |
| Models loaded | none |

## Limits

- **Markdown only**, and paragraphs only: EPUB, PDF and HTML are out of scope (D3.1).
- **No semantic recall.** A query matches words (stemmed), not meaning (D3.2).
- **Command line only.** There is no upload in the web UI (D3.3, until Phase 8).
- **Answers don't use it yet.** Answering from passages is Stage 4.3.
- **The search index is plain text on disk** (see above).
