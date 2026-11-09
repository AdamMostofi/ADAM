# Vector Index and Embedding Model

**Status:** Current. Decided 2026-11-09 in Stage 0.5 ([#32](https://github.com/AdamMostofi/ADAM/issues/32)).
**Raw data:** [index benchmark](../measurements/2026-11-09-index-benchmark.json), [embedding benchmark, round 2](../measurements/2026-11-09-embedding-benchmark-round2.json), [memory after the change](../measurements/2026-11-09-memory-after-stage-0.5.json).

## The decision

| Part | Choice | Replaces |
|---|---|---|
| **Vector store** | Fact embeddings as blobs in one SQLite file (`adam_vectors.db`), searched with numpy | LanceDB |
| **Embedding model** | `all-MiniLM-L6-v2` int8 ONNX ([Xenova/all-MiniLM-L6-v2](https://huggingface.co/Xenova/all-MiniLM-L6-v2), commit `751bff3`, Apache-2.0), run directly with onnxruntime and its memory arena off | The same model through fastembed |

**Result:** chat went from 565 MB to **334 MB**, within the [400 MB budget](./memory-budget.md), with the Ear still on. Disk growth is now linear: about 2 MB for 1,000 facts, down from 43 MB in 3,001 files.

## The rules, set before measuring

1. Chat must fit within the 400 MB total budget.
2. Search quality (recall@3) within 5 points of the best model tested.
3. Bounded disk growth, with a recorded limit after 1,000 facts.
4. Tie-breaker: the simplest option, meaning the fewest new dependencies.

## What it means

- **No cap on facts.** Writing a fact stores one row. Writing the same fact id again replaces that row. Duplicate *content* is still stored twice until Stage 0.6 adds de-duplication.
- **Search is exact.** Every store tested compares against every vector, so the store never changes which facts are found. Quality comes only from the embedding model.
- **Memory grows with facts:** all vectors are loaded for search, about 1.5 KB per fact. That's 1.5 MB at 1,000 facts and 15 MB at 10,000. **Past about 50,000 facts, switch to `sqlite-vec`**, which searches from disk.
- **The index is derived data.** `MemorySystem.rebuild_index()` recreates it from the fact store. A changed embedding dimension gives a clear "rebuild the index" error.
- **The model is cached** in `~/.cache/huggingface` (or `HF_HOME`), which survives WSL restarts. With `HF_HUB_OFFLINE=1` it runs with no network access.

## Store benchmark

1,000 facts written one at a time, as ADAM writes them, plus 10,000 vectors for scale. Each measurement runs in a fresh process.

| Store | Disk (1k) | Files (1k) | Search (1k) | RAM above Python (1k / 10k) |
|---|---|---|---|---|
| LanceDB, one write per fact (old) | 43.4 MB | 3,001 (1,001 versions) | 49 ms | +447 MB / not run |
| LanceDB with scheduled cleanup | 1.6 MB | 4 | 5 ms | +256 / +1,072 MB |
| `sqlite-vec` | 1.6 MB | 1 | 0.3 ms | +11 / +35 MB |
| **numpy in SQLite** | 2.1 MB | 1 | 0.04 ms | +13 / +55 MB |

`sqlite-vec` and numpy both pass rules 1–3. Rule 4 picks numpy: it adds no dependency, while `sqlite-vec` is pre-1.0.

## Embedding benchmark (round 2)

89 questions phrased with almost no words in common with their answer, each looked up among 1,000 facts, with look-alike facts nearby (several capitals, several birds, and so on).

| Model | Recall@3 | Recall@1 | MRR | RAM above Python | ms per fact |
|---|---|---|---|---|---|
| **MiniLM int8, onnxruntime direct** | **0.944** | **0.787** | **0.862** | **+114 MB** | 0.39 |
| MiniLM fp32, onnxruntime direct (arena off) | 0.933 | 0.775 | 0.861 | +168 MB | 0.88 |
| MiniLM fp32 through fastembed (old) | 0.933 | 0.775 | 0.861 | +279 MB | 0.88 |
| potion-retrieval-32M (model2vec) | 0.921 | 0.719 | 0.826 | +200 MB | 0.01 |
| static-retrieval-mrl-en-v1 | 0.921 | 0.697 | 0.815 | +163 MB | 0.02 |
| bge-small-en-v1.5 (int8) | 0.910 | 0.787 | 0.853 | +322 MB | 1.89 |
| potion-base-32M | 0.865 | 0.708 | 0.795 | +200 MB | 0.01 |
| snowflake-arctic-embed-xs | 0.843 | 0.685 | 0.777 | +276 MB | 0.90 |
| potion-base-8M | 0.843 | 0.652 | 0.757 | +83 MB | 0.01 |

**What it showed:**
- **Most of MiniLM's RAM wasn't the model.** The same file run directly with onnxruntime's memory arena off used 111 MB less.
- **int8 saved a further 54 MB** at equal or better quality, and is twice as fast.
- **The static models aren't the best fit here.** They come close at top-3, but are clearly worse at ranking the right fact first, and don't use less RAM than int8 MiniLM.
- **The first round** (32 questions) agreed: MiniLM best, potion-8M about 12 points lower.
- **The gold set is small** (89 questions), so differences of one or two questions (1–2 points) are noise.

## Memory after the change

| State | Before (Stage 0.4) | After | Budget |
|---|---|---|---|
| Startup | 211.6 MB | 127.0 MB | Within |
| Chat | 565.0 MB | **334.1 MB** (Python 205.1 + `llama-server` 128.9) | **Within** |
| Ingest (200 facts) | 575.9 MB | 335.9 MB | Not enforced |

## Removed dependencies
LanceDB, pyarrow, fastembed and 15 packages that only they needed. Added directly: onnxruntime, tokenizers and huggingface-hub, which were already installed as fastembed dependencies.

## Re-running the benchmark
`scripts/bench_index.py` needs research-only packages that ADAM no longer installs:

```bash
uv pip install --python .venv/bin/python fastembed model2vec sqlite-vec safetensors lancedb
.venv/bin/python scripts/bench_index.py --out report.json
```

Run `uv sync --locked --extra dev` afterwards to return to the locked environment.
