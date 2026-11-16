"""Where the store's keys come from (design section 11, decision D4).

The store holds three random 32-byte keys, each wrapped (AES-256-GCM) by a key
encryption key (KEK):

* the data key, which encrypts archived objects;
* the object-id key, which makes object ids keyed hashes, so an id can't
  confirm a guessed value;
* the fingerprint key, used for secret fingerprints.

The KEK comes from one of three sources, chosen once, when the store is
created (decision D4, decided by the owner: a choice at onboarding):

* **`key_file`** (the default): a random key file kept *outside* the store, in
  `$XDG_CONFIG_HOME/agent-memory/keys/<project-id>.key` (mode 0600). A copied
  or synced store can't be read without it.
* **`passphrase`**: derived from `AMEM_PASSPHRASE` with scrypt and a salt kept
  in the store. scrypt costs about 125 ms, which every hook process would pay,
  so the derived KEK is cached for the session (#83): a 0600 file in
  `$XDG_RUNTIME_DIR/agent-memory/` (a per-user tmpfs, cleared at logout),
  named by a hash of the salt and passphrase, kept for 12 hours.
  `AMEM_PASSPHRASE_CACHE=0` turns the cache off. Without `$XDG_RUNTIME_DIR`
  there is no cache.
* **`keychain`**: a random KEK kept in the OS keychain through the optional
  `keyring` package (macOS Keychain, Windows Credential Manager, Secret
  Service). WSL usually has none, and then the store says so instead of
  falling back silently.

`AMEM_KEY_SOURCE` (`key-file`, `passphrase` or `keychain`) chooses for a new
store. The Claude Code plugin sets it from the user's choice in its config
dialog.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
SOURCES = ("key_file", "passphrase", "keychain")
CACHE_SECONDS = 12 * 3600


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


def _cache_path(passphrase: str, salt: bytes) -> Path | None:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime or os.environ.get("AMEM_PASSPHRASE_CACHE", "1") == "0":
        return None
    name = hashlib.sha256(salt + b"\0" + passphrase.encode()).hexdigest()[:24]
    return Path(runtime) / "agent-memory" / f"{name}.kek"


def cached_passphrase_kek(passphrase: str, salt: bytes) -> bytes:
    """passphrase_kek, cached for the session in the user's runtime directory (#83)."""
    path = _cache_path(passphrase, salt)
    if path is not None:
        try:
            if time.time() - path.stat().st_mtime < CACHE_SECONDS:
                data = path.read_bytes()
                if len(data) == KEY_BYTES:
                    return data
        except OSError:
            pass
    kek = passphrase_kek(passphrase, salt)
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(kek)
            os.replace(tmp, path)
        except OSError:
            pass   # no cache: slower, never wrong
    return kek


def keychain_kek(project_id: str) -> bytes:
    """The project's KEK from the OS keychain (created on first use), through the optional `keyring` package."""
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError as err:
        raise KeyError_("the keychain option needs the `keyring` package (pip install keyring), "
                        "or choose key-file or passphrase") from err
    try:
        stored = keyring.get_password("agent-memory", project_id)
        if stored is None:
            stored = secrets.token_bytes(KEY_BYTES).hex()
            keyring.set_password("agent-memory", project_id, stored)
            stored = keyring.get_password("agent-memory", project_id) or stored
    except KeyringError as err:
        raise KeyError_(f"the OS keychain isn't usable here ({err}); choose key-file or passphrase") from err
    try:
        data = bytes.fromhex(stored)
    except ValueError as err:
        raise KeyError_("the keychain entry for this project isn't a key") from err
    if len(data) != KEY_BYTES:
        raise KeyError_("the keychain entry for this project isn't a 32-byte key")
    return data


def normalize_source(name: str | None) -> str | None:
    if not name:
        return None
    value = name.strip().lower().replace("-", "_")
    if value not in SOURCES:
        raise KeyError_(f"unknown key source {name!r}; choose key-file, passphrase or keychain")
    return value


def wrap(kek: bytes, key: bytes, label: str) -> bytes:
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(kek).encrypt(nonce, key, label.encode())


def unwrap(kek: bytes, blob: bytes, label: str) -> bytes:
    try:
        return AESGCM(kek).decrypt(blob[:12], blob[12:], label.encode())
    except Exception as err:   # InvalidTag: wrong key or tampered meta
        raise KeyError_(f"can't unlock the {label}: wrong key or passphrase, or the store's keys were altered") from err
