"""The raw archive: full content, compressed, encrypted, content-addressed (design section 5.2).

* **Ids.** An object's id is a keyed hash (HMAC-SHA256) of its content, so
  identical content is stored once, and an id can't confirm a guessed value.
* **File format.** Each object is zlib-compressed, then encrypted with
  AES-256-GCM using a fresh nonce, with the id as associated data. So a
  changed byte, or a file swapped for another object, fails authentication.
* **Layout.** Files live at `objects/<first two hex>/<rest>`, written to a
  temporary file, fsynced, then renamed into place, so a crash never leaves
  half an object.
* **Nothing is truncated.** If an object can't be stored whole (the store's
  quota would be exceeded, the disk is short of space, or the write fails),
  `put` raises ArchiveError, and the store records a gap instead of keeping
  part of it.

Encryption uses one data key per project, not the design's key per session:
content addressing must deduplicate identical content across sessions, which
per-session keys would prevent. Purge (Stage 2.7) re-encrypts with a new key
instead.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import shutil
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"AMEM1"
DEFAULT_MIN_FREE_BYTES = 256 * 1024 * 1024


class ArchiveError(RuntimeError):
    """An object couldn't be stored whole."""


class CorruptObject(RuntimeError):
    """An object is missing, altered, or doesn't match its id."""


class Archive:
    def __init__(self, root: Path, data_key: bytes, id_key: bytes,
                 quota_bytes: int | None = None, min_free_bytes: int = DEFAULT_MIN_FREE_BYTES):
        self.root = root / "objects"
        self.root.mkdir(parents=True, exist_ok=True)
        self._aead = AESGCM(data_key)
        self._id_key = id_key
        self.quota_bytes = quota_bytes
        self.min_free_bytes = min_free_bytes

    def object_id(self, content: bytes) -> str:
        return hmac.new(self._id_key, content, hashlib.sha256).hexdigest()

    def path(self, object_id: str) -> Path:
        return self.root / object_id[:2] / object_id[2:]

    def size(self) -> int:
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())

    def put(self, content: bytes) -> str:
        oid = self.object_id(content)
        target = self.path(oid)
        if target.exists():
            return oid
        nonce = secrets.token_bytes(12)
        blob = MAGIC + nonce + self._aead.encrypt(nonce, zlib.compress(content, 6), oid.encode())
        if self.quota_bytes is not None and self.size() + len(blob) > self.quota_bytes:
            raise ArchiveError(f"storing {len(content)} bytes would exceed the store quota of {self.quota_bytes} bytes")
        if shutil.disk_usage(self.root).free - len(blob) < self.min_free_bytes:
            raise ArchiveError(f"less than {self.min_free_bytes} bytes would remain free on the store's disk")
        target.parent.mkdir(exist_ok=True)
        tmp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
        try:
            with open(tmp, "wb") as f:
                f.write(blob)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, target)
        except OSError as err:
            tmp.unlink(missing_ok=True)
            raise ArchiveError(f"writing the object failed: {err}") from err
        return oid

    def get(self, object_id: str) -> bytes:
        path = self.path(object_id)
        try:
            blob = path.read_bytes()
        except FileNotFoundError as err:
            raise CorruptObject(f"object {object_id} is missing") from err
        if not blob.startswith(MAGIC):
            raise CorruptObject(f"object {object_id} has an unknown format")
        nonce, body = blob[len(MAGIC):len(MAGIC) + 12], blob[len(MAGIC) + 12:]
        try:
            content = zlib.decompress(self._aead.decrypt(nonce, body, object_id.encode()))
        except Exception as err:
            raise CorruptObject(f"object {object_id} failed authentication: it was altered or replaced") from err
        if not hmac.compare_digest(self.object_id(content), object_id):
            raise CorruptObject(f"object {object_id} doesn't match its id")
        return content

    def ids(self) -> list[str]:
        return sorted(f.parent.name + f.name for f in self.root.glob("??/*") if not f.name.startswith("."))
