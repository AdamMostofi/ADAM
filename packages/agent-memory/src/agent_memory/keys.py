"""Where the store's keys come from (design section 11, decision D4).

The store holds three random 32-byte keys, each wrapped (AES-256-GCM) by a key
encryption key (KEK):

* the data key, which encrypts archived objects;
* the object-id key, which makes object ids keyed hashes, so an id can't
  confirm a guessed value;
* the fingerprint key, used for secret fingerprints.

The KEK comes from one of two places:

* `AMEM_PASSPHRASE`: derived with scrypt and a salt kept in the store;
* otherwise, a random key file kept *outside* the store, in
  `$XDG_CONFIG_HOME/agent-memory/keys/<project-id>.key` (mode 0600). A copied
  or synced store can't be read without it.

D4 recommends the OS keychain, with a passphrase fallback on WSL. There's no
keychain on WSL, and the keychain is an owner decision, so this build uses the
key file by default. It is recorded as an open question for the owner.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32


class KeyError_(RuntimeError):
    """The store's keys can't be unlocked with the key available."""


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "agent-memory"


def key_file_kek(project_id: str, directory: Path | None = None) -> bytes:
    """The project's KEK from its key file, created (0600) on first use."""
    keys = (directory or config_dir()) / "keys"
    keys.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = keys / f"{project_id}.key"
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(secrets.token_bytes(KEY_BYTES))
    data = path.read_bytes()
    if len(data) != KEY_BYTES:
        raise KeyError_(f"{path} is not a {KEY_BYTES}-byte key")
    return data


def passphrase_kek(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode(), salt=salt, n=2 ** 15, r=8, p=1, maxmem=64 * 1024 * 1024,
                          dklen=KEY_BYTES)


def wrap(kek: bytes, key: bytes, label: str) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(kek).encrypt(nonce, key, label.encode())


def unwrap(kek: bytes, blob: bytes, label: str) -> bytes:
    try:
        return AESGCM(kek).decrypt(blob[:12], blob[12:], label.encode())
    except Exception as err:   # InvalidTag: wrong key or tampered meta
        raise KeyError_(f"can't unlock the {label}: wrong key or passphrase, or the store's keys were altered") from err
