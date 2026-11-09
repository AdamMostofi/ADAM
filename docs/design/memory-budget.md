# Memory Budget

**Status:** Current. This is the one definition of ADAM's memory budget; other documents point here.
**Decided:** 2026-11-09 by the owner (Option A in [#33](https://github.com/AdamMostofi/ADAM/issues/33)).
**Last measured:** 2026-11-09, after Stage 0.5 ([raw report](../measurements/2026-11-09-memory-after-stage-0.5.json)). **Status: within budget**: startup 127.0 MB, chat 334.1 MB.

## The definition

> **400 MB total while ADAM is starting up, idle, or chatting.**
> A separate study process (book ingestion, extraction, reading) may use more, then exits.

- **Total** means every ADAM process together: the Python process and anything it starts, such as `llama-server`.
- **Measured as total RSS**, the conservative figure: shared libraries count in full for each process. PSS, which splits shared pages, is recorded next to it.
- **This is RAM, not disk.** It never limits how much history or data ADAM keeps on disk.

This replaces the older wording: "start at no more than 400 MB", "400 MB peak-RSS", and "core ≤ 400 MB".

### States

| State | What it means | Enforced |
|---|---|---|
| `startup` | ADAM is running and ready, before any request | Yes |
| `chat` | After chat turns that use memory and the Mouth, including `llama-server` | Yes |
| `ingest` | After storing many facts in one process | No; this is study work, recorded only |
| `peak` | The highest total seen during the run | No; recorded only |

## How to measure

```bash
FASTEMBED_CACHE_PATH=~/.cache/fastembed ADAM_LLAMA_SERVER=~/.local/bin/llama-server \
  .venv/bin/python scripts/measure_memory.py --out report.json
```

The script runs every measurement in a fresh process with temporary stores, so production data is never opened. It prints a table and **exits with code 1 when an enforced state is over budget**. `scripts/memory_probe.py` is the standard-library probe it uses, reading `/proc`.

It needs the real models, so it isn't part of CI. Run it after any change that adds or swaps a component.

## Current measurements, after Stage 0.5

Locked environment, Python 3.11.15, 200 facts ingested. The embedding model is MiniLM int8 run directly with onnxruntime; the vector index is numpy in SQLite ([decision](./vector-index.md)).

| Step | Total RSS (MB) | Total PSS (MB) | Notes |
|---|---|---|---|
| Python started | 16.5 | 10.9 | |
| Libraries imported (numpy, networkx, flask) | 59.8 | 53.1 | |
| ADAM modules imported | 66.6 | 59.9 | |
| **`startup`** | **127.0** | 120.0 | Core built, Ear (Needle) loaded |
| First facts stored | 195.5 | 188.5 | Embedding model loaded |
| **`chat`** | **334.1** | 321.7 | Python 205.1 + `llama-server` 128.9 |
| `ingest` (200 facts) | 335.9 | 323.5 | |
| `peak` | 335.9 | | |

**Result: within budget, with 66 MB of headroom in `chat`.**

| Component, loaded alone | Process RSS (MB) |
|---|---|
| Embedding: MiniLM int8 (onnxruntime) | 117.4 |
| Vector index: numpy in SQLite, 1,000 facts | 39.2 |
| Ear: Needle | 101.2 |
| Mouth: `llama-server` | 128.9 (separate process) |

## Earlier measurements, Stage 0.4 (before the index change)

Locked environment (`uv.lock`, Python 3.11.15), WSL2 on the development laptop, 200 facts ingested.

| Step | Total RSS (MB) | Total PSS (MB) | Notes |
|---|---|---|---|
| Python started | 16.7 | 11.1 | |
| Libraries imported (numpy, networkx, lancedb, flask) | 160.6 | 153.9 | |
| ADAM modules imported | 161.3 | 154.6 | |
| **`startup`** | **211.6** | 204.5 | Core built, Ear (Needle) loaded; 0.6 s |
| First facts stored | 413.7 | 406.7 | Embedding model and vector table loaded |
| **`chat`** | **565.0** | 552.6 | Python 435.3 + `llama-server` 129.7 |
| `ingest` (200 facts) | 575.9 | 563.4 | |
| `peak` | 575.9 | | |

**Result: `startup` is within budget; `chat` is 165 MB over.**

### Each part loaded on its own

| Component | Process RSS (MB) | Above a bare Python (≈16.5 MB) |
|---|---|---|
| Embedding: fastembed + MiniLM | 223.7 | ≈207 |
| Vector store: LanceDB (with pyarrow) | 194.3 | ≈178 |
| Ear: Needle | 101.4 | ≈85 |
| Mouth: `llama-server` with TinyChat15M | 129.7 | (separate process) |

Totals overlap, because components share numpy and other libraries, so these don't add up exactly to the lifecycle figures.

## Decisions per component

| Component | Cost | Recommendation | Where it's settled |
|---|---|---|---|
| Embedding model | Was ≈200 MB, now ≈100 MB | **Done:** MiniLM int8 run directly with onnxruntime, at the same quality | Stage 0.5 ([decision](./vector-index.md)) |
| Vector store | Was ≈145–180 MB, now ≈23 MB | **Done:** numpy index inside SQLite; also fixed the 1.4 GB disk growth | Stage 0.5 ([decision](./vector-index.md)) |
| Mouth (`llama-server`) | ≈130 MB | **Keep, started only when needed** (it already is). Stage 4.3 limits it to small talk | Stage 4.3 ([#34](https://github.com/AdamMostofi/ADAM/issues/34)) |
| Ear (Needle) | ≈50–85 MB | **Make optional; decide at 4.3.** It affects no answer today, contacts Hugging Face at startup, and its vendor stopped hosting the native library (see below) | Stage 4.3 ([#34](https://github.com/AdamMostofi/ADAM/issues/34)) |
| Flask | small | Keep; only the web console imports it | |

**After Stage 0.5:** `chat` is 334.1 MB, within budget. Stage 0.6 re-measures after the reset.

## Known issue: the Ear's native library (found 2026-11-09)

The `Cactus-Compute/needle3` repository on Hugging Face was changed on 2026-11-05. It now holds only the weights, so every `cactus-needle` release fails to download its native library on a fresh machine (HTTP 404).

- **This machine still works:** library 3.3.1 is cached in `~/.cache/cactus-needle`.
- **`cactus-needle` is pinned to 3.2.1**, the release that uses the cached library. 3.2.10 asks for 3.3.3, which was never cached.
- **ADAM still starts without it:** if Needle can't load, the Ear falls back to its keyword method and logs a warning, so a fresh install still starts.
- **Needle contacts Hugging Face at startup** even when cached, so startup isn't fully offline while the Ear is enabled.
