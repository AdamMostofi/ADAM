"""Detect any test-run change to ADAM's production stores.

Used by `tests/conftest.py`. The fingerprint covers every file under each
store: size and modification time for all files, plus a SHA-256 hash for
files up to 1 MB (SQLite databases, Lance manifests, saved graphs). Writes,
deletions, and new files all show up as differences.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

PRODUCTION_STORES = ("adam_memory.db", "adam_vectors.db", "adam_vectors.lance", "adam_save", "skills")
STORE_ENV_VARS = ("ADAM_DB", "ADAM_VECTORS", "ADAM_LANCE")
HASH_LIMIT = 1 << 20


def _hash(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(repo: Path) -> dict[str, tuple]:
    """Map each production file (relative to `repo`) to its size, mtime, and hash."""
    result: dict[str, tuple] = {}
    for name in PRODUCTION_STORES:
        base = repo / name
        if not base.exists():
            result[name] = ("absent",)
            continue
        files = [str(base)] if base.is_file() else [
            os.path.join(d, f) for d, _, names in os.walk(base) for f in names
        ]
        for f in files:
            stat = os.stat(f)
            digest = _hash(f) if stat.st_size <= HASH_LIMIT else None
            result[os.path.relpath(f, repo)] = (stat.st_size, stat.st_mtime_ns, digest)
    return result


def differences(before: dict[str, tuple], after: dict[str, tuple]) -> list[str]:
    """Readable list of what changed between two fingerprints."""
    lines = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        if old is None or old == ("absent",):
            lines.append(f"created: {path}")
        elif new is None or new == ("absent",):
            lines.append(f"deleted: {path}")
        else:
            lines.append(f"modified: {path}")
    return lines


def env_problems(repo: Path, environ: dict[str, str]) -> list[str]:
    """Store paths from the environment that would point inside the repo."""
    problems = []
    repo = repo.resolve()
    for var in STORE_ENV_VARS:
        value = environ.get(var)
        if not value:
            continue
        resolved = Path(value).expanduser().resolve()
        if resolved == repo or repo in resolved.parents:
            problems.append(f"{var}={value} resolves inside the repo ({resolved})")
    return problems


def failure_message(changes: list[str]) -> str:
    shown = "\n".join(f"  {c}" for c in changes[:20])
    more = f"\n  ... and {len(changes) - 20} more" if len(changes) > 20 else ""
    return (
        "PRODUCTION STORE GUARD: the test run changed ADAM's production stores.\n"
        f"{shown}{more}\n"
        "Every test must use temporary stores. Restore from backups/ if needed."
    )
