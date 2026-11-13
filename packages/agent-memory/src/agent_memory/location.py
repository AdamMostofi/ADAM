"""Where a project's store lives (design section 5.4, decision D3).

**D3, decided by the owner on 2026-11-13: the store is part of the project.**
It lives in `<project>/.agent-memory/`, so wherever the project is installed,
its memory is installed with it.

* **Git:** the folder holds its own `.gitignore` (`*`), so git ignores it
  without the engine touching the project's files.
* **Overrides:** an explicit `home` argument or `AMEM_HOME` still puts the
  store elsewhere, as `<home>/<name>-<hash of the project's real path>`.
  That's useful for tests, or for a project on a read-only or synced drive.
* **Growth:** handled by tiered lossless compression of old, unvisited
  content (Stage 2.7), not by moving the store away.

A store in a synced folder (OneDrive, Dropbox, iCloud, Google Drive and the
like) is allowed but warned about. Sync clients copy half-written database
files and keep copies the engine can't purge. With D3 this happens whenever
the project itself is in a synced folder.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

STORE_DIRNAME = ".agent-memory"

SYNCED_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "my drive", "icloud drive",
                  "mobile documents", "icloud~", "box sync", "pcloud", "nextcloud", "owncloud", "mega",
                  "sync.com", "syncthing", "tresorit")


def base_dir(home: str | os.PathLike | None = None) -> Path | None:
    """The override base directory, if one is set; None means the store lives in the project."""
    if home:
        return Path(home).expanduser()
    if os.environ.get("AMEM_HOME"):
        return Path(os.environ["AMEM_HOME"]).expanduser()
    return None


def project_id(project_root: str | os.PathLike) -> str:
    real = os.path.realpath(project_root)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(real.rstrip("/")) or "root").strip("-") or "project"
    return f"{name}-{hashlib.sha256(real.encode()).hexdigest()[:10]}"


def store_path(project_root: str | os.PathLike, home: str | os.PathLike | None = None) -> Path:
    base = base_dir(home)
    if base is None:
        return Path(os.path.realpath(project_root)) / STORE_DIRNAME
    return base / project_id(project_root)


def default_project_id(store: Path) -> str:
    """The project id for a store path: the project's id for an in-project store, else the folder name."""
    if store.name == STORE_DIRNAME:
        return project_id(store.parent)
    return store.name


def ignore_in_git(store: Path) -> None:
    """Make git ignore the store without editing the project's own .gitignore."""
    marker = store / ".gitignore"
    if store.name == STORE_DIRNAME and not marker.exists():
        marker.write_text("# agent-memory store: never commit it (it holds the full, encrypted history)\n*\n")


def synced_folder_warnings(path: str | os.PathLike) -> list[str]:
    """Warnings if the path looks like it is inside a cloud-synced folder."""
    parts = [p.lower() for p in Path(os.path.realpath(path)).parts]
    hits = [p for p in parts if any(marker in p for marker in SYNCED_MARKERS)]
    if not hits:
        return []
    return [f"The store at {path} appears to be inside a synced folder ({hits[0]!r}). Sync clients can copy "
            "half-written database files and keep copies the engine can't purge. Set AMEM_HOME to a local, "
            "unsynced folder."]
