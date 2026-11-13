"""Where a project's store lives (design section 5.4, decision D3).

The store location is configurable because lossless history grows, and on the
development machine the default disk (C:, which also backs WSL) is short of
space. The base directory is the first of these that is set:

1. an explicit `home` argument;
2. `AMEM_HOME`;
3. `$XDG_DATA_HOME/agent-memory`;
4. `~/.local/share/agent-memory`.

Each project gets its own folder, `<name>-<hash of its real path>`. D3 is
still open for the owner; this default is the design's recommendation, and
changing it needs no migration, because the location is always configurable.

A store in a synced folder (OneDrive, Dropbox, iCloud, Google Drive and the
like) is allowed but warned about. Sync clients copy half-written database
files, and they keep copies outside the engine's control, which matters for
purging secrets.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

SYNCED_MARKERS = ("onedrive", "dropbox", "google drive", "googledrive", "my drive", "icloud drive",
                  "mobile documents", "icloud~", "box sync", "pcloud", "nextcloud", "owncloud", "mega",
                  "sync.com", "syncthing", "tresorit")


def base_dir(home: str | os.PathLike | None = None) -> Path:
    if home:
        return Path(home).expanduser()
    if os.environ.get("AMEM_HOME"):
        return Path(os.environ["AMEM_HOME"]).expanduser()
    data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data) / "agent-memory"


def project_id(project_root: str | os.PathLike) -> str:
    real = os.path.realpath(project_root)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(real.rstrip("/")) or "root").strip("-") or "project"
    return f"{name}-{hashlib.sha256(real.encode()).hexdigest()[:10]}"


def store_path(project_root: str | os.PathLike, home: str | os.PathLike | None = None) -> Path:
    return base_dir(home) / project_id(project_root)


def synced_folder_warnings(path: str | os.PathLike) -> list[str]:
    """Warnings if the path looks like it is inside a cloud-synced folder."""
    parts = [p.lower() for p in Path(os.path.realpath(path)).parts]
    hits = [p for p in parts if any(marker in p for marker in SYNCED_MARKERS)]
    if not hits:
        return []
    return [f"The store at {path} appears to be inside a synced folder ({hits[0]!r}). Sync clients can copy "
            "half-written database files and keep copies the engine can't purge. Set AMEM_HOME to a local, "
            "unsynced folder."]
