"""Benchmark embedding models and vector stores for ADAM's semantic index (Stage 0.5, #32).

Usage:
    FASTEMBED_CACHE_PATH=~/.cache/fastembed python scripts/bench_index.py --out report.json

Models are scored on a fixed gold set: 32 questions phrased with almost no
words in common with their answer, each looked up among 1,000 facts.
Stores are measured on the same 1,000 facts written one at a time (as ADAM
writes them), and on 10,000 synthetic vectors for scale. Every measurement
runs in a fresh process so memory figures are not mixed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))

MODELS = {
    "minilm": ("fastembed", "sentence-transformers/all-MiniLM-L6-v2"),
    "bge-small": ("fastembed", "BAAI/bge-small-en-v1.5"),
    "potion-8m": ("model2vec", "minishlab/potion-base-8M"),
}
STORES = ("lance_per_fact", "lance_optimized", "sqlite_vec", "numpy_sqlite")

FACTS = [
    ("shark", "is", "fish"), ("dolphin", "is", "mammal"), ("eagle", "is", "bird"),
    ("penguin", "is", "bird"), ("frog", "is", "amphibian"), ("snake", "is", "reptile"),
    ("bat", "is", "mammal"), ("whale", "is", "mammal"), ("salmon", "is", "fish"),
    ("owl", "is", "bird"), ("crocodile", "is", "reptile"), ("bee", "is", "insect"),
    ("spider", "is", "arachnid"), ("octopus", "is", "mollusc"), ("horse", "is", "mammal"),
    ("paris", "capital_of", "france"), ("tokyo", "capital_of", "japan"), ("cairo", "capital_of", "egypt"),
    ("ottawa", "capital_of", "canada"), ("canberra", "capital_of", "australia"),
    ("nairobi", "capital_of", "kenya"), ("lima", "capital_of", "peru"), ("oslo", "capital_of", "norway"),
    ("water", "boils_at", "100 celsius"), ("ice", "melts_at", "0 celsius"), ("earth", "orbits", "sun"),
    ("moon", "orbits", "earth"), ("photosynthesis", "produces", "oxygen"), ("heart", "pumps", "blood"),
    ("lungs", "absorb", "oxygen"), ("diamond", "is", "carbon"), ("mercury", "is", "metal"),
    ("gold", "is", "metal"), ("python", "is", "programming_language"), ("linux", "is", "operating_system"),
    ("sqlite", "is", "database"), ("http", "is", "protocol"), ("cpu", "executes", "instructions"),
    ("ram", "stores", "data"), ("apple", "is", "fruit"), ("carrot", "is", "vegetable"),
    ("bread", "contains", "gluten"), ("cheese", "made_from", "milk"), ("coffee", "contains", "caffeine"),
    ("rice", "is", "grain"), ("violin", "is", "string_instrument"), ("drum", "is", "percussion_instrument"),
    ("shakespeare", "wrote", "hamlet"), ("newton", "discovered", "gravity"), ("einstein", "developed", "relativity"),
    ("tiger", "is", "mammal"), ("parrot", "is", "bird"), ("trout", "is", "fish"),
    ("lizard", "is", "reptile"), ("ant", "is", "insect"),
]
GOLD = [
    ("a sea predator that breathes with gills", "shark is fish"),
    ("intelligent marine animal that nurses its young", "dolphin is mammal"),
    ("large bird of prey with sharp eyesight", "eagle is bird"),
    ("flightless bird living in antarctica", "penguin is bird"),
    ("creature that lives in water and on land and croaks", "frog is amphibian"),
    ("legless cold-blooded creature that slithers", "snake is reptile"),
    ("flying animal that uses echolocation at night", "bat is mammal"),
    ("the biggest animal in the ocean", "whale is mammal"),
    ("nocturnal bird that hoots", "owl is bird"),
    ("insect that makes honey", "bee is insect"),
    ("eight-legged creature that spins webs", "spider is arachnid"),
    ("sea creature with eight arms", "octopus is mollusc"),
    ("seat of the japanese government", "tokyo capital_of japan"),
    ("main city of the french republic", "paris capital_of france"),
    ("government city of canada", "ottawa capital_of canada"),
    ("australia's political centre", "canberra capital_of australia"),
    ("kenya's main city", "nairobi capital_of kenya"),
    ("temperature at which water turns to steam", "water boils_at 100 celsius"),
    ("when frozen water becomes liquid", "ice melts_at 0 celsius"),
    ("our planet travels around a star", "earth orbits sun"),
    ("plants turn sunlight into this gas", "photosynthesis produces oxygen"),
    ("organ that circulates blood through the body", "heart pumps blood"),
    ("hardest gemstone made of one element", "diamond is carbon"),
    ("a precious yellow metal", "gold is metal"),
    ("a popular language for writing software", "python is programming_language"),
    ("open source kernel for servers", "linux is operating_system"),
    ("embedded file-based relational engine", "sqlite is database"),
    ("red or green fruit that grows on trees", "apple is fruit"),
    ("orange root vegetable", "carrot is vegetable"),
    ("stimulant in a morning drink", "coffee contains caffeine"),
    ("dairy product from curdled milk", "cheese made_from milk"),
    ("staple grain eaten across asia", "rice is grain"),
]
TOTAL_FACTS = 1000


def corpus() -> list[str]:
    texts = [f"{s} {p} {o}" for s, p, o in FACTS]
    texts += [f"item{i} is kind{i % 37}" for i in range(TOTAL_FACTS - len(texts))]
    return texts


# --------------------------------------------------------------------- workers

def worker_model(name: str) -> dict:
    import numpy as np
    import memory_probe as mp

    base = mp.tree_memory().total_rss_mb
    kind, model_id = MODELS[name]
    t = time.time()
    if kind == "fastembed":
        from fastembed import TextEmbedding
        model = TextEmbedding(model_name=model_id)
        encode = lambda xs: np.array(list(model.embed(xs)), dtype=np.float32)
    else:
        from model2vec import StaticModel
        model = StaticModel.from_pretrained(model_id)
        encode = lambda xs: np.asarray(model.encode(xs), dtype=np.float32)
    load_s = time.time() - t

    texts = corpus()
    t = time.time()
    doc = encode(texts)
    embed_ms = (time.time() - t) / len(texts) * 1000
    doc /= np.linalg.norm(doc, axis=1, keepdims=True)
    queries = encode([q for q, _ in GOLD])
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)
    index = {text: i for i, text in enumerate(texts)}
    ranks = []
    for qi, (_, answer) in enumerate(GOLD):
        order = np.argsort(-doc @ queries[qi])
        ranks.append(int(np.where(order == index[answer])[0][0]) + 1)
    rss = mp.tree_memory().total_rss_mb
    return {
        "model": name, "dim": int(doc.shape[1]),
        "recall_at_1": round(sum(r == 1 for r in ranks) / len(ranks), 3),
        "recall_at_3": round(sum(r <= 3 for r in ranks) / len(ranks), 3),
        "mrr": round(sum(1 / r for r in ranks) / len(ranks), 3),
        "load_seconds": round(load_s, 2), "embed_ms_per_fact": round(embed_ms, 2),
        "rss_mb": round(rss, 1), "rss_above_python_mb": round(rss - base, 1),
        "misses": [GOLD[i][0] for i, r in enumerate(ranks) if r > 3],
    }


def dir_bytes(path: str) -> tuple[int, int]:
    if os.path.isfile(path):
        return os.path.getsize(path), 1
    files = [os.path.join(d, f) for d, _, names in os.walk(path) for f in names]
    return sum(os.path.getsize(f) for f in files), len(files)


def worker_store(name: str, n: int, dim: int) -> dict:
    import sqlite3
    import numpy as np
    import memory_probe as mp

    base = mp.tree_memory().total_rss_mb
    rng = np.random.default_rng(7)
    vectors = rng.standard_normal((n, dim)).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    queries = vectors[rng.choice(n, 32, replace=False)]
    work = tempfile.mkdtemp(prefix="adam-bench-")
    path = os.path.join(work, "index")
    extra = {}

    t = time.time()
    if name.startswith("lance"):
        import datetime
        import lancedb
        db = lancedb.connect(path)
        table = None
        for i in range(n):
            row = [{"id": str(i), "vector": vectors[i].tolist()}]
            if table is None:
                table = db.create_table("facts", data=row)
            else:
                table.add(row)
            if name == "lance_optimized" and (i + 1) % 100 == 0:
                try:
                    table.optimize(cleanup_older_than=datetime.timedelta(seconds=0), delete_unverified=True)
                except TypeError:
                    table.optimize(cleanup_older_than=datetime.timedelta(seconds=0))
        write_s = time.time() - t
        extra["version_files"] = len(os.listdir(os.path.join(path, "facts.lance", "_versions")))
        search = lambda q: [r["id"] for r in table.search(q.tolist()).limit(3).to_list()]
    elif name == "sqlite_vec":
        import sqlite_vec
        conn = sqlite3.connect(path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute(f"CREATE VIRTUAL TABLE vec USING vec0(embedding float[{dim}])")
        for i in range(n):
            with conn:
                conn.execute("INSERT INTO vec(rowid, embedding) VALUES (?, ?)", (i, vectors[i].tobytes()))
        write_s = time.time() - t
        search = lambda q: [r[0] for r in conn.execute(
            "SELECT rowid FROM vec WHERE embedding MATCH ? AND k = 3 ORDER BY distance", (q.tobytes(),))]
    else:  # numpy_sqlite
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE vec (id INTEGER PRIMARY KEY, embedding BLOB NOT NULL)")
        for i in range(n):
            with conn:
                conn.execute("INSERT INTO vec VALUES (?, ?)", (i, vectors[i].tobytes()))
        write_s = time.time() - t
        cache = {}

        def search(q):
            if "m" not in cache:
                rows = conn.execute("SELECT id, embedding FROM vec ORDER BY id").fetchall()
                cache["ids"] = np.array([r[0] for r in rows])
                cache["m"] = np.frombuffer(b"".join(r[1] for r in rows), dtype=np.float32).reshape(len(rows), dim)
            scores = cache["m"] @ q
            top = np.argpartition(-scores, 3)[:3]
            return list(cache["ids"][top[np.argsort(-scores[top])]])

    search(queries[0])  # warm up
    t = time.time()
    results = [search(q) for q in queries]
    query_ms = (time.time() - t) / len(queries) * 1000
    disk, files = dir_bytes(path)
    rss = mp.tree_memory().total_rss_mb
    shutil.rmtree(work, ignore_errors=True)
    return {
        "store": name, "n": n, "dim": dim, "write_seconds": round(write_s, 2),
        "query_ms": round(query_ms, 2), "disk_mb": round(disk / 1e6, 2), "files": files,
        "rss_mb": round(rss, 1), "rss_above_python_mb": round(rss - base, 1),
        "top1_found": sum(1 for r in results if r), **extra,
    }


# ----------------------------------------------------------------- orchestrator

def run(args: list[str], timeout: int = 1800) -> dict:
    out = subprocess.run([sys.executable, __file__, *args], capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[-1500:])
    return json.loads(out.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worker", choices=["model", "store"])
    parser.add_argument("--name")
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--dim", type=int, default=384)
    parser.add_argument("--out")
    parser.add_argument("--scale", type=int, default=10000, help="vector count for the scale run")
    args = parser.parse_args()
    sys.path.insert(0, HERE)

    if args.worker == "model":
        print(json.dumps(worker_model(args.name)))
        return 0
    if args.worker == "store":
        print(json.dumps(worker_store(args.name, args.n, args.dim)))
        return 0

    report = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "python": sys.version.split()[0],
              "gold_questions": len(GOLD), "facts": TOTAL_FACTS, "models": [], "stores": []}
    for name in MODELS:
        result = run(["--worker", "model", "--name", name])
        report["models"].append(result)
        print(f"model {name:<10} dim {result['dim']:>3}  recall@1 {result['recall_at_1']:.3f}  "
              f"recall@3 {result['recall_at_3']:.3f}  MRR {result['mrr']:.3f}  "
              f"RSS +{result['rss_above_python_mb']} MB  embed {result['embed_ms_per_fact']} ms/fact", flush=True)
    for n in (1000, args.scale):
        for store in STORES:
            if store == "lance_per_fact" and n > 1000:
                continue  # quadratic version growth makes this impractical; the 1,000 run shows it
            result = run(["--worker", "store", "--name", store, "--n", str(n)])
            report["stores"].append(result)
            versions = f"  versions {result['version_files']}" if "version_files" in result else ""
            print(f"store {store:<16} n {n:>6}  disk {result['disk_mb']:>8} MB  files {result['files']:>6}  "
                  f"write {result['write_seconds']:>6}s  query {result['query_ms']:>7} ms  "
                  f"RSS +{result['rss_above_python_mb']} MB{versions}", flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
