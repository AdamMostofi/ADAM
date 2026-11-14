"""The raw archive: full content, compressed, encrypted, content-addressed (design section 5.2).

* **Ids.** An object's id is a keyed hash (HMAC-SHA256) of its content, so
  identical content is stored once, and an id can't confirm a guessed value.
* **Loose objects (the hot tier).** Each object is zlib-compressed, then
  encrypted with AES-256-GCM using a fresh nonce, with the id as associated
  data. A changed byte, or a file swapped for another object, fails
  authentication.
  - Layout: `objects/<first two hex>/<rest>`.
  - Each is written to a temporary file, fsynced, then renamed, so a crash
    never leaves half an object.
  - A batch can defer its fsyncs and `flush()` them together.
* **Packs (the cold tier, Stage 2.11, decision D3).** Old objects nobody has
  read for a while are packed together.
  - Many objects are concatenated, compressed with lzma (xz, preset 6), and
    encrypted as one blob under `packs/<id>`. Measured on the ADAM
    repository: 22.5% of raw size, against 30.9% for per-object zlib.
  - The store keeps the index (object to pack, offset and length).
  - Reading a cold object is transparent, and its content and id are
    unchanged: every object is re-checked against its id when read.
  - A pack is read back and checked before any loose copy is removed.
* **Key rotation.** A purge can rotate the data key. During rotation the
  previous key is kept for reading, so a crash halfway leaves every object
  readable.
* **Nothing is truncated.** If an object can't be stored whole (the store's
  quota would be exceeded, the disk is short of space, or the write fails),
  `put` raises ArchiveError, and the store records a gap instead of keeping
  part of it.

Encryption uses one data key per project, not the design's key per session:
content addressing must deduplicate identical content across sessions, which
per-session keys would prevent.
"""
from __future__ import annotations

import hashlib
import hmac
import lzma
import os
import secrets
import shutil
import zlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"AMEM1"
PACK_MAGIC = b"AMEMP1"
PACK_PRESET = 6
DEFAULT_MIN_FREE_BYTES = 256 * 1024 * 1024


class ArchiveError(RuntimeError):
    """An object couldn't be stored whole."""


class CorruptObject(RuntimeError):
    """An object is missing, altered, or doesn't match its id."""


def _atomic_write(target: Path, blob: bytes, sync: bool = True) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(blob)
            f.flush()
            if sync:
                os.fsync(f.fileno())
        os.replace(tmp, target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


class Archive:
    def __init__(self, root: Path, data_key: bytes, id_key: bytes,
                 quota_bytes: int | None = None, min_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
                 previous_key: bytes | None = None):
        self.root = root / "objects"
        self.root.mkdir(parents=True, exist_ok=True)
        self.packs = root / "packs"
        self._aead = AESGCM(data_key)
        self._previous = AESGCM(previous_key) if previous_key else None
        self._id_key = id_key
        self.quota_bytes = quota_bytes
        self.min_free_bytes = min_free_bytes
        self._unsynced: list[Path] = []   # objects written by a batch, made durable together by flush()
        self.cold_lookup = None           # set by the store: object id -> (pack id, offset, length) or None
        self.on_read = None               # set by the store: records that an object was read (visits)
        self._pack_cache: dict[str, bytes] = {}

    # ------------------------------------------------------------ keys and ids
    def object_id(self, content: bytes) -> str:
        return hmac.new(self._id_key, content, hashlib.sha256).hexdigest()

    def _encrypt(self, data: bytes, aad: bytes) -> tuple[bytes, bytes]:
        nonce = secrets.token_bytes(12)
        return nonce, self._aead.encrypt(nonce, data, aad)

    def _decrypt(self, nonce: bytes, body: bytes, aad: bytes) -> bytes:
        try:
            return self._aead.decrypt(nonce, body, aad)
        except Exception:
            if self._previous is None:
                raise
            return self._previous.decrypt(nonce, body, aad)   # written before a key rotation finished

    # ------------------------------------------------------------ loose objects
    def path(self, object_id: str) -> Path:
        return self.root / object_id[:2] / object_id[2:]

    def size(self) -> int:
        return sum(f.stat().st_size for d in (self.root, self.packs) if d.exists()
                   for f in d.rglob("*") if f.is_file())

    def put(self, content: bytes, sync: bool = True) -> str:
        """Store content; returns its id. `sync=False` (batches) defers durability to `flush()`."""
        oid = self.object_id(content)
        target = self.path(oid)
        if target.exists() or (self.cold_lookup and self.cold_lookup(oid)):
            return oid
        nonce, sealed = self._encrypt(zlib.compress(content, 6), oid.encode())
        blob = MAGIC + nonce + sealed
        if self.quota_bytes is not None and self.size() + len(blob) > self.quota_bytes:
            raise ArchiveError(f"storing {len(content)} bytes would exceed the store quota of {self.quota_bytes} bytes")
        if shutil.disk_usage(self.root).free - len(blob) < self.min_free_bytes:
            raise ArchiveError(f"less than {self.min_free_bytes} bytes would remain free on the store's disk")
        try:
            _atomic_write(target, blob, sync)
        except OSError as err:
            raise ArchiveError(f"writing the object failed: {err}") from err
        if not sync:
            self._unsynced.append(target)
        return oid

    def flush(self) -> None:
        """Make every object written with sync=False durable: one system-wide sync where the OS has one."""
        if not self._unsynced:
            return
        if hasattr(os, "sync"):
            os.sync()
        else:   # pragma: no cover (Windows)
            for path in self._unsynced:
                with open(path, "rb+") as f:
                    os.fsync(f.fileno())
        self._unsynced.clear()

    def _read_loose(self, object_id: str) -> bytes | None:
        try:
            blob = self.path(object_id).read_bytes()
        except FileNotFoundError:
            return None
        if not blob.startswith(MAGIC):
            raise CorruptObject(f"object {object_id} has an unknown format")
        nonce, body = blob[len(MAGIC):len(MAGIC) + 12], blob[len(MAGIC) + 12:]
        try:
            return zlib.decompress(self._decrypt(nonce, body, object_id.encode()))
        except Exception as err:
            raise CorruptObject(f"object {object_id} failed authentication: it was altered or replaced") from err

    def get(self, object_id: str) -> bytes:
        content = self._read_loose(object_id)
        if content is None:
            where = self.cold_lookup(object_id) if self.cold_lookup else None
            if where is None:
                raise CorruptObject(f"object {object_id} is missing")
            pack_id, offset, length = where
            content = self.read_pack(pack_id)[offset:offset + length]
        if not hmac.compare_digest(self.object_id(content), object_id):
            raise CorruptObject(f"object {object_id} doesn't match its id")
        if self.on_read:
            self.on_read(object_id)
        return content

    def is_loose(self, object_id: str) -> bool:
        return self.path(object_id).exists()

    def remove_loose(self, object_id: str) -> None:
        self.path(object_id).unlink(missing_ok=True)

    def ids(self) -> list[str]:
        """Loose object ids (the hot tier)."""
        return sorted(f.parent.name + f.name for f in self.root.glob("??/*") if not f.name.startswith("."))

    # ------------------------------------------------------------ packs (the cold tier)
    def pack_path(self, pack_id: str) -> Path:
        return self.packs / pack_id

    def pack_ids(self) -> list[str]:
        return sorted(p.name for p in self.packs.glob("*") if not p.name.startswith(".")) if self.packs.exists() else []

    def write_pack(self, objects: dict[str, bytes]) -> tuple[str, dict[str, tuple[int, int]]]:
        """Pack objects together (lzma, then AES-GCM), check the pack by reading it back, and return its index."""
        index, chunks, offset = {}, [], 0
        for oid in sorted(objects):
            data = objects[oid]
            if not hmac.compare_digest(self.object_id(data), oid):
                raise CorruptObject(f"refusing to pack {oid}: content doesn't match its id")
            index[oid] = (offset, len(data))
            chunks.append(data)
            offset += len(data)
        pack_id = secrets.token_hex(16)
        nonce, sealed = self._encrypt(lzma.compress(b"".join(chunks), preset=PACK_PRESET), pack_id.encode())
        try:
            _atomic_write(self.pack_path(pack_id), PACK_MAGIC + nonce + sealed)
        except OSError as err:
            raise ArchiveError(f"writing the pack failed: {err}") from err
        self._pack_cache.pop(pack_id, None)
        plain = self.read_pack(pack_id)   # read back from disk: lossless, or nothing changes
        for oid, (off, length) in index.items():
            if not hmac.compare_digest(self.object_id(plain[off:off + length]), oid):
                self.pack_path(pack_id).unlink(missing_ok=True)
                raise CorruptObject(f"pack {pack_id} didn't read back object {oid} exactly")
        return pack_id, index

    def read_pack(self, pack_id: str) -> bytes:
        if pack_id in self._pack_cache:
            return self._pack_cache[pack_id]
        try:
            blob = self.pack_path(pack_id).read_bytes()
        except FileNotFoundError as err:
            raise CorruptObject(f"pack {pack_id} is missing") from err
        if not blob.startswith(PACK_MAGIC):
            raise CorruptObject(f"pack {pack_id} has an unknown format")
        nonce, body = blob[len(PACK_MAGIC):len(PACK_MAGIC) + 12], blob[len(PACK_MAGIC) + 12:]
        try:
            plain = lzma.decompress(self._decrypt(nonce, body, pack_id.encode()))
        except Exception as err:
            raise CorruptObject(f"pack {pack_id} failed authentication: it was altered or replaced") from err
        self._pack_cache = {pack_id: plain}   # keep the last pack only: reads of one pack come in runs
        return plain

    def delete_pack(self, pack_id: str) -> None:
        self._pack_cache.pop(pack_id, None)
        self.pack_path(pack_id).unlink(missing_ok=True)

    # ------------------------------------------------------------ key rotation
    def reencrypt_all(self) -> dict:
        """Rewrite every loose object and pack under the current key (each file atomically)."""
        loose = packs = 0
        for oid in self.ids():
            content = self._read_loose(oid)
            nonce, sealed = self._encrypt(zlib.compress(content, 6), oid.encode())
            _atomic_write(self.path(oid), MAGIC + nonce + sealed)
            loose += 1
        for pack_id in self.pack_ids():
            plain = self.read_pack(pack_id)
            nonce, sealed = self._encrypt(lzma.compress(plain, preset=PACK_PRESET), pack_id.encode())
            _atomic_write(self.pack_path(pack_id), PACK_MAGIC + nonce + sealed)
            packs += 1
        self._pack_cache.clear()
        return {"objects": loose, "packs": packs}
